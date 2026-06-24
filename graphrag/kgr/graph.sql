-- Property graph over kgr.nodes / kgr.edges.
-- add_table_monitor keeps it in sync with incremental inserts/updates (bitcoin pattern).
-- save_persist survives restarts. graph_table enables GRAPH_TABLE() aggregation.

CREATE OR REPLACE DIRECTED GRAPH "kgr"."kg" (
    NODES => INPUT_TABLES(
        -- LABEL_KEY (axis) groupings, unpivoted: one label_key per row + the array
        -- of labels on it. Lets Kinetica group each node's multi-label vector by
        -- axis into a concise ontology. Rebuilt from kgr.ontology by apply_graph().
        (SELECT "label_key" AS LABEL_KEY, "label" AS LABEL FROM "kgr"."label_keys"),
        (SELECT * FROM "kgr"."nodes")
    ),
    EDGES => INPUT_TABLES(
        -- Edge LABEL_KEY (axis) groupings, same (LABEL_KEY, LABEL) tuple form as the
        -- NODES grouping above: label_key = the verb's semantic CATEGORY (Offensive,
        -- Defensive, …), label = the canonical verbs in it. The EDGES analog of node
        -- axes. With schema_edge_labelkeys=true, /show/graph collapses each category
        -- into one abstract edge. Rebuilt from kgr.ontology by apply_graph().
        (SELECT "label_key" AS LABEL_KEY, "label" AS LABEL FROM "kgr"."edge_label_keys"),
        (SELECT * FROM "kgr"."edges")
    ),
    OPTIONS => KV_PAIRS(
        add_table_monitor = 'true',
        save_persist = 'true'
    )
);
