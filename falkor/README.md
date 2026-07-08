# falkor — Kinetica → FalkorDB graph demo

Mirror a Kinetica graph (`expero.banking_graph`) into **FalkorDB** and run graph queries
against it, validated to return the *same* results as Kinetica.

- **FalkorDB** runs on-prem via Docker (data on `:6379`, Browser UI on `:3000`).
- A small Python **loader** reads Kinetica tables via SQL and rebuilds the FalkorDB graph
  from an editable YAML mapping (`mapping.yaml`).
- Three benchmark tests assert FalkorDB reproduces Kinetica's graph-query results exactly.

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

# 6. Verify (29 tests; benchmarks assert Kinetica ground truth)
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

## Lifecycle

```bash
docker compose ps                 # status
docker compose logs -f falkordb   # logs
docker compose down               # stop (data kept in the falkordb-data volume)
docker compose down -v            # stop AND delete the data volume
```

## Layout

- `graph_loader/` — the loader package (`config`, `mapper`, `kinetica_source`, `falkordb_sink`, `cli`)
- `mapping.yaml` — table→graph mapping (edit to change the model; no code changes)
- `build-graph.py`, `count-nodes.py`, `query-paths.py` — entry-point scripts
- `tests/` — unit + live-integration + Kinetica-benchmark tests
- `docs/superpowers/` — design spec and implementation plan
- `CLAUDE.md` — architecture, conventions, and gotchas for future work
