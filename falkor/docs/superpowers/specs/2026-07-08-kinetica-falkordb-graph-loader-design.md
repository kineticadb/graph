# Kinetica → FalkorDB Graph Loader — Design

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation plan

## Goal

Pull data from Kinetica tables (`expero.vertexes`, `expero.edges`) via SQL and build a
graph in the local FalkorDB instance. The source data may change; each run does a
**full rebuild on demand** (query → wipe target graph → rebuild). The table→graph
mapping is expressed in an editable **YAML file** so the model can evolve without code
changes.

## Non-goals (YAGNI)

- No incremental / change-data-capture sync. Full rebuild only.
- No near-real-time streaming (no Kinetica table monitor).
- No off-the-shelf ETL tool.
- Atomic temp-graph swap is **deferred** (see Error Handling).

## Source data model

Node and edge data each live in a single table, with the label carried in a `label`
column (mirroring the existing Kinetica `expero.banking_graph` graph definition).

- `expero.vertexes`: `id` (node identifier), `label` (node type), plus label-namespaced
  property columns (`"party:party_name"`, `"bank:bank_name"`, `"banking_transaction:amount"`,
  `"wire_message:risk_score"`, `"party:risk_score"`, `"bank:risk_score"`). Rows have nulls
  for property columns that don't apply to their label.
- `expero.edges`: `id` (edge id), `source_name` / `target_name` (both hold the same
  identifier values as `expero.vertexes.id` — **confirmed**), `label` (relationship type).

### Target query conventions (drive the property names)

The graph must be queryable the same way as the source Kinetica graph. Example query the
user will run:

```cypher
MATCH (a:bank WHERE a.NODE = 'd8d3cb99-0e3b-45b4-8221-79e8425065f3')
      -[ab:performed]-> (b:wire_message)
      -[bc:is_for_transaction]-> (c:banking_transaction)
RETURN a.bank_name AS bank, b.NODE AS wire, ab.LABEL AS ablabel,
       c.NODE AS transaction, c.banking_transaction_amount, b.wire_message_risk_score
```

This dictates the mapping:

- **Node `label` → the Cypher label** (`(a:bank)`, `(c:banking_transaction)`, `(a:street_address)`).
  It is NOT modeled as a `{label:'...'}` property.
- **Node identity → property `NODE`** (queried as `a.NODE`, `b.NODE`).
- **Node attribute columns keep their aliased names** (`bank_name`, `wire_message_risk_score`,
  `banking_transaction_amount`, ...), queried directly (`a.bank_name`).
- **Edge `label` → the relationship type** (`-[ab:performed]->`) AND a property `LABEL`
  (queried as `ab.LABEL`).
- **Edge identity → property `ID`.**

## Architecture

A small Python pipeline in the `falkor/` repo: one generic runner driven by a YAML
mapping file. Five focused components:

| Component | Responsibility | Depends on |
|-----------|---------------|-----------|
| Config loader | Read + validate the YAML mapping; fail fast on errors | `pyyaml` |
| Kinetica source | Connect (URL+creds from `.env`), run each SQL, yield rows in batches | `gpudb` (Kinetica Python API) |
| FalkorDB sink | Connect, wipe target graph, run batched parameterized Cypher, create indexes | `falkordb` |
| Mapper | Turn `(rows, spec)` → Cypher + params for nodes and edges | pure Python (no I/O) |
| CLI | `build-graph.py --config mapping.yaml` — orchestrate the run, print counts | the above |

The Mapper is **pure** (rows in, Cypher/params out) so it is unit-testable without any
database.

## YAML mapping

```yaml
graph: banking_graph          # FalkorDB target graph

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
    id: node_id                # column holding node identity
    id_property: NODE          # stored in the graph as n.NODE
    label_column: label        # value becomes the node's Cypher label
    label_property: LABEL      # also stored as n.LABEL
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
    id: edge_id                # column holding edge identity
    id_property: ID            # stored in the graph as r.ID
    type_column: label         # value becomes the relationship type
    type_property: LABEL       # also stored as r.LABEL
    source_key: node1          # matches a node's NODE (id)
    target_key: node2
    properties: []             # no additional edge attributes in this source
```

