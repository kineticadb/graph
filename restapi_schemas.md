# Graph REST API Reference

This document provides a comprehensive reference for the Graph REST API endpoints. These endpoints allow you to create, query, solve, and manage graph networks.

---

## Table of Contents

* [Create Graph (`/create/graph`)](https://www.google.com/search?q=%23create-graph)
* [Query Graph (`/query/graph`)](https://www.google.com/search?q=%23query-graph)
* [Solve Graph (`/solve/graph`)](https://www.google.com/search?q=%23solve-graph)
* [Match Graph (`/match/graph`)](https://www.google.com/search?q=%23match-graph)
* [Show Graph (`/show/graph`)](https://www.google.com/search?q=%23show-graph)

---

## Create Graph

**Endpoint:** `/create/graph`

**Description:** Creates a new graph network using provided nodes, edges, weights, and restrictions. It is highly recommended to review the [Graphs and Solvers](https://www.google.com/search?q=/graph_solver/network_graph_solver/) documentation before use.

### Fields

| Name | Type | Description |
| --- | --- | --- |
| `graph_name` | `string` | **Required.** Unique name for the graph resource. |
| `directed_graph` | `boolean` | If `true` (default), the graph is directed. |
| `nodes` | `array<string>` | Node identifiers (e.g., `'table.column AS NODE_ID'`). |
| `edges` | `array<string>` | Edge identifiers (e.g., `'table.column AS EDGE_ID'`). |
| `weights` | `array<string>` | Inform the solver of edge costs (e.g., `'ST_LENGTH(wkt) AS WEIGHTS_VALUESPECIFIED'`). |
| `restrictions` | `array<string>` | Nodes/edges to be ignored (e.g., `'column AS RESTRICTIONS_VALUECOMPARED'`). |
| `options` | `map<string, string>` | Optional parameters for graph creation. |

### Selected Options

* `recreate`: If `true`, deletes and recreates the graph if it already exists (Default: `false`).
* `save_persist`: If `true`, saves the graph to the persist directory; otherwise, it is lost on shutdown.
* `add_table_monitor`: If `true`, the graph updates dynamically upon inserts to source tables.
* `merge_tolerance`: Minimum separation allowed between unique geospatial nodes (Default: `1.0E-5`).

---

## Query Graph

**Endpoint:** `/query/graph`

**Description:** Performs a topological query (adjacency list) on an existing graph. Providing edges returns nodes; providing nodes returns edges.

### Fields

| Name | Type | Description |
| --- | --- | --- |
| `graph_name` | `string` | Name of the graph to query. |
| `queries` | `array<string>` | Identifiers for nodes or edges to query. |
| `rings` | `int` | Number of hops (rings) to traverse (Default: `1`). `0` returns nodes matching criteria. |
| `adjacency_table` | `string` | Table to store results. If blank, results return in the response. |

### Selected Options

* `force_undirected`: If `true`, returns both inbound and outbound edges for directed graphs.
* `limit`: Limits the number of query results.
* `find_common_labels`: Lists common labels between source and target nodes.

---

## Solve Graph

**Endpoint:** `/solve/graph`

**Description:** Solves an existing graph for specific problems like shortest path, page rank, or the traveling salesman problem.

### Solver Types

* `SHORTEST_PATH`: Optimal path from source to destination (Dijkstra).
* `PAGE_RANK`: Probability of nodes being visited based on topology.
* `MULTIPLE_ROUTING`: Traveling Salesman Problem (round-trip min cost).
* `CENTRALITY`: Measures node importance (betweenness).
* `BACKHAUL_ROUTING`: Connects remote assets to backbone nodes.

### Fields

| Name | Type | Description |
| --- | --- | --- |
| `solver_type` | `string` | The algorithm to use (Default: `SHORTEST_PATH`). |
| `source_nodes` | `array<string>` | Starting point identifiers. |
| `destination_nodes` | `array<string>` | Target point identifiers. |
| `solution_table` | `string` | Table name for the result (Default: `graph_solutions`). |

---

## Match Graph

**Endpoint:** `/match/graph`

**Description:** Matches latitude/longitude points to an existing road network graph. Useful for snap-to-road functionality and logistics optimization.

### Solve Methods

* `markov_chain`: Hidden Markov Model (HMM) for highly accurate road matching.
* `match_supply_demand`: Optimizes scheduling multiple supplies to varying demand sites.
* `match_charging_stations`: Optimal path across EV-charging stations.
* `match_isochrone`: Solves for reachability limits (isochrones).

### Key Options

* `gps_noise`: Meters to ignore for redundant points (Default: `5.0`).
* `search_radius`: Max snapping distance for sample points.
* `partial_loading`: (MSDO only) Allows off-loading only part of a truck's supply.

---

## Show Graph

**Endpoint:** `/show/graph`

**Description:** Returns information and characteristics of graphs existing on the server.

### Fields

| Name | Type | Description |
| --- | --- | --- |
| `graph_name` | `string` | Specific graph to inspect. If empty, returns all graphs. |
| `options` | `map` | `show_original_request`: Returns the JSON used to create the graph (Default: `true`). |


