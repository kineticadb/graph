"""Generic upsert helpers for kgr.nodes / kgr.edges / kgr.documents.

Rows are dicts of {column: value}. Only columns that exist on the table are
sent (extras are dropped, with a debug log). The ontology evolver is in charge
of ensuring the columns exist before this is called.

All writes go through `db.insert_records_json` with `update_on_existing_pk` so
re-ingesting the same document collapses cleanly via the table's PK.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import compound_edges_enabled
from .db import connect, fetch

logger = logging.getLogger("kgr.upsert")


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def edge_key(src: str, dst: str, label: str, source_uri: str) -> str:
    return hashlib.sha1(
        "|".join((src, dst, label, source_uri)).encode("utf-8")
    ).hexdigest()


def upsert_nodes(entities: Iterable[dict[str, Any]], source_uri: str) -> int:
    """`entities` items: {id, label (structural str), labels (multi-label vector),
    label_raw (pre-fold label), name, qualified_name, attrs: dict}.

    LABEL is the full multi-label vector `e['labels']` (structural type + facets on
    other axes), falling back to `[label]` for sources that don't emit facets (SQL path).
    """
    now = now_ms()
    cols = _table_columns("kgr.nodes")
    entities = [e for e in entities if e.get("id")]
    # Accumulate the distinct pre-fold labels per node: union the incoming
    # original label with whatever the node already carries (so a later generic
    # mention can't erase an earlier specific one like "Company").
    track_raw = "label_raw" in cols
    existing_raw = _existing_label_raw({e["id"] for e in entities}) if track_raw else {}
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for e in entities:
        nid = e["id"]
        if nid in seen:
            continue
        seen.add(nid)
        attrs = e.get("attrs") or {}
        labels = [str(l) for l in (e.get("labels") or []) if str(l).strip()]
        if not labels:
            labels = [e.get("label") or "Entity"]
        base = {
            "NODE": nid,
            "LABEL": labels,
            "name_original": (e.get("name") or "")[:256],
            "qualified_name": (e.get("qualified_name") or e.get("name") or "")[:512],
            "source_uri": source_uri,
            "first_seen_ts": now,
            "last_seen_ts": now,
        }
        if track_raw:
            raw = (e.get("label_raw") or e.get("label") or "Entity").strip()
            base["label_raw"] = sorted(existing_raw.get(nid, set()) | {raw})
        base.update({k: _coerce(v) for k, v in attrs.items() if k in cols})
        rows.append({k: v for k, v in base.items() if k in cols})
    return _bulk_insert("kgr.nodes", rows, update=True)


def _existing_label_raw(node_ids: set[str]) -> dict[str, set[str]]:
    """Fetch each node's current label_raw array (decoded) for a union on upsert."""
    if not node_ids:
        return {}
    ids = ", ".join(f"'{_q(n)}'" for n in node_ids)
    out: dict[str, set[str]] = {}
    for r in fetch(f'SELECT NODE, label_raw FROM "kgr"."nodes" WHERE NODE IN ({ids})'):
        raw = r.get("label_raw")
        if not raw:
            continue
        try:
            arr = json.loads(raw) if isinstance(raw, str) else list(raw)
        except (json.JSONDecodeError, TypeError):
            arr = []
        if arr:
            out[r["NODE"]] = set(arr)
    return out


