# Kinetica → FalkorDB Graph Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that reads `expero.vertexes` / `expero.edges` from Kinetica via SQL and rebuilds a FalkorDB graph, driven by an editable YAML mapping.

**Architecture:** A Python loader process bridges two connections — it pulls rows from Kinetica (`gpudb`) and writes them to FalkorDB (`falkordb`) as parameterized Cypher. A pure `mapper` module translates `(rows, spec)` → Cypher; `config` validates the YAML; `cli` orchestrates a full wipe-and-rebuild. FalkorDB never contacts Kinetica.

**Tech Stack:** Python 3.9+, `gpudb`, `falkordb`, `pyyaml`, `python-dotenv`, `pytest`.

## Global Constraints

- Python 3.9+ (Ubuntu 24.04 ships 3.12). Use a repo-local virtualenv at `.venv`; run tests with `.venv/bin/pytest`.
- **Cypher safety:** never string-interpolate a value into Cypher unless it passed `mapper.safe_ident()` (validates `^[A-Za-z0-9_]+$`). All data values are passed as query **parameters**, never interpolated.
- **Full-rebuild semantics:** every run wipes the target graph, then rebuilds. No incremental sync.
- Credentials come from `.env` (gitignored): `KINETICA_URL`, `KINETICA_USER`, `KINETICA_PASS`, `FALKORDB_PASSWORD` (and optional `FALKORDB_HOST`/`FALKORDB_PORT`, default `localhost`/`6379`). Loaded via `python-dotenv`.
- **FalkorDB Cypher uses the `WHERE`-after-`MATCH` form.** The inline node-pattern predicate `MATCH (a:bank WHERE a.NODE = …)` is Kinetica-specific; in FalkorDB write `MATCH (a:bank)-[…]->(…) WHERE a.NODE = … RETURN …`.
- Node identity → property `NODE`; edge identity → property `ID`; label → the Cypher label/type **and** a `LABEL` property. Every node also gets a shared `:Entity` label; the id index lives on `:Entity(NODE)`.

---

### Task 1: Project scaffolding + dependencies

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `conftest.py`, `graph_loader/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`
- Modify: `.gitignore` (add `.venv/`, `__pycache__/`, `*.pyc`)

**Interfaces:**
- Produces: an importable `graph_loader` package and a working `.venv/bin/pytest`.

- [ ] **Step 1: Create `requirements.txt`**

```
gpudb
falkordb
pyyaml
python-dotenv
pytest
```

- [ ] **Step 2: Create `pytest.ini`** (makes `graph_loader` importable from repo root)

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 3: Create `conftest.py`** (loads `.env` so integration tests get `FALKORDB_PASSWORD`)

```python
from dotenv import load_dotenv

load_dotenv()
```

- [ ] **Step 4: Create empty `graph_loader/__init__.py` and `tests/__init__.py`**

```python
# graph_loader/__init__.py
```
```python
# tests/__init__.py
```

- [ ] **Step 5: Add ignores to `.gitignore`** (append these lines)

```
.venv/
__pycache__/
*.pyc
```

- [ ] **Step 6: Write a smoke test `tests/test_smoke.py`**

```python
def test_package_imports():
    import graph_loader  # noqa: F401
```

- [ ] **Step 7: Create the venv and install**

Run:
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Expected: installs `gpudb`, `falkordb`, `pyyaml`, `python-dotenv`, `pytest` without error.

- [ ] **Step 8: Run the smoke test**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 9: Commit**

```bash
git add requirements.txt pytest.ini conftest.py graph_loader tests .gitignore
git commit -m "chore: scaffold graph_loader package and test harness"
```

---

### Task 2: Config loader + dataclasses + validation

**Files:**
- Create: `graph_loader/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `NodeSpec(sql, id, id_property, label_column, label_property, properties)`
  - `EdgeSpec(sql, id, id_property, type_column, type_property, source_key, target_key, properties)`
  - `Mapping(graph, nodes: list[NodeSpec], edges: list[EdgeSpec], node_key_property: str)`
  - `load_mapping(path: str) -> Mapping`
  - `ConfigError(Exception)`

- [ ] **Step 1: Write failing tests `tests/test_config.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with "No module named 'graph_loader.config'".

