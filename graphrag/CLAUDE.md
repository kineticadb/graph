# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Resuming work?** See `TO_DO.md` for session handoff — where we left off and the next action (currently: run `kgr init` to apply the pending `Application`/`AIAssistant` seed folds — deferred while the graph was frozen for video snapshots).

## What this is

`kgr` ingests documents and lands extracted entities/relations into a Kinetica property graph that grows its schema as new content arrives.

The primary input is free text (e.g. news paragraphs). The pipeline:

1. **Split** a `.txt` / `.md` file on blank lines into paragraphs.
2. **Extract** with the LLM: ask Claude for an ontology *and* the entities/relations under it for the paragraph, given the current ontology as context. The schema-of-fields is induced, not pre-declared.
3. **Evolve**: any new entity-type, relation-type, or attribute the LLM proposes is appended to `kgr.ontology`; new attributes trigger `ALTER TABLE kgr.nodes ADD COLUMN ...` (or `kgr.edges`).
4. **Upsert** rows into `kgr.nodes` and `kgr.edges` via `insert_records_json` with `update_on_existing_pk`. Same entity ID across paragraphs → row updates rather than duplicates.
5. **Re-apply graph** (`CREATE OR REPLACE`) once per ingest so `kgr.kg` picks up new rows and any new columns added by ALTER TABLE.
6. **Log** the raw paragraph (with timestamp + source URI + sha8) to `corpus.txt` for posterity/replay.

`.sql` files take a separate AST-based path (sqlglot) — same final destination (`kgr.nodes` / `kgr.edges`) but the ontology is pre-seeded with `SqlTable` / `SqlColumn` / `DEFINES` / etc.

## Commands

```bash
.venv/bin/pip install -e .
cp .env.example .env && $EDITOR .env             # set KINETICA_DB_SKILL_PASS

.venv/bin/kgr init                               # idempotent: schema + property graph
.venv/bin/kgr ingest examples/ft_article.txt     # text path (paragraphs)
.venv/bin/kgr ingest examples/sample.sql         # SQL path (AST)
.venv/bin/kgr ingest path/to/dir/                # walks directory, routes by extension

.venv/bin/pip install -e '.[web]'                # extra: trafilatura + feedparser + requests
.venv/bin/kgr ingest-url https://example.com/article    # fetch article body, ingest as text
.venv/bin/kgr ingest-feed https://site/rss --limit 5    # walk an RSS/Atom feed once, ingest each entry
.venv/bin/kgr watch-feeds                               # daemon: poll bundled threat/security feeds on a loop
.venv/bin/kgr watch-feeds --feeds my.txt --interval 600 --once   # custom feeds / interval; --once = single cycle (cron)
.venv/bin/kgr interrupt                          # stop a running watch-feeds job (SIGTERM, then SIGKILL)
.venv/bin/kgr clear --yes                        # interrupt job, drop graph + kgr tables + corpus.txt, re-init (start over)

.venv/bin/kgr backfill-labels                    # fold existing nodes/edges LABELs to canonical form, re-apply graph
.venv/bin/kgr recompose-edges                    # rewrite edges LABELs to compound form (--base = back to bare)
.venv/bin/kgr replay-corpus --refresh-every 5    # re-run every corpus.txt paragraph through the current extractor (rebuild, no re-fetch)

.venv/bin/kgr ask "What threats involve Microsoft?"     # NL→Cypher→NL one-shot (--show-cypher, --json)
.venv/bin/kgr chat                                      # interactive Q&A REPL over the graph (multi-turn)
```

There is no test runner — `test/probe.txt` is a manual scratch input, not a suite. Only two ingest paths exist: `.txt`/`.md` (text path) and `.sql` (AST path), routed by `ingest_path`. There is no C++ extractor (a `[cpp]`/tree-sitter extra was removed as vestigial — re-add it only alongside an actual `extractors/cpp.py`).

For ad-hoc queries against the live graph use the `kineticadb:kinetica-execute` skill — `graph show`, `query "..."` — not raw SDK calls. Conventions in `~/agent-skills/knowledge/graph-workflows.md`.

## LLM call (`kgr/extractors/text.py`)

Three paths, tried in order:
1. `KGR_LLM=stub` env → heuristic regex stub (no model). Useful for offline tests; output quality is poor by design.
2. `claude` CLI on `$PATH` → `claude -p --output-format json --json-schema '<schema>' <prompt>`. Reads the structured result from the `structured_output` field. This is the default in this environment.
3. `ANTHROPIC_API_KEY` set → Anthropic SDK (`anthropic.Anthropic().messages.create`).

The JSON schema enforced on the LLM is `_RESPONSE_SCHEMA` in `extractors/text.py`. Model defaults to whatever `claude` resolves; override with `KGR_LLM_MODEL`. Other env knobs (`KGR_LLM_TIMEOUT`, `KGR_CORPUS_PATH`, `KGR_WEB_TIMEOUT`, `KGR_USER_AGENT`, Kinetica connection vars) are tabulated in README.md → "Environment knobs".

