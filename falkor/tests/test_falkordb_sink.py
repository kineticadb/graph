import os
import pytest
from graph_loader.falkordb_sink import FalkorDBSink


@pytest.fixture
def sink():
    try:
        s = FalkorDBSink.connect(
            "loader_sink_test",
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            password=os.environ.get("FALKORDB_PASSWORD"),
        )
        s.run("RETURN 1")  # force a connection
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"FalkorDB not reachable: {exc}")
    yield s
    s.wipe()


def test_wipe_then_build_and_count(sink):
    sink.wipe()
    sink.run("CREATE INDEX FOR (n:Entity) ON (n.NODE)")
    sink.run(
        "UNWIND $rows AS row MERGE (n:Entity {NODE: row.id}) SET n:bank, n.LABEL = $label, n += row.props",
        {"rows": [{"id": "b1", "props": {"bank_name": "Acme"}}], "label": "bank"},
    )
    result = sink.run("MATCH (n:bank) RETURN n.NODE AS id, n.bank_name AS name")
    assert result.result_set == [["b1", "Acme"]]
