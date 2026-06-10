"""Canonical NODE-id construction.

Deterministic IDs for AST-derived entities (so re-ingesting the same file
collapses cleanly via PK upsert). Hashed IDs for LLM-only entities.
"""
from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")


def slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.strip()).strip("_") or "_"


def short_sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def sql_table_id(schema: str | None, table: str) -> str:
    schema = (schema or "").lower() or "public"
    return f"sql:table:{slug(schema)}.{slug(table.lower())}"


def sql_column_id(schema: str | None, table: str, column: str) -> str:
    schema = (schema or "").lower() or "public"
    return f"sql:column:{slug(schema)}.{slug(table.lower())}.{slug(column.lower())}"


def sql_query_id(normalized_sql: str) -> str:
    return f"sql:query:{short_sha1(normalized_sql)}"


def concept_id(canonical_text: str) -> str:
    return f"concept:{slug(canonical_text.lower())[:48]}-{short_sha1(canonical_text.lower())}"
