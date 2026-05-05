# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

This repo is documentation, not a library or service. The deliverable is `Kinetica_Graph_User_Guide.md` — a long-form user guide (plus its rendered `.html` sibling) covering Kinetica's property-graph features: graph creation grammar, Cypher, `GRAPH_TABLE`, `SOLVE_GRAPH`, `MATCH_GRAPH`, ontology/label keys, and visualization.

The one piece of code here, `generate_usecase_images.py`, exists to produce the four `images/usecase_*.png` figures embedded in the guide. It connects to a live Kinetica instance, runs Cypher against pre-existing demo graphs (`expero.banking_graph`, `bluesky`, `rearm`, `wiki_graph`), and renders matplotlib/networkx diagrams.

## Running the image generator

```bash
# uses .venv (matplotlib, networkx installed); creds come from .env
python3 generate_usecase_images.py
```

The script skips figures whose source graph isn't available — the logistics figure has a static fallback, the others just log "skipping". When editing, keep that defensive shape: assume any given demo graph may be missing on a fresh Kinetica.

## Executing Kinetica queries

Queries run through the `kinetica-execute` skill's CLI, **not** a direct Python SDK call:

```bash
python3 /home/kkaramete/.claude/plugins/cache/kinetica-skills/kineticadb/1.0.27/skills/kinetica-execute/scripts/kinetica-cli.py query "<SQL or Cypher>"
```

Connection settings live in `.env` (`KINETICA_DB_SKILL_URL`, `_USER`, `_PASS`, `_TIMEOUT`). The `kineticadb:kinetica-execute` skill is the preferred entry point — invoke it rather than shelling out manually unless you're replicating what `generate_usecase_images.py` already does.

## Graph query conventions used throughout the guide

- Cypher queries are always prefixed with `GRAPH <graph_name>` (no quotes needed for simple names, quoted for schema-qualified ones like `"expero.banking_graph"`).
- To list graphs, use `DESCRIBE GRAPH *` (SQL), not a CLI subcommand.
- For simple aggregation over a materialized graph, prefer `GRAPH_TABLE + COUNT/GROUP BY`. Kinetica SQL does **not** support `LIST()` or `GROUP_CONCAT()`.
- For the `bluesky` demo graph, query via Cypher with edge/node labels directly — don't inspect underlying tables first.
- `MATCH_GRAPH` `match_batch_solves` expects OD identifiers `OD_ID`, `ORIGIN_WKTPOINT`, `DESTINATION_WKTPOINT`.

## Editing the guide

`Kinetica_Graph_User_Guide.md` is the source of truth; the `.html` is a rendered snapshot. Image references use relative paths (`images/usecase_*.png`) and a few absolute GitHub raw URLs for logos/schema diagrams — preserve that split when adding assets.

**After every `.md` edit, re-inline the markdown into the `.html`** — the HTML file has a `<script type="text/markdown" id="md-source">…</script>` block that the in-browser marked.js renders. Run:

```bash
python3 -c "
from pathlib import Path
h = Path('Kinetica_Graph_User_Guide.html').read_text()
m = Path('Kinetica_Graph_User_Guide.md').read_text()
s = '<script type=\"text/markdown\" id=\"md-source\">'
i = h.index(s) + len(s); j = h.index('</script>', i)
Path('Kinetica_Graph_User_Guide.html').write_text(h[:i] + '\n' + m + '\n' + h[j:])"
```

The HTML's sidebar TOC is generated from `h2` headings only; in-content anchors (`#5-ontology-and-label-grouping`, `#7-graph_table--sql-aggregation-on-traversals`) use GitHub-style slugs — preserve em-dashes (`—`) if you want double-hyphen slugs (matches how marked/GitHub slugifies them).

## Schema and grammar pages

Section 7 of the guide links to standalone HTML pages under `schemas/` for each graph endpoint. Two generators produce them:

- `generate_schema_pages.py` — renders one HTML page per endpoint (`create_graph`, `query_graph`, `solve_graph`, `match_graph`, `show_graph`, `alter_graph`, `get_graph_entities`) from JSON in `~/gpudb-dev/gpudb-schemas/endpoint-schemas/`. Source schemas have raw newlines inside string values (not `\n`); the script normalizes before parsing.
- `generate_grammar_page.py` — makes a live `/show/graph/grammar` call and emits `schemas/show_graph_grammar.html` as a collapsible JSON tree. Needs `.venv/bin/python` so `gpudb` is importable; reads creds from `.env` (same vars as `generate_usecase_images.py`).

Re-run whichever generator's source changed, then regenerate `schemas/index.html` if the endpoint set itself changed. The pages share the guide's dark/light theme — don't drift the styling.

## Graph Explorer integration

Section 13 ("Graph Explorer") mirrors the public README at `github.com/kineticadb/graph/tree/master/explorer`. When updating it, pull narrative/feature content from that README rather than drafting from scratch. The Explorer itself is hosted at `graph-explorer.kinetica.com`.

## Screenshot toolchain

`screenshot_session.py` and `replay_session.py` drive the Explorer headlessly via Playwright to regenerate `images/explorer/*.png` from session JSONs in `sessions/`. The `out/<graph_name>/` subdirs hold the raw per-query captures; the curated set under `images/explorer/` is what the guide references. Ontology DOTs can be re-rendered via `db.show_graph(name, options={'export_graph_schema':'true', ...})` + `dot -Tpng` when the Explorer can't produce the exact view needed.

### PNG → WebP conversion (mandatory after any new screenshot)

The guide's image assets are stored as **WebP**, not PNG — switching cut `images/` from 9.0 MB to 4.0 MB at `quality=85, method=6` (visually lossless). After any new PNG lands under `images/` (Explorer capture, workbook screenshot, manual paste from `~/Pictures/Screenshots/`), convert it via:

```bash
python3 convert_screenshots.py images/         # smart: keep PNG only if WebP grows
python3 convert_screenshots.py --force images/ # consistency: always swap to WebP
```

The helper deletes the source PNG when the WebP is smaller (or always with `--force`). It skips files that already have a sibling `.webp`, so re-running is safe. Then update any `images/...png` references in the markdown to `.webp` and re-inline. Two non-image animations live in the same tree as **MP4** (`emergency_response.mp4`, `msdo_dc.mp4`) and are embedded with `<video autoplay loop muted playsinline>` rather than `<img>` — those replaced 5.8 MB of GIF with 1.3 MB of MP4.

`favicon.png` is the lone PNG that should **not** be converted — browsers reference it via `<link rel="icon" type="image/png">`.
