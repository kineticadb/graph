# Kinetica Graph Cypher Queries: Various Use Cases

This documentation provides comprehensive examples and use cases for Kinetica's graph capabilities using Cypher queries. The examples cover various use cases including banking, logistics, social networks, and more.

---

## Table of Contents

1. [Banking](#banking)
2. [Logistics](#logistics)
3. [Social Networks](#social-networks)
4. [GraphRag BBC News](#graphrag-bbc-news)
5. [Wikipedia Example](#wikipedia-example)

---

## Banking

*Cypher queries on financial banking applications*

### Example 1

**Query:**

```sql
create or replace directed graph expero.banking_graph (
    nodes => INPUT_TABLES(
        (SELECT
            id as NODE,           
            label as LABEL
            ,"banking_transaction:amount" as banking_transaction_amount
            ,"wire_message:risk_score" as wire_message_risk_score
            , "party:risk_score" as party_risk_score
            , "party:party_name" as party_name
            , "bank:bank_name" as bank_name
            , "bank:risk_score" as bank_risk_score
        FROM expero.vertexes)
    ),
    edges => INPUT_TABLES((
        SELECT
            id as ID,
            source_name as NODE1,
            target_name as NODE2,
            label as LABEL
        FROM expero.edges
    )),
    OPTIONS => KV_PAIRS(
         is_partitioned = 'false'
     )     
);
```

---

### Example 2

**Comments:**

- Find all the transactions at a bank via wire message transfers and list the risk scores of each transaction

**Query:**

```sql
GRAPH expero.banking_graph
 MATCH  (a:bank WHERE (a.NODE ='d8d3cb99-0e3b-45b4-8221-79e8425065f3')) -[ab:performed]-> (b:wire_message) - [bc:is_for_transaction] -> (c:banking_transaction)
  RETURN a.bank_name as bank, b.NODE as wire, ab.LABEL as ablabel, c.NODE as transaction,  
         c.banking_transaction_amount, b.wire_message_risk_score
```

---

### Example 3

**Comments:**

- Among all the transactions at a Harvey Group via aggregated wire message transfers sort all based on the maximum total transactions with their risk factors

**Query:**

```sql
select wire, risk, ROUND(SUM(amount),0) AS total FROM 
graph_table 
(GRAPH expero.banking_graph
  MATCH  (a:bank WHERE (a.bank_name = 'Harvey Group'))-[ab:performed]->(b:wire_message)-[bc:is_for_transaction]->(c:banking_transaction)
  RETURN a.NODE as bank, a.LABEL as alabel, b.NODE as wire, b.LABEL as blabel, ab.LABEL as ablabel, c.NODE as transaction, c.LABEL as clabel, 
         bc.LABEL as bclabel, c.banking_transaction_amount as amount, b.wire_message_risk_score as risk
) group by 1,2 order by 3 desc
```

---

### Example 4

**Comments:**

- Find among all transactions via wires whose risk score is greater than 20, list the people who have internal accounts to the same bank and also list the individual's risk scores with the transaction amount

**Query:**

```sql
GRAPH expero.banking_graph
  MATCH  (a:bank WHERE (a.NODE ='d8d3cb99-0e3b-45b4-8221-79e8425065f3')) -[ab:performed]-> (b:wire_message WHERE b.wire_message_risk_score > 20) - [bc:is_for_transaction] -> (c:banking_transaction) - [d:involved] -> (e:internal_account)
<- [f:manages] - (g:party) 
 RETURN   g.party_name as person, g.party_risk_score as risk_score, c.banking_transaction_amount
```

---

### Example 5

**Comments:**

- Add to above the individual's devices from which the transaction is performed

**Query:**

```sql
GRAPH expero.banking_graph 
  MATCH  (a:bank WHERE (a.NODE ='d8d3cb99-0e3b-45b4-8221-79e8425065f3') ) -[ab:performed]-> (b:wire_message  WHERE b.wire_message_risk_score > 20) - [bc:is_for_transaction] -> (c:banking_transaction) - [d:involved] -> (e:internal_account)
 <- [f:manages] - (g:party) <- [h] -(i) -[] ->(j)
 RETURN  distinct g.party_name as person, g.party_risk_score as risk_score, c.banking_transaction_amount, j.NODE as device_id
```

---

### Example 6

**Comments:**

- Find internal account person person and his device where the transafers are done with the maximum suspicious activity based on the aggregated total transfers to a bank via wire transfers whose risks are greater than 20

**Query:**

```sql
select person, bank, min(device_id) as device_id, max(risk_score) as max_risk_score, ROUND(SUM(amount),2) AS total_transaction FROM 
graph_table (
    GRAPH expero.banking_graph 
  MATCH  (a:bank WHERE ((a.NODE ='d8d3cb99-0e3b-45b4-8221-79e8425065f3')) ) -[ab:performed]-> (b:wire_message  WHERE b.wire_message_risk_score > 20) - [bc:is_for_transaction] -> (c:banking_transaction) - [d:involved] -> (e:internal_account)
 <- [f:manages] - (g:party) <- [h] -(i) -[] ->(j)
 RETURN  distinct g.party_name as person, a.bank_name as bank, g.party_risk_score as risk_score, c.banking_transaction_amount as amount, j.NODE as device_id
) group by 1,2 order by 4 desc;
```

---

### Example 7

**Comments:**

- For banks whose risks are greater than 95 list all the people with internal accounts and their wire suspicous message  activity whose risk scores > 20 by aggregating these transactions and the total number of devises used per group

**Query:**

```sql
select person, bank, count(distinct device_id) as device_id, max(risk_score) as max_risk_score, ROUND(SUM(amount),2) AS total_transaction FROM 
graph_table (
    GRAPH expero.banking_graph 
  MATCH  (a:bank WHERE (a.bank_risk_score > 95) ) -[ab:performed]-> (b:wire_message  WHERE b.wire_message_risk_score > 20) - [bc:is_for_transaction] -> (c:banking_transaction) - [d:involved] -> (e:internal_account)
 <- [f:manages] - (g:party) <- [h] -(i) -[] ->(j)
 RETURN  distinct g.party_name as person, a.bank_name as bank, g.party_risk_score as risk_score, c.banking_transaction_amount as amount, j.NODE as device_id
) group by 1,2 order by 4 desc;
```

---

### Example 8

**Comments:**

- Find all the transactions at banks that has names closer to 'ernser' via wire message transfers and list the risk scores of each transaction

**Query:**

```sql
GRAPH expero.banking_graph
  MATCH  (a:bank WHERE (LOWER(a.bank_name) LIKE '%ernser%')) -[ab:performed]-> (b:wire_message) - [bc:is_for_transaction] -> (c:banking_transaction)
  RETURN a.bank_name as bank, b.NODE as wire, ab.LABEL as ablabel, c.NODE as transaction,  
         c.banking_transaction_amount, b.wire_message_risk_score
```

---

## Logistics

*Minimum cost transport solver via mixed-integer linear programming on network multi-modal graphs for multi-constraint supply chain logistics*

### Example 1

**MULTI STEP MSDO: **

Minimum cost transport solver via mixed-integer linear programming on network multi-modal graphs for multi-constraint supply chain logistics

What it is :

1. Involves many interconnected supply centers.

2. The multi-step solve works backward;

3. Starting from the final demand (sink) to find the first accommodating supply (source).

4. At each solve step previous supplies become the demand for the next optimization run.

5. The cycle continues until supply reaches the main source (hub).

6. Cycling supplies to demands, enables inventory replenishment planning.

Also demonstrates how each graph edge is labeled and the transports moving only on matching edge labels (multi-modality).

It also demonstrates the ability to satisfy demand-supply specifications. E.g.: certain transports may only carry particular types of goods.

Finally the multyi-hop multi-path cypher queries run to find the least costly route by looking at all possible combinatorial cypher paths

---

### Example 2

**Query:**

```sql
CREATE OR REPLACE TABLE rearm_graph_nodes (    
    node int not null,
    wktpoint GEOMETRY NOT NULL,   
    label varchar[] not null
);

CREATE OR REPLACE TABLE rearm_graph_edges (    
    node1 int not null,
    node2 int not null,
    weight float not null,
    label varchar[] not null
);
INSERT INTO rearm_graph_nodes(node,wktpoint,label) VALUES 
(1,  ST_geomFromText('POINT(1 1)'), string_to_array('MAINHUB',',')),
(2,  ST_geomFromText('POINT(2 1)'), string_to_array('USHUB',',')),
(3,  ST_geomFromText('POINT(3 1)'), string_to_array('USHUB',',')),
(4,  ST_geomFromText('POINT(2 2)'), string_to_array('SEAHUB',',')),
(5,  ST_geomFromText('POINT(1 2)'), string_to_array('LANDHUB',',')),
(6,  ST_geomFromText('POINT(2 3)'), string_to_array('LANDHUB',',')),
(7,  ST_geomFromText('POINT(1 3)'), string_to_array('SPOKE',','));

INSERT INTO rearm_graph_edges(node1,node2,weight,label) VALUES 
(1,2, 3, string_to_array('AIR',',')),
(1,3, 5, string_to_array('AIR',',')),
(2,4, 4, string_to_array('AIR',',')),
(3,4, 3, string_to_array('AIR',',')),
(4,5, 8, string_to_array('SEA',',')),
(4,6, 9, string_to_array('SEA',',')),
(5,7, 5, string_to_array('LAND',',')),
(6,7, 7, string_to_array('LAND',','));
```

---

### Example 3

**Comments:**

- KI_HINT_MERGE_GRAPH_INPUTS

**Query:**

```sql
(	    
    NODES => INPUT_TABLES(
        (select * from rearm_graph_nodes)        
    ),
    EDGES => INPUT_TABLES(rearm_graph_edges),
    OPTIONS => KV_PAIRS(graph_table = 'rearm')
);
```

---

### Example 4

---

### Example 5

**Comments:**

- This is to demostrate the multi step run of the MSDO
- There are 8 transports used to make the deliveries in multi-modal fashion all the way from the main hub (SUPPLY_MAIN depicted as node 1) to the main spoke (demand depicted as node 7)
- The supply_order is helping to cut down on number of combinations - order the supplies based on logical supply sequences - otherwise or in lieu of this knowledge,
- turn on the supply side permutations and increase the supply combinations at the options, it'll still find the correct 8 vehicles transport. All specs are identical hence
- there is no mismatch between transport and demand specifications.
- batch_tsm_mode = 'false',
- max_combinations = '10000',
- max_trip_cost = '2900.0',
- unit_unloading_cost = '0.0',
- service_limit = '0',
- service_radius = '0.0',
- max_stops = '0',
- enable_reuse = 'false',
- restricted_type = 'none',

**Query:**

```sql
DROP TABLE IF EXISTS rearm_msdo;
EXECUTE FUNCTION 
MATCH_GRAPH(
    GRAPH => 'rearm', 
    SAMPLE_POINTS => INPUT_TABLES
    (   
        (SELECT             
            1  AS  SUPPLY_NODE,
            101 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'AIR' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            8 AS SUPPLY_ORDER,
            1 AS SUPPLY_MAIN,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            1  AS  SUPPLY_NODE,
            102 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'AIR' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            7 AS SUPPLY_ORDER,
            1 AS SUPPLY_MAIN,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            2  AS  SUPPLY_NODE,
            20 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'AIR' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            6 AS SUPPLY_ORDER,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            3  AS  SUPPLY_NODE,
            30 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'AIR' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            5 AS SUPPLY_ORDER,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            4  AS  SUPPLY_NODE,
            401 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'SEA' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            4 AS SUPPLY_ORDER,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            4  AS  SUPPLY_NODE,
            402 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'SEA' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            3 AS SUPPLY_ORDER,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            5  AS  SUPPLY_NODE,
            50 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            1 AS SUPPLY_ORDER,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),       
        (SELECT             
            6  AS  SUPPLY_NODE,
            60 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            2 AS SUPPLY_ORDER,
             string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            7  AS DEMAND_NODE,
            70 AS DEMAND_ID,
            16 AS DEMAND_SIZE,                
            1  AS DEMAND_REGION_ID,
             string_to_array('pharmacy,food',',') AS DEMAND_SPECS
        )
    ),
    SOLVE_METHOD   => 'match_supply_demand',
    SOLUTION_TABLE => 'rearm_msdo',
    OPTIONS => KV_PAIRS
    ( 
    aggregated_output = 'true',
    output_tracks = 'false',    
    partial_loading = 'true',
     max_supply_combinations = '10000',
    permute_supplies = 'false',    
    round_trip = 'false',
    filter_unreachable_input = 'false',
    svg_width = '800', svg_height = '400',  
    svg_speed = '1', svg_basemap = 'false', svg_addlabels = 'false',
    multi_step = 'true'
    )
);
select IF(nv != 8,'failed', 'passed') from
(select count(*) as nv from rearm_msdo);
```

---

### Example 6

**Comments:**

- This is to demostrate the effect of supply specifications matching with the demand
- Below is run w/o the multi_step option
- There are only two of supply 5 and two vehicles of 6 exist to provide a total of 16 units to demand node of 7
- Demand of 7 requires fragile and food specs; supply 5's 20 unit vehicle 50 does not have the fragile spec, hence it is not used but the 500's 6 size is used since it satisfies the demnd specs list.
- along with the rest of the deliveries from the supply 6's vehicles 60 and 600.
- batch_tsm_mode = 'false',
- max_combinations = '10000',
- max_trip_cost = '2900.0',
- unit_unloading_cost = '0.0',
- service_limit = '0',
- service_radius = '0.0',
- max_stops = '0',
- enable_reuse = 'false',
- restricted_type = 'none',

**Query:**

```sql
DROP TABLE IF EXISTS rearm_msdo;
EXECUTE FUNCTION 
MATCH_GRAPH(
    GRAPH => 'rearm', 
    SAMPLE_POINTS => INPUT_TABLES
    (   

        (SELECT             
            5  AS  SUPPLY_NODE,
            50 AS  SUPPLY_ID,
            20 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            string_to_array('pharmacy,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            5  AS  SUPPLY_NODE,
            500 AS  SUPPLY_ID,
            6 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,            
            string_to_array('pharmacy,fragile,food',',') AS SUPPLY_SPECS
        ),      
        (SELECT             
            6  AS  SUPPLY_NODE,
            60 AS  SUPPLY_ID,
            6 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,            
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            6  AS  SUPPLY_NODE,
            600 AS  SUPPLY_ID,
            6 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,            
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            7  AS DEMAND_NODE,
            70 AS DEMAND_ID,
            16 AS DEMAND_SIZE,                
            1  AS DEMAND_REGION_ID,
            string_to_array('fragile,food',',') AS DEMAND_SPECS
        )
    ),
    SOLVE_METHOD   => 'match_supply_demand',
    SOLUTION_TABLE => 'rearm_msdo',
    OPTIONS => KV_PAIRS
    ( 
    aggregated_output = 'true',
    output_tracks = 'false',    
    partial_loading = 'true',
     max_supply_combinations = '10000',
    permute_supplies = 'false',    
    round_trip = 'false',
    filter_unreachable_input = 'false',
    svg_width = '800', svg_height = '400',  
    svg_speed = '1', svg_basemap = 'false', svg_addlabels = 'false',
    multi_step = 'false'
    )
);
select IF(nv != 3,'failed', 'passed') from
(select count(*) as nv from rearm_msdo);
```

---

### Example 7

**Comments:**

- This is to demostrate the effect of supply penalty
- If the supply node of 6 has the penalty then msdo prefers to make all the shipment by the supply 5 vehicles
- The penaly of 10 + the cost 7 from 6 to the demnd site 7 becomes 17; with the three vehicles from 5 to 7 is total 15 hence it prefers all three of 5
- If the supply side permutation is turned on (true on options) the MSDO can find this but if turned off, then the combinations are used from the order supplied via SUPPLY_ORDER
- If supply 6's penalty is turned off, then one vehicle each of supplies 5 and 6 wouild be used as the total cost would be 5+7 = 12 only.
- batch_tsm_mode = 'false',
- max_combinations = '10000',
- max_trip_cost = '2900.0',
- unit_unloading_cost = '0.0',
- service_limit = '0',
- service_radius = '0.0',
- max_stops = '0',
- enable_reuse = 'false',
- restricted_type = 'none',

**Query:**

```sql
DROP TABLE IF EXISTS rearm_msdo;
EXECUTE FUNCTION 
MATCH_GRAPH(
    GRAPH => 'rearm', 
    SAMPLE_POINTS => INPUT_TABLES
    (   

        (SELECT             
            5  AS  SUPPLY_NODE,
            50 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            1 AS SUPPLY_ORDER,
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            5  AS  SUPPLY_NODE,
            51 AS  SUPPLY_ID,
            4 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            2 AS SUPPLY_ORDER,
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            5  AS  SUPPLY_NODE,
            52 AS  SUPPLY_ID,
            4 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            3 AS SUPPLY_ORDER,
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            6  AS  SUPPLY_NODE,
            60 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'LAND' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            float(10) AS SUPPLY_PENALTY,
            4 AS SUPPLY_ORDER,
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            4  AS  SUPPLY_NODE,
            401 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'SEA' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,            
            5 AS SUPPLY_ORDER,
            1 AS SUPPLY_MAIN,
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            4  AS  SUPPLY_NODE,
            402 AS  SUPPLY_ID,
            10 AS SUPPLY_SIZE,
            'SEA' AS SUPPLY_EDGELABEL,
            1  AS  SUPPLY_REGION_ID,
            6 AS SUPPLY_ORDER,
            1 AS SUPPLY_MAIN,         
            string_to_array('fragile,food',',') AS SUPPLY_SPECS
        ),
        (SELECT             
            7  AS DEMAND_NODE,
            70 AS DEMAND_ID,
            16 AS DEMAND_SIZE,                
            1  AS DEMAND_REGION_ID,
            string_to_array('fragile,food',',') AS DEMAND_SPECS
        )
    ),
    SOLVE_METHOD   => 'match_supply_demand',
    SOLUTION_TABLE => 'rearm_msdo',
    OPTIONS => KV_PAIRS
    ( 
    aggregated_output = 'true',
    output_tracks = 'false',    
    partial_loading = 'true',
     max_supply_combinations = '50000',
    permute_supplies = 'true',    
    round_trip = 'false',
    filter_unreachable_input = 'false',
    svg_width = '800', svg_height = '400',  
    svg_speed = '1', svg_basemap = 'false', svg_addlabels = 'false',
    multi_step = 'true'
    )
);
select IF(nv != 5,'failed', 'passed') from
(select count(*) as nv from rearm_msdo);
```

---

### Example 8

**Comments:**

- This is to demostrate the MSDO supply/demand sites depicted with lon/lat coordinates
- Two demand sites 6 and 7 receives possible supplies from 1 and 3 -
- The total supply size is 20, ten each and total demand size is 12.
- Supply 3 transport that is the nearest to both demands supply all of its capacity to both 6 and 7 demands as 4 and 6 respectively.
- The remaining demand size 2 of site 8 is supplied by supply 1.
- batch_tsm_mode = 'false',
- partial_loading = 'true',
- max_combinations = '10000',
- max_supply_combinations = '100',
- max_trip_cost = '2900.0',
- unit_unloading_cost = '0.0',
- service_limit = '0',
- service_radius = '0.0',
- max_stops = '0',
- enable_reuse = 'false',
- restricted_type = 'none',
- permute_supplies = 'true',
- filter_unreachable_input = 'true',

**Query:**

```sql
DROP TABLE IF EXISTS rearm_msdo;
EXECUTE FUNCTION 
MATCH_GRAPH(
    GRAPH => 'rearm', 
    SAMPLE_POINTS => INPUT_TABLES
    (        

        (SELECT 
            6 AS DEMAND_ID,
            ST_geomFromText('POINT(2 3)') AS DEMAND_NODE,
            4 AS DEMAND_SIZE,                
            1 AS DEMAND_REGION_ID
        ),
        (SELECT 
            7 AS DEMAND_ID,
            ST_geomFromText('POINT(1 3)') AS DEMAND_NODE,
            8 AS DEMAND_SIZE,                
            1 AS DEMAND_REGION_ID
        ),
        (SELECT 
            3 AS  SUPPLY_ID,
            ST_geomFromText('POINT(3 1)') AS SUPPLY_NODE,            
            10 AS SUPPLY_SIZE,
            'k2' AS SUPPLY_EDGELABEL,
             1 AS     SUPPLY_REGION_ID
        ),
        (SELECT             
            1 AS  SUPPLY_ID,
            ST_geomFromText('POINT(1 1)') AS SUPPLY_NODE,            
            10 AS SUPPLY_SIZE,
            'k1' AS SUPPLY_EDGELABEL,
             1 AS     SUPPLY_REGION_ID
        )
    ),
    SOLVE_METHOD   => 'match_supply_demand',
    SOLUTION_TABLE => 'rearm_msdo',
    OPTIONS => KV_PAIRS
    ( 
    aggregated_output = 'true',
    output_tracks = 'false',    
    round_trip = 'false',
    svg_width = '800', svg_height = '400',  
    svg_speed = '1', svg_basemap = 'false', svg_addlabels = 'false'
    )
);
select IF(nv != 2,'failed', 'passed') from
(select count(*) as nv from rearm_msdo);
```

---

### Example 9

**Comments:**

- This is to show finding two possible path cypher query from point (3,1) location hub to the spoke node in 3 hops
- KI_HINT_MERGE_GRAPH_INPUTS

**Query:**

```sql
MATCH (n1 where wktpoint = ST_geomFromText('POINT(3 1)'))-[e1]->(n2)-[e2]->(n3)-[e3]->(n4:SPOKE)
RETURN  n1.node as n1_node,n2.node as n2_node,n3.node as n3_node,n4.node as n4_node
```

---

### Example 10

**Comments:**

- This is a variable path cypher query finding all possible paths from both USHUBs to the spoke node 7 via SEAHUB in the 1st hop and inifinitly many (30) hops till it reaches to a SPOKE node.

**Query:**

```sql
GRAPH rearm  
MATCH (n1:USHUB)-[e1]->(n2:SEAHUB)-[e2]->{1,30}(n3:SPOKE)
RETURN  n1.node as n1_node,n2.node as n2_node, n3.node as n3_node
```

---

### Example 11

**Comments:**

- This is using a 3 hop cypher query finding all possible paths from USHUBs to SPOKE nodes and
- for each path we aggregate the overall cost to find the minimum cost path by ordering the cost by the outer OLAP

**Query:**

```sql
SELECT n1_node, n2_node, n3_node, n4_node, w1+w2+w3 as cost FROM 
GRAPH_TABLE(
    GRAPH rearm  
    MATCH (n1:USHUB)-[e1]->(n2)-[e2]->(n3)-[e3]->(n4:SPOKE)
    RETURN  n1.node as n1_node,e1.weight as w1, n2.node as n2_node,
    e2.weight as w2,n3.node as n3_node,e3.weight as w3,n4.node as n4_node
)
order by cost asc limit 1
```

---

### Example 12

**Query:**

```sql
GRAPH rearm  
MATCH (n1:USHUB)-[e1]->(n2)-[e2]->(n3)-[e3]->(n4:SPOKE)
RETURN  n1.node as n1_node,e1.weight as w1, n2.node as n2_node, e2.weight as w2, n3.node as n3_node, e3.weight as w3, n4.node as n4_node;
```

---

## Social Networks

*cypher queries on social networks*

### Example 1

**Description:** Description for Block 1

**Query:**

```sql
CREATE OR REPLACE TABLE bluesky1_nodes (    
    node char(64) not null,    
    label varchar[] not null,
    user_text string not null,
    user_age  int not null
);

CREATE OR REPLACE TABLE bluesky1_edges (    
    node1 char(64) not null,
    node2 char(64) not null,
    label char(64) not null
);

INSERT INTO bluesky1_nodes(node,label,user_text,user_age) VALUES
        ('kaan', string_to_array('user',','), 'I am a good programmer', 58),
        ('tan' , string_to_array('user',','), 'I am a good manager', 28),
        ('eli' , string_to_array('user',','), 'I am a good VP', 45),
        ('shouvik', string_to_array('user',',') , 'I am a good cleaner' , 60),  
        ('post1' , string_to_array('post',',') , 'Kinetica is a hybrid DB' , 15 ),       
        ('post2' , string_to_array('post',',') , 'Kinetica is a distributed DB' , 24 ),
        ('post3' , string_to_array('post',',') , 'Kinetica is a temporal DB' , 32 ),
        ('post4' , string_to_array('post',',') , 'Kinetica is a fast DB' , 45 ),
        ('post5' , string_to_array('post',',') , 'Kinetica is a resilient DB' , 10 ),
        ('post6' , string_to_array('post',',') , 'Kinetica is a spatial DB' , 29 ); 


INSERT INTO bluesky1_edges(node1,node2,label) VALUES
          ('kaan', 'post1', 'posted'),
          ('kaan', 'post2' , 'liked'), 
          ('tan' , 'post1' , 'liked'),
          ('tan' , 'post2' , 'posted'),
          ('tan' , 'post5' , 'liked'),
          ('tan' , 'post6' , 'posted'),
          ('tan',  'post4' , 'liked'),
          ('eli',  'post1', 'liked'),
          ('eli' , 'post5' , 'posted'), 
          ('eli' , 'post3' , 'posted'),
          ('eli' , 'post4' , 'liked'),
          ('eli' , 'post2' , 'liked'),
          ('shouvik' , 'post1' , 'liked'), 
          ('shouvik' , 'post6' , 'liked'),
          ('shouvik' , 'post4' , 'posted');       

create or replace table bluesky1_edges_nodelabels as
        select * from (
         SELECT 'kaan' AS NODE1, 'post1' AS NODE2, 'posted' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'kaan' AS NODE1, 'post2' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'tan' AS NODE1, 'post1' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'tan' AS NODE1, 'post2' AS NODE2, 'posted' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'tan' AS NODE1, 'post5' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'tan' AS NODE1, 'post6' AS NODE2, 'posted' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'tan' AS NODE1, 'post4' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'eli' AS NODE1, 'post1' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'eli' AS NODE1, 'post5' AS NODE2, 'posted' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'eli' AS NODE1, 'post3' AS NODE2, 'posted' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'eli' AS NODE1, 'post4' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'eli' AS NODE1, 'post2' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'shouvik' AS NODE1, 'post1' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union
         SELECT 'shouvik' AS NODE1, 'post6' AS NODE2, 'liked' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL union         
         SELECT 'shouvik' AS NODE1, 'post4' AS NODE2, 'posted' AS LABEL, 'user' AS EDGE_NODE1_LABEL, 'post' AS EDGE_NODE2_LABEL         
        );
```

---

### Example 2

**Query:**

```sql
CREATE OR REPLACE GRAPH bluesky (
    NODES => INPUT_TABLES(
         (select * from bluesky1_nodes)

    ),
    EDGES => INPUT_TABLES(
        (select * from bluesky1_edges)    
    ),    
    OPTIONS => KV_PAIRS( label_delimiter = ':', graph_table = 'bluesky1_graph_table', schema_edge_labelkeys = 'false', schema_node_labelkeys = 'false')
);
```

---

### Example 3

---

### Example 4

**Comments:**

- Finding who likes Tan back whose posts that Tan likes ?

**Query:**

```sql
GRAPH bluesky 
MATCH  (a:user WHERE (a.NODE ='tan'))-[ab:liked]-(b:post)-[bc:posted]-(c:user)-[cd:liked]-(d:post)-[de:posted]-(e:user WHERE (e.NODE = 'tan'))
RETURN distinct c.NODE as poster, c.user_text as info;
```

---

### Example 5

**Comments:**

- Finding who likes Tan among his posts that has 'distributed' in it back whose posts that Tan likes ?

**Query:**

```sql
GRAPH bluesky 
  MATCH  (a:user WHERE (a.NODE ='tan'))-[ab:liked]-(b:post)-[bc:posted]-(c:user)-[cd:liked]-
  (d:post WHERE (CONTAINS('distributed', d.user_text) = 1))-[de:posted]-(e:user WHERE (e.NODE = 'tan'))
  RETURN distinct c.NODE as poster, c.user_text as poster_text, d.user_text as original;
```

---

### Example 6

**Comments:**

- Finding who likes a user back whose posts that the user likes ?

**Query:**

```sql
GRAPH bluesky 
  MATCH  (a:user) -[ab:liked]- (b:post) - [bc:posted] - (c:user) - [cd:liked] - (d:post ) - [de:posted] - (e:user)
  WHERE e.NODE = a.NODE
  RETURN distinct a.NODE as originator, c.NODE as poster, c.user_text as poster_text, d.user_text as original, a.user_age AS age, d.user_age as post_length;
```

---

### Example 7

**Comments:**

- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (multi_paths, true)

**Query:**

```sql
select originator as user, sum(post_length) as total FROM 
graph_table(
  MATCH  (a:user) -[ab:liked]- (b:post) - [bc:posted] - (c:user) - [cd:liked] - (d:post ) - [de:posted] - (e:user)
  WHERE e.NODE = a.NODE
  RETURN distinct a.NODE as originator, c.NODE as poster, c.user_text as poster_text, d.user_text as original, a.user_age AS age, d.user_age as post_length)
  group by 1 order by 2 desc;
```

---

### Example 8

**Comments:**

- How many average liking back based on the originator's age group
- -------------------------------------------------------------------
- per age group aggregate total individual likes over the originator
- per originator group by the age group
- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (multi_paths, true)

**Query:**

```sql
select age_group, float(sum(total))/count(og) as mean_age_back from 
(select 
     CASE
        WHEN age < 30 THEN 'lessthan_30'
        WHEN age BETWEEN 30 AND 40 THEN 'between_30_40'
        WHEN age BETWEEN 41 AND 50 THEN 'between_40_50'
        ELSE 'olderthan_50'
    END AS age_group,
    originator as og,
    count(*) as total


 FROM 
    graph_table(
        MATCH  (a:user) -[ab:liked]- (b:post) - [bc:posted] - (c:user) - [cd:liked] - (d:post ) - [de:posted] - (e:user)
        WHERE e.NODE = a.NODE
        RETURN distinct a.NODE as originator, c.NODE as poster, c.user_text as poster_text, d.user_text as original, 
                        a.user_age AS age, d.user_age as post_length
    )
 group by age_group,og)
 group by age_group;
```

---

### Example 9

**Comments:**

- How many people per person liking the person's posts back
- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (multi_paths, true)

**Query:**

```sql
select float(sum(total))/count(user) as mean_like_back from 
(select originator as user, count(*) as total FROM 
graph_table(
  MATCH  (a:user) -[ab:liked]- (b:post) - [bc:posted] - (c:user) - [cd:liked] - (d:post ) - [de:posted] - (e:user)
  WHERE e.NODE = a.NODE
  RETURN distinct a.NODE as originator, c.NODE as poster, c.user_text as poster_text, d.user_text as original, a.user_age AS age, d.user_age as post_length)
  group by 1);
```

---

## GraphRag BBC News

*GraphRag BBC News*

### Example 1

**Description:** Description for Block 1

**Comments:**

- Create the Node Table
- Insert the Entities

**Query:**

```sql
CREATE TABLE news_nodes (
    node CHAR(64),
    label VARCHAR[] -- Kinetica uses VARCHAR for arrays/collections
);

INSERT INTO news_nodes (node, label) VALUES ('US Supreme Court', ARRAY['Organization', 'Judicial']);
INSERT INTO news_nodes (node, label) VALUES ('Trump Administration', ARRAY['Organization', 'Executive']);
INSERT INTO news_nodes (node, label) VALUES ('National Guard', ARRAY['Organization', 'Military']);
INSERT INTO news_nodes (node, label) VALUES ('Chicago', ARRAY['Location']);
INSERT INTO news_nodes (node, label) VALUES ('Illinois', ARRAY['Location']);
INSERT INTO news_nodes (node, label) VALUES ('JB Pritzker', ARRAY['Person', 'Governor']);
```

---

### Example 2

**Comments:**

- Create the Edge Table
- Insert the Relationships

**Query:**

```sql
CREATE TABLE news_edges (
    node1 CHAR(64),
    node2 CHAR(64),
    label VARCHAR[]
);

INSERT INTO news_edges (node1, node2, label) VALUES ('US Supreme Court', 'Trump Administration', ARRAY['REJECTED_BID']);
INSERT INTO news_edges (node1, node2, label) VALUES ('Trump Administration', 'National Guard', ARRAY['ATTEMPTED_DEPLOY']);
INSERT INTO news_edges (node1, node2, label) VALUES ('National Guard', 'Chicago', ARRAY['TARGET_LOCATION']);
INSERT INTO news_edges (node1, node2, label) VALUES ('JB Pritzker', 'Illinois', ARRAY['GOVERNS']);
INSERT INTO news_edges (node1, node2, label) VALUES ('JB Pritzker', 'Trump Administration', ARRAY['OBJECTED_TO']);
```

---

### Example 3

**Comments:**

- Nodes: Sourcing data from the news_nodes table
- Edges: Sourcing data from the news_edges table
- Configuration options for schema and storage

**Query:**

```sql
CREATE OR REPLACE DIRECTED GRAPH news_graph (
    nodes => input_tables(
        (SELECT node, label FROM news_nodes)
    ),

    edges => input_tables(
        (SELECT node1, node2, label FROM news_edges)
    ),

    options => kv_pairs(
        'graph_table' = 'news_graph_table',
        'schema_node_labelkeys' = 'true',
        'schema_edge_labelkeys' = 'true'
    )
);
```

---

### Example 4

---

### Example 5

---

### Example 6

**Comments:**

- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, true)

**Query:**

```sql
MATCH
    (n1:Executive) - [e1] ->(n2)- [e2] ->(n3:Location)
    return n1.node as executor, n3.node as place;
```

---

### Example 7

**Comments:**

- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, true) KI_HINT_MERGE_GRAPH_INPUTS

**Query:**

```sql
MATCH  
    (n1:Executive) - [e1] -(n2)- [e2] -(n3:Location)
    return n1.node as executor, e1.label as action, n2.node as person, n3.node as place;
```

---

### Example 8

**Comments:**

- Find the chain of events: Court -> Administration -> National Guard

**Query:**

```sql
GRAPH news_graph 
MATCH (court:Organization)-[r1]->(admin:Organization)-[r2]->(guard:Organization)
WHERE court.node = 'US Supreme Court'
RETURN 
    court.node AS rejecting_authority, 
    admin.node AS administration, 
    guard.node AS target_entity;
```

---

### Example 9

**Comments:**

- Finding opposition

**Query:**

```sql
GRAPH news_graph
MATCH (person:Person)-[obj:Action]->(admin:Organization)<-[rej:Action]-(court:Organization)
WHERE person.node = 'JB Pritzker'
RETURN 
    person.node AS objector_name, 
    admin.node AS target_of_objection, 
    court.node AS final_deciding_body;
```

---

### Example 10

**Comments:**

- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, false) KI_HINT_MERGE_GRAPH_INPUTS

**Query:**

```sql
MATCH  
    (n1:Executive) <- [e1] -(n2)
    return n1.node as executor, e1.label as action, n2.node as person
```

---

### Example 11

---

### Example 12

Prompts:

1. Create a kinetica graph sql create graph statement from the text above. 

2. Modify nodes as a node table whose schema is char(64) for node and varchar[] for label columns and insert the nodes with their labels such as insert into nodes (node,label) values( 'US Supreme Court' ,'Organization' ) etc.

3. Modify the news_nodes table schema varchar(max) to varchar[] for unlimited array type. Keep everything else the same for the news_nodes. For news_edges use the column name grammar specific to Kinetica as node1 and node2 for source and target respectively instead and label instead of relattionship. Also make the varchar[] schema for label column instead of varchar(64) , remove edge_id column. Recreate the SQL statements accordingly.

4. Now that the nodes and edges tables are correct, let us correct the crud for the graph creation sql statement. since we have used the column names according to the kinetica's ad-hoc grammar we could directly use the below statement: 

CREATE OR REPLACE DIRECTED GRAPH news_graph (

-- Nodes: Merging Instance data and Ontology Categories

nodes => input_tables((SELECT * FROM news_nodes)),

-- Edges: Merging Relationship data and Ontology Categories

edges => input_tables((SELECT * FROM news_edges)),

options => kv_pairs('graph_table' = 'graphdb_table',schema_node_labelkeys = 'true',schema_edge_labelkeys = 'true'));

5. Perfect! but in cypher queries duolicated aliases are not allowed, for instance, use court.node as court_name etc.

6. Voila!

---

### Example 13

**Query:**

```sql
SELECT * FROM TABLE(
    SOLVE_GRAPH(
        GRAPH => 'news_graph',
        SOLVER_TYPE => 'ALLPATHS',
        SOURCE_NODES => INPUT_TABLE((SELECT 'JB Pritzker' AS node)),
        DESTINATION_NODES => INPUT_TABLE((SELECT 'National Guard' AS node)),
        OPTIONS => Kv_pairs(uniform_weights = '1')
    )
);
```

---

## Wikipedia Example

*Wikipedia mini graph with people and interests *

### Example 1

**Comments:**

- ------------------------------------------------- 1. Create the nodes and edges table schemas ----------------------------------------------------------------
- Use column names that match with the graph grammar - e.g.: 'node', 'label' etc so that one would not need to annotate the column with a 'AS' directive in graph endpoints
- The endpoint /show/graph/grammar returns the JSON string object that lists the graph grammar (identifiers and identifier combinations) per component (nodes,edges are components)
- Graph also knows the aliases to the component identifiers. E.g.: 'NODE_ID' is a component identifier for a integer type column for the nodes component. 'NODE_NAME' is for a string based column for the nodes.
- However, fortunately, there exist generic aliases so one would not need to expilicitly specify the naming with the type. e.g.: A generic alias 'NODE' suffices for any column type annotation for a node component.
- A valid identifier combination for the nodes component for instance is NODE and LABEL two tuple columns. This combination and many more are listed in the JSON grammar. Note that, 'LABEL' is a short hand alias to 'NODE_LABEL' identifier.
- Any other non-graph related columns are allowed since the plannar might use them in OLAP joins necessary for cypher queries implicitly.
- ---------------------------------------------------------------------------------------------------------------------------------------------------------------
- Non-graph columns
- Use column names that match with the graph grammar - e.g.: 'node1', 'node2', 'label' etc so that one would not need to annotate the column with a 'AS' directive in graph endpoints.
- Generic edge identifer aliases can be used as short hand to explicit longer naming convention. e.g.: 'NODE1' is a generic alias to 'EDGE_NODE1_NAME' which makes the annotation concise.
- Note that 'LABEL' naming can be used instead of 'EDGE_LABEL' as long as the column is referred for describing the edges component in subsequent graph endpoints.
- Likewise, the same 'LABEL' naming in node tables can be used to describe the node labels as long as it is described for the nodes component section in the endpoint. (See create/graph below)
- ----------------------------------------------------------------------------------------------------------------------------------------------------------------
- Non-graph columns

**Query:**

```sql
CREATE OR REPLACE TABLE wiki_graph_nodes (    
    node  CHAR(64) NOT NULL,
    label VARCHAR[] NOT NULL,
    age INT
);

CREATE OR REPLACE TABLE wiki_graph_edges (    
    node1  CHAR(64) NOT NULL,
    node2  CHAR(64) NOT NULL,
    label VARCHAR[] NOT NULL,
    met_time DATE   
);
```

---

### Example 2

**Comments:**

- ------------------------------------------------- 2. Insert data into nodes and edges tables ----------------------------------------------------------------

**Query:**

```sql
INSERT INTO wiki_graph_nodes(node,label,age) VALUES 
('Jane', string_to_array('FEMALE,business',','),29),
('Bill', string_to_array('MALE,golf',','),58),
('Susan',string_to_array('FEMALE,dance',','),24),
('Alex', string_to_array('MALE,chess',','),23),
('Tom',  string_to_array('MALE,chess',','),42);
```

---

### Example 3

**Query:**

```sql
INSERT INTO wiki_graph_edges(node1,node2,label,met_time) VALUES 
 ('Jane','Bill',string_to_array('Friend',','),'1997-09-15'),
 ('Bill','Alex',string_to_array('Family',','),'1991-02-26'),
 ('Bill','Susan',string_to_array('Friend',','),'2001-01-30'),
 ('Susan','Alex',string_to_array('Friend',','),'2010-04-19'),
 ('Alex','Tom',string_to_array('Friend',','),'2024-10-07');
```

---

### Example 4

**Comments:**

- ------------------------------------------------- 3. Create Graph ----------------------------------------------------------------
- The SQL syntax has the input_tables macro for describing the nodes and edges components.
- Since we have used the names of the columns in the table schemas that match with the identifier combinations expressed in the grammar JSON,
- we are able to use simply (select * from wiki_graph_nodes) - Another short hand ccould simply be (wiki_graph_nodes)
- If the naming convention had not been used in the table column naming, then one would be required to explicitly annotate columns based on the graph grammar using the 'AS' keyword.
- E.g.: Say, the wiki_graph_nodes has the column name 'person' instead of name 'node' for the values 'Jane', 'Bill' etc., and label is 'hobby' then the nodes component syntax would have been
- nodes => input_tables((select Person AS node, hobby as label, age from wiki_graph_graph_nodes))
- Moreover, if we'd like to group labels under label grouping so that graph schema (ontology) generated would be very concise, then we could create node and edge label key and label combinations.
- This can easily be done using another select statement inside the input_tables macro as shown below. E.g.: 'Gender' is a super set for 'MALE' and 'FEMALE' labels that we attach to the nodes.
- Using the 'schema_node|edge_labelkeys' options, we can opt to collapse the ontology graph (connection of how labelled entities are related) based on their label keys. By default, we use label_keys, i.e., the options are set to true.
- The result of the generated graph ontology can be viewed by the button 'View Schema' appearing below. Clicking on that button will enable visualization of the graph ontology. In later SQL blocks, we'll show the ontology that is not using the label_keys.
- Another useful option is the 'graph_table' option where we can specify a relational table name that would be created by the graph to reflect the image of the graph in memory as tables. IF specified, the graph_table name is created to show the content of edges,
- and the graph_table+'_nodes' table reflectthe conetnt of graph nodes. These tables are only needed for debugging purposes and/or graph visualization since we have a generic graph visualization UI tool that reads from these tables for visual inspection of the graphs.
- Note that for non-simple larger graphs (whose size > 1K), it wont be useful to generate these tables, and could also be costly. So, avoid this option if the graph size wouyld be > 1k.
- Since we have used the 'graph_table' option, it makes snse to add another SQL block with the Type 'Add Graph Map' (upper right '+' sign). In that block, click Config and choose 'Nodes & Edges'. Furthermore, populate the node table and node name and label column names accordingly.
- Once the node and edge UI widgets are populated with the column names in the graph_tables, respectively, the firce directed edge layout generation algorithm of the Orb library enables the visualization of the graph.
- The 'Styling' section in the Config helps to choose the coloring and fonts of the entities and labels.
- Note that the 'Reset' button the config returns the styling back to the choices listed under 'Manage' -> 'WorkBench' buttin of this page up top.
- ----------------------------------------------------------------------------------------------------------------------------------------------------------------
- optional label groupings with label_keys for consice ontology generation
- optional label groupings with label_keys for consice ontology generation

**Query:**

```sql
Create or Replace directed Graph
wiki_graph (
    nodes => input_tables(
        (select 'Gender' AS LABEL_KEY, string_to_array('MALE,FEMALE',',') AS LABEL),
        (select 'Interest' AS LABEL_KEY, string_to_array('golf,business,dance,chess',',') AS LABEL),

        (select * from wiki_graph_nodes)
    ),
    edges => input_tables(
        (select 'Relations' AS LABEL_KEY, string_to_array('Family,Friend',',') AS LABEL),

        (select * from wiki_graph_edges)
    ),
    options => kv_pairs(graph_table = 'wiki_graph_table')
);
```

---

### Example 5

---

### Example 6

**Comments:**

- Find all females that are within 4-hops to a person whose interests include 'chess' and ages less than 40
- This is a variable path query syntax using ()-[]->{first_hop, last_hop}()

**Query:**

```sql
GRAPH wiki_graph 
MATCH (a:FEMALE)-[b]-> {1,4}(c:chess WHERE c.age < 40)
RETURN distinct a.NODE as source, c.NODE as target
```

---

### Example 7

**Comments:**

- fuzzy text search finding all females whose names start with 'su' case insensitive and their 1st hop ring neighbors;
- Since this is a directed graph, if we'd like to include all cases ie inward and outward edges we can force undirected with the global option 'force_undirected' below.
- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, true)

**Query:**

```sql
MATCH (a:FEMALE WHERE(LOWER(a.node) LIKE '%su%'))-[b]-> (c)
RETURN a.NODE as source, c.NODE as target
```

---

### Example 8

**Query:**

```sql
select * from wiki_graph_nodes a WHERE(LOWER(a.node) LIKE '%susan%')
```

---

### Example 9

**Comments:**

- Find friends of friends of Tom who met with each other after 1990 (force undirected search)
- KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, true)  KI_HINT_MERGE_GRAPH_INPUTS