## Architecture

> **Edit `./kgr/`, not `build/lib/kgr/`.** The editable install (`pip install -e .`) runs from `./kgr/`. `build/` and `dist/` are stale build artifacts — `build/lib/kgr/` is an out-of-date copy (e.g. it predates `qa.py`). Edits there change nothing that runs.

- `db.py` — `connect()` (singleton GPUdb), `execute(sql)`, `fetch(sql)`, `execute_script(sql)`. The script splitter handles `--` line comments — needed because apostrophes inside comments otherwise open phantom string literals.
- `schema.{sql,py}` / `graph.sql` — `kgr init` applies them. `CREATE OR REPLACE DIRECTED GRAPH` uses `INPUT_TABLES(SELECT * FROM ...)` shape (not column-mapping); `add_table_monitor` + `save_persist` enabled.
- `canonical.py` — `concept_id(text)` for LLM-derived entities (slug + sha1 short hash); `sql_*_id` for the AST path. Same input → same NODE → PK upsert collapses duplicates across documents.
- `ontology.py` — `load()` reads `kgr.ontology`; `merge_proposal(entity_types, relation_types, source_uri)` is the append-only evolver. New attributes trigger `ALTER TABLE ADD COLUMN`. Existing attributes are never type-changed.
- **Per-instance label provenance**: folding is *non-destructive at the node level*. `fold_proposal` stashes each entity's pre-fold label, and `upsert_nodes` accumulates the distinct originals into `kgr.nodes.label_raw VARCHAR[]` (union across mentions, so a later generic mention can't erase an earlier specific one). The canonical `LABEL` drives structure/queries; `label_raw` answers "what did the LLM originally call this node" (e.g. Microsoft: `LABEL=["Organization"]`, `label_raw=["Company"]`). Forward-only — rows written before this existed have null `label_raw` until re-ingested. Query with `RETURN n."label_raw"`; it's also a column in the explorer.
- **Label folding**: `fold_proposal(proposal, source_uri)` runs *before* `merge_proposal` and rewrites the LLM's proposed labels to their canonical forms. Fast path: look up `canonical_name` in `kgr.ontology` (covers everything in `kgr/ontology_seed.json` once `kgr init` has loaded it). Slow path: a single `claude -p` synonym check against existing canonicals. The instance labels in `proposal["entities"][i]["label"]` and `proposal["relations"][i]["label"]` are rewritten in place. Aliases land as their own rows in `kgr.ontology` (with `canonical_name` pointing at the canonical) so provenance survives — the graph itself only ever sees canonical labels.
- `ontology_seed.json` — hand-curated alias→canonical map loaded by `kgr init`. Add to it whenever you find the LLM coining variants of an existing concept.
- `upsert.py` — generic `upsert_nodes(entities, source_uri)` / `upsert_edges(relations, source_uri)`. Both take lists of plain dicts; only columns that exist on the table are sent (extras silently dropped). Writes go through `insert_records_json(... update_on_existing_pk='true')`.
- `extractors/text.py` — LLM-driven extractor returning `{entity_types, relation_types, entities, relations}`.
- `extractors/sql.py` — sqlglot AST extractor. Returns the same shape (`entities`, `relations` as plain dicts).
- `sources/web.py` — `fetch(url) -> Article` via `requests` + `trafilatura` (article body + title). `sources/feed.py` — `iter_entries(feed_url, limit)` via `feedparser`, yielded **oldest-first** (the feed is reversed) so `--limit` takes a contiguous newest-N window. Both are imported lazily inside `ingest.py` so the core install works without the `[web]` extra.
- `ingest.py` — top-level orchestration; appends each paragraph to `corpus.txt`, calls `apply_graph()` (CREATE OR REPLACE) once per document, and records the document in `kgr.documents`.
- `replay.py` — `replay-corpus`. Parses `corpus.txt` back into `(para_uri, text)` pairs (the `--- <ts> <uri> sha8=<hex> ---` header regex) and feeds each through extract→fold→merge→upsert exactly as `_ingest_text` does, then re-applies the graph. Use after an ontology/extractor change (e.g. new multi-label facets) to deterministically re-derive the graph from the same text — no network, no feed drift. Runs **serially** (the ontology evolves per paragraph; concurrent `merge_proposal` would race). `--refresh-every N` re-applies the graph every N paragraphs.
- `qa.py` — natural-language Q&A (`kgr ask` / `kgr chat`). Hybrid NL→Cypher→NL: `graph_schema()` derives the live meta-graph (node types, relation types, the actual `(srcLabel,rel,dstLabel)` triples from `kgr.edges`⋈`kgr.nodes`, entity attrs from `kgr.ontology`); `generate_cypher()` LLM-writes read-only Cypher grounded on that schema; `validate_cypher()` rejects unknown labels/relations + write keywords (re-prompts once); `answer()` executes via `db.fetch` (aggregations wrap in `GRAPH_TABLE()` — no `graph_table` create-option needed) and `synthesize()` turns rows into prose. LLM backend resolution mirrors `text.py` (claude CLI / SDK); `KGR_LLM=stub` is unsupported here.
- `watch.py` — the `watch-feeds` polling daemon. `watch_feeds(feeds, interval, limit, once)` loops over feeds calling `ingest_url` per entry, emits one JSON line per event (`ingested` / `feed_error` / `ingest_error` / `cycle_done`). Durable dedup is `kgr.documents`; an in-run `seen` set of entry URLs avoids re-fetching unchanged entries. A failed ingest is *not* marked seen, so it retries next cycle. `sources/security_feeds.txt` is the bundled default feed list (threat/security topics); override with `--feeds`. Also home to the interrupt machinery: the daemon writes a pidfile (`$KGR_RUNTIME_DIR` or `~/.kgr/watch.pid`) and traps `SIGTERM`→`KeyboardInterrupt` for graceful shutdown; `interrupt()` finds the job via that pidfile *plus* a `/proc` argv-token scan (matches `watch-feeds` as an exact arg + a `kgr` entrypoint token — deliberately strict so it never matches shell wrappers or `pgrep` patterns), then `SIGTERM`→`SIGKILL`.
- `schema.drop_all()` — best-effort teardown (`DROP GRAPH` then the six tables — `edges`, `nodes`, `documents`, `label_keys`, `edge_label_keys`, `ontology` — errors collected not raised). The `clear` command composes `interrupt()` + `drop_all()` + optional `corpus.txt` removal + `apply_all()` re-init; it requires `--yes` or it only prints a dry-run plan.

