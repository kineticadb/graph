"""sqlglot-based SQL extractor.

Emits:
  - Table nodes (label SqlTable) for every table referenced or defined.
  - Column nodes (label SqlColumn) for every column declared in a CREATE TABLE / CREATE VIEW.
  - Query nodes (label SqlQuery) for every top-level statement.
  - Edges:
      SqlTable -[DEFINES]-> SqlColumn   (from CREATE TABLE)
      SqlQuery -[READS]->   SqlTable    (anything in FROM/JOIN of a SELECT)
      SqlQuery -[WRITES]->  SqlTable    (INSERT/UPDATE/DELETE/CREATE TABLE/CREATE VIEW target)
      SqlView  -[DERIVES_FROM]-> SqlTable (CREATE VIEW ... AS SELECT ... FROM <table>)
"""
from __future__ import annotations

from typing import Iterable

import sqlglot
from sqlglot import exp

from ..canonical import (
    sql_column_id,
    sql_query_id,
    sql_table_id,
)


def extract(sql_text: str, *, dialect: str | None = None) -> tuple[list[dict], list[dict]]:
    """Return (entities, relations) as plain dicts ready for kgr.upsert."""
    nodes: list[dict] = []
    edges: list[dict] = []
    try:
        statements = sqlglot.parse(sql_text, read=dialect or None)
    except sqlglot.errors.ParseError:
        return [], []
    for stmt in statements:
        if stmt is None:
            continue
        _walk(stmt, nodes, edges)
    return nodes, edges


def _walk(stmt: exp.Expression, nodes: list[dict], edges: list[dict]) -> None:
    normalized = stmt.sql(comments=False).strip()
    if not normalized:
        return
    qid = sql_query_id(normalized)
    qlabel = _query_label(stmt)
    create_target = _write_target(stmt) if isinstance(stmt, exp.Create) else None
    create_kind = (stmt.args.get("kind") or "").upper() if isinstance(stmt, exp.Create) else ""
    qname = _query_name(stmt, qlabel)
    nodes.append({
        "id": qid,
        "label": qlabel,
        "name": qname,
        "qualified_name": normalized[:120].replace("\n", " "),
        "attrs": {"sql": normalized[:512]},
    })
    target_label = "SqlView" if create_kind == "VIEW" else "SqlTable"

    for table in _referenced_tables(stmt):
        is_create_target = create_target is not None and _same_table(create_target, table)
        label = target_label if is_create_target else "SqlTable"
        tid, tnode = _table_node(table, label=label)
        nodes.append(tnode)
        edges.append(_edge(qid, tid, "WRITES" if _is_write_target(stmt, table) else "READS"))

    if isinstance(stmt, exp.Create) and isinstance(stmt.this, exp.Schema):
        target = stmt.this.this
        if isinstance(target, exp.Table):
            tid, _ = _table_node(target, label=target_label)
            for col_def in stmt.this.expressions:
                if isinstance(col_def, exp.ColumnDef):
                    cname = col_def.name
                    ctype = col_def.args.get("kind").sql() if col_def.args.get("kind") else ""
                    schema_name = target.args.get("db").name if target.args.get("db") else None
                    cid = sql_column_id(schema_name, target.name, cname)
                    nodes.append({
                        "id": cid,
                        "label": "SqlColumn",
                        "name": cname,
                        "qualified_name": f"{target.name}.{cname}",
                        "attrs": {"datatype": ctype} if ctype else {},
                    })
                    edges.append(_edge(tid, cid, "DEFINES"))

    if create_kind == "VIEW" and create_target is not None:
        vid, _ = _table_node(create_target, label="SqlView")
        for src in _referenced_tables(stmt.args.get("expression")):
            if _same_table(src, create_target):
                continue
            sid, _ = _table_node(src)
            edges.append(_edge(vid, sid, "DERIVES_FROM"))


def _query_label(stmt: exp.Expression) -> str:
    if isinstance(stmt, exp.Select):
        return "SqlSelect"
    if isinstance(stmt, exp.Insert):
        return "SqlInsert"
    if isinstance(stmt, exp.Update):
        return "SqlUpdate"
    if isinstance(stmt, exp.Delete):
        return "SqlDelete"
    if isinstance(stmt, exp.Create):
        kind = (stmt.args.get("kind") or "OBJECT").upper()
        return f"SqlCreate{kind.capitalize()}"
    return f"Sql{type(stmt).__name__}"


def _query_name(stmt: exp.Expression, qlabel: str) -> str:
    """Human-readable name: action verb + target/source tables when we can tell."""
    target = _write_target(stmt)
    if isinstance(stmt, exp.Create) and target is not None:
        kind = (stmt.args.get("kind") or "").upper().lower()
        return f"CREATE {kind} {target.sql()}"
    if isinstance(stmt, exp.Insert) and target is not None:
        return f"INSERT INTO {target.sql()}"
    if isinstance(stmt, exp.Update) and target is not None:
        return f"UPDATE {target.sql()}"
    if isinstance(stmt, exp.Delete) and target is not None:
        return f"DELETE FROM {target.sql()}"
    if isinstance(stmt, exp.Select):
        froms = [t.sql() for t in _referenced_tables(stmt)]
        if froms:
            return f"SELECT FROM {', '.join(froms[:3])}"
    return qlabel


def _referenced_tables(node: exp.Expression | None) -> Iterable[exp.Table]:
    if node is None:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[exp.Table] = []
    for t in node.find_all(exp.Table):
        key = ((t.args.get("db").name if t.args.get("db") else ""), t.name)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _is_write_target(stmt: exp.Expression, table: exp.Table) -> bool:
    target = _write_target(stmt)
    return target is not None and _same_table(target, table)


def _write_target(stmt: exp.Expression) -> exp.Table | None:
    if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete, exp.Create)):
        node = stmt.this
        if isinstance(node, exp.Schema):
            node = node.this
        if isinstance(node, exp.Table):
            return node
    return None


def _same_table(a: exp.Expression | None, b: exp.Table) -> bool:
    if not isinstance(a, exp.Table):
        return False
    return (a.name == b.name) and (
        (a.args.get("db").name if a.args.get("db") else "")
        == (b.args.get("db").name if b.args.get("db") else "")
    )


def _table_node(t: exp.Table, *, label: str = "SqlTable") -> tuple[str, dict]:
    schema = t.args.get("db").name if t.args.get("db") else None
    name = t.name
    tid = sql_table_id(schema, name)
    qname = f"{schema}.{name}" if schema else name
    return tid, {"id": tid, "label": label, "name": name, "qualified_name": qname, "attrs": {}}


def _edge(src: str, dst: str, label: str, confidence: float = 1.0) -> dict:
    return {"src": src, "dst": dst, "label": label, "confidence": confidence, "attrs": {}}
