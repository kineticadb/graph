# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kinetica Graph Explorer (v7.2.3.12) — a React-based single-page application for exploring graph data structures stored in a Kinetica GPU database.

**`KineticaGraphExplorer.html`** — Standalone HTML file, all dependencies via CDN, Babel transpiles JSX in-browser. Open directly in a browser, no build step needed.

There is no package.json, no build system, no test framework, and no linting configuration.

## Development

Edit `KineticaGraphExplorer.html` and open/refresh in a browser. No build or install steps.

## Architecture

### Component Hierarchy

`App` (root) manages all top-level state: graphs, credentials, labels, ontology, picking mode, and split-pane layout. Child components:

- `Sidebar` — Server connection (URL, credentials, profile switching via `DEFAULT_PROFILES`), graph list, session Load/Save buttons, Auto-run toggle. Shows version number
- `DashboardHeader` — Split-aligned layout matching `hSplit` pane proportion. Left side (`hSplit%`): graph name, N:/E: counts (blue/green), color-coded progress bar (blue=nodes, green=edges), separator, `+ Query` button + minimized Q1/Q2 pills. Right side (`1-hSplit%`): `Pick` + Auto-refresh + timestamp. Separator aligns with label chart boundary
- `SummaryCards` — Labeled/unlabeled node/edge counts with distinct label counts
- `LabelChart` — Doughnut chart (Chart.js) + interactive table for label distribution. Table supports clickable column headers to sort by label name (alphabetical) or count (default). Row colors always match the chart via `colorIdxMap` lookup
- `OntologyViewer` — Graphviz WASM rendering of graph ontology DOT with D3 zoom/pan and node/edge picking. Always visible once graph loaded; clears to "No ontology available" when `dotString` is null (e.g., graph with no labels). Header bar includes Full/NKey/EKey schema toggles (auto-reload ontology on change), `↻ Refresh` button, Reset View button, and `⤢` maximize / `▣ Restore` button (full viewport overlay, Esc to restore)
- `CanvasGraph` — force-graph (force-graph library) 2D visualization for non-WKT graphs. Always visible once graph loaded (black canvas placeholder when no data). Single-line responsive header: title + compact stats + selected label filters (left), flex node/edge sliders + viz limit + `↻ Pull+Visualize` button (right, never clipped). Colors match LabelChart via combo key color map. Click-to-copy node ID + node detail lookup from source table. `⤢` maximize / `▣ Restore` button. Supports both NAME and ID column schemas
- `MapView` — Geospatial graph renderer (auto-selected when `identifierType === 'wkt'`). Two rendering modes based on edge count:
  - **Client-side canvas** (<2M edges): Pre-parsed WKT→Float32Array coords per batch (no WKT strings retained), color-batched drawing, rAF-throttled rendering, adaptive LOD decimation, progressive rendering (draws edges onto canvas as batches arrive — no final concat). Edge IDs stored in chunked arrays for pick. Zoom (cursor-centered), pan, HiDPI, viewport culling. Data bounding box (dashed orange) shown during interaction. Edge picking shows EDGE_ID + NODE1_WKTPOINT + NODE2_WKTPOINT + source table lookup. Label filtering supported
  - **WMS server-side** (>2M edges): Kinetica `/wms` endpoint renders PNG tiles. Three styles selectable via header buttons (`Heatmap | CB | Auto`): **Auto** (default) uses heatmap at low zoom <30x, `cb_raster` at deep zoom if edge labels available; **Heatmap** forces heatmap at any zoom; **CB** forces class-break raster coloring by edge label. `cb_raster` uses top 20 labels (by count), PALETTE colors matching LabelChart, numeric midpoint ranges for numeric label columns. `extractEdgeSourceTable` provides `{ table, idCol, wktCol, labelCol }` — `labelCol` extracted from `AS LABEL`/`AS EDGE_LABEL` alias (handles `func(col) AS LABEL` casts). BBOX auto-computed from edge table via `ST_MINX/MAXX/MINY/MAXY` SQL query, aspect-ratio adjusted to container. Zoom/pan update BBOX and debounce-fetch new tiles. Header shows zoom level + active style. `⤢` maximize / `▣ Restore` button