- [ ] **Step 3: Implement `graph_loader/config.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import yaml


class ConfigError(Exception):
    """Raised when the mapping YAML is missing keys or malformed."""


@dataclass
class NodeSpec:
    sql: str
    id: str
    id_property: str
    label_column: str
    label_property: str
    properties: List[str]


@dataclass
class EdgeSpec:
    sql: str
    id: str
    id_property: str
    type_column: str
    type_property: str
    source_key: str
    target_key: str
    properties: List[str]


@dataclass
class Mapping:
    graph: str
    nodes: List[NodeSpec]
    edges: List[EdgeSpec]
    node_key_property: str


def _require(d: dict, key: str, ctx: str):
    if not isinstance(d, dict) or key not in d:
        raise ConfigError(f"{ctx}: missing required key '{key}'")
    return d[key]


def load_mapping(path: str) -> Mapping:
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ConfigError("mapping file must be a YAML mapping/object")

    graph = _require(raw, "graph", "top level")
    nodes_raw = _require(raw, "nodes", "top level")
    if not nodes_raw:
        raise ConfigError("at least one node spec is required")

    nodes = []
    for i, n in enumerate(nodes_raw):
        ctx = f"nodes[{i}]"
        nodes.append(NodeSpec(
            sql=_require(n, "sql", ctx),
            id=_require(n, "id", ctx),
            id_property=n.get("id_property", "NODE"),
            label_column=_require(n, "label_column", ctx),
            label_property=n.get("label_property", "LABEL"),
            properties=list(n.get("properties", [])),
        ))

    key_props = {n.id_property for n in nodes}
    if len(key_props) != 1:
        raise ConfigError(
            f"all node specs must share one id_property; found {sorted(key_props)}"
        )
    node_key_property = next(iter(key_props))

    edges = []
    for i, e in enumerate(raw.get("edges", []) or []):
        ctx = f"edges[{i}]"
        edges.append(EdgeSpec(
            sql=_require(e, "sql", ctx),
            id=_require(e, "id", ctx),
            id_property=e.get("id_property", "ID"),
            type_column=_require(e, "type_column", ctx),
            type_property=e.get("type_property", "LABEL"),
            source_key=_require(e, "source_key", ctx),
            target_key=_require(e, "target_key", ctx),
            properties=list(e.get("properties", [])),
        ))

    return Mapping(graph=graph, nodes=nodes, edges=edges,
                   node_key_property=node_key_property)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add graph_loader/config.py tests/test_config.py
git commit -m "feat: mapping config loader with validation"
```

---

### Task 3: Mapper — safe_ident + node_batches + indexes

**Files:**
- Create: `graph_loader/mapper.py`, `tests/test_mapper.py`

**Interfaces:**
- Consumes: `graph_loader.config.NodeSpec`
- Produces:
  - `MappingError(Exception)`
  - `safe_ident(value) -> str`
  - `CypherBatch(query: str, params: dict)`
  - `node_batches(spec: NodeSpec, rows: list[dict], batch_size: int = 5000) -> list[CypherBatch]`
  - `entity_index_statement(node_key_property: str) -> str`
  - `label_index_statements(node_key_property: str, labels: list[str]) -> list[str]`

- [ ] **Step 1: Write failing tests `tests/test_mapper.py`**

```python
import pytest
from graph_loader.config import NodeSpec
from graph_loader import mapper


def _node_spec():
    return NodeSpec(
        sql="", id="node_id", id_property="NODE",
        label_column="label", label_property="LABEL",
        properties=["bank_name", "bank_risk_score"],
    )


def test_safe_ident_accepts_word():
    assert mapper.safe_ident("bank_message1") == "bank_message1"


@pytest.mark.parametrize("bad", ["a-b", "a b", "a;DROP", "", 3])
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mapper.py -v`
Expected: FAIL with "No module named 'graph_loader.mapper'".

