-- Property graph over kgr.nodes / kgr.edges.
-- add_table_monitor keeps it in sync with incremental inserts/updates (bitcoin pattern).
-- save_persist survives restarts. graph_table enables GRAPH_TABLE() aggregation.

CREATE OR REPLACE DIRECTED GRAPH "kgr"."kg" (
    NODES => INPUT_TABLES(
        (SELECT * FROM "kgr"."nodes")
    ),
    EDGES => INPUT_TABLES(
        (SELECT * FROM "kgr"."edges")
    ),
    OPTIONS => KV_PAIRS(
        add_table_monitor = 'true',
        save_persist = 'true'
    )
);
