# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`falkor` is (1) an on-prem **FalkorDB** deployment (Docker, Ubuntu 24.04) and (2) a Python
**graph loader** that reads Kinetica tables via SQL and rebuilds a FalkorDB graph from an
editable YAML mapping. It was built to mirror a Kinetica graph (`expero.banking_graph`) in
FalkorDB and validate that graph queries return identical results.

## Commands

```bash
# Deployment (once, on a fresh host)
./install-docker.sh          # Docker Engine + Compose (needs sudo)
newgrp docker                # apply docker-group membership without re-login
./setup-falkordb.sh          # start FalkorDB (compose up), wait for healthcheck, smoke test

# Loader (needs .env — see Credentials)
.venv/bin/python build-graph.py --config mapping.yaml   # full wipe + rebuild of banking_graph
.venv/bin/python count-nodes.py [LABEL]                 # node counts by label (or all labels)
.venv/bin/python query-paths.py <bank_node_id> --min-risk 20

# Tests
.venv/bin/pytest -v                                     # full suite
.venv/bin/pytest tests/test_mapper.py -v                # one file
.venv/bin/pytest tests/test_benchmark_banking.py -v     # Kinetica ground-truth benchmarks
```

Note: Bash tool shells here are not in the `docker` group, so `docker`/`redis-cli` calls
must be wrapped: `sg docker -c '<cmd>'`. This is NOT needed in a normal interactive shell
after `newgrp docker` / re-login. The FalkorDB *client* (port 6379) needs no docker group.

## Architecture

Full-rebuild-on-demand pipeline. FalkorDB never contacts Kinetica — the loader process
bridges two connections (Kinetica SQL in, FalkorDB Cypher out). Modules in `graph_loader/`:

- `config.py` — loads/validates the YAML mapping into `NodeSpec`/`EdgeSpec`/`Mapping` dataclasses.
- `mapper.py` — **pure** (rows + spec → Cypher + params); no I/O, fully unit-testable.
- `kinetica_source.py` — runs SQL against Kinetica, yields row dicts.
- `falkordb_sink.py` — connects, wipes, runs parameterized Cypher.
- `cli.py` — `run_build(mapping, source, sink)` orchestration (source/sink injected for tests);
  `build(path)` wires the real connectors from `.env`; `main()` is the CLI.

Data flow per run: wipe graph → create `:Entity(NODE)` index → load nodes (grouped by label)
→ create per-label `:(NODE)` indexes → load edges. Nodes before edges so edge `MATCH`es hit
the index.

### Graph model conventions (these drive query shape)

- Node identity → property **`NODE`**; edge identity → property **`ID`**.
- A row's `label` value becomes the **Cypher label** (`:bank`) AND a **`LABEL`** property.
  Edge `label` becomes the **relationship type** (`:performed`) AND a `LABEL` property.
- Every node also carries a shared **`:Entity`** label; the id index lives on `:Entity(NODE)`,
  so edges match endpoints label-agnostically. Per-label `:(NODE)` indexes support ad-hoc
  label-scoped queries.

## Kinetica GQL → FalkorDB Cypher translation

Kinetica graph queries (`GRAPH … MATCH … RETURN`, optionally wrapped in
`graph_table(...)` for SQL post-processing) convert to Cypher mechanically:

| Kinetica | FalkorDB Cypher |
|---|---|
| inline node predicate `(a:bank WHERE a.NODE = '…')` | drop it; put `a.NODE = '…'` in one `WHERE` **after** the whole `MATCH`, `AND`-joined with other hops' predicates |
| `graph_table(GRAPH … MATCH …)` wrapper | dropped — Cypher `MATCH` returns rows directly |
| `GROUP BY 1,2` | **implicit** — the non-aggregated `RETURN` keys are the grouping keys; there is NO `GROUP BY` keyword |
| `ROUND(SUM(amount),0)` | `round(sum(c.amount))` |
| `ORDER BY 3 DESC` (column number) | `ORDER BY <alias> DESC` |
| reversed edge `(e) <-[:manages]- (g)` | kept verbatim: `(e)<-[:manages]-(g)` |
| SQL `JOIN` | graph **traversal** — follow relationships, not joins |
| window fns / `ROLLUP` / `CUBE` | **not supported** in Cypher — keep that work in Kinetica |

FalkorDB uses the `WHERE`-after-`MATCH` form; the inline node-pattern predicate is
Kinetica-specific. Injected values (ids, thresholds) go in as query **parameters**
(`$bank_id`), never string-interpolated. See `tests/test_benchmark_banking.py` for three
worked conversions (a 65-path traversal, an 8-path per-hop-filtered traversal, and an
18-row `GROUP BY`/`ROUND(SUM)` aggregation) each asserted against Kinetica ground truth.

## Credentials

`.env` (gitignored; `.env.example` is the template): `KINETICA_URL`, `KINETICA_USER`,
`KINETICA_PASS`, `FALKORDB_PASSWORD`, optional `FALKORDB_HOST`/`FALKORDB_PORT`
(default `localhost`/`6379`). `conftest.py` loads `.env` so integration tests get the
password. FalkorDB runs with `requirepass` (auth required; user is the default Redis user).

## Gotchas / non-obvious constraints

- **Kinetica reads (`kinetica_source.py`):** use `execute_sql_and_decode(get_column_major=False)`
  — plain `execute_sql` leaves the response encoded (no usable `.records`), and the default
  column-major decode is not per-row. Page via `offset` while the response key
  `has_more_records` is true: `limit=-9999` does NOT mean "all rows" (it caps at the server's
  `max_get_records_size`, ~20k) and would silently truncate large tables.
- **Cypher safety (`mapper.py`):** labels/types can't be Cypher parameters, so any identifier
  interpolated into a query MUST pass `safe_ident()` (`^[A-Za-z0-9_]+$`, `fullmatch`). All data
  values are parameters.
- **Load counts** reflect graph elements actually created (query-result stats), not source-row
  counts — an edge whose endpoint node is missing creates nothing, so the counts surface
  dangling edges in the source data.
- **Testing:** unit tests (config, mapper, kinetica_source) need no services. `test_falkordb_sink.py`,
  `test_end_to_end.py`, and `test_benchmark_banking.py` hit the live FalkorDB and SKIP (not fail)
  if it's unreachable or `banking_graph` isn't loaded. Benchmarks require a prior `build-graph.py` run.

## Deployment notes

- `docker-compose.yml`: `falkordb/falkordb:latest`, port 6379 (data) + 3000 (Browser UI),
  named volume `falkordb-data`, AOF (`appendfsync everysec`) + RDB, `restart: unless-stopped`,
  auth via `REDIS_ARGS --requirepass ${FALKORDB_PASSWORD}`.
- Image pinned to `latest`; pin an explicit tag for reproducible deploys.
- Ports 6379/3000 are exposed to the LAN with password auth but no TLS — fine on a trusted
  network; add a firewall rule or TLS if reachable more broadly.
- Design/plan docs live in `docs/superpowers/specs/` and `docs/superpowers/plans/`.