- [ ] **Step 3: Implement `graph_loader/mapper.py`** (node half; edges added in Task 4)

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from .config import NodeSpec

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


class MappingError(Exception):
    """Raised when a label/type/identifier value is not a safe Cypher token."""


def safe_ident(value) -> str:
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise MappingError(f"unsafe identifier for Cypher: {value!r}")
    return value


@dataclass
class CypherBatch:
    query: str
    params: dict


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _props(row: dict, names: List[str]) -> Dict:
    return {name: row[name] for name in names if row.get(name) is not None}


def _group_by(rows: List[dict], column: str) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for row in rows:
        key = safe_ident(row[column])
        grouped.setdefault(key, []).append(row)
    return grouped


def node_batches(spec: NodeSpec, rows: List[dict], batch_size: int = 5000) -> List[CypherBatch]:
    idp = safe_ident(spec.id_property)
    lp = safe_ident(spec.label_property)
    batches: List[CypherBatch] = []
    for label, lrows in _group_by(rows, spec.label_column).items():
        query = (
            "UNWIND $rows AS row "
            f"MERGE (n:Entity {{{idp}: row.id}}) "
            f"SET n:{label}, n.{lp} = $label, n += row.props"
        )
        for chunk in _chunks(lrows, batch_size):
            payload = [{"id": r[spec.id], "props": _props(r, spec.properties)} for r in chunk]
            batches.append(CypherBatch(query=query, params={"rows": payload, "label": label}))
    return batches


def entity_index_statement(node_key_property: str) -> str:
    keyprop = safe_ident(node_key_property)
    return f"CREATE INDEX FOR (n:Entity) ON (n.{keyprop})"


def label_index_statements(node_key_property: str, labels: List[str]) -> List[str]:
    keyprop = safe_ident(node_key_property)
    return [f"CREATE INDEX FOR (n:{safe_ident(l)}) ON (n.{keyprop})" for l in labels]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_mapper.py -v`
Expected: PASS (all node/index/ident tests pass).

- [ ] **Step 5: Commit**

```bash
git add graph_loader/mapper.py tests/test_mapper.py
git commit -m "feat: mapper node batches, ident validation, index statements"
```

---

### Task 4: Mapper — edge_batches

**Files:**
- Modify: `graph_loader/mapper.py`
- Modify: `tests/test_mapper.py`

**Interfaces:**
- Consumes: `graph_loader.config.EdgeSpec`
- Produces: `edge_batches(spec: EdgeSpec, rows: list[dict], node_key_property: str, batch_size: int = 5000) -> list[CypherBatch]`

- [ ] **Step 1: Add failing tests to `tests/test_mapper.py`**

```python
from graph_loader.config import EdgeSpec


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_mapper.py -k edge -v`
Expected: FAIL with "module 'graph_loader.mapper' has no attribute 'edge_batches'".

- [ ] **Step 3: Add `edge_batches` to `graph_loader/mapper.py`** (append; add `EdgeSpec` to the config import line)

Change the import line at the top from `from .config import NodeSpec` to:
```python
from .config import EdgeSpec, NodeSpec
```
Then append:
```python
def edge_batches(spec: EdgeSpec, rows: List[dict], node_key_property: str,
                 batch_size: int = 5000) -> List[CypherBatch]:
    keyprop = safe_ident(node_key_property)
    idp = safe_ident(spec.id_property)
    tp = safe_ident(spec.type_property)
    batches: List[CypherBatch] = []
    for etype, erows in _group_by(rows, spec.type_column).items():
        query = (
            "UNWIND $rows AS row "
            f"MATCH (a:Entity {{{keyprop}: row.n1}}), (b:Entity {{{keyprop}: row.n2}}) "
            f"MERGE (a)-[r:{etype} {{{idp}: row.id}}]->(b) "
            f"SET r.{tp} = $type, r += row.props"
        )
        for chunk in _chunks(erows, batch_size):
            payload = [{"id": r[spec.id], "n1": r[spec.source_key],
                        "n2": r[spec.target_key], "props": _props(r, spec.properties)}
                       for r in chunk]
            batches.append(CypherBatch(query=query, params={"rows": payload, "type": etype}))
    return batches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_mapper.py -v`
Expected: PASS (all mapper tests).

- [ ] **Step 5: Commit**

```bash
git add graph_loader/mapper.py tests/test_mapper.py
git commit -m "feat: mapper edge batches"
```

---

### Task 5: Kinetica source

**Files:**
- Create: `graph_loader/kinetica_source.py`, `tests/test_kinetica_source.py`

**Interfaces:**
- Produces:
  - `KineticaSource(db)` — wraps a `gpudb.GPUdb`-like client
  - `KineticaSource.connect(url, username, password) -> KineticaSource`
  - `KineticaSource.rows(sql: str) -> Iterator[dict]`

- [ ] **Step 1: Write failing test `tests/test_kinetica_source.py`** (uses a fake client, no real DB)

```python
from collections import OrderedDict
from graph_loader.kinetica_source import KineticaSource