**Query:**

```sql
MATCH (a:MALE  WHERE(node = 'Tom') )<-[b:Friend]-(c)<-[d where (d.met_time > '1990-01-01')]-(e)
RETURN a.node as source, e.node as target
```

---

### Example 10

**Comments:**

- ------------------------------------------------------------------------------- 4. Run many to many multi hop cypher queries with automatic visualization ---------------------------------------------------------------------------------------------------------------------
- Find everyone to the friends of Tom in two hops
- Cypher query match syntax for one hop is designated to be (n1)-[e]->(n2) where n1 is the first node and e is the edge and the n2 is the second node. These are variables and they can be selected to be of a certain label by specifying the lable name after the ':' of a variable.
- Any other filtering on the value of the node or edge variable or non-graph column can be made using the WHERE expression. E.g.: (c:chess WHERE c.age < 50) depicts a node variable of label 'chess' and the 'age' condition less than 50.
- In a cypher query for a directed graph, the direction of the arrows matter. In above graph, Tom is a node that does not have a outward edge; one should then flip the direction of the arrow coming towards Tom as: ()<-[]-().
- If there is no arrows, the search is undirected, but for directed graphs using ()-[]-() syntax with no arrows requires to specify the global option force_undirected to be true.
- This is accomplished by adding a comment anywhere in the call below: /* KI_HINT_QUERY_GRAPH_ENDPOINT_OPTIONS (force_undirected, true) */
- So, finding everyone within two hops to teh firends of 'Tom' can be speficified as follows:
- The return syntax requires to use distinct alias names for multiple column outputs, i.e., a.node and c.node should be differentitated; so use a.node as originator or a.node as a_node as a convention.
- The return is shown the Data tab below and the query table output is captured and visually shown in teh Visualization tab, if it does not come up automatically, hit 'Graph' selection in the choices under Visualization tab after running the query
- The visualization can be modified using the 'Config' button inside the Visualization tab. Just like the graph visualization, the Styling can be changed for the coloring and the font choices of the entities.
- It is recommended that the nodes are colored with their labels, and the edges are colored using the 'Path' option.
- It results in each query path edges found in the cypher query from source to target in a different color. The node and edge labels also appear with the same color. Each label combination is assigned a different color which can be seen in the tabular legends on the upper right corener of the canvas.
- ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Query:**

