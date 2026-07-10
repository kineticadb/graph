import duckdb
import pytest

from graph_loader.cli import run_build
from graph_loader.config import EdgeSpec, Mapping, NodeSpec
from graph_loader.duckdb_source import DuckDBSource


def _write_parquet(path, create_sql):
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t AS {create_sql}")
    con.execute(f"COPY t TO '{path}' (FORMAT parquet)")
    con.close()


def _vertexes(tmp_path):
    p = tmp_path / "vertexes.parquet"
    _write_parquet(p, """SELECT * FROM (VALUES
        ('b1', 'bank'), ('w1', 'wire_message'), ('b2', 'bank')
    ) AS v(id, label)""")
    return str(p)


def test_rows_runs_mapping_sql_against_registered_view(tmp_path):
    # The mapping's own SQL ("... FROM expero.vertexes") runs unchanged because
    # the table name is registered as a view over the Parquet file.
    src = DuckDBSource.connect({"expero.vertexes": _vertexes(tmp_path)})
    out = list(src.rows(
        "SELECT id AS node_id, label AS label FROM expero.vertexes ORDER BY id"))
    assert out == [
        {"node_id": "b1", "label": "bank"},
        {"node_id": "b2", "label": "bank"},
        {"node_id": "w1", "label": "wire_message"},
    ]
    assert all(isinstance(r, dict) for r in out)


def test_rows_pages_through_full_result_via_fetchmany(tmp_path):
    # A page size below the row count must still yield every row (no truncation).
    src = DuckDBSource.connect({"expero.vertexes": _vertexes(tmp_path)}, page_size=2)
    out = list(src.rows("SELECT id FROM expero.vertexes ORDER BY id"))
    assert [r["id"] for r in out] == ["b1", "b2", "w1"]


def test_rows_coerces_decimal_to_float(tmp_path):
    # DECIMAL columns come back from DuckDB as Python Decimal, which the
    # FalkorDB client can't serialise -- rows() must hand back plain floats.
    p = tmp_path / "amounts.parquet"
    _write_parquet(p, "SELECT * FROM (VALUES ('b1', 10.5), ('b2', 3.0)) AS v(id, amount)")
    src = DuckDBSource.connect({"expero.vertexes": str(p)})
    out = list(src.rows("SELECT id, amount FROM expero.vertexes ORDER BY id"))
    assert out[0]["amount"] == 10.5
    assert all(isinstance(r["amount"], float) for r in out)


def test_connect_rejects_unsafe_table_name(tmp_path):
    with pytest.raises(ValueError):
        DuckDBSource.connect({"expero.vertexes; DROP": _vertexes(tmp_path)})


def test_end_to_end_build_with_no_kinetica(tmp_path):
    # The whole loader runs off files: DuckDBSource -> run_build -> (fake) sink.
    verts = _vertexes(tmp_path)
    edges = tmp_path / "edges.parquet"
    _write_parquet(edges, """SELECT * FROM (VALUES
        ('e1', 'b1', 'w1', 'performed')
    ) AS e(id, source_name, target_name, label)""")

    mapping = Mapping(
        graph="g",
        nodes=[NodeSpec(
            sql="SELECT id AS node_id, label AS label FROM expero.vertexes",
            id="node_id", id_property="NODE", label_column="label",
            label_property="LABEL", properties=[])],
        edges=[EdgeSpec(
            sql=("SELECT id AS edge_id, source_name AS node1, "
                 "target_name AS node2, label AS label FROM expero.edges"),
            id="edge_id", id_property="ID", type_column="label",
            type_property="LABEL", source_key="node1", target_key="node2",
            properties=[])],
        node_key_property="NODE",
    )
    source = DuckDBSource.connect(
        {"expero.vertexes": verts, "expero.edges": str(edges)})

    class _Result:
        def __init__(self, params):
            n = len(params["rows"]) if params and "rows" in params else 0
            self.nodes_created = n
            self.relationships_created = n

    class _Sink:
        def __init__(self):
            self.wiped = False
        def wipe(self):
            self.wiped = True
        def run(self, query, params=None):
            return _Result(params)

    counts = run_build(mapping, source, _Sink())
    assert counts == {"nodes": {"bank": 2, "wire_message": 1},
                      "edges": {"performed": 1}}