- `QueryPanel` — Self-contained floating SQL window (multiple instances supported) with minimize/maximize/restore/close buttons. Minimize collapses to Q1/Q2 pill in header bar (state preserved via stateRef snapshot). Contains: collapsible **Query Helper** (top, generates GQL from multi-label/entity selections using ontology BFS with waypoints and direction-aware arrows), SQL editor, "View Results" and "Visualization" toggle buttons. Helper auto-collapses after query generation; layout dynamically allocates space (60% helper expanded / 35% collapsed when tab active). Each panel manages its own query execution, results, and state. Exposes state via `stateRef` for session save (including helper fields). Result parsing is memoized; force-graph uses ResizeObserver for responsive scaling with zoomToFit on resize. Click-to-copy node ID + node detail lookup from source table
- `SplitPane` — Resizable split layout (horizontal/vertical) with draggable divider and double-click reset
- `CornerHandle` — Draggable corner resize handle for floating panels
- `WelcomeScreen` — Empty/initial state

### API Hook

`useKineticaApi` — Custom React hook handling all Kinetica REST API communication. Supports AbortController cancellation, 10-minute timeout, and Basic Auth (base64).

### Kinetica API Endpoints Used

- `POST /show/graph` — List graphs (empty name), get graph label details + ontology DOT (specific name with `export_graph_schema: 'true'`). Supports internal options: `schema_node_labelkeys`, `schema_edge_labelkeys`, `schema_full_search`. Ontology auto-loads on graph selection — no separate Ontology button needed
- `POST /get/graph/entities` — Fetch graph nodes/edges directly from the graph server (preferred). Options: `entity_type` (`"node"`/`"edge"`), `offset`, `limit` (-1 for all). Response: strided flat arrays (`entities_int`/`entities_string`), `labels` array (1-based index, may be JSON arrays for multi-label), `info.identifier_type`, `info.total_count`. Batches at 100K for graphs >500K edges. Falls back to table-based fetch if endpoint unavailable
- `POST /get/records` — Fallback: fetch backing table rows for visualization; also used for node detail lookup from source table
- `POST /execute/sql` — Run SQL/GQL queries via `QueryPanel`; also used for WMS BBOX computation (`ST_MINX/MAXX/MINY/MAXY`)
- `GET /wms` — Server-side map tile rendering for large WKT graphs (>2M edges). Supports `heatmap` (fast, low zoom) and `raster` (detailed, high zoom) styles. Parameters: `LAYERS`, `GEO_ATTR`, `BBOX`, `WIDTH`, `HEIGHT`, `SRS=EPSG:4326`, `STYLES`

### Key Libraries (loaded via CDN)

- React 18, D3 v7, Chart.js, Graphviz HPCC WASM, force-graph

### Cross-View Picking

Clicking nodes/edges in the `OntologyViewer` highlights matching labels in the `LabelChart` table. Coordinated through shared `pickedLabel`/`pickingMode` state in `App`.

### Helpers

- `extractGraphTable(originalRequest, graphName)` — Parses the graph creation statement to find the backing table name
- `extractNodeSourceTable(originalRequest, graphName)` — Parses `NODES => INPUT_TABLE(S)(...)` section to find the original node source table and ID column
- `extractEdgeSourceTable(originalRequest, graphName)` — Parses `EDGES => INPUT_TABLE(S)(...)` section to find the original edge source table, ID column, and WKT geometry column (aliased as `EDGE_WKTLINE`). Returns `{ table, idCol, wktCol }`. Used for edge picking and WMS `GEO_ATTR`
- `resolveCol(headers, candidates)` — Fuzzy column name resolution for table preview
- `safeParse(str, fallback)` — Safe JSON.parse wrapper
- `normNodeKey(raw)` — Normalizes DOT node names like `"FEMALE:\ndance (20%)"` to keys `"FEMALE|dance"`

### Query Helper

Collapsible panel inside each QueryPanel that generates GQL queries from form inputs. Opens expanded by default; auto-collapses after generating a query (clears previous visualization). All state is preserved on collapse/expand and saved in sessions.

