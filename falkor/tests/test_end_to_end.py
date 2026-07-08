import os
import pytest
from graph_loader.config import Mapping, NodeSpec, EdgeSpec
from graph_loader.cli import run_build
from graph_loader.falkordb_sink import FalkorDBSink

BANK_ID = "d8d3cb99-0e3b-45b4-8221-79e8425065f3"


class _FakeSource:
    def rows(self, sql):
        if "vertexes" in sql:
            return iter([
                {"node_id": BANK_ID, "label": "bank", "bank_name": "Acme Bank",
                 "bank_risk_score": 0.3, "banking_transaction_amount": None,
                 "wire_message_risk_score": None, "party_risk_score": None, "party_name": None},
                {"node_id": "w7", "label": "wire_message", "wire_message_risk_score": 0.9,
                 "bank_name": None, "bank_risk_score": None, "banking_transaction_amount": None,
                 "party_risk_score": None, "party_name": None},
                {"node_id": "t3", "label": "banking_transaction", "banking_transaction_amount": 1000.0,
                 "bank_name": None, "bank_risk_score": None, "wire_message_risk_score": None,
                 "party_risk_score": None, "party_name": None},
            ])
        return iter([
            {"edge_id": "e1", "node1": BANK_ID, "node2": "w7", "label": "performed"},
            {"edge_id": "e2", "node1": "w7", "node2": "t3", "label": "is_for_transaction"},
        ])


def _mapping():
    props = ["banking_transaction_amount", "wire_message_risk_score", "party_risk_score",
             "party_name", "bank_name", "bank_risk_score"]
    return Mapping(
        graph="loader_e2e_test",
        nodes=[NodeSpec(sql="SELECT ... FROM expero.vertexes", id="node_id",
                        id_property="NODE", label_column="label",
                        label_property="LABEL", properties=props)],
        edges=[EdgeSpec(sql="SELECT ... FROM expero.edges", id="edge_id",
                        id_property="ID", type_column="label", type_property="LABEL",
                        source_key="node1", target_key="node2", properties=[])],
        node_key_property="NODE",
    )


@pytest.fixture
def sink():
    try:
        s = FalkorDBSink.connect(
            "loader_e2e_test",
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            password=os.environ.get("FALKORDB_PASSWORD"),
        )
        s.run("RETURN 1")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"FalkorDB not reachable: {exc}")
    yield s
    s.wipe()


def test_end_to_end_sample_query(sink):
    counts = run_build(_mapping(), _FakeSource(), sink)
    assert counts["nodes"] == {"bank": 1, "wire_message": 1, "banking_transaction": 1}
    assert counts["edges"] == {"performed": 1, "is_for_transaction": 1}

    # User's multi-hop query, in FalkorDB's WHERE-after-MATCH form.
    result = sink.run(
        """
        MATCH (a:bank)-[ab:performed]->(b:wire_message)-[bc:is_for_transaction]->(c:banking_transaction)
        WHERE a.NODE = $bank_id
        RETURN a.bank_name AS bank, b.NODE AS wire, ab.LABEL AS ablabel,
               c.NODE AS transaction, c.banking_transaction_amount AS amount,
               b.wire_message_risk_score AS risk,
               a.wire_message_risk_score AS bank_wrong, b.bank_name AS wire_wrong
        """,
        {"bank_id": BANK_ID},
    )
    assert result.result_set == [["Acme Bank", "w7", "performed", "t3", 1000.0, 0.9, None, None]]
