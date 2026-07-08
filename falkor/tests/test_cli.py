from graph_loader.config import Mapping, NodeSpec, EdgeSpec
from graph_loader.cli import run_build


class _FakeSource:
    def rows(self, sql):
        if "vertexes" in sql:
            return iter([
                {"node_id": "b1", "label": "bank", "bank_name": "Acme"},
                {"node_id": "w1", "label": "wire_message", "bank_name": None},
            ])
        return iter([{"edge_id": "e1", "node1": "b1", "node2": "w1", "label": "performed"}])


class _FakeResult:
    """Mimics a falkordb QueryResult's write-stats. Simulates every unwound
    row being created, so counts reflect result stats (not source rows)."""

    def __init__(self, params):
        n = len(params["rows"]) if params and "rows" in params else 0
        self.nodes_created = n
        self.relationships_created = n


class _RecordingSink:
    def __init__(self):
        self.queries = []
        self.wiped = False

    def wipe(self):
        self.wiped = True

    def run(self, query, params=None):
        self.queries.append((query, params))
        return _FakeResult(params)


def _mapping():
    return Mapping(
        graph="g",
        nodes=[NodeSpec(sql="SELECT ... FROM expero.vertexes", id="node_id",
                        id_property="NODE", label_column="label",
                        label_property="LABEL", properties=["bank_name"])],
        edges=[EdgeSpec(sql="SELECT ... FROM expero.edges", id="edge_id",
                        id_property="ID", type_column="label", type_property="LABEL",
                        source_key="node1", target_key="node2", properties=[])],
        node_key_property="NODE",
    )


def test_run_build_wipes_indexes_and_counts():
    sink = _RecordingSink()
    counts = run_build(_mapping(), _FakeSource(), sink)
    assert sink.wiped is True
    joined = " ".join(q for q, _ in sink.queries)
    assert "CREATE INDEX FOR (n:Entity) ON (n.NODE)" in joined
    assert "CREATE INDEX FOR (n:bank) ON (n.NODE)" in joined
    assert "MERGE (a)-[r:performed" in joined
    assert counts == {"nodes": {"bank": 1, "wire_message": 1}, "edges": {"performed": 1}}