- **Inputs**: Source Label(s) (multi-select tag picker), Source Entity (optional), Target Label(s) (multi-select), Target Entity (optional)
- **Waypoints**: "+ Add Hop" adds intermediate constraints. Each hop row shows: hop index (large) | Node Label(s) (multi-select tags) | → | Edge Label(s) (multi-select tags) | ✕ remove. Both node and edge labels support multi-select with OR logic. Pathfinding auto-determines hop count — no manual Hops input needed
- **Multi-label (OR logic)**: Selecting multiple labels (e.g., `street_address` + `email`) means "match nodes with ANY of these labels". GQL syntax: `(a:street_address|email)`. Same for edges: `manages` + `part_of` → `-[e:manages|part_of]->`. Pathfinding tries routes from all matching ontology nodes. User-selected edge labels are preserved in generated GQL even when BFS finds a path via a single edge
- **Ontology pathfinding**: Parses `dotString` into adjacency map via regex (matches both `->` directed and `--` undirected edges; normalizes multi-label DOT names). For undirected graphs (`graph G { ... -- ... }`), adds edges in both directions and generates `-[]-` edges in GQL (no arrows). Builds reverse adjacency for bidirectional BFS. Chains through waypoints finding sub-paths. For directed graphs, respects edge direction (`dir: 'fwd'` → `->`, `dir: 'rev'` → `<-`). Edge label constraints use OR matching. `labelsToKeys` sorts results to prefer exact matches over partial (e.g., `actor` before `actor|director`)
- **GQL generation**: Uses only user-selected labels (not full ontology keys) in MATCH patterns. Uses `as` aliases in RETURN (e.g., `a.NODE as a_node`). Labels with spaces are double-quoted (e.g., `(c:"news company")`). Graph names are always double-quoted per part (e.g., `GRAPH "schema"."355_g"`). Falls back to generic untyped pattern when ontology not loaded or no path found
- **Collapsed status**: When helper is collapsed after generation, the path found info (with arrows) shows in green next to the header
- **Auto-visualization**: Query results with hop data automatically switch to the Visualization tab. No-result queries and new query generation clear the previous visualization
- **Node Detail Lookup**: Clicking a node in the visualization fetches its full record from the original node source table. Displayed as a horizontal table strip below the graph. Cleared on Generate Query or Run
- **Props needed**: `dotString`, `activeGraph`, `graphDirected`, `labelData`, `nodeSourceTable` passed from App to QueryPanel

### Node Source Table Extraction

`extractNodeSourceTable(originalRequest, graphName)` parses the graph creation statement's `NODES => INPUT_TABLES(...)` section:
- Finds all `FROM <table>` references and uses the last real table (handles multi sub-select cases like wiki_graph with constants + real table)
- Extracts the original ID column aliased as `NODE` or `NODE_ID`
- If no alias found, probes the table at fetch time for common ID columns (`node`, `id`, `NODE_NAME`, `NODE_ID`, `name`)
- App stores result as `nodeSourceTable: { table, idCol }` state, passed to QueryPanel and CanvasGraph
- Node click uses `/get/records` with `expression` filter on the source table's original ID column (tries string then numeric match)

### Kinetica `/execute/sql` Response Format

Responses are **double-wrapped**: the top-level JSON has `{ status, message, data_type, data, data_str }`. The actual payload is inside `data_str` (a JSON string that must be parsed). Once unwrapped, graph queries produce **two distinct data sources**:

**`data_str.json_encoded_response`** — Contains the **RETURN statement** columns (e.g., `bank`, `wire`, `ablabel`, `transaction`, `banking_transaction_amount`). This is what the "View Results" button displays. Column-oriented object with `column_headers`, `column_datatypes`, and `column_1`..`column_N` arrays.

**`data_str.info.gql_result`** — Contains the **hop-based path structure** (`NODE1_HOP_1`, `NODE2_HOP_1`, `EDGE_LABELS_HOP_1`, etc.). This is what the "Visualization" button uses to build the force-graph. Same column-oriented format as above.

Both use the same structure: iterate `column_1[i]`..`column_N[i]` for each row index `i`, using `column_headers` for display names.

Other fields: `data_str.info.count` (record count), `data_str.response_schema_str` (Avro schema).

### Session Save/Load

Sessions are saved as JSON files (schema version 1). The session object captures:
- `connection` — Server URL and username (password excluded)
- `graph.name` — Active graph, `selectedNodeLabels`, `selectedEdgeLabels`, `ontologyDot`
- `graph.dataFetched` — Whether table data was loaded; `graph.showForceGraph` — Whether visualization was active
- `queries[]` — Array of open query panels with `sql` text, `activeTab` state, and `helper` object (srcLabels, srcEntity, tgtLabels, tgtEntity, waypoints, showHelper)

