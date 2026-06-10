"""Text extractor: LLM ontology induction + entity/relation extraction.

Mode is chosen at import time by env:

  - ANTHROPIC_API_KEY set        -> real Claude call (KGR_LLM_MODEL controls model id)
  - otherwise                    -> a clearly-marked heuristic stub used only to
                                    let the pipeline run end-to-end without keys.

Both paths return a uniform dict:

    {
        "entity_types":   [{"name": "...", "attributes": [{"name": "...", "type": "VARCHAR(...)"|"DATE"|...}]}],
        "relation_types": [{"name": "...", "attributes": [...]}],
        "entities":       [{"id": "...", "label": "Person", "name": "...", "qualified_name": "...", "attrs": {...}}],
        "relations":      [{"src": "...", "dst": "...", "label": "WORKS_AT", "confidence": 0.9, "attrs": {...}}]
    }

`id` values use the canonical scheme: lowercase-slug + sha1 short hash (see canonical.concept_id).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

from ..canonical import concept_id
from ..ontology import Ontology


PROMPT_TEMPLATE = """You extract a knowledge graph from a short text passage.

Return a single JSON object with keys: entity_types, relation_types, entities, relations.

Conventions:
- entity_types[i] = {{"name": "<TitleCase singular type, e.g. Person, Company, Event, Location, FinancialInstrument, Government>",
                     "attributes": [{{"name": "<lower_snake_case attr>", "type": "VARCHAR(<n>)"|"DATE"|"DOUBLE"|"BIGINT"|"BOOLEAN"}}]}}
- relation_types[i] = same shape, with UPPER_SNAKE_CASE names (e.g. ACQUIRED, WORKS_AT, REPORTED_IN, REGULATES).
- Attribute names are GLOBAL across types on the same table (entity attrs share kgr.nodes, relation attrs share kgr.edges).
  Reuse an existing attribute name when the meaning matches. Pick distinct names when it doesn't.
- entities[i].id is a stable canonical id DERIVED FROM THE ENTITY'S NAME, not prefixed with its type.
  The LABEL already records the type — the id is the entity's identity. Use lowercase + underscores only.
  Examples: name "Jerome Powell" -> id "jerome_powell"; "Apple Inc." -> "apple_inc"; "Washington" -> "washington".
  Reuse the SAME id when the same real-world entity appears across paragraphs.
- relations[i].src and .dst MUST refer to entities you list under "entities".
- Use the existing ontology (below) when types or attributes already cover the concept — only add NEW types when truly needed.
- Be conservative: skip generic concepts (e.g. "company" as a category, "money" as a noun). Extract NAMED entities.

Existing ontology (entity_type -> attrs, relation_type -> attrs):
{ontology_summary}

Passage:
{passage}