```sql
GRAPH wiki_graph 
MATCH (a:MALE  WHERE(node = 'Tom') )<-[b:Friend]-(c) <- [d] - (e) 
RETURN a.node as originator, c.node as friend, e.node as target
```

---

### Example 11

**Comments:**

- Find friends of friends of to Jane who met with each other after 2000

**Query:**

```sql
GRAPH wiki_graph 
MATCH (a:MALE  WHERE(node = 'Jane') )-[b:Friend]->(c)-[d:Friend where d.met_time > '2000-01-01' ]->(e)
RETURN c.node as source, e.node as target
```

---

### Example 12

**Comments:**

- Find everyone who are friends to Tom within their second and 4th hops

**Query:**

```sql
GRAPH wiki_graph 
MATCH (a:MALE  WHERE(node = 'Tom') )<-[b:Friend]-{2,4}(e)
RETURN a.node as source, e.node as target
```

---

### Example 13

**Comments:**

- Find all females that are within 4-hops to a person whose interests include 'chess' and age is < 50

**Query:**

```sql
GRAPH wiki_graph 
MATCH (a:FEMALE)-[b]-> {1,4}(c:chess WHERE c.age < 50)
RETURN distinct a.NODE as source, c.NODE as target
```

---

### Example 14

**Comments:**

