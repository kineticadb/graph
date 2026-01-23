# **Kinetica Graph: Schema & Naming Best Practices**

To streamline graph creation in Kinetica, you can leverage **pre-defined grammar aliases** for your column names. Using these specific names allows the engine to automatically map your data, removing the need for explicit AS directives or manual annotations.

## ---

**🧩 Core Concepts**

Graphs in Kinetica are built from two primary components: **Nodes** and **Edges**.

* **Grammar Verification**: To view the full list of valid identifier combinations for your version, call the /show/graph/grammar endpoint.  
* **Polymorphic Labels**: The alias LABEL is context-aware. In a Node section, it maps to NODE\_LABEL; in an Edge section, it maps to EDGE\_LABEL.

## ---

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

## ---

**💻 Implementation Example**

### **1\. Define Your Tables**

Create tables using the standard grammar to bypass manual mapping.

SQL

\-- Schema using standard grammar  
CREATE OR REPLACE TABLE wiki\_graph\_nodes (      
    node  CHAR(64) NOT NULL,  
    label VARCHAR\[\] NOT NULL,  
    age   INT \-- Non-graph column  
);

CREATE OR REPLACE TABLE wiki\_graph\_edges (      
    node1  CHAR(64) NOT NULL,  
    node2  CHAR(64) NOT NULL,  
    label  VARCHAR\[\] NOT NULL,  
    met\_time DATE \-- Non-graph column  
);

### **2\. Create the Graph**

Because the columns match the expected grammar, the syntax remains clean. You can also group labels under **LABEL\_KEY** (e.g., grouping "MALE" under "Gender") to keep the ontology concise.

SQL

CREATE OR REPLACE DIRECTED GRAPH wiki\_graph (  
    nodes \=\> input\_tables(  
        \-- Optional label groupings for ontology  
        (SELECT 'Gender' AS LABEL\_KEY, string\_to\_array('MALE,FEMALE',',') AS LABEL),  
        \-- Primary node data (Auto-mapped)  
        (SELECT \* FROM wiki\_graph\_nodes)  
    ),  
    edges \=\> input\_tables(  
        (SELECT \* FROM wiki\_graph\_edges)  
    ),  
    \-- graph\_table creates relational tables for debugging/UI  
    options \=\> kv\_pairs(graph\_table \= 'wiki\_graph\_table')  
);

## ---

**⚠️ Visualization & Debugging**

* **graph\_table**: This option creates relational tables (e.g., wiki\_graph\_table\_nodes) that mirror the in-memory graph.  
* **Performance Warning**: Avoid using graph\_table for graphs larger than **1,000 elements**, as the overhead for table generation is high.  
* **Workbench UI**: These tables power the generic graph UI using the **Orb library**, allowing for visual inspection and force-directed layouts.

---

**Would you like me to generate a sample JSON request body for the /create/graph REST endpoint using these same conventions?**