class _Resp:
    def __init__(self, records):
        self.records = records


class _FakeDB:
    def __init__(self, records):
        self._records = records
        self.calls = []

    def execute_sql(self, sql, **kwargs):
        self.calls.append((sql, kwargs))
        return _Resp(self._records)


def test_rows_yields_plain_dicts():
    fake = _FakeDB([OrderedDict([("node_id", "b1"), ("label", "bank")])])
    src = KineticaSource(fake)
    out = list(src.rows("SELECT ..."))
    assert out == [{"node_id": "b1", "label": "bank"}]
    assert fake.calls[0][0] == "SELECT ..."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kinetica_source.py -v`
Expected: FAIL with "No module named 'graph_loader.kinetica_source'".

- [ ] **Step 3: Implement `graph_loader/kinetica_source.py`**

```python
from __future__ import annotations

from typing import Iterator

import gpudb


class KineticaSource:
    """Runs SQL against Kinetica and yields rows as plain dicts."""

    def __init__(self, db):
        self._db = db

    @classmethod
    def connect(cls, url: str, username: str, password: str) -> "KineticaSource":
        return cls(gpudb.GPUdb(host=url, username=username, password=password))

    def rows(self, sql: str) -> Iterator[dict]:
        # limit=-9999 is Kinetica's convention for "return all rows".
        resp = self._db.execute_sql(sql, limit=-9999)
        for rec in resp.records:
            yield dict(rec)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_kinetica_source.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add graph_loader/kinetica_source.py tests/test_kinetica_source.py
git commit -m "feat: Kinetica SQL source"
```

---

### Task 6: FalkorDB sink (integration against the running local FalkorDB)

**Files:**
- Create: `graph_loader/falkordb_sink.py`, `tests/test_falkordb_sink.py`

**Interfaces:**
- Produces:
  - `FalkorDBSink(graph)` — wraps a `falkordb` graph handle
  - `FalkorDBSink.connect(graph_name, host="localhost", port=6379, password=None) -> FalkorDBSink`
  - `FalkorDBSink.wipe() -> None`
  - `FalkorDBSink.run(query, params=None)` — returns the falkordb query result

**Note:** This test talks to the FalkorDB started by `setup-falkordb.sh`. `conftest.py` loads `.env`, so `FALKORDB_PASSWORD` is available. The test uses a throwaway graph name and never touches `banking_graph` or `demo`.

- [ ] **Step 1: Write failing integration test `tests/test_falkordb_sink.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_falkordb_sink.py -v`
Expected: FAIL with "No module named 'graph_loader.falkordb_sink'".

- [ ] **Step 3: Implement `graph_loader/falkordb_sink.py`**

```python
from __future__ import annotations

from falkordb import FalkorDB


