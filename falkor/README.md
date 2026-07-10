# falkor — Kinetica → FalkorDB graph demo

Mirror a Kinetica graph (`expero.banking_graph`) into **FalkorDB** and run graph queries
against it, validated to return the *same* results as Kinetica.

- **FalkorDB** runs on-prem via Docker (data on `:6379`, Browser UI on `:3000`).
- A small Python **loader** reads Kinetica tables via SQL and rebuilds the FalkorDB graph
  from an editable YAML mapping (`mapping.yaml`).
- Three benchmark tests assert FalkorDB reproduces Kinetica's graph-query results exactly.
- Optionally, build **and** query with **no Kinetica** at all — source rows from Parquet/CSV
  via DuckDB, and keep the graph lean by hydrating wide columns after a query
  (see [Lean graph without Kinetica](#lean-graph-without-kinetica-the-duckdb-route)).

## Prerequisites

- Ubuntu 24.04 host
- A reachable Kinetica instance with `expero.vertexes` / `expero.edges` loaded
- Python 3.9+

## Setup (fresh clone)

```bash
# 1. Install Docker (once, if not already present)
./install-docker.sh
newgrp docker                     # apply docker-group membership without re-login

# 2. Configure credentials — copy the template, then EDIT with real values
cp .env.example .env
#    set in .env:
#      KINETICA_URL=http://127.0.0.1:9191
#      KINETICA_USER=admin
#      KINETICA_PASS=...
#      FALKORDB_PASSWORD=...        # any strong password; FalkorDB will require it

# 3. Start FalkorDB (reads FALKORDB_PASSWORD from .env)
./setup-falkordb.sh               # compose up, waits for healthcheck, runs a smoke test

# 4. Python environment
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 5. Build the graph from Kinetica (full wipe + rebuild)
.venv/bin/python build-graph.py   # prints per-label node counts and per-type edge counts

# 6. Verify (42 tests; benchmarks assert Kinetica ground truth)
.venv/bin/pytest -v
```

> `.env.example` is a **template you copy**, not a file you run. The Python tools load `.env`
> automatically (via `python-dotenv`), so you do **not** need to `source` it for
> `build-graph.py` / `pytest`. Only pull the vars into your shell
> (`set -a; . ./.env; set +a`) when running ad-hoc `redis-cli` or inline Python snippets.

## Explore the graph

**Browser UI:** open <http://localhost:3000>, pick the `banking_graph` from the graph
dropdown (▼ next to the graph name — no need to type it), and run Cypher.

**Count nodes by label:**
```bash
.venv/bin/python count-nodes.py            # all labels with counts
.venv/bin/python count-nodes.py bank       # a single label
```

**Trace parties behind a bank's high-risk wires:**
```bash
.venv/bin/python query-paths.py <bank_node_id> --min-risk 20
```

## Example queries (Kinetica GQL → FalkorDB Cypher)

The graph model: node identity is the `NODE` property, a row's `label` is the Cypher label
(+ a `LABEL` property), and every node also carries a shared `:Entity` label (indexed on
`NODE`) so edges match fast.

**Aggregation — total transaction amount per wire for a bank** (Kinetica `graph_table(...)`
+ `GROUP BY 1,2 ORDER BY 3 DESC` → Cypher implicit grouping):
```cypher
MATCH (a:bank)-[:performed]->(b:wire_message)-[:is_for_transaction]->(c:banking_transaction)
WHERE a.bank_name = 'Harvey Group'
RETURN b.NODE AS wire, b.wire_message_risk_score AS risk,
       round(sum(c.banking_transaction_amount)) AS total
ORDER BY total DESC
```

**Visualize the same subgraph** — return the *path* (graph objects), not aggregates, so the
Browser draws the node-link picture; add per-hop filters in the `WHERE`:
```cypher
MATCH p=(a:bank)-[:performed]->(b:wire_message)-[:is_for_transaction]->(c:banking_transaction)
WHERE a.bank_name = 'Harvey Group'
  AND b.wire_message_risk_score > 20
RETURN p
```

Translation rules: inline node predicates (`(a:bank WHERE …)`) move to one `WHERE` after the
`MATCH`; `GROUP BY` is implicit (the non-aggregated `RETURN` keys); `JOIN`s become traversals;
window/rollup/cube aren't supported (keep those in Kinetica). More detail and worked examples
in `CLAUDE.md` and `tests/test_benchmark_banking.py`.

## Lean graph without Kinetica: the DuckDB route

You can build **and** query without ever contacting Kinetica, and keep FalkorDB memory
small by leaving attribute-rich columns out of the graph. The graph holds only identity +
the columns you traverse/filter on; the wide columns stay in a Parquet/CSV file and are
joined back **after** a query returns.

Why: making every column a node property bloats FalkorDB (the per-node cost is the *values*).
Keep the graph skinny, hydrate the rest on demand.

The end-to-end flow:

```
Parquet/CSV ──DuckDB──► FalkorDB graph ──Cypher──► NODE ids ──DuckDB SQL join──► final result
 (wide table)  (build)   (skinny: id +   (traversal)  (small     (hydrate wide      (rows +
                          filter cols)                  set)       cols by id)        attributes)
```

**Step 1 — point the loader at files instead of Kinetica.** In `mapping.yaml`, uncomment the
`duckdb:` block and map each table used in the node/edge SQL to a file (local path, glob, or
`s3://` URL). The node/edge SQL itself is reused unchanged — each table becomes a DuckDB view.

```yaml
duckdb:
  tables:
    expero.vertexes: data/vertexes.parquet
    expero.edges: data/edges.parquet
hydrate:
  source: data/vertexes.parquet   # the WIDE file (all attribute columns)
  key: NODE
```

Keep the graph skinny: list only identity + filter/sort columns under each node's `properties:`.
Leave the attribute-rich columns out — they live in the hydrate file.

**Step 2 — build the FalkorDB graph from files (no Kinetica):**

```bash
.venv/bin/python build-graph.py --config mapping.yaml --source duckdb
```

**Step 3 — run Cypher.** The traversal runs entirely in FalkorDB and returns a small set of
`NODE` ids (plus any graph columns). It does **not** touch the wide file — so anything you
filter on in the `MATCH`/`WHERE` must be a graph property.

```python
res = falkordb.query(
    "MATCH (a:bank)-[:performed]->(w:wire_message) "
    "WHERE w.wire_message_risk_score > 20 "
    "RETURN a.NODE AS NODE, w.wire_message_risk_score AS risk"
).result_set
cypher_rows = [{"NODE": r[0], "risk": r[1]} for r in res]
```

**Step 4 — SQL join / hydration (only the ids you need).** `hydrate()` reads just those ids'
wide columns from the Parquet/CSV via DuckDB and merges them onto the result rows. Only the
selected columns are read, and the wide table never fully lands in RAM.

```python
from graph_loader.hydrate import hydrate

final = hydrate(cypher_rows, "data/vertexes.parquet", key="NODE")
# final: each row = its Cypher columns (NODE, risk) + the wide attributes
#        (party_name, full_address, …) that were never stored in the graph.
```

**Step 5 — final result.** Rows carry both the graph columns and the hydrated attributes.
Need heavier analytics (window functions, `ROLLUP`) that Cypher can't express? Run them in the
same DuckDB step — it speaks standard SQL over the joined result, still offline.

**One‑call form (steps 3–5).** `run_hydrated` takes your two inputs — the Cypher and the
post‑join SQL — runs the traversal, exposes its result to DuckDB as `cypher`, the wide file as
`wide`, and returns the joined rows:

```python
from graph_loader.hydrate import run_hydrated

final = run_hydrated(
    "MATCH (a:bank)-[:performed]->(w:wire_message) "
    "WHERE w.wire_message_risk_score > 20 "
    "RETURN a.NODE AS NODE, w.wire_message_risk_score AS risk",          # INPUT 1
    "SELECT c.NODE, c.risk, w.party_name, w.full_address "
    "FROM cypher c JOIN wide w USING (NODE) ORDER BY c.risk DESC",       # INPUT 2
    falkordb=graph, source="data/vertexes.parquet",
)
```

Notes: the returned ids are scattered, so DuckDB's win here is column projection + out-of-core
reads, not row-group pruning (that only matters for remote/cold files). Numeric columns are
coerced to `float` on the way out so the FalkorDB client accepts them.

## Lifecycle

```bash
docker compose ps                 # status
docker compose logs -f falkordb   # logs
docker compose down               # stop (data kept in the falkordb-data volume)
docker compose down -v            # stop AND delete the data volume
```

## Layout

- `graph_loader/` — the loader package (`config`, `mapper`, `kinetica_source`, `duckdb_source`,
  `falkordb_sink`, `hydrate`, `cli`)
- `mapping.yaml` — table→graph mapping (edit to change the model; no code changes)
- `build-graph.py`, `count-nodes.py`, `query-paths.py` — entry-point scripts
- `tests/` — unit + live-integration + Kinetica-benchmark tests
- `docs/superpowers/` — design spec and implementation plan
- `CLAUDE.md` — architecture, conventions, and gotchas for future work
