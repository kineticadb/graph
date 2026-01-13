
<img alt="Kinetica-Graph" src="./title_image.png" />

# Kinetica-Graph

---

__Kinetica Graph is a distributed hybrid Graph Database that works in tandem with its relational Kinetica-DB and its OLAP expression support__. What differentiates Kineti-Graph from others are the following:

- Fixed and calculable storage bytes in memory regardless of unstructured vertex valences. It requires a total memory 2x the CSR format (bare-minimum) plus the label indexes. The formula is basically __4 X the number of graph edges__.

- Because of its __inplace double links__ graph topology data structure, it is inherently a __dynamic__ graph database; hence insertions and deletions are in constant time without having to recreate the entire graph structure at each modification as is the case for CSR based graph databases (neo4j, tiger).

- All of its endpoints allow __OLAP expression support__ which makes the graph output to be readily useful as a table function for further joins and group bys. Thanks to its hybrid implementation a complex analytics can be expressed in one __concise SQL statement__.

- Graph only duplicates graph topology related data from rich structured relational data. The access to other columns and rich attributes is seamlessly available via its expression support and the data is __sharded and distributed__ in the most efficient manner by its accompanying relational Kinetica database.

- Graph itself can be __distributed over many graph servers__ that can be orchestrated over a single or many nodes of a cluster. The only duplication is done via the nodes over the inter-graph (processor) boundaries, none of the __partitioned graphs__ need to know the other graphs' duplicated nodes. The algorithms (graph solvers) are capable of iterating between the partitions.

- __Multi-hop multiple path many-to-many__ property graph queries are __Cypher__ compliant. GQL standards are  followed. We have the optimized the query planning and tied the access to all data seamlessly inside a cypher query.

- There is __distributed rendering__ support for geo-graphs and generic graph visualization is provided in a jupiter notebook equivalent workbench environment.

- __Queries__ can automatically be __visualized__ extensively with rich set of UI widgets that allow visualizations based on labels/hops/paths.

- It has **built-in ontology schema** generation from the CRUD graph statement, and allow the ontology visualization in dot format. Graph in billions can meaningfully be visualized and understood easily in this automatic schema view which is a unique feature. 
  