class FalkorDBSink:
    """Writes Cypher to a FalkorDB graph."""

    def __init__(self, graph):
        self._graph = graph

    @classmethod
    def connect(cls, graph_name: str, host: str = "localhost", port: int = 6379,
                password: str = None) -> "FalkorDBSink":
        db = FalkorDB(host=host, port=port, password=password)
        return cls(db.select_graph(graph_name))

    def wipe(self) -> None:
        try:
            self._graph.delete()
        except Exception:
            pass  # graph did not exist yet; nothing to wipe

    def run(self, query: str, params: dict = None):
        return self._graph.query(query, params or {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_falkordb_sink.py -v`
Expected: PASS (1 passed). If it SKIPS, start FalkorDB first: `sg docker -c './setup-falkordb.sh'` (or `./setup-falkordb.sh` in a shell with the docker group).

- [ ] **Step 5: Commit**

```bash
git add graph_loader/falkordb_sink.py tests/test_falkordb_sink.py
git commit -m "feat: FalkorDB sink with wipe and parameterized run"
```

---

### Task 7: CLI orchestration + mapping.yaml + .env wiring

**Files:**
- Create: `graph_loader/cli.py`, `build-graph.py`, `mapping.yaml`
- Modify: `.env.example` (add Kinetica keys), `.env` (add Kinetica keys — local only, not committed)

**Interfaces:**
- Consumes: `config.load_mapping`, `mapper.*`, `KineticaSource`, `FalkorDBSink`
- Produces:
  - `run_build(mapping, source, sink) -> dict` — returns `{"nodes": {label: count}, "edges": {type: count}}` (pure orchestration; source/sink injected for testability)
  - `build(mapping_path: str) -> dict` — loads `.env`, connects real source/sink, calls `run_build`
  - `main(argv=None)` — argparse entrypoint printing counts

- [ ] **Step 1: Write failing test for `run_build` in `tests/test_cli.py`** (fakes for source + sink; no DB)

```python
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


class _RecordingSink:
    def __init__(self):
        self.queries = []
        self.wiped = False

    def wipe(self):
        self.wiped = True

    def run(self, query, params=None):
        self.queries.append((query, params))


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL with "No module named 'graph_loader.cli'".

- [ ] **Step 3: Implement `graph_loader/cli.py`**

```python
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from . import mapper
from .config import load_mapping
from .falkordb_sink import FalkorDBSink
from .kinetica_source import KineticaSource


def run_build(mapping, source, sink) -> dict:
    counts = {"nodes": {}, "edges": {}}
    sink.wipe()
    sink.run(mapper.entity_index_statement(mapping.node_key_property))

    labels = set()
    for spec in mapping.nodes:
        rows = list(source.rows(spec.sql))
        for batch in mapper.node_batches(spec, rows):
            sink.run(batch.query, batch.params)
        for r in rows:
            label = r[spec.label_column]
            labels.add(label)
            counts["nodes"][label] = counts["nodes"].get(label, 0) + 1

    for stmt in mapper.label_index_statements(mapping.node_key_property, sorted(labels)):
        sink.run(stmt)

    for spec in mapping.edges:
        rows = list(source.rows(spec.sql))
        for batch in mapper.edge_batches(spec, rows, mapping.node_key_property):
            sink.run(batch.query, batch.params)
        for r in rows:
            etype = r[spec.type_column]
            counts["edges"][etype] = counts["edges"].get(etype, 0) + 1

    return counts


def build(mapping_path: str) -> dict:
    load_dotenv()
    mapping = load_mapping(mapping_path)
    source = KineticaSource.connect(
        os.environ["KINETICA_URL"],
        os.environ["KINETICA_USER"],
        os.environ["KINETICA_PASS"],
    )
    sink = FalkorDBSink.connect(
        mapping.graph,
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", "6379")),
        password=os.environ.get("FALKORDB_PASSWORD"),
    )
    return run_build(mapping, source, sink)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a FalkorDB graph from Kinetica tables")
    parser.add_argument("--config", default="mapping.yaml",
                        help="Path to the YAML mapping (default: mapping.yaml)")
    args = parser.parse_args(argv)
    counts = build(args.config)
    print("Loaded nodes:", counts["nodes"])
    print("Loaded edges:", counts["edges"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Create `build-graph.py` entrypoint**

```python
#!/usr/bin/env python3
from graph_loader.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Create `mapping.yaml`** (the real mapping for `expero`)

```yaml
graph: banking_graph

nodes:
  - sql: |
      SELECT
        id    AS node_id,
        label AS label,
        "banking_transaction:amount" AS banking_transaction_amount,
        "wire_message:risk_score"    AS wire_message_risk_score,
        "party:risk_score"           AS party_risk_score,
        "party:party_name"           AS party_name,
        "bank:bank_name"             AS bank_name,
        "bank:risk_score"            AS bank_risk_score
      FROM expero.vertexes
    id: node_id
    id_property: NODE
    label_column: label
    label_property: LABEL
    properties:
      - banking_transaction_amount
      - wire_message_risk_score
      - party_risk_score
      - party_name
      - bank_name
      - bank_risk_score

edges:
  - sql: |
      SELECT
        id          AS edge_id,
        source_name AS node1,
        target_name AS node2,
        label       AS label
      FROM expero.edges
    id: edge_id
    id_property: ID
    type_column: label
    type_property: LABEL
    source_key: node1
    target_key: node2
    properties: []
```

- [ ] **Step 7: Add Kinetica keys to `.env.example`** (append)

```
KINETICA_URL=https://your-instance.kinetica.com/
KINETICA_USER=change-me
KINETICA_PASS=change-me
```

- [ ] **Step 8: Add the same keys to your local `.env`** with real values (not committed — `.env` is gitignored). Edit `.env` and add `KINETICA_URL`, `KINETICA_USER`, `KINETICA_PASS`.

- [ ] **Step 9: Run the full unit suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all non-integration tests; sink test passes if FalkorDB is up).

- [ ] **Step 10: Commit** (note: `.env` is intentionally NOT staged)

```bash
git add graph_loader/cli.py build-graph.py mapping.yaml .env.example
git commit -m "feat: CLI orchestration, mapping.yaml, env wiring"
```

---

### Task 8: End-to-end integration test (fake Kinetica → real FalkorDB) proving the sample query

**Files:**
- Create: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `cli.run_build`, `FalkorDBSink`

**Note:** This proves the graph is queryable exactly as intended — it runs the user's multi-hop query (rewritten to FalkorDB's `WHERE`-after-`MATCH` form) and asserts the row.

