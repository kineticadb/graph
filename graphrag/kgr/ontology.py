"""Ontology registry + append-only schema evolver.

The ontology lives in `kgr.ontology`. Each row declares either a type
(attr_name == '') or an attribute column on that type (attr_name != '').

When a new entity-type attribute appears, we ALTER TABLE kgr.nodes ADD COLUMN.
When a new relation-type attribute appears, we ALTER TABLE kgr.edges ADD COLUMN.
Type-level rows (attr_name='') just record the type name + when first seen.

Attribute names are global across types on the same table — i.e. if Person
declares `name VARCHAR(256)` and Company also wants `name`, they share one
column. The LLM is told this in the prompt so it picks compatible names.

Append-only: an existing attribute's type cannot be changed by later input.
If a later paragraph proposes the same attr with a different SQL type, we
keep the original and log it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_AXIS, DEFAULT_RELATION_AXIS
from .db import connect, execute, fetch

_SEED_PATH = Path(__file__).resolve().parent / "ontology_seed.json"


# ---------------------------------------------------------------------------
# In-memory representation
# ---------------------------------------------------------------------------

@dataclass
class TypeSpec:
    kind: str  # 'entity' or 'relation'
    name: str
    attrs: dict[str, str] = field(default_factory=dict)  # attr_name -> SQL type
    axis: str | None = None  # LABEL_KEY axis for entity types (null for relations)


@dataclass
class Ontology:
    entities: dict[str, TypeSpec] = field(default_factory=dict)
    relations: dict[str, TypeSpec] = field(default_factory=dict)

    def node_attr_columns(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for t in self.entities.values():
            for k, v in t.attrs.items():
                out.setdefault(k, v)
        return out

    def edge_attr_columns(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for t in self.relations.values():
            for k, v in t.attrs.items():
                out.setdefault(k, v)
        return out


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def load() -> Ontology:
    ont = Ontology()
    rows = fetch('SELECT type_kind, type_name, attr_name, attr_sql_type, axis FROM "kgr"."ontology"')
    for r in rows:
        kind = r["type_kind"]
        type_name = r["type_name"]
        attr_name = r["attr_name"]
        attr_sql_type = r["attr_sql_type"]
        bag = ont.entities if kind == "entity" else ont.relations
        spec = bag.setdefault(type_name, TypeSpec(kind=kind, name=type_name))
        if attr_name:
            spec.attrs[attr_name] = attr_sql_type
        else:
            # The type-declaration row (attr_name='') carries the axis (both kinds).
            spec.axis = r.get("axis") or (DEFAULT_AXIS if kind == "entity" else DEFAULT_RELATION_AXIS)
    return ont


def merge_proposal(
    proposal_entity_types: Iterable[dict],
    proposal_relation_types: Iterable[dict],
    source_uri: str,
) -> dict:
    """Apply an append-only diff against the registry and run ALTER TABLE for new columns.

    Each proposed type is `{"name": str, "attributes": [{"name": str, "type": "VARCHAR(...)"|...}]}`.
    Returns a summary of what was newly added (types, node-attr columns, edge-attr columns).
    """
    current = load()
    now = _now_ms()
    new_rows: list[dict] = []
    new_node_cols: dict[str, str] = {}
    new_edge_cols: dict[str, str] = {}
    new_types: list[tuple[str, str]] = []

    def _process(kind: str, proposed: Iterable[dict], known: dict[str, TypeSpec], col_sink: dict[str, str]) -> None:
        for t in proposed:
            tname = (t.get("name") or "").strip()
            if not tname:
                continue
            spec = known.get(tname)
            if spec is None:
                spec = TypeSpec(kind=kind, name=tname)
                known[tname] = spec
                # Both entity and relation types land on an axis (LABEL_KEY): the
                # proposal may carry one, else the kind's default (EntityType /
                # Action). Relation axes are the verb's semantic category.
                axis = (t.get("axis") or DEFAULT_AXIS) if kind == "entity" else (t.get("axis") or DEFAULT_RELATION_AXIS)
                new_rows.append(_row(kind, tname, "", "", source_uri, now, axis=axis))
                new_types.append((kind, tname))
            for a in t.get("attributes", []) or []:
                aname = (a.get("name") or "").strip()
                atype = (a.get("type") or "").strip()
                if not aname or not atype:
                    continue
                # Append-only: existing attr keeps its declared type.
                if aname in spec.attrs:
                    continue
                spec.attrs[aname] = atype
                new_rows.append(_row(kind, tname, aname, atype, source_uri, now))
                # The column lives on the shared table — only add once per name.
                col_sink.setdefault(aname, atype)

    _process("entity", proposal_entity_types, current.entities, new_node_cols)
    _process("relation", proposal_relation_types, current.relations, new_edge_cols)

    # Reconcile against existing columns on the physical tables (a column
    # may exist already because some earlier proposal added it under a different type).
    existing_node_cols = _table_columns("kgr.nodes")
    existing_edge_cols = _table_columns("kgr.edges")
    new_node_cols = {k: v for k, v in new_node_cols.items() if k not in existing_node_cols}
    new_edge_cols = {k: v for k, v in new_edge_cols.items() if k not in existing_edge_cols}

    for col, sql_type in new_node_cols.items():
        execute(f'ALTER TABLE "kgr"."nodes" ADD COLUMN "{col}" {sql_type}')
    for col, sql_type in new_edge_cols.items():
        execute(f'ALTER TABLE "kgr"."edges" ADD COLUMN "{col}" {sql_type}')

    if new_rows:
        _insert_ontology_rows(new_rows)

    return {
        "new_types": new_types,
        "new_node_columns": new_node_cols,
        "new_edge_columns": new_edge_cols,
    }


def _table_columns(table: str) -> set[str]:
    db = connect()
    r = db.show_table(table, options={"get_column_info": "true"})
    schemas = r.get("type_schemas", [])
    if not schemas:
        return set()
    out: set[str] = set()
    for f in json.loads(schemas[0]).get("fields", []):
        out.add(f["name"])
    return out


def _insert_ontology_rows(rows: list[dict]) -> None:
    db = connect()
    payload = json.dumps(rows)
    resp_raw = db.insert_records_json(
        payload, "kgr.ontology", options={"update_on_existing_pk": "true"}
    )
    resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
    if isinstance(resp, dict) and resp.get("status") == "ERROR":
        raise RuntimeError(f"kgr.ontology upsert failed: {resp.get('message')}")


def _row(kind: str, type_name: str, attr_name: str, attr_sql_type: str, source_uri: str, now_ms: int,
         axis: str | None = None) -> dict:
    key = hashlib.sha1(f"{kind}|{type_name}|{attr_name}".encode()).hexdigest()
    return {
        "type_kind": kind,
        "type_name": type_name,
        # Default: each type is its own canonical. Override at the call site for aliases.
        "canonical_name": type_name,
        "attr_name": attr_name,
        "attr_sql_type": attr_sql_type or "",
        "first_seen_uri": source_uri,
        "first_seen_ts": now_ms,
        "ont_key": key,
        # Axis (LABEL_KEY) for entity types; null for relations / attribute rows.
        "axis": axis,
    }


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Label folding: alias -> canonical
# ---------------------------------------------------------------------------

def resolve_canonical(kind: str, type_name: str) -> str | None:
    """Return the canonical name for an existing alias, or None if unknown.

    Fast path: a single SQL lookup against kgr.ontology. Reads the *type
    declaration* row (attr_name = '') for the given (kind, name).
    """
    q = (
        f"SELECT canonical_name FROM \"kgr\".\"ontology\" "
        f"WHERE type_kind = '{kind}' AND type_name = '{type_name.replace(chr(39), chr(39)*2)}' "
        f"AND attr_name = '' LIMIT 1"
    )
    rows = fetch(q)
    if rows:
        return rows[0]["canonical_name"] or type_name
    return None


def fold_check_via_llm(kind: str, proposed_name: str, existing_canonicals: list[str]) -> str | None:
    """Ask Claude whether `proposed_name` is a synonym of any existing canonical.

    Returns the canonical name to fold into, or None if the type is genuinely new.
    Single small `claude -p` call with a strict JSON schema. Never raises — on
    any error we conservatively return None (treat as new canonical).
    """
    if not existing_canonicals:
        return None
    if not shutil.which("claude"):
        return None  # fall through; no LLM available

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["canonical"],
        "properties": {
            "canonical": {"type": ["string", "null"]},
        },
    }
    prompt = (
        f"You decide whether a newly-proposed {kind} type name is a synonym of "
        f"any existing canonical type in the ontology.\n\n"
        f"Proposed {kind} type: {proposed_name}\n"
        f"Existing canonical {kind} types: {', '.join(sorted(existing_canonicals))}\n\n"
        f"If the proposed type is semantically the same as one of the existing canonicals, "
        f"return that canonical's exact name. Otherwise return null.\n"
        f"Reply with only a JSON object: {{\"canonical\": \"<existing name>\"}} or {{\"canonical\": null}}."
    )
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema), prompt],
            capture_output=True, text=True,
            timeout=int(os.environ.get("KGR_LLM_TIMEOUT", "60")),
        )
        if proc.returncode != 0:
            return None
        wrapper = json.loads(proc.stdout)
        if wrapper.get("is_error"):
            return None
        structured = wrapper.get("structured_output") or {}
        canonical = structured.get("canonical")
        if isinstance(canonical, str) and canonical in existing_canonicals:
            return canonical
        return None
    except Exception:
        return None


def fold_proposal(proposal: dict[str, Any], source_uri: str) -> dict[str, str]:
    """Rewrite the LLM proposal's labels in-place to their canonical forms.

    For every proposed entity-type / relation-type:
      - If it's already a known canonical or known alias → use the existing canonical.
      - Else if it's a genuinely new name but the LLM fold-check finds it's a synonym
        of an existing canonical → persist a new alias row in kgr.ontology and use
        the existing canonical.
      - Else: leave it alone (it becomes a new canonical when merge_proposal runs).

    Then rewrite every entity.label and relation.label in `proposal` to its canonical
    form. proposal["entity_types"] / ["relation_types"] are pruned to only the
    types that survive as canonicals (their attributes still flow through to
    merge_proposal).

    Returns: {f"{kind}:{original_name}": canonical} for everything that was folded.
    """
    folded: dict[str, str] = {}

    def _resolve_one(kind: str, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return name
        # Cache by kind+name in this call.
        cache_key = f"{kind}:{name}"
        if cache_key in folded:
            return folded[cache_key]

        canonical_existing = resolve_canonical(kind, name)
        if canonical_existing is not None:
            folded[cache_key] = canonical_existing
            return canonical_existing

        # Genuinely new: ask the LLM whether it's a synonym of an existing canonical.
        existing_canonicals = _list_canonicals(kind)
        fold_to = fold_check_via_llm(kind, name, existing_canonicals)
        if fold_to:
            _persist_alias(kind, alias=name, canonical=fold_to, source_uri=source_uri)
            folded[cache_key] = fold_to
            return fold_to

        # Not folded — stays as its own (future) canonical.
        folded[cache_key] = name
        return name

    # Walk every proposed type and pre-resolve. Build a rename map per kind.
    rename: dict[str, dict[str, str]] = {"entity": {}, "relation": {}}
    for kind, key in (("entity", "entity_types"), ("relation", "relation_types")):
        for t in proposal.get(key, []) or []:
            orig = (t.get("name") or "").strip()
            if not orig:
                continue
            canonical = _resolve_one(kind, orig)
            if canonical != orig:
                rename[kind][orig] = canonical
                t["name"] = canonical  # rewrite so merge_proposal sees the canonical

    # Drop duplicate canonical entries that arose from folding (keep the first occurrence).
    for key in ("entity_types", "relation_types"):
        seen: set[str] = set()
        dedup: list[dict] = []
        for t in proposal.get(key, []) or []:
            n = (t.get("name") or "").strip()
            if not n or n in seen:
                continue
            seen.add(n)
            dedup.append(t)
        proposal[key] = dedup

    # Rewrite instance labels. Resolve EACH label directly (not just via the
    # declared-type rename map) — the LLM often tags an instance with a label it
    # never lists in *_types (e.g. an entity labeled "Company" with no "Company"
    # entry in entity_types), and those would otherwise escape folding entirely.
    # Facet labels discovered on entities, with their axis, to register as types.
    facet_types: dict[str, str] = {}
    for e in proposal.get("entities", []) or []:
        lbl = (e.get("label") or "").strip()
        primary = ""
        if lbl:
            e["label_raw"] = lbl          # remember the original (pre-fold) label
            primary = _resolve_one("entity", lbl)
            e["label"] = primary
        # Build the multi-label vector: the structural primary plus any facets the
        # LLM tagged on other axes (e.g. Anthropic -> [Organization, AI, LLM]).
        # Order carries NO meaning to the graph — axis (LABEL_KEY) does — but we
        # keep the primary first for readable rows.
        labels_vec: list[str] = [primary] if primary else []
        for f in e.get("facets") or []:
            if isinstance(f, str):
                f_lbl, f_axis = f.strip(), ""
            else:
                f_lbl = (f.get("label") or "").strip()
                f_axis = (f.get("axis") or "").strip()
            if not f_lbl:
                continue
            canon = _resolve_one("entity", f_lbl)
            # Prefer an axis already recorded for this canonical; else trust the
            # LLM's proposed axis; else default. Register so it joins a LABEL_KEY group.
            axis = _label_axis(canon) or f_axis or DEFAULT_AXIS
            facet_types[canon] = axis
            if canon not in labels_vec:
                labels_vec.append(canon)
        if labels_vec:
            e["labels"] = labels_vec

    for r in proposal.get("relations", []) or []:
        lbl = (r.get("label") or "").strip()
        if lbl:
            r["label_raw"] = lbl
            r["label"] = _resolve_one("relation", lbl)

    # Register discovered facet types (with axis) so merge_proposal persists their
    # ontology rows and rebuild_label_keys groups them under their LABEL_KEY.
    if facet_types:
        et = proposal.setdefault("entity_types", [])
        existing = {(t.get("name") or "").strip() for t in et}
        for name, axis in facet_types.items():
            if name and name not in existing:
                et.append({"name": name, "attributes": [], "axis": axis})
                existing.add(name)

    return folded


def _list_canonicals(kind: str) -> list[str]:
    rows = fetch(
        f"SELECT DISTINCT canonical_name FROM \"kgr\".\"ontology\" "
        f"WHERE type_kind = '{kind}' AND attr_name = ''"
    )
    return [r["canonical_name"] for r in rows if r.get("canonical_name")]


def _persist_alias(kind: str, alias: str, canonical: str, source_uri: str) -> None:
    """Insert an alias row (type_name=alias, canonical_name=canonical) into kgr.ontology."""
    now = _now_ms()
    row = _row(kind, alias, "", "", source_uri, now)
    row["canonical_name"] = canonical
    _insert_ontology_rows([row])


# ---------------------------------------------------------------------------
# Axes (LABEL_KEY) — facet dimensions for the multi-label vector
# ---------------------------------------------------------------------------

def axis_map() -> dict[str, str]:
    """{entity label -> axis}. Includes canonical AND alias rows so any label
    found on a node resolves. Null/blank axis falls back to the structural default.
    """
    out: dict[str, str] = {}
    for r in fetch(
        "SELECT type_name, axis FROM \"kgr\".\"ontology\" "
        "WHERE type_kind = 'entity' AND attr_name = ''"
    ):
        out[r["type_name"]] = (r.get("axis") or DEFAULT_AXIS)
    return out


def _label_axis(name: str) -> str | None:
    """The axis recorded for a single entity label, or None if unknown."""
    q = (
        "SELECT axis FROM \"kgr\".\"ontology\" "
        f"WHERE type_kind = 'entity' AND attr_name = '' AND type_name = '{name.replace(chr(39), chr(39)*2)}' "
        "LIMIT 1"
    )
    rows = fetch(q)
    if rows:
        return rows[0].get("axis") or DEFAULT_AXIS
    return None


def pick_structural(labels: list[str], amap: dict[str, str] | None = None) -> str | None:
    """Return the label on the structural (EntityType) axis from a node's vector.

    Order-independent: the graph engine treats the LABEL array as an unordered
    multi-label, so we resolve the structural type by AXIS membership, never by
    position. Falls back to the first label if none is classified as structural.
    """
    if not labels:
        return None
    amap = amap if amap is not None else axis_map()
    for lbl in labels:
        if amap.get(lbl, DEFAULT_AXIS) == DEFAULT_AXIS:
            return lbl
    return labels[0]


def rebuild_label_keys() -> int:
    """Materialize kgr.label_keys from kgr.ontology: one row per axis, holding the
    sorted array of CANONICAL entity labels on it (aliases are excluded — nodes only
    ever store canonicals). Upserts current axes and prunes axes that no longer exist.
    Returns the number of axis rows written.
    """
    groups: dict[str, set[str]] = {}
    for r in fetch(
        "SELECT type_name, axis, canonical_name FROM \"kgr\".\"ontology\" "
        "WHERE type_kind = 'entity' AND attr_name = ''"
    ):
        name = r["type_name"]
        canon = r.get("canonical_name") or name
        if name != canon:  # alias — not stored on nodes, so not a graph label
            continue
        axis = r.get("axis") or DEFAULT_AXIS
        groups.setdefault(axis, set()).add(name)

    rows = [{"label_key": ax, "label": sorted(lbls)} for ax, lbls in groups.items() if lbls]
    if rows:
        db = connect()
        payload = json.dumps(rows)
        resp_raw = db.insert_records_json(
            payload, "kgr.label_keys", options={"update_on_existing_pk": "true"}
        )
        resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
        if isinstance(resp, dict) and resp.get("status") == "ERROR":
            raise RuntimeError(f"kgr.label_keys upsert failed: {resp.get('message')}")
    # Prune axes that disappeared.
    keep = {ax for ax in groups}
    if keep:
        in_list = ", ".join("'" + ax.replace("'", "''") + "'" for ax in keep)
        execute(f'DELETE FROM "kgr"."label_keys" WHERE "label_key" NOT IN ({in_list})')
    else:
        execute('DELETE FROM "kgr"."label_keys" WHERE 1 = 1')
    return len(rows)


def categorize_relation_axes(seed_axes: list[str] | None = None) -> dict[str, str]:
    """LLM-assign a semantic category (axis) to every currently-uncategorized verb.

    One batched `claude -p` call maps each canonical relation verb still on the
    default `Action` axis to its best category — reusing the existing relation axes
    (plus any `seed_axes`), coining a new one only when none fits. Updates
    kgr.ontology.axis for those verbs. Forward use (the extractor proposes axes on
    new verbs) plus this back-pass over what's already there. Never raises; returns
    {verb: axis} for what it changed. Re-apply the graph afterwards.
    """
    canon = [
        r for r in fetch(
            "SELECT type_name, axis, canonical_name FROM \"kgr\".\"ontology\" "
            "WHERE type_kind = 'relation' AND attr_name = ''"
        )
        if (r.get("canonical_name") or r["type_name"]) == r["type_name"]
    ]
    known = sorted({(r.get("axis") or DEFAULT_RELATION_AXIS) for r in canon} | set(seed_axes or []))
    uncategorized = sorted(r["type_name"] for r in canon
                           if (r.get("axis") or DEFAULT_RELATION_AXIS) == DEFAULT_RELATION_AXIS)
    if not uncategorized or not shutil.which("claude"):
        return {}

    schema = {
        "type": "object", "additionalProperties": False, "required": ["assignments"],
        "properties": {"assignments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["verb", "axis"],
            "properties": {"verb": {"type": "string"}, "axis": {"type": "string"}}}}},
    }
    prompt = (
        "Classify each knowledge-graph relation verb into a semantic CATEGORY (axis).\n"
        f"Existing categories (reuse when one fits; coin a new TitleCase one only if none does): {', '.join(known)}\n\n"
        f"Verbs to classify: {', '.join(uncategorized)}\n\n"
        "Return JSON {\"assignments\": [{\"verb\": \"<verb>\", \"axis\": \"<Category>\"}, ...]} covering every verb."
    )
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema), prompt],
            capture_output=True, text=True, timeout=int(os.environ.get("KGR_LLM_TIMEOUT", "180")),
        )
        if proc.returncode != 0:
            return {}
        structured = (json.loads(proc.stdout) or {}).get("structured_output") or {}
    except Exception:
        return {}

    valid = set(uncategorized)
    mapping = {a["verb"]: a["axis"].strip() for a in structured.get("assignments", [])
               if a.get("verb") in valid and (a.get("axis") or "").strip()}
    if not mapping:
        return {}
    now = _now_ms()
    rows = []
    for verb, axis in mapping.items():
        row = _row("relation", verb, "", "", "llm://categorize_relation_axes", now, axis=axis)
        row["canonical_name"] = verb
        rows.append(row)
    _insert_ontology_rows(rows)
    return mapping


def rebuild_edge_label_keys() -> int:
    """Materialize kgr.edge_label_keys: one row per relation axis -> the array of
    canonical verbs in it (e.g. Offensive -> [AFFECTS, EXPLOITS, TARGETS]). The
    relation axis is the verb's semantic CATEGORY — the EDGES analog of node axes,
    a second-level grouping over the canonical verbs (akin to canonicalization but
    one level up). Fed into CREATE GRAPH's EDGES component as the same valid
    (LABEL_KEY, LABEL) grouping SELECT used for nodes, so /show/graph with
    schema_edge_labelkeys=true collapses all verbs in a category into one abstract
    edge. Single-membership (each verb -> one category). Stored LABEL stays bare.
    Upserts current axes and prunes ones that no longer exist.
    """
    groups: dict[str, set[str]] = {}
    for r in fetch(
        "SELECT type_name, axis, canonical_name FROM \"kgr\".\"ontology\" "
        "WHERE type_kind = 'relation' AND attr_name = ''"
    ):
        name = r["type_name"]
        canon = r.get("canonical_name") or name
        if name != canon:  # alias — not stored on edges
            continue
        axis = r.get("axis") or DEFAULT_RELATION_AXIS
        groups.setdefault(axis, set()).add(name)

    rows = [{"label_key": k, "label": sorted(v)} for k, v in groups.items() if v]
    if rows:
        db = connect()
        payload = json.dumps(rows)
        resp_raw = db.insert_records_json(payload, "kgr.edge_label_keys", options={"update_on_existing_pk": "true"})
        resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
        if isinstance(resp, dict) and resp.get("status") == "ERROR":
            raise RuntimeError(f"kgr.edge_label_keys upsert failed: {resp.get('message')}")
    keep = set(groups)
    if keep:
        in_list = ", ".join("'" + k.replace("'", "''") + "'" for k in keep)
        execute(f'DELETE FROM "kgr"."edge_label_keys" WHERE "label_key" NOT IN ({in_list})')
    else:
        execute('DELETE FROM "kgr"."edge_label_keys" WHERE 1 = 1')
    return len(rows)


# ---------------------------------------------------------------------------
# Seed loading
# ---------------------------------------------------------------------------

def apply_seed(path: Path | None = None) -> dict:
    """Idempotently load the ontology seed JSON into kgr.ontology.

    For each (alias, canonical) pair:
      - Insert/upsert an alias row (type_name=alias, canonical_name=canonical).
      - Insert/upsert a canonical row if not present (type_name=canonical, canonical_name=canonical).
      - If `alias` already exists with a different canonical_name, update it (the seed wins).

    Does NOT rewrite labels in kgr.nodes / kgr.edges — backfill is a separate step.
    """
    src = path or _SEED_PATH
    if not src.is_file():
        return {"applied_aliases": [], "added_canonicals": []}
    blob = json.loads(src.read_text())
    now = _now_ms()
    rows: list[dict] = []
    applied: list[tuple[str, str, str]] = []  # (kind, alias, canonical)
    canonicals_added: list[tuple[str, str]] = []

    existing_canonical_for = _existing_canonical_map()  # (kind, type_name) -> canonical_name

    # Axis per facet entity canonical; structural labels default to EntityType.
    entity_axis_for: dict[str, str] = {}
    for label, axis in (blob.get("entity_axes") or {}).items():
        label, axis = label.strip(), (axis or "").strip()
        if label and axis:
            entity_axis_for[label] = axis

    def _entity_axis(name: str) -> str:
        return entity_axis_for.get(name, DEFAULT_AXIS)

    # Axis (semantic category) per relation verb; unseeded verbs default to Action.
    relation_axis_for: dict[str, str] = {}
    for verb, axis in (blob.get("relation_axes") or {}).items():
        verb, axis = verb.strip(), (axis or "").strip()
        if verb and axis:
            relation_axis_for[verb] = axis

    def _relation_axis(name: str) -> str:
        return relation_axis_for.get(name, DEFAULT_RELATION_AXIS)

    def _process_alias(kind: str, alias: str, canonical: str, axis: str | None):
        alias, canonical = alias.strip(), canonical.strip()
        if not alias or not canonical:
            return
        # canonical row (idempotent — UPSERT will be a no-op if unchanged)
        if (kind, canonical) not in existing_canonical_for:
            row = _row(kind, canonical, "", "", str(src), now, axis=axis)
            row["canonical_name"] = canonical
            rows.append(row)
            canonicals_added.append((kind, canonical))
            existing_canonical_for[(kind, canonical)] = canonical
        # alias row (shares the canonical's axis)
        current = existing_canonical_for.get((kind, alias))
        if current != canonical:
            row = _row(kind, alias, "", "", str(src), now, axis=axis)
            row["canonical_name"] = canonical
            rows.append(row)
            applied.append((kind, alias, canonical))
            existing_canonical_for[(kind, alias)] = canonical

    # Structural entity aliases (axis defaults to EntityType).
    for alias, canonical in (blob.get("entity_aliases") or {}).items():
        _process_alias("entity", alias, canonical, _entity_axis(canonical.strip()))

    # Facet canonicals — force-write so an existing structural classification is
    # corrected to its facet axis (upsert by ont_key overwrites the axis value).
    for label, axis in entity_axis_for.items():
        row = _row("entity", label, "", "", str(src), now, axis=axis)
        rows.append(row)
        if ("entity", label) not in existing_canonical_for:
            canonicals_added.append(("entity", label))
        existing_canonical_for[("entity", label)] = label

    # Facet aliases -> facet canonical (share the canonical's facet axis).
    for alias, canonical in (blob.get("entity_axis_aliases") or {}).items():
        _process_alias("entity", alias, canonical, _entity_axis(canonical.strip()))

    # Relation aliases (share the canonical verb's semantic category axis).
    for alias, canonical in (blob.get("relation_aliases") or {}).items():
        _process_alias("relation", alias, canonical, _relation_axis(canonical.strip()))

    # Relation axis canonicals — force-write so a verb's category is corrected
    # (upsert by ont_key overwrites the axis), mirroring entity facet canonicals.
    for verb, axis in relation_axis_for.items():
        row = _row("relation", verb, "", "", str(src), now, axis=axis)
        rows.append(row)
        if ("relation", verb) not in existing_canonical_for:
            canonicals_added.append(("relation", verb))
        existing_canonical_for[("relation", verb)] = verb

    if rows:
        _insert_ontology_rows(rows)

    return {"applied_aliases": applied, "added_canonicals": canonicals_added}


def compound_edge_labels() -> int:
    """Rewrite every kgr.edges row's LABEL to compound form `<srcLabel>_<baseLabel>_<dstLabel>`.

    Idempotent: skips edges whose LABEL already matches the expected compound form
    given the current endpoint labels. Re-applying the graph after this call is
    the caller's responsibility (apply_all does it automatically).
    """
    # Build {NODE: structural LABEL} map from kgr.nodes once. The structural label
    # is resolved by AXIS membership (the EntityType-axis element of the vector),
    # not by array position — the graph treats LABEL as an unordered multi-label.
    amap = axis_map()
    node_label: dict[str, str] = {}
    for r in fetch('SELECT NODE, LABEL FROM "kgr"."nodes"'):
        raw = r.get("LABEL")
        if not raw:
            continue
        try:
            arr = json.loads(raw) if isinstance(raw, str) else list(raw)
        except json.JSONDecodeError:
            continue
        structural = pick_structural(arr, amap)
        if structural:
            node_label[r["NODE"]] = structural

    # Pull canonical relation type names so we can recover the BASE part from
    # an existing LABEL — whether stored as bare base ("WORKS_AT"), as an
    # already-compound string ("Person_WORKS_AT_Organization"), or anything in
    # between (e.g. "WORKS_AT_Person" partial).
    canonicals = set(_list_canonicals("relation"))

    changed: list[dict] = []
    for r in fetch('SELECT * FROM "kgr"."edges"'):
        n1 = r.get("NODE1")
        n2 = r.get("NODE2")
        src_lbl = node_label.get(n1, "Unknown")
        dst_lbl = node_label.get(n2, "Unknown")
        raw = r.get("LABEL")
        try:
            current_arr = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        except json.JSONDecodeError:
            current_arr = []
        if not current_arr:
            continue
        current = current_arr[0]
        base = _extract_base(current, canonicals)
        expected = f"{src_lbl}_{base}_{dst_lbl}"
        if current == expected:
            continue
        r["LABEL"] = [expected]
        changed.append(r)
    if not changed:
        return 0
    db = connect()
    payload = json.dumps(changed, default=str)
    resp_raw = db.insert_records_json(payload, "kgr.edges", options={"update_on_existing_pk": "true"})
    resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
    if isinstance(resp, dict) and resp.get("status") == "ERROR":
        raise RuntimeError(f"compound_edge_labels failed: {resp.get('message')}")
    return len(changed)


def base_edge_labels() -> int:
    """Rewrite every kgr.edges row's LABEL to its bare base relation form.

    The inverse of `compound_edge_labels`: `Person_WORKS_AT_Organization` ->
    `WORKS_AT`. Uses the canonical relation set to recover the base, so labels
    whose base contains underscores (`LOCATED_IN`) survive. Idempotent — skips
    rows already in base form. Re-applying the graph is the caller's job.
    """
    canonicals = set(_list_canonicals("relation"))
    changed: list[dict] = []
    for r in fetch('SELECT * FROM "kgr"."edges"'):
        raw = r.get("LABEL")
        try:
            current_arr = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        except json.JSONDecodeError:
            current_arr = []
        if not current_arr:
            continue
        current = current_arr[0]
        base = _extract_base(current, canonicals)
        if current == base:
            continue
        r["LABEL"] = [base]
        changed.append(r)
    if not changed:
        return 0
    db = connect()
    payload = json.dumps(changed, default=str)
    resp_raw = db.insert_records_json(payload, "kgr.edges", options={"update_on_existing_pk": "true"})
    resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
    if isinstance(resp, dict) and resp.get("status") == "ERROR":
        raise RuntimeError(f"base_edge_labels failed: {resp.get('message')}")
    return len(changed)


def _extract_base(label: str, canonicals: set[str]) -> str:
    """Recover the base relation type from a label that may be bare or compound.

    Strategy: prefer the longest canonical that appears as a `_<canonical>_` or
    boundary substring; fall back to the whole label if nothing matches.
    """
    if label in canonicals:
        return label
    # Try suffix/prefix match: `<src>_<base>_<dst>` -- look for a canonical
    # in any contiguous run of underscores between segments.
    parts = label.split("_")
    # Sliding window: any consecutive parts joined by '_' that match a canonical
    for size in range(len(parts), 0, -1):
        for start in range(0, len(parts) - size + 1):
            candidate = "_".join(parts[start:start + size])
            if candidate in canonicals:
                return candidate
    return label  # nothing matched — leave it as is


def backfill_labels() -> dict:
    """Rewrite LABEL arrays in kgr.nodes and kgr.edges to canonical forms.

    Walks every existing row, decodes its LABEL, replaces each alias element
    with its canonical from kgr.ontology, and re-upserts the row through
    `insert_records_json` (with `update_on_existing_pk='true'`) when changed.
    The graph is not re-applied here — call `apply_graph()` after backfilling
    so the live graph picks up the new label values.
    """
    nodes_alias = {a: c for (k, a), c in _alias_map().items() if k == "entity"}
    edges_alias = {a: c for (k, a), c in _alias_map().items() if k == "relation"}
    return {
        "nodes_updated": _backfill_table("kgr.nodes", nodes_alias),
        "edges_updated": _backfill_table("kgr.edges", edges_alias),
    }


def _alias_map() -> dict[tuple[str, str], str]:
    """{(kind, alias): canonical} for every alias row in kgr.ontology."""
    out: dict[tuple[str, str], str] = {}
    for r in fetch(
        "SELECT type_kind, type_name, canonical_name FROM \"kgr\".\"ontology\" "
        "WHERE attr_name = '' AND canonical_name IS NOT NULL "
        "AND type_name <> canonical_name"
    ):
        out[(r["type_kind"], r["type_name"])] = r["canonical_name"]
    return out


def _backfill_table(table: str, alias_map: dict[str, str]) -> int:
    if not alias_map:
        return 0
    schema, _, name = table.partition(".")
    # Cheap precheck: only do the full SELECT * + rewrite if some distinct LABEL value
    # actually contains an aliased name. Distinct labels are a small set even on huge
    # tables (one per label vocabulary entry) so this is a tiny query.
    distinct_labels: list[list[str]] = []
    for r in fetch(f'SELECT DISTINCT LABEL FROM "{schema}"."{name}"'):
        raw = r.get("LABEL")
        if not raw:
            continue
        try:
            arr = json.loads(raw) if isinstance(raw, str) else list(raw)
        except json.JSONDecodeError:
            continue
        distinct_labels.append(arr)
    if not any(lbl in alias_map for arr in distinct_labels for lbl in arr):
        return 0
    rows = fetch(f'SELECT * FROM "{schema}"."{name}"')
    changed: list[dict] = []
    for r in rows:
        original = r.get("LABEL")
        if not original:
            continue
        # LABEL comes back JSON-encoded (e.g. '["Company"]'). Parse, fold, re-emit.
        try:
            current = json.loads(original) if isinstance(original, str) else original
        except json.JSONDecodeError:
            continue
        new = [alias_map.get(lbl, lbl) for lbl in current]
        if new == current:
            continue
        r["LABEL"] = new
        changed.append(r)
    if not changed:
        return 0
    db = connect()
    payload = json.dumps(changed, default=str)
    resp_raw = db.insert_records_json(
        payload, table, options={"update_on_existing_pk": "true"}
    )
    resp = json.loads(resp_raw) if isinstance(resp_raw, (str, bytes)) else resp_raw
    if isinstance(resp, dict) and resp.get("status") == "ERROR":
        raise RuntimeError(f"backfill of {table} failed: {resp.get('message')}")
    return len(changed)


def _existing_canonical_map() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for r in fetch(
        "SELECT type_kind, type_name, canonical_name FROM \"kgr\".\"ontology\" WHERE attr_name = ''"
    ):
        out[(r["type_kind"], r["type_name"])] = r.get("canonical_name") or r["type_name"]
    return out