Respond with ONLY the JSON object."""


def extract(passage: str, ontology: Ontology) -> dict[str, Any]:
    passage = passage.strip()
    if not passage:
        return _empty()
    if os.environ.get("KGR_LLM") == "stub":
        return _extract_heuristic(passage, ontology)
    if shutil.which("claude"):
        return _extract_via_claude_cli(passage, ontology)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _extract_via_claude_sdk(passage, ontology)
    return _extract_heuristic(passage, ontology)


# ---------------------------------------------------------------------------
# Claude path
# ---------------------------------------------------------------------------

_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entity_types", "relation_types", "entities", "relations"],
    "properties": {
        "entity_types": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "attributes"],
                "properties": {
                    "name": {"type": "string"},
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "type"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "relation_types": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "attributes"],
                "properties": {
                    "name": {"type": "string"},
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "type"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label", "name"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "name": {"type": "string"},
                    "qualified_name": {"type": "string"},
                    "attrs": {"type": "object"},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["src", "dst", "label"],
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "label": {"type": "string"},
                    "confidence": {"type": "number"},
                    "attrs": {"type": "object"},
                },
            },
        },
    },
}


def _extract_via_claude_cli(passage: str, ontology: Ontology) -> dict[str, Any]:
    """Use the locally-authenticated `claude -p` CLI (print/non-interactive mode).

    --bare         skips hooks, LSP, plugins, CLAUDE.md auto-discovery, etc — pure prompt-in / text-out.
    --json-schema  forces the model's output to conform to our entity/relation JSON shape.
    """
    prompt = PROMPT_TEMPLATE.format(
        ontology_summary=_summarize_ontology(ontology),
        passage=passage,
    )
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(_RESPONSE_SCHEMA),
        prompt,
    ]
    model = os.environ.get("KGR_LLM_MODEL")
    if model:
        cmd[2:2] = ["--model", model]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=int(os.environ.get("KGR_LLM_TIMEOUT", "180")),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr.strip()[:400]}")
    try:
        wrapper = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude -p wrapper was not JSON: {e}\n{proc.stdout[:400]}")
    if wrapper.get("is_error"):
        raise RuntimeError(f"claude -p returned error: {wrapper.get('result') or wrapper}")
    structured = wrapper.get("structured_output")
    if structured is None:
        # Fall back to parsing the freeform result text.
        return _parse_json_blob(wrapper.get("result", ""))
    return _normalize(structured)


def _extract_via_claude_sdk(passage: str, ontology: Ontology) -> dict[str, Any]:
    import anthropic  # imported lazily

    client = anthropic.Anthropic()
    model = os.environ.get("KGR_LLM_MODEL", "claude-opus-4-7")
    prompt = PROMPT_TEMPLATE.format(
        ontology_summary=_summarize_ontology(ontology),
        passage=passage,
    )
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    return _parse_json_blob(text)


def _parse_json_blob(text: str) -> dict[str, Any]:
    text = text.strip()
    # Strip a fenced code block if present.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # If the model wrapped JSON in prose, extract the first {...} blob.
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM returned non-JSON response: {e}\n{text[:400]}")
    return _normalize(data)


def _summarize_ontology(ont: Ontology) -> str:
    if not ont.entities and not ont.relations:
        return "(empty)"
    lines: list[str] = []
    for t in sorted(ont.entities.values(), key=lambda x: x.name):
        attrs = ", ".join(f"{k}:{v}" for k, v in sorted(t.attrs.items())) or "(none)"
        lines.append(f"  entity {t.name}: {attrs}")
    for t in sorted(ont.relations.values(), key=lambda x: x.name):
        attrs = ", ".join(f"{k}:{v}" for k, v in sorted(t.attrs.items())) or "(none)"
        lines.append(f"  relation {t.name}: {attrs}")
    return "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Heuristic stub (no API key)
# ---------------------------------------------------------------------------

_CAPITALIZED_PHRASE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9&.\-]*)(?:\s+[A-Z][a-zA-Z0-9&.\-]*)*\b")
_COMPANY_SUFFIX = re.compile(r"\b(Inc\.?|Corp\.?|Ltd\.?|Plc|PLC|LLC|N\.V\.|S\.A\.|Group|Holdings|Bank|Capital)\b")
_VERBS = {
    "acquired": "ACQUIRED",
    "bought": "ACQUIRED",
    "merged": "MERGED_WITH",
    "invested": "INVESTED_IN",
    "appointed": "APPOINTED",
    "hired": "HIRED",
    "joined": "JOINED",
    "fired": "FIRED",
    "filed": "FILED",
    "sued": "SUED",
    "settled": "SETTLED_WITH",
    "announced": "ANNOUNCED",
    "raised": "RAISED",
    "reported": "REPORTED",
}
_STOPWORDS = {"The", "A", "An", "On", "In", "Of", "From", "To", "By", "Mr", "Mrs", "Ms", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"}


def _extract_heuristic(passage: str, ontology: Ontology) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    for m in _CAPITALIZED_PHRASE.finditer(passage):
        phrase = m.group(0).strip()
        if phrase in _STOPWORDS or len(phrase) < 3:
            continue
        # Skip a leading stopword (e.g. "The Federal Reserve" -> "Federal Reserve").
        toks = phrase.split()
        while toks and toks[0] in _STOPWORDS:
            toks.pop(0)
        if not toks:
            continue
        phrase = " ".join(toks)
        if phrase in candidates:
            continue
        label = "Company" if _COMPANY_SUFFIX.search(phrase) else "Entity"
        candidates[phrase] = {
            "id": concept_id(phrase),
            "label": label,
            "name": phrase,
            "qualified_name": phrase,
            "attrs": {},
        }

    entity_types = []
    if any(e["label"] == "Company" for e in candidates.values()):
        entity_types.append({"name": "Company", "attributes": []})
    if any(e["label"] == "Entity" for e in candidates.values()):
        entity_types.append({"name": "Entity", "attributes": []})

    # Build co-mention edges between adjacent candidates separated by a known verb.
    relations: list[dict[str, Any]] = []
    relation_type_names: set[str] = set()
    positions = [(m.start(), m.group(0).strip(), candidates.get(_strip_stop(m.group(0).strip()))) for m in _CAPITALIZED_PHRASE.finditer(passage) if candidates.get(_strip_stop(m.group(0).strip()))]
    for i in range(len(positions) - 1):
        _, _, src = positions[i]
        nxt_start, _, dst = positions[i + 1]
        between = passage[positions[i][0] : nxt_start].lower()
        rel_label = None
        for verb, label in _VERBS.items():
            if f" {verb} " in between or between.startswith(f"{verb} "):
                rel_label = label
                break
        if rel_label is None:
            continue
        relations.append({
            "src": src["id"], "dst": dst["id"], "label": rel_label, "confidence": 0.4, "attrs": {},
        })
        relation_type_names.add(rel_label)

    relation_types = [{"name": n, "attributes": []} for n in sorted(relation_type_names)]
    return _normalize({
        "entity_types": entity_types,
        "relation_types": relation_types,
        "entities": list(candidates.values()),
        "relations": relations,
    })


def _strip_stop(phrase: str) -> str:
    toks = phrase.split()
    while toks and toks[0] in _STOPWORDS:
        toks.pop(0)
    return " ".join(toks)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize(data: dict) -> dict[str, Any]:
    return {
        "entity_types": data.get("entity_types") or [],
        "relation_types": data.get("relation_types") or [],
        "entities": data.get("entities") or [],
        "relations": data.get("relations") or [],
    }


def _empty() -> dict[str, Any]:
    return {"entity_types": [], "relation_types": [], "entities": [], "relations": []}