Changing the graph model = editing this file; no Python changes.

## Two data-driven design decisions

### 1. Dynamic labels / types (label lives in a column)

Cypher cannot parameterize a label or relationship type (`MERGE (n:$label …)` is illegal).
The Mapper groups rows by the `label_column` (nodes) / `type_column` (edges) value and
emits one `UNWIND … MERGE` per distinct value, interpolating the label/type into the query
string. **Every value is validated against `^[A-Za-z0-9_]+$`** before interpolation to
prevent Cypher injection / syntax errors; a value that fails validation aborts the run with
a clear error.

The label value is *also* written as a property (`LABEL`) so Kinetica-style queries that
read `a.LABEL` / `ab.LABEL` keep working. Null attribute values are skipped automatically
(`SET n += row` drops null-valued keys in Cypher), so a `party` node does not receive
`bank_name`, etc.

### 2. Shared `Entity` label for edge matching

`expero.edges` does not name its endpoints' labels, so edge `MATCH` must be
label-agnostic. To keep it fast, every node gets a shared secondary label `Entity` in
addition to its own label, and an id index is placed on `:Entity(NODE)`. Per-label indexes
on `:<Label>(NODE)` are also created so the user's own label-scoped queries
(`MATCH (a:bank WHERE a.NODE = …)`) are fast too.

Generated Cypher (label/type values validated + interpolated):

- Index: `CREATE INDEX FOR (n:Entity) ON (n.NODE)`, plus `CREATE INDEX FOR (n:<Label>) ON (n.NODE)` per distinct node label.
- Node upsert (per label): `UNWIND $rows AS row MERGE (n:Entity {NODE: row.id}) SET n:<Label>, n.LABEL = row.label, n += row.props`
- Edge upsert (per type): `UNWIND $rows AS row MATCH (a:Entity {NODE: row.n1}), (b:Entity {NODE: row.n2}) MERGE (a)-[r:<Type> {ID: row.id}]->(b) SET r.LABEL = row.label, r += row.props`

Edges MERGE on `ID` so distinct parallel edges (same type between the same pair) are
preserved rather than collapsed.

## Data flow (one run)

1. Load + validate YAML (structure, required keys).
2. Connect to Kinetica and FalkorDB.
3. Wipe the target graph (clean slate for full rebuild).
4. Nodes first: for each node spec → run SQL → batch rows → group by label →
   `UNWIND … MERGE`. Create the `:Entity(NODE)` index and per-label `:(NODE)` indexes.
5. Edges second: for each edge spec → run SQL → batch → group by type → `UNWIND … MATCH … MERGE`.
6. Print counts (nodes per label, edges per type).

Nodes-before-edges + the `NODE` indexes make edge `MATCH`es fast. Batched `UNWIND`
(a few thousand rows per query) keeps it efficient over the wire.

## Credentials

Extend the existing `.env` (already gitignored):

```
KINETICA_URL=...
KINETICA_USER=...
KINETICA_PASS=...
# existing: FALKORDB_PASSWORD; FALKORDB_HOST/PORT default to localhost:6379
```

## Error handling

- Fail fast on: malformed YAML, missing required keys, a label/type value failing the
  `^[A-Za-z0-9_]+$` check, SQL errors (wrapped with which spec failed), connection failures.
- **Atomicity — deferred.** A full rebuild that fails midway leaves a partial graph. A
  future enhancement can build into a temp graph (`banking_graph__building`) and swap it in
  only on success. Not in the first version; flagged as a conscious choice.

## Testing

- **Unit:** Mapper (rows + spec → expected Cypher/params, including label grouping, `NODE`/
  `LABEL`/`ID` property naming, null skipping, label validation) and config validation. No DB.
- **Integration:** run the full pipeline against the running local FalkorDB using a small
  fake source (hardcoded rows) to confirm nodes + edges land, the sample multi-hop query
  from "Target query conventions" returns rows, and counts match.
- **Smoke:** one real small query against `expero.vertexes` / `expero.edges` end-to-end
  once Kinetica creds are wired.

## Dependencies

`gpudb` (Kinetica Python API), `falkordb`, `pyyaml`. Python virtualenv in the repo.
