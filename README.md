
<img alt="Kinetica-Graph" src="./title_image.png" />

# Kinetica-Graph

---

Kinetica Graph is a distributed, hybrid graph database that integrates seamlessly with Kinetica’s relational engine and OLAP capabilities. It distinguishes itself through several key technical advantages:

- **Predictable Memory Footprint:** Unlike traditional graph databases, Kinetica Graph utilizes a fixed storage model. Memory requirements are consistently calculated at roughly $4 \\times \\text{number of edges}$ (approximately twice the size of a standard CSR format plus label indexes).
  
- **Dynamic, Real-Time Updates:** Using an "inplace double links" topology, the system supports constant-time insertions and deletions. This avoids the costly full-graph reconstructions required by CSR-based competitors like Neo4j or TigerGraph.
  
- **Seamless Relational Integration:** By functioning as a hybrid system, users can execute complex analytics within a single SQL statement. Graph outputs work as table functions, allowing for immediate joins and aggregations via OLAP expressions.
  
- **Distributed Architecture:** The graph can be partitioned across multiple servers and nodes. It minimizes data redundancy by only duplicating nodes at partition boundaries, with graph solvers designed to iterate efficiently across these distributed segments.1
  
- **Standardized Querying:** The platform is GQL-compliant and supports multi-hop, many-to-many Cypher queries with an optimized query planner that accesses both graph and relational data simultaneously.
  
- **Advanced Visualization:** Kinetica offers distributed rendering for geo-graphs and a notebook-based workbench.2 A unique feature is the automatic ontology schema generation, which allows users to visualize the structure of billion-scale datasets.

- **Scalable Analytics:** Many scalable graph solvers are available via simple handful restful endpoints, offers best in class geo-graph analytics with supply chain logistics, isochrone coverages and mixed integer programming (MIP) based optimizations as well as novel graph embeddings, Louvain clustering, Markov chain map matching, connected components, pattern matching, Eulerian loops for detecting fraud, spectral bisection clsutering, Jaccard similarities for recommendation systems and many more.