- If we'd like to see the graph schema ontology without collapsing entities based on their labelkey groupings, we can set the respective options to false as shown below using the ALTER/GRAPH endpoint.
- Hit 'View Schema ' button for a more extended look at the ontology.
- Note that previous the most concised graph schema usi8ng the label_keys is not spread onto all the connections based on the labels. The percentages show how many nodes and edges exists between the respective labels.
- E.g.: 'MALE:CHESS' node in the schema ontology shows 40% which means 40 percent of the all graph nodes has bith MALE and CHESS labels.
- For a large graph knowing how many edges exists between two labelsets of nodes gives a greeat insight to the content of the graph, and enable the understing of how many hops is required to reach from one label to another.
- WARNING: Modify graph can have the same components as in the create graph call, i.e., one can dump the graph to another graph table using another graph_table option value or one can add/delete/modify the graph via a set of
- nodes, edges, weights, restrictions components. Next example will demonstrate that.
- --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

**Query:**

```sql
ALTER GRAPH wiki_graph MODIFY (
    options => kv_pairs(schema_node_labelkeys = 'false', schema_edge_labelkeys = 'false')
);
```

---

### Example 15

**Comments:**

- Let's add a new edge and delete an existing one with the alter/graph modify statement below.
- The graph wiki_graph dynamically modified and the result is written to a new graph table so that we can visualize the graph by selecting the new graph table wiki_graph_modified and wiki_graph_modified inside the UI widgets of Graph Configuration.
- Notice how the graph schema antology changes (hit 'View Schema' button)

