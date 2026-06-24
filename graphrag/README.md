# kgr

**A knowledge graph that learns its own ontology.** Drop in text, news feeds, or SQL; kgr extracts entities and relations, evolves the schema to fit them, and lands everything in a live Kinetica property graph.

kgr turns a stream of documents into a continuously-growing knowledge graph in Kinetica. For each paragraph it asks an LLM not just *what* the entities and relations are, but *what types* they belong to — so the ontology is **induced, not pre-declared**. New entity types, relation types, and attributes are appended to a registry and materialized as `ALTER TABLE` columns on the fly; rows upsert by identity, so the same entity across many documents collapses into one node. It ingests free text (e.g. threat-intel news, via an RSS polling daemon), web articles, and SQL (parsed to an AST) — all landing in the same `kgr.nodes` / `kgr.edges` property graph.

What makes it distinctive:

- **Schema-on-write, induced by an LLM.** The graph's ontology emerges from the data and evolves with it (new types → new ontology rows → new columns), instead of being modeled in advance. A curated alias map keeps the vocabulary from sprawling.
- **Idempotent and incremental.** Content-hash dedup at the document level plus PK upserts at the row level mean you can re-ingest files or poll feeds forever and only genuinely new information lands.
- **Native to a Kinetica property graph.** Extraction feeds straight into a live, queryable graph (Cypher / graph analytics), with conventions tuned so Kinetica can derive the meta-graph schema cheaply.

## Quick start

```bash
# one-time setup
.venv/bin/pip install -e .                       # core
.venv/bin/pip install -e ".[web]"                # add web driver (trafilatura, feedparser, requests)
cp .env.example .env && $EDITOR .env             # set KINETICA_DB_SKILL_PASS

# create the schema and the property graph (idempotent — safe to re-run)
.venv/bin/kgr init

# ingest from files
.venv/bin/kgr ingest examples/ft_article.txt
.venv/bin/kgr ingest path/to/any.txt
.venv/bin/kgr ingest path/to/dir/                # walks a directory tree

# ingest from the web (requires the [web] extra)
.venv/bin/kgr ingest-url 'https://www.bbc.com/news/articles/c62xevydk05o'
.venv/bin/kgr ingest-feed https://feeds.bbci.co.uk/news/business/rss.xml --limit 5
```

Every paragraph kgr reads is also appended to `corpus.txt` with a timestamp + source URI + sha8 header — an immutable replay log of the corpus.

## Reproduce the demo graph from a clean checkout

The repo ships a `corpus.txt` (the captured paragraph log) so anyone can rebuild the
exact multi-label demo graph **deterministically, with no network / RSS re-sweep** —
`kgr replay-corpus` re-runs every logged paragraph through the current extractor.

**Prerequisites**
- Python ≥ 3.10.
- A reachable Kinetica instance + credentials (the `KINETICA_DB_SKILL_*` vars below).
- An LLM backend for extraction + Q&A — **either** the `claude` CLI on `PATH`
  (authenticated), **or** `ANTHROPIC_API_KEY` set. Both `replay-corpus` and `ask` need it.

**Steps** (from the `graphrag/` directory):

```bash
python -m venv .venv
.venv/bin/pip install -e '.[web]'                 # core + web extra (pulls typeguard for gpudb)
cp .env.example .env && $EDITOR .env              # set KINETICA_DB_SKILL_URL / _USER / _PASS

.venv/bin/kgr init                                # schema + property graph (idempotent)
.venv/bin/kgr replay-corpus --refresh-every 5     # rebuild the multi-label graph from corpus.txt

# round-trip NL query (LLM writes Cypher -> runs it -> answers); --show-cypher prints the query
.venv/bin/kgr ask "Who works at organizations that make products affected by known vulnerabilities?" --show-cypher
```

`replay-corpus` makes one LLM call per paragraph (~130), so a full rebuild takes a few
minutes; the graph re-applies every `--refresh-every` paragraphs so you can watch
`num_nodes` climb. Re-running `init` or `replay-corpus` is idempotent.

## Running the CLI & getting help

`kgr` is installed into the project virtualenv, so from the `graphrag/` directory
invoke it via the venv:

```bash
cd graphrag
.venv/bin/kgr --help            # top-level help: full command list + a "common" quick-reference + env knobs
.venv/bin/kgr <command> --help  # per-command options, e.g. .venv/bin/kgr watch-feeds --help
```

Prefer to type plain `kgr`? Activate the venv first (puts it on `PATH` for the session):

