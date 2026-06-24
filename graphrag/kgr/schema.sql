-- kgr schema: documents (provenance) + ontology + nodes + edges.
--
-- Nodes/edges hold only the columns Kinetica's graph engine needs (NODE / NODE1 /
-- NODE2 / LABEL) plus minimal provenance. All rich attribute columns are
-- *induced* from the LLM-derived ontology and added later via ALTER TABLE in
-- kgr.ontology (append-only). The CREATE GRAPH below stays simple:
-- `SELECT * FROM kgr.nodes` / `SELECT * FROM kgr.edges`.

CREATE SCHEMA IF NOT EXISTS "kgr";

CREATE TABLE IF NOT EXISTS "kgr"."documents" (
    "doc_uri"           VARCHAR(512, PRIMARY_KEY, SHARD_KEY) NOT NULL,
    "sha256"            VARCHAR(64) NOT NULL,
    "source_type"       VARCHAR(32) NOT NULL,
    "first_ingested_ts" TIMESTAMP NOT NULL,
    "last_ingested_ts"  TIMESTAMP NOT NULL,
    "status"            VARCHAR(16) NOT NULL
);

-- Ontology registry. type_kind is 'entity' or 'relation'. attr_name='' is the
-- row that declares the type itself; non-empty rows declare attribute columns
-- on kgr.nodes (entity attrs) or kgr.edges (relation attrs).
CREATE TABLE IF NOT EXISTS "kgr"."ontology" (
    "type_kind"      VARCHAR(16) NOT NULL,
    "type_name"      VARCHAR(128) NOT NULL,
    "attr_name"      VARCHAR(128) NOT NULL,
    "attr_sql_type"  VARCHAR(64)  NOT NULL,
    "first_seen_uri" VARCHAR(512) NOT NULL,
    "first_seen_ts"  TIMESTAMP NOT NULL,
    "ont_key"        VARCHAR(384, PRIMARY_KEY, SHARD_KEY) NOT NULL,
    -- Folded alias mapping. canonical_name == type_name means this row IS the
    -- canonical. canonical_name != type_name means this row is an alias.
    -- Added via ALTER TABLE in older installs; column lives at the end so the
    -- CREATE TABLE here matches that column ordering.
    "canonical_name" VARCHAR(128),
    -- The label AXIS (a.k.a. LABEL_KEY) this entity type belongs to: the facet
    -- dimension it classifies. Structural types (Person, Organization, …) sit on
    -- the default 'EntityType' axis; facet types (AI, LLM, …) on others (Industry,
    -- Technology, …). The normalized source of truth (one axis per label) that
    -- kgr.label_keys is materialized from. Only meaningful for entity rows.
    "axis" VARCHAR(64)
);

-- Label-key (axis) groupings, UNPIVOTED: one row per axis, holding the array of
-- entity labels that belong to it. The materialized, transposed form of
-- kgr.ontology.axis (one axis per label) for the graph engine — CREATE GRAPH
-- feeds it into the NODES component as
--   (SELECT label_key AS LABEL_KEY, label AS LABEL FROM kgr.label_keys)
-- so Kinetica groups each node's multi-label vector by axis (LABEL_KEY) into a
-- concise, compressible ontology. Rebuilt from kgr.ontology before each graph apply.
CREATE TABLE IF NOT EXISTS "kgr"."label_keys" (
    "label_key" VARCHAR(64, PRIMARY_KEY, SHARD_KEY) NOT NULL,
    "label"     VARCHAR[] NOT NULL
);

-- Edge label-key (axis) groupings, same shape/role as kgr.label_keys but for the
-- EDGES component: one row per edge label_key -> the array of edge (relation)
-- labels under it. Fed into CREATE GRAPH as a separate grouping SELECT
--   (SELECT label_key AS LABEL_KEY, label AS LABEL FROM kgr.edge_label_keys)
-- so Kinetica's /show/graph schema DOT can group/disambiguate edges by label_key.
-- The stored kgr.edges.LABEL stays bare (no compounding). Rebuilt before each apply.
CREATE TABLE IF NOT EXISTS "kgr"."edge_label_keys" (
    "label_key" VARCHAR(128, PRIMARY_KEY, SHARD_KEY) NOT NULL,
    "label"     VARCHAR[] NOT NULL
);

CREATE TABLE IF NOT EXISTS "kgr"."nodes" (
    "NODE"           VARCHAR(256, PRIMARY_KEY, SHARD_KEY) NOT NULL,
    "LABEL"          VARCHAR[] NOT NULL,
    -- The distinct *pre-fold* labels the LLM originally proposed for this node
    -- (e.g. ["Company"] for a node whose canonical LABEL is now ["Organization"]).
    -- Accumulated across mentions; null for rows written before folding captured it.
    "label_raw"      VARCHAR[],
    "name_original"  VARCHAR(256) NOT NULL,
    "qualified_name" VARCHAR(512) NOT NULL,
    "source_uri"     VARCHAR(512) NOT NULL,
    "first_seen_ts"  TIMESTAMP NOT NULL,
    "last_seen_ts"   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS "kgr"."edges" (
    "edge_key"   VARCHAR(64, PRIMARY_KEY, SHARD_KEY) NOT NULL,
    "NODE1"      VARCHAR(256) NOT NULL,
    "NODE2"      VARCHAR(256) NOT NULL,
    "LABEL"      VARCHAR[] NOT NULL,
    "source_uri" VARCHAR(512) NOT NULL,
    "confidence" FLOAT NOT NULL,
    "ts"         TIMESTAMP NOT NULL
);