On load: uses the active server connection (warns if session server differs), checks graph exists (warns if not found), restores label selections, ontology, re-fetches graph data + visualization if previously active, and reopens query panels. If **Auto-run** toggle is on (default), restored queries execute automatically. Session Load/Save/Auto-run controls are in the Sidebar (visible when connected). Schema defined in `tests/session_schema.json`. Session files named with timestamp: `graph_session_YYYYMMDD_HHMM.json` for chronological sort order.

**Session loss protection**: Switching graphs, changing profiles, connecting, or loading a session triggers a red confirmation banner: "Active session for **graph** will be lost" with `[Save & Continue]` `[Continue]` `[Cancel]` buttons. Same red (`#d63031`) used for viz limit warning banner.

**Implementation notes:**
- `loadGraphDetails` calls `/show/graph` with `export_graph_schema: 'true'` to get labels + ontology DOT + directed flag in one call. On graph change, clears all stale state (dotString, graphTableData, labelData, graphCounts, maximizedPanel, nodeSourceTable, edgeSourceTable) before the API call
- `fetchGraphData` tries `/get/graph/entities` first, falls back to `fetchGraphTableData` if unavailable. Accepts optional `overrideGraph` parameter to avoid stale closure issues during session restore
- `fetchGraphEntities` batches at 100K for graphs >500K edges (determined from `labelData`), single `limit:-1` for smaller graphs. Also accepts `overrideGraph` to bypass stale `activeGraph` closure
- Query panels are cleared when switching graphs or disconnecting
- Label refresh does not redraw query visualizations — `labelColorMap` is built once from initial `labelData` via a ref
- Column resolution (`resolveCol`) supports both NAME and ID variants; link source/target are stringified for force-graph compatibility
- **Ontology toggles** (Full/NKey/EKey) in OntologyViewer header bar auto-reload ontology via `reloadOntology` when toggled. `↻ Ontology` button in DashboardHeader for manual refresh. Ontology auto-loads on graph selection
- All UI buttons have hover tooltips describing their function
- ResizeObserver only calls `zoomToFit` on significant size changes (>120px) to prevent re-centering when node detail strip toggles
- **Label selection uses combo keys**: Selecting a multi-label row stores a single combo key (sorted, pipe-joined). Filters match exact combos
- **Color maps use combo keys with n:/e: prefixes**: Node and edge charts assign PALETTE indices independently. `getNodeLabelColor`/`getEdgeLabelColor` and `getNodeColor`/`getEdgeColor` parse raw JSON labels to combo keys for lookup
- **Graph directed flag** (`graphDirected`) extracted from `/show/graph` response `directed` field during `loadGraphDetails`. Undirected detection also works from ontology DOT (`graph G { ... -- ... }`)
- Node/edge sliders go up to 1M

### `/show/graph` Response Format

Also double-wrapped via `data_str`. Key fields:
- `info.labeljson` — JSON string with `node_labels`, `edge_labels` arrays (each with `labels` and `count`), plus `total_labeled_nodes/edges` and `total_unlabeled_nodes/edges`
- `info.dot` — Graphviz DOT string (when `export_graph_schema: 'true'`)
- `directed` — Array of booleans indicating if each graph is directed

## Tests

```bash
python3 tests/test_banking_query.py           # all tests (requires live server)
python3 tests/test_banking_query.py --offline  # fixture-only tests (no server)
```

Test fixtures in `tests/`:
- `banking_query_response.json` — Saved `/execute/sql` response for the banking GQL query
- `banking_show_graph_response.json` — Saved `/show/graph` response for `expero.banking_graph`
- `expero_banking_graph_session.json` — Saved session file with graph state, labels, ontology DOT, and 2 GQL queries
- `session_schema.json` — JSON Schema for session file validation

**Test suites** (30 total):
- `TestFixtureParsing` (10 offline) — Response parsing, hop structure, labels, path continuity
- `TestSessionFixture` (13 offline) — Session schema validation, structure, DOT, queries, flags
- `TestLiveServer` (3 live) — Query execution, show/graph, fixture-vs-live consistency
- `TestSessionLiveRestore` (4 live) — Server reachable, graph exists, queries execute with hops, labels valid

**Test reference data** (server: `http://127.0.0.1:9191`, user: `admin`, password: `***REMOVED***`):
- Graph: `expero.banking_graph`
- Query: 2-hop GQL — bank → wire_message → banking_transaction (65 records)
- Node labels: `bank`, `wire_message`, `banking_transaction`
- Edge labels: `performed`, `is_for_transaction`
- Path continuity invariant: `NODE2_HOP_1 == NODE1_HOP_2` for every row
