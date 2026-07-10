import duckdb
import pytest

from graph_loader.config import NodeSpec
from graph_loader.hydrate import hydrate, run_hydrated
from graph_loader.mapper import MappingError, node_batches


class _FakeQR:
    """Mimics a FalkorDB QueryResult: header is [type, name] pairs."""

    def __init__(self, header, result_set):
        self.header = header
        self.result_set = result_set


class _FakeGraph:
    def __init__(self, qr):
        self._qr = qr
        self.queries = []

    def query(self, cypher, params=None):
        self.queries.append(cypher)
        return self._qr


def _wide(tmp_path):
    p = tmp_path / "vertexes.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        ('b1', 'Acme Bank',  90),
        ('w1', 'Wire One',    5),
        ('b2', 'Beta Bank',  40)
    ) AS v(NODE, party_name, risk_score)""")
    con.execute(f"COPY t TO '{p}' (FORMAT parquet)")
    con.close()
    return str(p)


def test_hydrate_attaches_wide_columns_and_keeps_originals(tmp_path):
    src = _wide(tmp_path)
    # Simulates a Cypher result: ids plus a computed column from the traversal.
    results = [{"NODE": "b1", "path_len": 3}, {"NODE": "b2", "path_len": 1}]
    out = hydrate(results, src, key="NODE")

    assert out[0]["party_name"] == "Acme Bank"
    assert out[0]["path_len"] == 3          # original result column preserved
    assert out[1]["risk_score"] == 40
    assert len(out) == 2


def test_hydrate_only_reads_requested_ids(tmp_path):
    # 'w1' is in the file but not in the result set -> not returned.
    out = hydrate([{"NODE": "b1"}], _wide(tmp_path), key="NODE")
    assert [r["NODE"] for r in out] == ["b1"]


def test_hydrate_empty_input_short_circuits():
    assert hydrate([], "does-not-matter.parquet") == []


def test_hydrate_rejects_unsafe_key():
    with pytest.raises(MappingError):
        hydrate([{"x": 1}], "f.parquet", key="NODE; DROP")


def test_hydrate_surfaces_a_column_never_ingested_into_the_graph(tmp_path):
    # This is the whole point of the DuckDB route: keep a wide column OUT of the
    # FalkorDB graph (no memory cost per node), yet still return it on results.
    #
    # `full_address` lives only in the wide file -- it is never made a node
    # property, so it cannot appear in any Cypher result. Hydration pulls it
    # back by NODE after the traversal.
    p = tmp_path / "vertexes.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        ('b1', 'Acme Bank', 90, '1 Market St, San Francisco'),
        ('b2', 'Beta Bank', 40, '9 King St, London')
    ) AS v(NODE, party_name, risk_score, full_address)""")
    con.execute(f"COPY t TO '{p}' (FORMAT parquet)")
    con.close()

    # The graph ingest keeps only identity + a filter column (risk_score). The
    # source rows still carry full_address, but the NodeSpec.properties list
    # does not include it, so it never becomes a graph property.
    source_rows = [
        {"node_id": "b1", "label": "bank", "risk_score": 90,
         "party_name": "Acme Bank", "full_address": "1 Market St, San Francisco"},
        {"node_id": "b2", "label": "bank", "risk_score": 40,
         "party_name": "Beta Bank", "full_address": "9 King St, London"},
    ]
    spec = NodeSpec(sql="", id="node_id", id_property="NODE",
                    label_column="label", label_property="LABEL",
                    properties=["risk_score"])  # skinny: full_address excluded
    ingested_props = set()
    for batch in node_batches(spec, source_rows):
        for r in batch.params["rows"]:
            ingested_props |= set(r["props"])
    assert ingested_props == {"risk_score"}
    assert "full_address" not in ingested_props   # never entered the graph

    # A Cypher result can only carry what the graph holds: NODE + risk_score.
    cypher_result = [{"NODE": "b1", "risk_score": 90},
                     {"NODE": "b2", "risk_score": 40}]
    assert all("full_address" not in r for r in cypher_result)

    # Hydration surfaces the never-ingested column, joined by NODE.
    enriched = hydrate(cypher_result, str(p), key="NODE")
    assert enriched[0]["full_address"] == "1 Market St, San Francisco"
    assert enriched[1]["full_address"] == "9 King St, London"
    assert enriched[0]["risk_score"] == 90        # graph column still present


def test_run_hydrated_joins_cypher_output_to_wide_file(tmp_path):
    # Two user inputs only: a Cypher query and a post-join SQL. The Cypher
    # result is exposed to DuckDB as `cypher`; the wide file as `wide`.
    p = tmp_path / "vertexes.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        ('b1', 'Acme Bank', '1 Market St, SF'),
        ('b2', 'Beta Bank', '9 King St, London')
    ) AS v(NODE, party_name, full_address)""")
    con.execute(f"COPY t TO '{p}' (FORMAT parquet)")
    con.close()

    graph = _FakeGraph(_FakeQR(
        header=[[1, "NODE"], [1, "risk"]],
        result_set=[["b1", 90], ["b2", 40]],
    ))
    cypher = ("MATCH (a:bank)-[:performed]->(w:wire_message) "
              "RETURN a.NODE AS NODE, w.wire_message_risk_score AS risk")
    join_sql = ("SELECT c.NODE, c.risk, w.party_name, w.full_address "
                "FROM cypher c JOIN wide w USING (NODE) ORDER BY c.NODE")

    out = run_hydrated(cypher, join_sql, falkordb=graph, source=str(p))

    assert graph.queries == [cypher]            # the Cypher was executed
    assert out == [
        {"NODE": "b1", "risk": 90, "party_name": "Acme Bank",
         "full_address": "1 Market St, SF"},
        {"NODE": "b2", "risk": 40, "party_name": "Beta Bank",
         "full_address": "9 King St, London"},
    ]


def test_run_hydrated_empty_cypher_result_returns_empty():
    graph = _FakeGraph(_FakeQR(header=[[1, "NODE"]], result_set=[]))
    out = run_hydrated("MATCH (n) RETURN n.NODE AS NODE",
                       "SELECT * FROM cypher c JOIN wide w USING (NODE)",
                       falkordb=graph, source="unused.parquet")
    assert out == []


def test_run_hydrated_rejects_unsafe_relation_name():
    graph = _FakeGraph(_FakeQR(header=[[1, "NODE"]], result_set=[["b1"]]))
    with pytest.raises(ValueError):
        run_hydrated("MATCH (n) RETURN n.NODE AS NODE", "SELECT 1",
                     falkordb=graph, source="f.parquet",
                     cypher_relation="c; DROP")
