# 💻 A simple wikipedia example
<h2> A property graph between persons as entities with interests as labels and their ties as relations</h2>

To streamline graph creation in Kinetica, you can leverage **pre-defined grammar aliases** for your column names. Using these specific names allows the engine to automatically map your data, removing the need for explicit AS directives or manual annotations.

**🧩 Core Concepts**

Graphs in Kinetica are built from two primary components: **Nodes** and **Edges**.

* **Grammar Verification**: To view the full list of valid identifier combinations for your version, call the /show/graph/grammar endpoint.  
* **Polymorphic Labels**: The alias LABEL is context-aware. In a Node section, it maps to NODE\_LABEL; in an Edge section, it maps to EDGE\_LABEL.

**🏗️ Component Naming Conventions**

By using the generic aliases below, the /create/graph endpoint will automatically ingest your tables without extra configuration.

### **Node Tables**

| Generic Alias | Technical Identifier | Description |
| :---- | :---- | :---- |
| **NODE** | NODE\_ID / NODE\_NAME | The primary identifier (Integer or String). |
| **LABEL** | NODE\_LABEL | Categorical string used to classify the node. |

**Note:** Additional columns (e.g., age, revenue) are ignored during the graph build but remain available for **OLAP joins** during Cypher queries.

### **Edge Tables**

| Generic Alias | Technical Identifier | Description |
| :---- | :---- | :---- |
| **NODE1** | EDGE\_NODE1\_NAME | The source node of the relationship. |
| **NODE2** | EDGE\_NODE2\_NAME | The target node of the relationship. |
| **LABEL** | EDGE\_LABEL | The type of relationship (e.g., 'FRIEND\_OF'). |


<div style="width:20%; margin: auto;">
<kbd>
<img  width="100%" src="./wikipedia.png" />
</kbd>
</div>

### **1\. Define Your Tables**

Create tables using the standard grammar to bypass manual mapping.

```SQL
-- Create the nodes table schema
CREATE OR REPLACE TABLE wiki_graph_nodes (    
    node  CHAR(64) NOT NULL,
    label VARCHAR[] NOT NULL,
    -- Non-graph columns    
    age   INT
);

CREATE OR REPLACE TABLE wiki\_graph\_edges (      
    node1  CHAR(64) NOT NULL,  
    node2  CHAR(64) NOT NULL,  
    label  VARCHAR[] NOT NULL,
    -- Non-graph column  
    met_time DATE   
);
```
### **2\. Insert data into nodes and edges tables**
```SQL
INSERT INTO wiki_graph_nodes(node,label,age) VALUES 
('Jane', string_to_array('FEMALE,business',','),29),
('Bill', string_to_array('MALE,golf',','),58),
('Susan',string_to_array('FEMALE,dance',','),24),
('Alex', string_to_array('MALE,chess',','),23),
('Tom',  string_to_array('MALE,chess',','),42);

INSERT INTO wiki_graph_edges(node1,node2,label,met_time) VALUES 
 ('Jane','Bill',string_to_array('Friend',','),'1997-09-15'),
 ('Bill','Alex',string_to_array('Family',','),'1991-02-26'),
 ('Bill','Susan',string_to_array('Friend',','),'2001-01-30'),
 ('Susan','Alex',string_to_array('Friend',','),'2010-04-19'),
 ('Alex','Tom',string_to_array('Friend',','),'2024-10-07');
```

* **Grammar Verification**: To view the full list of valid identifier combinations, call the `/show/graph/grammar` endpoint. This returns a JSON object listing identifiers and combinations (e.g., the `NODE` and `LABEL` two-tuple) per component.
* **Auto-Annotation**: By using the names `node`, `node1`, `node2`, and `label`, you bypass the need for `AS` directives in your graph endpoints.

### **3\. Create Graph**

This step involves defining the directed graph using the `input_tables` macro. Because the underlying tables follow the recommended naming conventions (the "Graph Grammar"), the syntax remains clean and concise. 

### Ontology & Label Grouping

To keep the graph schema (ontology) concise, you can group labels under "Label Keys." For example, "MALE" and "FEMALE" can be grouped under a "Gender" super-set.

* **Label Keys**: Using `LABEL_KEY` allows the system to collapse the ontology visualization based on these categories.
* **Default Behavior**: The option to use label keys for ontology generation is enabled by default (`true`).

