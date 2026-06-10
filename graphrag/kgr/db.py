"""Kinetica connection + thin SQL helpers."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import gpudb
from dotenv import load_dotenv


def _load_env() -> None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return
    load_dotenv(override=False)


@lru_cache(maxsize=1)
def connect() -> gpudb.GPUdb:
    _load_env()
    url = os.environ["KINETICA_DB_SKILL_URL"]
    user = os.environ.get("KINETICA_DB_SKILL_USER", "admin")
    password = os.environ.get("KINETICA_DB_SKILL_PASS", "")
    timeout_ms = int(os.environ.get("KINETICA_DB_SKILL_TIMEOUT", "30000"))
    opts = gpudb.GPUdb.Options()
    opts.username = user
    opts.password = password
    opts.timeout = timeout_ms
    return gpudb.GPUdb(host=url, options=opts)


def execute(sql: str, *, data: Sequence[Sequence[Any]] | None = None) -> dict:
    """Run a SQL statement. For multi-row parameterized writes, pass `data`."""
    db = connect()
    if data is not None:
        resp = db.execute_sql(sql, data=list(data), encoding="json")
    else:
        resp = db.execute_sql(sql, limit=-9999, encoding="json")
    _check(resp, sql)
    return resp


def fetch(sql: str) -> list[dict]:
    """Run a SELECT and return decoded row dicts."""
    resp = execute(sql)
    headers, columns = _extract_columnar(resp)
    if not headers:
        return []
    n = len(columns.get("column_1", []))
    return [
        {h: columns.get(f"column_{j + 1}", [None] * n)[i] for j, h in enumerate(headers)}
        for i in range(n)
    ]


def _check(resp: Any, sql: str) -> None:
    status = (resp or {}).get("status_info", {}) if isinstance(resp, dict) else {}
    if status.get("status") == "ERROR":
        raise RuntimeError(f"Kinetica error: {status.get('message')}\nSQL: {sql.strip()[:400]}")


def _extract_columnar(resp: dict) -> tuple[list[str], dict[str, list]]:
    jer = resp.get("json_encoded_response", "")
    if jer:
        parsed = json.loads(jer)
        headers = parsed.get("column_headers", [])
        columns = {
            k: v
            for k, v in parsed.items()
            if k.startswith("column_") and k not in ("column_headers", "column_datatypes")
        }
        return headers, columns
    headers = resp.get("column_headers", [])
    columns = {f"column_{i + 1}": resp.get(f"column_{i + 1}", []) for i in range(len(headers))}
    return headers, columns


def execute_script(sql_text: str) -> None:
    """Split a multi-statement SQL string on ';' and run each non-empty statement."""
    for stmt in _split_statements(sql_text):
        execute(stmt)


def _split_statements(sql_text: str) -> Iterable[str]:
    buf: list[str] = []
    in_str = False
    quote = ""
    in_line_comment = False
    i = 0
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql_text[i + 1] == "-":
            in_line_comment = True
            buf.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                yield stmt
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        yield tail