```bash
source .venv/bin/activate
kgr --help
kgr ingest examples/ft_article.txt
deactivate                      # when you're done
```

Notes:
- Help is `--help` / `-h` (argparse) — there is no `kgr help` subcommand.
- Running `kgr` with no arguments prints the usage line and exits non-zero; a subcommand is required.

## What lands in Kinetica

`kgr init` creates the schema `kgr` with four tables and one graph:

| object | role |
|---|---|
| `kgr.documents` | one row per file ingested; sha256 lets re-ingest of an unchanged file be a no-op |
| `kgr.ontology` | the evolving type/attribute registry — knows that `Company` is an alias of `Organization`, that `Person` has a `role`, etc. |
| `kgr.nodes` | one row per entity. Identifier columns (`NODE`, `LABEL`) plus `label_raw` (the original pre-fold label(s) the LLM proposed — e.g. `["Company"]` on a node whose canonical `LABEL` is `["Organization"]`) and a growing set of typed attribute columns added by the ontology evolver |
| `kgr.edges` | one row per relation. `NODE1`, `NODE2`, `LABEL`, plus its own growing typed attribute columns |
| `kgr.kg` | the directed property graph over `kgr.nodes` + `kgr.edges`; `add_table_monitor='true'` keeps it in sync with inserts |

## The pipeline (per paragraph)

1. **Hash & dedup** against `kgr.documents` — same file as last time? Skip.
2. **Append** the paragraph to `corpus.txt`.
3. **Extract** via `claude -p --output-format json --json-schema <schema>` — Claude returns a JSON blob of `entity_types`, `relation_types`, `entities`, `relations`. The current ontology is fed into the prompt so the LLM reuses existing types where possible.
4. **Fold labels** to canonical form (`fold_proposal`). The seed file (`kgr/ontology_seed.json`) handles common synonyms instantly; anything not in the seed and not yet seen triggers a single cheap `claude -p` synonym check against the existing canonicals.
5. **Evolve the ontology** (`merge_proposal`). Genuinely new types and attributes get appended to `kgr.ontology` and the appropriate `ALTER TABLE ADD COLUMN` runs on `kgr.nodes` / `kgr.edges`.
6. **Upsert** the entities/relations via `insert_records_json` with `update_on_existing_pk='true'`. Same canonical ID across paragraphs → row update, not a new row.
7. **Re-apply the graph** (`CREATE OR REPLACE`) so it picks up any new rows and any new columns.

## Querying what you've ingested

Once you have data, you can hit the graph two ways.

**SQL on the underlying tables:**
```sql
SELECT NODE, LABEL, name_original
FROM "kgr"."nodes"
WHERE LABEL = ARRAY['Organization']
LIMIT 20;
```

**Cypher over `kgr.kg`:**
```sql
GRAPH "kgr"."kg"
MATCH (a:Person)-[e:Person_WORKS_AT_Organization]->(b:Organization)
RETURN a."name_original" AS person, b."name_original" AS org;
```

Edge LABELs are stored in **compound form** `<srcNodeLabel>_<baseEdgeLabel>_<dstNodeLabel>` (e.g. `Organization_ACQUIRED_Organization`, `Person_UPGRADED_Organization`) so the graph schema (the meta-graph showing which node types connect via which edge types) can be derived from the LABEL vocabulary alone — no traversal needed. The base relation type lives in `kgr.ontology` and is what the LLM is given to reuse.

**Grab the meta-graph as a DOT file** (what Kinetica Explorer renders as "ontology view"):
```python
from kgr.db import connect
dot = connect().show_graph(
    graph_name="kgr.kg",
    options={"export_graph_schema": "true"},
)["info"]["dot"]
print(dot)   # `digraph G { ... }` — pipe through `dot -Tpng` for a PNG
```