- [ ] **Step 1: Write the end-to-end test `tests/test_end_to_end.py`**

```python
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
               b.wire_message_risk_score AS risk
        """,
        {"bank_id": BANK_ID},
    )
    assert result.result_set == [["Acme Bank", "w7", "performed", "t3", 1000.0, 0.9]]
```

- [ ] **Step 2: Run the test to verify it passes** (FalkorDB must be up)

Run: `.venv/bin/pytest tests/test_end_to_end.py -v`
Expected: PASS (1 passed) — proving nodes, edges, labels, `NODE`/`LABEL` properties, and the multi-hop traversal all work. If it SKIPS, start FalkorDB (`./setup-falkordb.sh`).

- [ ] **Step 3: Run the entire suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "test: end-to-end build proving the sample multi-hop query"
```

---

## Post-implementation: first real run

Once Kinetica creds are in `.env` and FalkorDB is up:

```bash
.venv/bin/python build-graph.py --config mapping.yaml
```

Expected output like:
```
Loaded nodes: {'bank': N, 'wire_message': N, 'party': N, 'banking_transaction': N}
Loaded edges: {'performed': N, 'is_for_transaction': N, ...}
```

Then query in the FalkorDB Browser (`http://localhost:3000`, graph `banking_graph`) or via
`redis-cli`, remembering FalkorDB's `WHERE`-after-`MATCH` form.
