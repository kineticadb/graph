import textwrap
import pytest
from graph_loader.config import load_mapping, ConfigError


def _write(tmp_path, text):
    p = tmp_path / "mapping.yaml"
    p.write_text(textwrap.dedent(text))
    return str(p)


def test_load_valid_mapping(tmp_path):
    path = _write(tmp_path, """
        graph: banking_graph
        nodes:
          - sql: SELECT id AS node_id, label AS label FROM expero.vertexes
            id: node_id
            label_column: label
            properties: [bank_name]
        edges:
          - sql: SELECT id AS edge_id, source_name AS node1, target_name AS node2, label AS label FROM expero.edges
            id: edge_id
            type_column: label
            source_key: node1
            target_key: node2
    """)
    m = load_mapping(path)
    assert m.graph == "banking_graph"
    assert m.nodes[0].id_property == "NODE"          # default
    assert m.nodes[0].label_property == "LABEL"       # default
    assert m.nodes[0].properties == ["bank_name"]
    assert m.edges[0].id_property == "ID"             # default
    assert m.edges[0].type_property == "LABEL"        # default
    assert m.node_key_property == "NODE"


def test_missing_required_key_raises(tmp_path):
    path = _write(tmp_path, """
        graph: g
        nodes:
          - id: node_id
            label_column: label
    """)
    with pytest.raises(ConfigError) as e:
        load_mapping(path)
    assert "sql" in str(e.value)


def test_inconsistent_id_property_raises(tmp_path):
    path = _write(tmp_path, """
        graph: g
        nodes:
          - sql: s1
            id: n
            id_property: NODE
            label_column: label
          - sql: s2
            id: n
            id_property: VID
            label_column: label
    """)
    with pytest.raises(ConfigError):
        load_mapping(path)


def test_malformed_yaml_raises(tmp_path):
    path = _write(tmp_path, """
        graph: g
        nodes:
          - sql: "unterminated
    """)
    with pytest.raises(ConfigError):
        load_mapping(path)