Two Cypher gotchas worth knowing:
- Always quote each schema part: `GRAPH "kgr"."kg"`, never `"kgr.kg"`.
- Quote `name_original` in RETURN: `n."name_original"` (Kinetica's Cypher parser treats some bare identifiers oddly).

For ad-hoc inspection from a shell, the `kineticadb:kinetica-execute` skill is the recommended entry point — see `~/agent-skills/knowledge/graph-workflows.md`.

## Keeping the vocabulary tight (label folding)

The LLM is creative — left alone it'll coin `UPGRADED`, `RAISED_TO_BUY`, `BOOSTED_RATING`, `RAISED_PRICE_TARGET` as four distinct relation types for what is one concept. `kgr` folds these to a single canonical via two mechanisms.

**Hand-curated seed** — `kgr/ontology_seed.json` ships with sensible defaults:
```json
{
  "entity_aliases":   { "Company": "Organization", "Facility": "Location", ... },
  "relation_aliases": { "RAISED_PRICE_TARGET": "UPGRADED", "PRODUCES": "MAKES", ... }
}
```
Loaded into `kgr.ontology` on every `kgr init`. Future LLM proposals matching any alias are folded instantly, zero LLM cost.

**Runtime fold-check** — anything *not* in the seed and not yet seen triggers a single small `claude -p` call: "is `<proposed>` a synonym of any of `[<existing canonicals>]`?" Decision is persisted so it never costs again.

**When you tighten the seed file**, run `kgr init` — it's self-healing:
1. The seed loader applies the new aliases (e.g. demoting some canonical to alias of another).
2. If any existing rows in `kgr.nodes` / `kgr.edges` still carry that label, they get rewritten automatically before the graph re-applies.

Or run the backfill on its own:
```bash
.venv/bin/kgr backfill-labels
```

## Commands

| command | what it does |
|---|---|
| `kgr init` | create schema + graph, load seed, self-heal labels, recompose edge labels to compound form |
| `kgr ask "<question>" [--show-cypher] [--json]` | natural-language Q&A: generate schema-grounded Cypher, run it, answer in prose |
| `kgr chat [--show-cypher]` | interactive Q&A REPL over the graph (reuses the `ask` pipeline, keeps context) |
| `kgr ingest <path>` | ingest a file or a directory tree |
| `kgr ingest-url <url>` | fetch a web article (trafilatura extraction) and ingest its body |
| `kgr ingest-feed <rss-url> [--limit N]` | iterate an RSS/Atom feed and ingest each entry |
| `kgr backfill-labels` | rewrite existing rows to canonical labels (auto-runs from `kgr init`) |
| `kgr recompose-edges [--base]` | rewrite kgr.edges LABELs to compound `<src>_<base>_<dst>` form; `--base` does the inverse (back to the bare relation, declutters the schema graph). `kgr init` runs whichever direction `KGR_COMPOUND_EDGES` selects |
| `kgr watch-feeds [--feeds PATH] [--interval SECS] [--limit N] [--once]` | polling daemon: re-walk feeds every `--interval` (default 900s) and ingest new entries; `--feeds` defaults to bundled threat/security feeds; `--once` = single cycle (cron). Re-seen articles are skipped via the `kgr.documents` sha256 ledger |
| `kgr interrupt` | stop a running `watch-feeds` job (SIGTERM, then SIGKILL after 10s) |
| `kgr clear [--yes] [--no-reinit] [--keep-corpus]` | interrupt any running job, then drop the graph + `nodes`/`edges`/`documents`/`ontology` and remove `corpus.txt`, then re-init. **Requires `--yes`** — without it, prints a dry-run plan. `--no-reinit` leaves the schema dropped; `--keep-corpus` preserves the log |

## Asking questions (graph-RAG)

Query the graph in plain English — kgr generates Cypher, runs it, and answers:

```bash
kgr ask "What has Microsoft patched, released, or investigated?"
kgr ask "Which vulnerabilities affect the most products? Give counts." --show-cypher
kgr chat                       # interactive REPL; follow-up questions keep context
```

How it works (hybrid NL→Cypher→NL, in `qa.py`):

1. **Ground** — derive the live meta-graph (node types, relation types, the actual
   `(srcLabel)-[:REL]->(dstLabel)` triples, entity attributes) so the model can only
   reference labels/edges that exist.
2. **Generate** — the LLM writes one read-only Cypher query for `GRAPH "kgr"."kg"`,
   given the question + schema + dialect rules.
3. **Validate** — every label/relation it used must be in the schema and the query
   must be read-only; otherwise it's re-prompted once with the specific problem.
4. **Execute + answer** — run via the graph engine (aggregations use `GRAPH_TABLE()`),
   then the LLM turns the rows into a grounded answer — or says the corpus doesn't
   contain it, rather than inventing facts.

`--show-cypher` prints the generated query and row count; `--json` (on `ask`) emits the
whole result object. Needs an LLM backend (the `claude` CLI or `ANTHROPIC_API_KEY`);
`KGR_LLM=stub` is not supported here.

### Worked example — a multi-hop question

```
$ kgr ask "Which organizations make products that are affected by known vulnerabilities?" --show-cypher

cypher: GRAPH "kgr"."kg"
        MATCH (o:Organization)-[:MAKES]->(p:Product)<-[:AFFECTS]-(v:Vulnerability)
        RETURN DISTINCT o."name_original" AS organization,
                        p."name_original" AS product,
                        v."name_original" AS vulnerability
        LIMIT 100
rows: 6

Only Cisco appears in the corpus as an organization with products affected by
known vulnerabilities:
  • Cisco Unified CM / Unified Communications Manager / Session Management Edition
    — affected by CVE-2026-20230
  • Unified Communications Manager — also affected by CVE-2025-20309
  • Catalyst SD-WAN Manager / Cisco Catalyst SD-WAN Manager — affected by CVE-2026-20245
```

Note the two-hop traversal with a **flipped arrow** — `(o)-[:MAKES]->(p)<-[:AFFECTS]-(v)`
walks org→product then product←vulnerability — generated straight from the question, and
constrained to labels/relations that actually exist in the graph. (The near-duplicate
product names hint at a future *entity*-resolution pass — distinct from the type-label
folding kgr already does.)

## Continuous feed watching

The 6 threat/security feeds are the built-in default, so no feed list is needed:

```bash
kgr watch-feeds --interval 120     # poll all 6 feeds, ingest new articles, repeat
kgr watch-feeds --once             # one pass over all 6, then exit (good for cron)
```

**The interval is a pause *between* cycles, not a timeout *on* one.** A cycle runs
to completion — fetching every feed and fully extracting every new article (LLM +
graph writes) — and only then does it `sleep(interval)` before the next pass. So a
slow cycle is never cut off; effective period = `cycle_time + interval`. The first
cycle is the slow one (every article is new → full LLM extraction); later cycles are
fast because re-seen articles hit the `kgr.documents` sha256 ledger and skip the LLM
entirely.

**Stopping it.** `Ctrl+C` in the daemon's own terminal stops it cleanly (logs
`{"event": "stopped"}` and cleans up). From *any other terminal* (same user, same
machine):

