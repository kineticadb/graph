# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kinetica Graph Explorer — a React-based single-page application for exploring graph data structures stored in a Kinetica GPU database.

**`KineticaGraphExplorer.html`** — Standalone HTML file, all dependencies via CDN, Babel transpiles JSX in-browser. Open directly in a browser, no build step needed.

There is no package.json, no build system, no test framework, and no linting configuration.

## Development

Edit `KineticaGraphExplorer.html` and open/refresh in a browser. No build or install steps.

## Architecture

### Component Hierarchy

`App` (root, ~300 lines) manages all top-level state: graphs, credentials, labels, ontology, picking mode, and split-pane layout. Child components:

- `Sidebar` — Server connection (URL, credentials, profile switching via `DEFAULT_PROFILES`), graph list
- `DashboardHeader` — Graph title, refresh status, action buttons (Ontology, Query, Save, Load, Auto-run, Refresh, Pick, Auto)
- `SummaryCards` — Node/edge count statistics
- `LabelChart` — Doughnut chart (Chart.js) + interactive table for label distribution
- `OntologyViewer` — Graphviz WASM rendering of graph ontology DOT with D3 zoom/pan and node/edge picking
- `CanvasGraph` — force-graph (force-graph library) 2D visualization of graph topology with node coloring by label
- `GraphTablePreview` — Tabular preview of a graph's backing table data fetched via `/get/records`
- `QueryPanel` — Self-contained floating SQL window (multiple instances supported). SQL editor on top, "View Results" and "Visualization" toggle buttons below. Each panel manages its own query execution, results, and state. Exposes state via `stateRef` for session save. Result parsing is memoized; force-graph uses ResizeObserver for responsive scaling with zoomToFit on resize
- `SplitPane` — Resizable split layout (horizontal/vertical) with draggable divider and double-click reset
- `CornerHandle` — Draggable corner resize handle for floating panels
- `LoaderOverlay` — Loading spinner with abort capability
- `WelcomeScreen` — Empty/initial state

### API Hook

`useKineticaApi` — Custom React hook handling all Kinetica REST API communication. Supports AbortController cancellation, 10-minute timeout, and Basic Auth (base64).

### Kinetica API Endpoints Used

- `POST /show/graph` — List graphs (empty name) or get graph label details (specific name)
- `POST /modify/graph` — Retrieve graph ontology in DOT format
- `POST /get/records` — Fetch backing table rows for `GraphTablePreview`
- `POST /execute/sql` — Run SQL/GQL queries via `QueryPanel`

### Key Libraries (loaded via CDN)

- React 18, D3 v7, Chart.js, Graphviz HPCC WASM, force-graph

### Cross-View Picking

Clicking nodes/edges in the `OntologyViewer` highlights matching labels in the `LabelChart` table. Coordinated through shared `pickedLabel`/`pickingMode` state in `App`.

### Helpers

- `extractGraphTable(originalRequest, graphName)` — Parses the graph creation statement to find the backing table name
- `resolveCol(headers, candidates)` — Fuzzy column name resolution for table preview
- `safeParse(str, fallback)` — Safe JSON.parse wrapper

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
- `queries[]` — Array of open query panels with `sql` text and `activeTab` state

On load: reconnects to the server, selects the graph, restores label selections, ontology, re-fetches table data + visualization if previously active, and reopens query panels. If **Auto-run** toggle is on (default), restored queries execute automatically and show their visualizations. Schema defined in `tests/session_schema.json`.

**Implementation notes:**
- `loadGraphDetails` returns the extracted `graphTable` value, which `loadSession` passes directly to `fetchGraphTableData(gt)` to avoid stale closure issues
- `fetchGraphTableData(overrideTable)` accepts an optional string parameter; non-string arguments (e.g., React click events from `onClick={onFetch}`) are ignored via `typeof` check
- Query panels are cleared when switching graphs or disconnecting
- Label refresh does not redraw query visualizations — `labelColorMap` is built once from initial `labelData` via a ref

### `/show/graph` Response Format

Also double-wrapped via `data_str`. The `info.labeljson` field (JSON string) contains `node_labels`, `edge_labels` arrays (each with `labels` and `count`), plus `total_labeled_nodes/edges` and `total_unlabeled_nodes/edges`.

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