**Query:**

```sql
ALTER GRAPH wiki_graph MODIFY (
    edges => input_tables(
        (select 'Tom' AS node1, 'Jane' as node2, 'Family' as label)
    ),
    restrictions => input_tables(
        (select 'Bill' AS node1, 'Alex' as node2)
    ),
    options => kv_pairs(graph_table = 'wiki_graph_modified', schema_node_labelkeys = 'false', schema_edge_labelkeys = 'false')
);
```

---

### Example 16

---

### Example 17

**Comments:**

- Let us reset our graph to the original one again
- optional label groupings with label_keys for consice ontology generation
- optional label groupings with label_keys for consice ontology generation

**Query:**

```sql
Create or Replace directed Graph
wiki_graph (
    nodes => input_tables(
        (select 'Gender' AS LABEL_KEY, string_to_array('MALE,FEMALE',',') AS LABEL),
        (select 'Interest' AS LABEL_KEY, string_to_array('golf,business,dance,chess',',') AS LABEL),

        (select * from wiki_graph_nodes)
    ),
    edges => input_tables(
        (select 'Relations' AS LABEL_KEY, string_to_array('Family,Friend',',') AS LABEL),

        (select * from wiki_graph_edges)
    ),
    options => kv_pairs(graph_table = 'wiki_graph_table')
);
```

---