def upsert_edges(
    relations: Iterable[dict[str, Any]],
    source_uri: str,
    *,
    entity_labels: dict[str, str] | None = None,
) -> int:
    """`relations` items: {src, dst, label (str), confidence, attrs: dict}.

    LABEL is stored in **compound form** `<srcLabel>_<baseLabel>_<dstLabel>` (e.g.
    `Person_WORKS_AT_Organization`) so that Kinetica's graph-schema generator
    can derive the meta-graph from metadata alone — `(NodeLabelA, EdgeLabel,
    NodeLabelB)` becomes unique per row, no traversal needed.

    `entity_labels` maps {node_id: base_label} for entities in the same batch.
    Missing endpoints are looked up from kgr.nodes in a single batched query.
    """
    relations = list(relations)
    if not relations:
        return 0
    now = now_ms()
    cols = _table_columns("kgr.edges")
    compound_on = compound_edges_enabled()
    label_map = dict(entity_labels or {})
    if compound_on:
        # Endpoint labels are only needed to compose the compound LABEL.
        label_map.update(_lookup_node_labels({r.get("src") for r in relations} | {r.get("dst") for r in relations}, label_map))

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for r in relations:
        src = r.get("src") or ""
        dst = r.get("dst") or ""
        base_label = r.get("label") or "RELATED_TO"
        if not src or not dst:
            continue
        if compound_on:
            src_lbl = label_map.get(src) or "Unknown"
            dst_lbl = label_map.get(dst) or "Unknown"
            label = _compose_edge_label(src_lbl, base_label, dst_lbl)
        else:
            label = base_label
        key = edge_key(src, dst, label, source_uri)
        if key in seen:
            continue
        seen.add(key)
        attrs = r.get("attrs") or {}
        base = {
            "edge_key": key,
            "NODE1": src,
            "NODE2": dst,
            "LABEL": [label],
            "source_uri": source_uri,
            "confidence": float(r.get("confidence", 1.0)),
            "ts": now,
        }
        base.update({k: _coerce(v) for k, v in attrs.items() if k in cols})
        rows.append({k: v for k, v in base.items() if k in cols})
    return _bulk_insert("kgr.edges", rows, update=True)


def _compose_edge_label(src_label: str, base_label: str, dst_label: str) -> str:
    return f"{src_label}_{base_label}_{dst_label}"


def _lookup_node_labels(node_ids: set[str | None], already_known: dict[str, str]) -> dict[str, str]:
    """Fetch the STRUCTURAL LABEL (EntityType-axis element) for any node_id not
    already in `already_known`. Resolved by axis membership, not array position."""
    from .ontology import axis_map, pick_structural

    missing = [nid for nid in node_ids if nid and nid not in already_known]
    if not missing:
        return {}
    amap = axis_map()
    in_list = ", ".join("'" + nid.replace("'", "''") + "'" for nid in missing)
    out: dict[str, str] = {}
    for r in fetch(f'SELECT NODE, LABEL FROM "kgr"."nodes" WHERE NODE IN ({in_list})'):
        raw = r.get("LABEL")
        if not raw:
            continue
        try:
            arr = json.loads(raw) if isinstance(raw, str) else list(raw)
        except json.JSONDecodeError:
            continue
        structural = pick_structural(arr, amap)
        if structural:
            out[r["NODE"]] = structural
    return out


def upsert_document(doc_uri: str, sha256: str, source_type: str, status: str = "ok") -> None:
    now = now_ms()
    rows = fetch(
        f"SELECT first_ingested_ts FROM \"kgr\".\"documents\" "
        f"WHERE doc_uri = '{_q(doc_uri)}' LIMIT 1"
    )
    first_ts = rows[0]["first_ingested_ts"] if rows else now
    _bulk_insert(
        "kgr.documents",
        [{
            "doc_uri": doc_uri,
            "sha256": sha256,
            "source_type": source_type,
            "first_ingested_ts": first_ts,
            "last_ingested_ts": now,
            "status": status,
        }],
        update=True,
    )


def document_sha256(doc_uri: str) -> str | None:
    rows = fetch(
        f"SELECT sha256 FROM \"kgr\".\"documents\" WHERE doc_uri = '{_q(doc_uri)}' LIMIT 1"
    )
    return rows[0]["sha256"] if rows else None


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _bulk_insert(table: str, rows: list[dict[str, Any]], *, update: bool) -> int:
    if not rows:
        return 0
    db = connect()
    payload = json.dumps(rows, default=str)
    options = {"update_on_existing_pk": "true"} if update else {}
    resp_raw = db.insert_records_json(payload, table, options=options)
    resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
    if isinstance(resp, dict) and resp.get("status") == "ERROR":
        raise RuntimeError(f"Kinetica upsert into {table} failed: {resp.get('message')}")
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict):
        return int(data.get("count_inserted", 0)) + int(data.get("count_updated", 0))
    return len(rows)


def _table_columns(table: str) -> set[str]:
    db = connect()
    r = db.show_table(table, options={"get_column_info": "true"})
    schemas = r.get("type_schemas", [])
    if not schemas:
        return set()
    return {f["name"] for f in json.loads(schemas[0]).get("fields", [])}


def _coerce(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, dict)):
        return json.dumps(v, default=str)
    return str(v)


def _q(s: str) -> str:
    return s.replace("'", "''")