```bash
kgr interrupt        # stop the running daemon
kgr clear --yes      # stop it AND wipe the graph + kgr tables (start over)
```

How a second terminal finds the job — there's no server or socket, just two
host-local lookups:

- **Pidfile** (primary): the daemon writes its PID to `$KGR_RUNTIME_DIR/watch.pid`
  (default `~/.kgr/watch.pid`); other `kgr` commands read it. If you override
  `KGR_RUNTIME_DIR`, set the same value in both terminals.
- **`/proc` scan** (fallback): if the pidfile is missing, `interrupt` finds the job
  by scanning the process table for a `watch-feeds` argv token. Before signaling, it
  verifies the PID is alive and really is a kgr watch process, then `SIGTERM` →
  `SIGKILL`.

This is local-only: the second terminal must be the same OS user on the same host
(it relies on `~/.kgr` and `/proc`, not the network).

## Environment knobs

| var | default | effect |
|---|---|---|
| `KINETICA_DB_SKILL_URL` / `_USER` / `_PASS` / `_TIMEOUT` | from `.env` | Kinetica connection |
| `KGR_LLM` | unset | set to `stub` to skip LLM calls (fast/cheap, low-quality output, useful for testing pipelines) |
| `KGR_LLM_MODEL` | the `claude` CLI default | override the model used by `claude -p` |
| `KGR_LLM_TIMEOUT` | `180` | seconds per LLM call |
| `KGR_COMPOUND_EDGES` | `off` | `on` ⇒ store edge LABELs as unique `<srcLabel>_<baseLabel>_<dstLabel>` (lets Kinetica derive the schema graph without traversal — worth it on huge graphs). Default `off` keeps bare base labels for a readable schema DOT. Flip it, then `kgr init` (or `recompose-edges` / `recompose-edges --base`) to rewrite existing rows |
| `KGR_CORPUS_PATH` | `./corpus.txt` | where the paragraph log goes |
| `KGR_WEB_TIMEOUT` | `30` | seconds for `ingest-url` HTTP fetches |
| `KGR_USER_AGENT` | `kgr/0.1 …` | User-Agent for web fetches (some sites 403 the default — e.g. CISA) |
| `KGR_RUNTIME_DIR` | `~/.kgr` | where `watch-feeds` writes its `watch.pid` (used by `interrupt`/`clear`) |
| `ANTHROPIC_API_KEY` | unset | only used if `claude` CLI isn't on `$PATH`; SDK fallback |

## Starting over