```SQL
-- Create or Replace a directed graph with label groupings and debugging table

CREATE OR REPLACE DIRECTED GRAPH wiki_graph (
    nodes => input_tables(
        -- Optional label groupings for concise ontology generation
        (SELECT 'Gender' AS LABEL_KEY, string_to_array('MALE,FEMALE',',') AS LABEL),
        (SELECT 'Interest' AS LABEL_KEY, string_to_array('golf,business,dance,chess',',') AS LABEL),

        -- Primary node data
        (SELECT * FROM wiki_graph_nodes)
    ),
    edges => input_tables(
        -- Optional label groupings for relations
        (SELECT 'Relations' AS LABEL_KEY, string_to_array('Family,Friend',',') AS LABEL),

        -- Primary edge data
        (SELECT * FROM wiki_graph_edges)
    ),
    options => kv_pairs(graph_table = 'wiki_graph_table')
);
```
<h3 style="text-align: center;"> View Schema (ontology)</h3>
<img  src="./schema.png" />

To view the full graph schema ontology without grouping entities by their label_keys, disable the grouping options via the ALTER GRAPH endpoint as shown below.

For a deeper dive into the ontology, click the "View Schema" button. Note that disabling label-key compression expands the schema to show all individual label connections. The percentages indicate the distribution of nodes and edges; for instance, a node labeled MALE:CHESS at 40% signifies that 40% of all nodes in the graph carry both labels. In large datasets, these metrics are vital for understanding graph density and calculating the hop distance between specific label sets.

```SQL
ALTER GRAPH wiki_graph MODIFY (
    options => kv_pairs(schema_node_labelkeys = 'false', schema_edge_labelkeys = 'false')
);
```
<img  src="./labelschemas.png" />

⚠️ WARNING: The MODIFY command supports the same components as CREATE GRAPH. Use this to retarget graph tables or perform CRUD operations on nodes, edges, weights, and restrictions.

* **Simplified Selection**: Since the table columns match the expected grammar (e.g., `node`, `label`), you can use a simple `SELECT *` or even just the table name.
* **Explicit Annotation**: If your table used non-standard names (e.g., `Person` instead of `node`), you would be required to use the `AS` keyword to map them:
`nodes => input_tables((SELECT Person AS node, hobby AS label FROM wiki_graph_nodes))`

## 4\. Visualization & Debugging

Click the Config button inside the Visualization tab to modify the UI:

<img src="./graphui.png">

* **graph\_table**: This option creates relational tables (e.g., wiki\_graph\_table\_nodes) that mirror the in-memory graph.  
* **Performance Warning**: Avoid using graph\_table for graphs larger than **1,000 elements**, as the overhead for table generation is high.  
* **Workbench UI**: These tables power the generic graph UI using the **Orb library**, allowing for visual inspection and force-directed layouts.

<img src="./wikigraph.png">

# 5.\.Graph Query Guide: Multi-Hop Traversal

This guide explains how to identify "friends of friends" of a specific node (e.g., 'Tom') within two hops using Cypher syntax and specific system hints.

## 5.1. Basic Syntax and Filtering
In Cypher, a single-hop relationship is expressed as:
` (n1)-[e]->(n2) `

* **Labels:** Filter by labels using the `variable:label` syntax.
* **Attributes:** Apply specific attribute filters within a `WHERE` clause.
    * *Example:* `(c:chess WHERE c.age < 50)` depicts a node with the label 'chess' where the 'age' property is less than 50.

## 5.2. Directionality and Global Options
Edge direction is critical in directed graphs. If the starting node (e.g., 'Tom') does not have outgoing edges, you must adjust the query:

* **Manual Flip:** Reverse the arrow direction: `()<-[]-()`.
* **Undirected Search:** To treat all edges as bidirectional, you must enable the global `force_undirected` option. 

Add the following comment hint anywhere within your call:
`/* KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, true) */`

## 5.3. Results and Aliasing
When returning multiple nodes from different hops, the return syntax requires distinct alias names to differentiate column outputs.
* **Requirement:** Use `AS` to rename columns.
* **Convention:** `RETURN a.node AS originator, c.node AS target`.

## 5.4. Visualization and Styling
Once the query is executed, you can inspect the results in two ways:

| Tab | Description |
| :--- | :--- |
| **Data** | Displays the raw tabular output and captured variables. |
| **Visualization** | Shows the graphical representation of the graph. |

### Customizing the Graph View
Click the **Config** button inside the **Visualization** tab to modify the UI:
* **Nodes:** It is recommended to color nodes by their **Labels**.
* **Edges:** Set edge coloring to the **Path** option. This ensures each unique traversal path found in the query is assigned a distinct color, making complex multi-hop results easier to read.
* **Legend:** A tabular legend in the upper-right corner of the canvas will display the color mappings for each label and path combination.
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
```SQL
GRAPH wiki_graph 
MATCH (a:MALE  WHERE(node = 'Tom') )<-[b:Friend]-(c) <- [d] - (e) 
RETURN a.node as originator, c.node as friend, e.node as target
```
<img src="./cypherquery.png"/>
