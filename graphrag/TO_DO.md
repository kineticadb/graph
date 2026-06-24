# TO_DO — kgr session handoff

**Project home:** `/home/kkaramete/github-graph/graph/graphrag` (git repo `kineticadb/graph`, branch `master`).
Launch Claude Code from here. **No git branches; the user does all check-ins** — leave work as uncommitted changes.
The old `/home/kkaramete/kgr` is a deprecated stale copy.

**Run it:** self-contained venv at `graphrag/.venv` (editable install of this package).
Invoke as `.venv/bin/kgr ...` from this directory. DB creds in `graphrag/.env` (gitignored).
(The old `/home/kkaramete/kgr/.venv` is obsolete — that whole directory can be deleted.)

## In flight (2026-06-23) — multi-label nodes + axis LABEL_KEY groupings

All implemented, **uncommitted on master**:
- `kgr.nodes.LABEL` is a multi-label vector (structural type + facets), e.g. Anthropic = `["Organization","AI","LLM"]`.
- Axes (`LABEL_KEY`) per label in `kgr.ontology.axis`; materialized to `kgr.label_keys`; fed to `CREATE GRAPH` NODES.
- Per-edge `kgr.edges.LABEL_KEY = "<src>_<dst>"` for `/show/graph` DOT disambiguation (option 2; stored `LABEL` stays bare).
- `kgr replay-corpus [--refresh-every N]` rebuilds the graph from `corpus.txt` without re-fetching.

## Next action

A clean `kgr clear --yes --keep-corpus` + `kgr replay-corpus --refresh-every 5` is (re)building the multi-label graph.
**When the replay finishes:**
1. `apply_schema()` (adds the `kgr.edges.LABEL_KEY` column via migration) →
2. `backfill_edge_label_keys()` (fill it on replayed edges) →
3. `apply_graph()` →
4. Pull the `/show/graph` schema DOT (`export_graph_schema='true'`) and confirm `AFFECTS` splits into distinct
   `(LABEL_KEY, AFFECTS)` edges per node-label pair. If Kinetica ignores a per-edge edge LABEL_KEY, fall back to the
   node-style grouping-table form for edges.

Then: decide whether to commit (user) and whether to revisit the `KGR_COMPOUND_EDGES` flag (still default off).