```bash
.venv/bin/python -c "
from kgr.db import connect
db = connect()
for s in ['DROP GRAPH \"kgr\".\"kg\"',
          'DROP TABLE IF EXISTS \"kgr\".\"nodes\"',
          'DROP TABLE IF EXISTS \"kgr\".\"edges\"',
          'DROP TABLE IF EXISTS \"kgr\".\"documents\"',
          'DROP TABLE IF EXISTS \"kgr\".\"ontology\"']:
    db.execute_sql(s)
"
rm -f corpus.txt
.venv/bin/kgr init
```

## Examples included

| file | what it shows |
|---|---|
| `examples/ft_article.txt` | five FT-style paragraphs covering rates, M&A, earnings, central banks, EV |
| `examples/sample.sql` | small SQL DDL+DML — exercises the SQL-AST extractor path |
| `examples/retail.sql` | bigger SQL example: multi-schema warehouse with views and CTEs |

Ingest any of them with `kgr ingest examples/<file>`.

## How a paragraph turns into rows

For the FT paragraph:

> Federal Reserve chair Jerome Powell told reporters in Washington on Wednesday that the central bank would hold its benchmark interest rate steady at 5.25 percent.

Claude returns something like:
```json
{
  "entity_types": [
    {"name": "Person", "attributes": [{"name": "role", "type": "VARCHAR(128)"}]},
    {"name": "Organization", "attributes": [{"name": "kind", "type": "VARCHAR(64)"}]},
    {"name": "FinancialInstrument", "attributes": [{"name": "rate_percent", "type": "DOUBLE"}]}
  ],
  "relation_types": [
    {"name": "WORKS_AT", "attributes": [{"name": "role", "type": "VARCHAR(128)"}]},
    {"name": "SETS", "attributes": [{"name": "rate_percent", "type": "DOUBLE"}]}
  ],
  "entities": [
    {"id": "jerome_powell", "label": "Person", "name": "Jerome Powell", "attrs": {"role": "Chair"}},
    {"id": "federal_reserve", "label": "Organization", "name": "Federal Reserve"},
    {"id": "fed_benchmark_interest_rate", "label": "FinancialInstrument", "name": "Federal Reserve benchmark interest rate", "attrs": {"rate_percent": 5.25}}
  ],
  "relations": [
    {"src": "jerome_powell", "dst": "federal_reserve", "label": "WORKS_AT", "attrs": {"role": "Chair"}},
    {"src": "federal_reserve", "dst": "fed_benchmark_interest_rate", "label": "SETS", "attrs": {"rate_percent": 5.25}}
  ]
}
```

After ingest:
- `kgr.ontology` gains `Person`, `Organization`, `FinancialInstrument`, `WORKS_AT`, `SETS` + their attribute declarations.
- `kgr.nodes` gains the three entity rows; `kgr.edges` gains the two relations. The `role` and `rate_percent` columns are added to the tables if not already present.
- The next paragraph that mentions Jerome Powell reuses `jerome_powell` (PK upsert just updates `last_seen_ts`).

## Packaging & distribution

`kgr` is a standard PEP 517 project — `pyproject.toml` declares the build
backend, dependencies, the `[web]` (and aggregate `[all]`) extra, the `kgr = kgr.cli:main`
entry point, and the runtime data files (`*.sql`, `ontology_seed.json`,
`sources/*.txt`) as package data so they travel inside a built artifact.

Two ways people consume it:

```bash
# (a) from source — the dev / clone workflow
python -m venv .venv
.venv/bin/pip install -e .            # add ".[web]" for ingest-url / feeds
# code edits take effect immediately; data files are read from the source tree

# (b) as a built artifact — for everyone else
.venv/bin/pip install build          # one-time
.venv/bin/python -m build            # writes dist/kgr-<ver>-py3-none-any.whl + .tar.gz
pip install dist/kgr-0.1.0-py3-none-any.whl   # on any machine; CLI + data files included
```

The two paths don't conflict: (a) reads the data files in place; (b) bundles
copies into the wheel. Both resolve them the same way (relative to the package,
not the working directory). Either way, each user still supplies their own
`.env` (Kinetica credentials) at runtime — that's config, not packaged.

To publish so others can `pip install kgr` from anywhere, upload the `dist/`
artifacts to PyPI or a private index (`twine upload dist/*`); bump
`project.version` in `pyproject.toml` per release.

## Further reading

- `CLAUDE.md` — internals, conventions, and known gotchas (`name` column trap, `claude -p` invocation pattern, Cypher quirks).
- `~/agent-skills/knowledge/graph-workflows.md` — Kinetica graph DDL + Cypher reference.
- `/home/kkaramete/.claude/plans/snazzy-plotting-squirrel.md` — the original design plan.