## Idempotency / dedup

`kgr.documents` (PK = `doc_uri`) stores a `sha256` of each ingested document's full content. `ingest_text` / `_ingest_sql` short-circuit to `{"status": "unchanged"}` when the incoming content hashes to the stored value — so re-running `ingest`, `ingest-url`, or `ingest-feed` on unchanged content is a no-op. The doc_uri for a file is its `file://` URI; for a URL it's the (post-redirect) URL. Per-paragraph URIs are `<doc_uri>#p<N>`. This is the document-level idempotency layer; PK upsert on `kgr.nodes`/`kgr.edges` is the row-level one.

## Schema conventions

- `LABEL VARCHAR[] NOT NULL` (no size, brackets right after `VARCHAR`). Returned over the wire JSON-encoded — `fetch()` shows `'["Person"]'` even though the column is a real array.
- All graph identifier columns are VARCHAR (`NODE_NAME` semantics). Required by Kinetica: NODE / NODE1 / NODE2 must share a data type across tables.
- **Don't name a column `name`** on any table consumed by `CREATE GRAPH`. `NAME` is an alias for `NODE_NAME` in the NODE component grammar, so it gets auto-detected as a second node identifier and doubles `NUM_NODES`. We use `name_original`. Same caution likely applies to `id` and `wktpoint`.
- **Node ID convention** (text path): the LLM emits an `id` derived from the entity's *name only*, no type prefix — `jerome_powell`, not `person:jerome_powell`. The LABEL already encodes type; the id is identity.
- **Compound edge labels** (graph level, **opt-in — default off**): when `KGR_COMPOUND_EDGES=on` (see `config.py`), `kgr.edges.LABEL` is stored as `<srcNodeLabel>_<baseRelationLabel>_<dstNodeLabel>` (e.g. `Person_WORKS_AT_Organization`) — bitcoin_graph pattern. This makes the (node_label, edge_label, node_label) triple unique per edge LABEL, so Kinetica's graph-schema generator can derive the meta-graph in O(distinct labels) without traversal — worth the visual density only on very large graphs. **Default off** stores the bare base label (`WORKS_AT`) so the `/show/graph` schema DOT is readable. Either way `kgr.ontology` only ever tracks the *base* relation type and its attributes; compounding lives solely in `kgr.edges.LABEL`. `upsert_edges` branches on the flag at write time. `compound_edge_labels()` ⇄ `base_edge_labels()` convert existing rows (both idempotent, both recover the base via the canonical relation set so underscored bases like `LOCATED_IN` survive); `kgr init` runs whichever direction the flag selects; `kgr recompose-edges [--base]` does it on demand. Do **not** abbreviate node labels *inside* the stored compound — 1–2-char prefixes collide (Organization vs Order) and a collision-safe prefix isn't stable as the ontology grows, churning `edge_key`. Declutter at the viz layer instead.
- `kgr.edges.edge_key = sha1(NODE1|NODE2|LABEL|source_uri)` — idempotent under PK upsert and across re-ingests of the same source.
- Attribute columns added by the ontology evolver are nullable. Same attribute name (e.g. `period`) shared across types maps to one shared column.
- **Multi-label nodes + axes (LABEL_KEY)**: `kgr.nodes.LABEL VARCHAR[]` is a *multi-label vector* — a structural type plus cross-cutting facets on other axes (e.g. Anthropic = `["Organization","AI","LLM"]`). Each label belongs to one **axis** (a.k.a. `LABEL_KEY`): the structural type sits on the default `EntityType` axis (`config.DEFAULT_AXIS`), facets on others (`Industry`, `Technology`, `Status`, …). The axis-per-label is recorded in `kgr.ontology.axis` (the normalized source of truth), seeded from `ontology_seed.json` → `entity_axes` / `entity_axis_aliases` and evolved by the LLM (the extractor emits `entities[i].facets = [{label, axis}]`; `fold_proposal` folds each facet to canonical, assigns its axis, builds `e["labels"]`, and registers new facet types). **`kgr.label_keys`** is the unpivoted materialization (one row per axis → array of its canonical labels), rebuilt from `kgr.ontology` by `apply_graph()` and fed into `CREATE GRAPH`'s NODES component as `(SELECT label_key AS LABEL_KEY, label AS LABEL FROM kgr.label_keys)` so Kinetica groups the meta-graph by axis (label-key compression; toggle with `schema_node_labelkeys`). Verified: the grouping rows have no `NODE` so `NUM_NODES` is *not* inflated.
- **Order carries no meaning in `LABEL`** — the graph engine treats the array as an unordered multi-label. The *structural* label is resolved by **axis membership** (`ontology.pick_structural()` picks the `EntityType`-axis element via `ontology.axis_map()`), **never** by `arr[0]`. Consumers that need the one structural label (compound-edge composition in `upsert._lookup_node_labels`, `compound_edge_labels()`, the meta-graph triples in `qa.graph_schema`) all go through `pick_structural`. Cypher `(n:AI)` matches any element of the vector, so `graph_schema().node_types` exposes *all* labels as queryable while triples use only the structural one.
- **Edge LABEL_KEY groupings (`kgr.edge_label_keys`) — an abstraction knob, the EDGES analog of node axes.** Same `(LABEL_KEY, LABEL)` grouping-SELECT form as nodes, fed into `CREATE GRAPH`'s EDGES component. Relations carry an `axis` in `kgr.ontology` = the verb's **semantic category** (`EXPLOITS/AFFECTS → Offensive`, `PATCHED → Defensive`, `WORKS_AT → Corporate`, …; seeded in `ontology_seed.json` → `relation_axes`, default `Action`). `rebuild_edge_label_keys()` groups canonical verbs by that axis → `label_key = category, label = [verbs]` (single-membership, a second-level grouping over canonical verbs — like canonicalization one level up). A per-*edge* `LABEL_KEY` column does **not** work — Kinetica rejects the `(NODE1,NODE2,LABEL,LABEL_KEY)` combo ("identifier combination is not valid for component 1"); it must be the separate grouping SELECT. What the `/show/graph` schema DOT shows is governed by query-time options (NOT the explorer — Kinetica's `/show/graph export_graph_schema=true` builds the DOT into `info.dot`):
  - `schema_edge_labelkeys=true` (EKey ON, default): **collapse** all verbs sharing a `label_key` into one edge labeled by the category (`Offensive`, `Defensive`, …) → simplified/abstract ontology. `schema_node_labelkeys` does the same for nodes (collapses by axis).
  - `schema_edge_labelkeys=false` (EKey OFF): edges shown by their raw verb (`AFFECTS`), which then legitimately spans every node-pair it connects.
  - `schema_full_search=true`: exhaustive per-`(src,verb,dst)` combo counting for **accurate** percentages (vs. the default cached single-edge approximation) — this, not LABEL_KEY, is the fix for correct detailed-view DOT. Stored `kgr.edges.LABEL` stays bare regardless; `KGR_COMPOUND_EDGES` (default off) is the separate, storage-level way to bake the triple into the label.

## Cypher gotchas

- Always prefix `GRAPH "kgr"."kg"` — quote each part separately, never `"kgr.kg"`.
- Quote `name_original` (and other quoted-identifier columns) in `RETURN`: `RETURN n."name_original" AS nm`.
- Inline label/attribute filters: `(n:Person WHERE n.role = 'CEO')` — not in a trailing `WHERE`.
- `GROUP BY` / `COUNT` needs `GRAPH_TABLE(...)` wrap. `COUNT(...)` returns a `json` type that can't be `ORDER BY`'d — cast to BIGINT in the outer SELECT.
- Full conventions live in `~/agent-skills/knowledge/graph-workflows.md`.
