"""Idempotently apply kgr schema + ontology seed + property graph.

Kinetica's `CREATE TABLE IF NOT EXISTS` checks the declared schema against the
existing table's type-id and refuses with `Table already exists with type_id ...`
on ANY drift — even adding a nullable column. Since the ontology evolver
`ALTER TABLE`s extra columns onto kgr.nodes / kgr.edges, we can never re-run
schema.sql against an existing install.

So this module:
  - Always runs `CREATE SCHEMA IF NOT EXISTS` (safe).
  - For each known table, checks existence via `show_table` and runs that
    table's CREATE TABLE block from schema.sql ONLY when missing.
  - Backfills `canonical_name` on kgr.ontology if it was added via ALTER.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .db import connect, execute, execute_script

_HERE = Path(__file__).resolve().parent

_KNOWN_TABLES = ["documents", "ontology", "nodes", "edges"]


def apply_schema() -> None:
    execute('CREATE SCHEMA IF NOT EXISTS "kgr"')
    statements = _per_table_create_statements()
    existing = _existing_tables()
    for table, stmt in statements.items():
        if table in existing:
            continue
        execute(stmt)
    _migrate_ontology_canonical_name()
    _migrate_nodes_label_raw()


def apply_graph() -> None:
    execute(_HERE.joinpath("graph.sql").read_text())


def apply_seed() -> dict:
    from .ontology import apply_seed as _apply
    return _apply()


def apply_all() -> dict:
    """Apply schema + seed + (if any drift) backfill + graph.

    Returns a summary suitable for logging:
        {
          "seed_aliases":  <count of (alias, canonical) pairs applied by the seed>,
          "seed_canonicals": <count of new canonical types added by the seed>,
          "backfilled_nodes": <kgr.nodes rows whose LABEL was rewritten>,
          "backfilled_edges": <kgr.edges rows whose LABEL was rewritten>,
        }

    The backfill step is self-healing: if `ontology_seed.json` was tightened
    so an existing canonical is now an alias of a different canonical, any
    rows still carrying the now-alias label get rewritten before the graph
    is (re-)applied.
    """
    from .config import compound_edges_enabled
    from .ontology import backfill_labels, base_edge_labels, compound_edge_labels

    apply_schema()
    seed = apply_seed()
    backfill = backfill_labels()
    # Normalize edge LABELs to match the configured mode (depends on the canonical
    # LABELs from the alias backfill above). Idempotent in either direction.
    if compound_edges_enabled():
        recomposed = compound_edge_labels()
    else:
        recomposed = base_edge_labels()
    apply_graph()
    return {
        "seed_aliases": len(seed.get("applied_aliases", [])),
        "seed_canonicals": len(seed.get("added_canonicals", [])),
        "backfilled_nodes": backfill["nodes_updated"],
        "backfilled_edges": backfill["edges_updated"],
        "compound_edges": compound_edges_enabled(),
        "recomposed_edges": recomposed,
    }


_DROP_ORDER = [
    'DROP GRAPH "kgr"."kg"',            # graph first — it reads from nodes/edges
    'DROP TABLE IF EXISTS "kgr"."edges"',
    'DROP TABLE IF EXISTS "kgr"."nodes"',
    'DROP TABLE IF EXISTS "kgr"."documents"',
    'DROP TABLE IF EXISTS "kgr"."ontology"',
]


def drop_all() -> dict:
    """Drop the property graph and every kgr table. Best-effort per statement.

    `DROP GRAPH` has no IF EXISTS, so a missing graph surfaces as an error that
    we record rather than raise on — drop_all stays idempotent.
    """
    dropped: list[str] = []
    errors: list[dict] = []
    for stmt in _DROP_ORDER:
        try:
            execute(stmt)
            dropped.append(stmt)
        except Exception as e:  # noqa: BLE001 — best-effort teardown
            errors.append({"stmt": stmt, "error": str(e)[:200]})
    return {"dropped": dropped, "errors": errors}


def _existing_tables() -> set[str]:
    db = connect()
    r = db.show_table("kgr", options={"show_children": "true"})
    return set(r.get("table_names", []))


def _per_table_create_statements() -> dict[str, str]:
    """Parse schema.sql and return {table_name: CREATE TABLE statement}."""
    text = _HERE.joinpath("schema.sql").read_text()
    out: dict[str, str] = {}
    # Split by ; while respecting comments (db._split_statements already does this).
    from .db import _split_statements
    for stmt in _split_statements(text):
        m = re.search(r'CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?"kgr"\."(\w+)"', stmt, re.IGNORECASE)
        if m:
            out[m.group(2)] = stmt
    return out


def _migrate_ontology_canonical_name() -> None:
    db = connect()
    schemas = db.show_table("kgr.ontology", options={"get_column_info": "true"}).get("type_schemas", [])
    if not schemas:
        return
    cols = {f["name"] for f in json.loads(schemas[0]).get("fields", [])}
    if "canonical_name" in cols:
        return
    execute('ALTER TABLE "kgr"."ontology" ADD COLUMN "canonical_name" VARCHAR(128)')
    execute('UPDATE "kgr"."ontology" SET "canonical_name" = "type_name" WHERE "canonical_name" IS NULL')


def _migrate_nodes_label_raw() -> None:
    db = connect()
    schemas = db.show_table("kgr.nodes", options={"get_column_info": "true"}).get("type_schemas", [])
    if not schemas:
        return
    cols = {f["name"] for f in json.loads(schemas[0]).get("fields", [])}
    if "label_raw" not in cols:
        execute('ALTER TABLE "kgr"."nodes" ADD COLUMN "label_raw" VARCHAR[]')


if __name__ == "__main__":
    apply_all()
    print("kgr schema + ontology seed + graph applied")
