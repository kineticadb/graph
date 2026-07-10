import pytest
from graph_loader.config import EdgeSpec, NodeSpec
from graph_loader import mapper


def _node_spec():
    return NodeSpec(
        sql="", id="node_id", id_property="NODE",
        label_column="label", label_property="LABEL",
        properties=["bank_name", "bank_risk_score"],
    )


def test_safe_ident_accepts_word():
    assert mapper.safe_ident("bank_message1") == "bank_message1"


@pytest.mark.parametrize("bad", ["a-b", "a b", "a;DROP", "", 3, "abc\n", "\n"])
def test_safe_ident_rejects_bad(bad):
    with pytest.raises(mapper.MappingError):
        mapper.safe_ident(bad)


def test_node_batches_group_by_label_and_skip_nulls():
    rows = [
        {"node_id": "b1", "label": "bank", "bank_name": "Acme", "bank_risk_score": 0.3},
        {"node_id": "w1", "label": "wire_message", "bank_name": None, "bank_risk_score": None},
    ]
    batches = mapper.node_batches(_node_spec(), rows)
    by_label = {b.params["label"]: b for b in batches}
    assert set(by_label) == {"bank", "wire_message"}

    bank = by_label["bank"]
    assert "MERGE (n:Entity {NODE: row.id})" in bank.query
    assert "SET n:bank" in bank.query
    assert "n.LABEL = $label" in bank.query
    assert bank.params["rows"] == [{"id": "b1", "props": {"bank_name": "Acme", "bank_risk_score": 0.3}}]

    wire = by_label["wire_message"]
    assert wire.params["rows"] == [{"id": "w1", "props": {}}]  # nulls dropped


def test_node_batches_discards_rows_with_null_or_missing_id():
    rows = [
        {"node_id": "b1", "label": "bank", "bank_name": "Acme", "bank_risk_score": 0.3},
        {"node_id": None, "label": "bank", "bank_name": "NoId", "bank_risk_score": 0.9},
        {"label": "bank", "bank_name": "Missing", "bank_risk_score": 0.1},  # no node_id key
    ]
    batches = mapper.node_batches(_node_spec(), rows)
    ids = [r["id"] for b in batches for r in b.params["rows"]]
    assert ids == ["b1"]  # null and missing ids dropped


def _edge_spec():
    return EdgeSpec(
        sql="", id="edge_id", id_property="ID",
        type_column="label", type_property="LABEL",
        source_key="node1", target_key="node2", properties=[],
    )


def test_edge_batches_discards_rows_with_null_id_or_endpoint():
    rows = [
        {"edge_id": "e1", "node1": "b1", "node2": "w1", "label": "performed"},
        {"edge_id": None, "node1": "b1", "node2": "w1", "label": "performed"},  # null id
        {"edge_id": "e3", "node1": None, "node2": "w1", "label": "performed"},  # null source
        {"edge_id": "e4", "node1": "b1", "label": "performed"},                 # missing target
    ]
    batches = mapper.edge_batches(_edge_spec(), rows, node_key_property="NODE")
    ids = [r["id"] for b in batches for r in b.params["rows"]]
    assert ids == ["e1"]  # only the fully-identified edge survives


def test_node_batches_reject_unsafe_label():
    rows = [{"node_id": "x", "label": "bad-label", "bank_name": None, "bank_risk_score": None}]
    with pytest.raises(mapper.MappingError):
        mapper.node_batches(_node_spec(), rows)


def test_node_batches_chunking():
    rows = [{"node_id": str(i), "label": "bank", "bank_name": "n", "bank_risk_score": 1}
            for i in range(12)]
    batches = mapper.node_batches(_node_spec(), rows, batch_size=5)
    assert [len(b.params["rows"]) for b in batches] == [5, 5, 2]


def test_index_statements():
    assert mapper.entity_index_statement("NODE") == "CREATE INDEX FOR (n:Entity) ON (n.NODE)"
    stmts = mapper.label_index_statements("NODE", ["bank", "wire_message"])
    assert stmts == [
        "CREATE INDEX FOR (n:bank) ON (n.NODE)",
        "CREATE INDEX FOR (n:wire_message) ON (n.NODE)",
    ]


def _edge_spec():
    return EdgeSpec(
        sql="", id="edge_id", id_property="ID",
        type_column="label", type_property="LABEL",
        source_key="node1", target_key="node2", properties=[],
    )


def test_edge_batches_group_by_type():
    rows = [
        {"edge_id": "e1", "node1": "b1", "node2": "w1", "label": "performed"},
        {"edge_id": "e2", "node1": "w1", "node2": "t1", "label": "is_for_transaction"},
    ]
    batches = mapper.edge_batches(_edge_spec(), rows, node_key_property="NODE")
    by_type = {b.params["type"]: b for b in batches}
    assert set(by_type) == {"performed", "is_for_transaction"}

    perf = by_type["performed"]
    assert "MATCH (a:Entity {NODE: row.n1}), (b:Entity {NODE: row.n2})" in perf.query
    assert "MERGE (a)-[r:performed {ID: row.id}]->(b)" in perf.query
    assert "SET r.LABEL = $type" in perf.query
    assert perf.params["rows"] == [{"id": "e1", "n1": "b1", "n2": "w1", "props": {}}]


def test_edge_batches_reject_unsafe_type():
    rows = [{"edge_id": "e", "node1": "a", "node2": "b", "label": "bad type"}]
    with pytest.raises(mapper.MappingError):
        mapper.edge_batches(_edge_spec(), rows, node_key_property="NODE")
