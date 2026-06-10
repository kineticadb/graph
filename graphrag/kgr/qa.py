"""Natural-language Q&A over the kgr property graph (graph-RAG).

Pipeline (`answer()`):
  1. schema    — derive the live meta-graph: node types, relation types, the
                 actual (srcLabel, relation, dstLabel) triples, and declared
                 attributes. This *grounds* the LLM so it can only reference
                 labels/edges that exist.
  2. generate  — LLM writes read-only Cypher for GRAPH "kgr"."kg" given the
                 question + schema + the dialect rules.
  3. validate  — every node label / relation it used must exist in the schema,
                 and the query must be read-only; on failure, re-prompt once
                 with the specific issues (the "hybrid / schema-validated" step).
  4. execute   — run via db.fetch; on a DB error, re-prompt once with the error.
  5. synthesize— LLM turns the result rows + original question into a grounded
                 natural-language answer.

LLM backend resolution mirrors extractors/text.py: KGR_LLM=stub → offline
heuristic; else `claude -p`; else the anthropic SDK.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from typing import Any, Optional

from .db import fetch

# --- read-only / safety guards ---------------------------------------------
_WRITE_KW = re.compile(
    r"\b(CREATE|DELETE|DETACH|SET|MERGE|REMOVE|DROP|ALTER|INSERT|UPDATE|TRUNCATE|CALL)\b",
    re.IGNORECASE,
)
_NODE_LABEL = re.compile(r"\(\s*\w*\s*:\s*([A-Za-z_]\w*)")
_REL_LABEL = re.compile(r"\[\s*\w*\s*:\s*([A-Za-z_]\w*)")

_CYPHER_SCHEMA = {
    "type": "object",
    "properties": {
        "cypher": {"type": "string", "description": "A single read-only Cypher query for GRAPH \"kgr\".\"kg\"."},
        "rationale": {"type": "string", "description": "One sentence on what the query retrieves."},
    },
    "required": ["cypher"],
    "additionalProperties": False,
}


# --- schema (the grounding) -------------------------------------------------

def _label0(raw: Any) -> Optional[str]:
    try:
        arr = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except json.JSONDecodeError:
        return None
    return arr[0] if arr else None


def graph_schema() -> dict:
    """Derive the live meta-graph used to ground generation + validation."""
    node_label: dict[str, str] = {}
    for r in fetch('SELECT NODE, LABEL FROM "kgr"."nodes"'):
        lbl = _label0(r.get("LABEL"))
        if lbl:
            node_label[r["NODE"]] = lbl

    triples: Counter = Counter()
    for r in fetch('SELECT NODE1, NODE2, LABEL FROM "kgr"."edges"'):
        rel = _label0(r.get("LABEL")) or "RELATED_TO"
        s = node_label.get(r.get("NODE1"), "Unknown")
        d = node_label.get(r.get("NODE2"), "Unknown")
        triples[(s, rel, d)] += 1

    attrs: dict[str, list[str]] = {}
    for r in fetch("SELECT type_name, attr_name FROM \"kgr\".\"ontology\" "
                   "WHERE type_kind = 'entity' AND attr_name <> ''"):
        attrs.setdefault(r["type_name"], []).append(r["attr_name"])

    return {
        "node_types": sorted(set(node_label.values())),
        "relation_types": sorted({t[1] for t in triples}),
        "triples": triples,
        "attrs": attrs,
    }


def schema_text(schema: dict, *, max_triples: int = 250) -> str:
    triples = schema["triples"].most_common(max_triples)
    lines = [f"  ({s})-[:{rel}]->({d})" for (s, rel, d), _ in triples]
    if len(schema["triples"]) > max_triples:
        lines.append(f"  … ({len(schema['triples']) - max_triples} more triples omitted)")
    attr_lines = [f"  {t}: {', '.join(a)}" for t, a in sorted(schema["attrs"].items()) if a]
    return (
        "NODE TYPES:\n  " + ", ".join(schema["node_types"]) + "\n\n"
        "RELATION TYPES:\n  " + ", ".join(schema["relation_types"]) + "\n\n"
        "EDGES THAT ACTUALLY EXIST (srcLabel)-[:REL]->(dstLabel):\n" + "\n".join(lines) + "\n\n"
        "ENTITY ATTRIBUTES (column names you may filter/return):\n" + "\n".join(attr_lines)
    )


_DIALECT = """\
Kinetica Cypher dialect rules (MUST follow):
- Start the query with: GRAPH "kgr"."kg"
- Reference node properties as quoted identifiers: n."name_original", n."role", etc. NEVER n.NODE.
- Filter inline at each hop: (n:Label WHERE n."name_original" = 'Microsoft') — not a trailing WHERE.
- Node label after a colon: (n:Organization). Relation type: -[e:AFFECTS]->. Arrow direction matters; flip with <-[e]-.
- Edge type values come back as a JSON array in e.LABEL; prefer matching the type via -[e:REL]-> over filtering e.LABEL.
- For counts / sums / GROUP BY you MUST wrap the match: SELECT col, CAST(COUNT(*) AS BIGINT) AS c FROM GRAPH_TABLE(GRAPH "kgr"."kg" MATCH ... RETURN ...) GROUP BY col.
- Read-only ONLY. Never CREATE/SET/DELETE/MERGE/etc.
- Use ONLY node labels and relation types that appear in the schema below. Always add a sensible LIMIT (<= 100).
"""


# --- LLM backends (mirror extractors/text.py) -------------------------------

def _llm(prompt: str, *, schema: Optional[dict] = None) -> Any:
    """Return a dict (when schema given) or str. Honors KGR_LLM=stub / claude / SDK."""
    if os.environ.get("KGR_LLM") == "stub":
        raise RuntimeError("KGR_LLM=stub: ask/chat need a real LLM backend (claude CLI or ANTHROPIC_API_KEY)")
    if shutil.which("claude"):
        return _llm_claude_cli(prompt, schema)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _llm_claude_sdk(prompt, schema)
    raise RuntimeError("no LLM backend: install the `claude` CLI or set ANTHROPIC_API_KEY")


def _llm_claude_cli(prompt: str, schema: Optional[dict]) -> Any:
    cmd = ["claude", "-p", "--output-format", "json"]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    model = os.environ.get("KGR_LLM_MODEL")
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=int(os.environ.get("KGR_LLM_TIMEOUT", "180")))
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed (rc={proc.returncode}): {proc.stderr.strip()[:400]}")
    wrapper = json.loads(proc.stdout)
    if wrapper.get("is_error"):
        raise RuntimeError(f"claude -p returned error: {wrapper.get('result') or wrapper}")
    if schema is not None:
        out = wrapper.get("structured_output")
        return out if out is not None else json.loads(wrapper.get("result", "{}"))
    return wrapper.get("result", "")


def _llm_claude_sdk(prompt: str, schema: Optional[dict]) -> Any:
    import anthropic
    client = anthropic.Anthropic()
    model = os.environ.get("KGR_LLM_MODEL", "claude-opus-4-7")
    resp = client.messages.create(model=model, max_tokens=2048,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    if schema is None:
        return text
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {"cypher": ""}


# --- pipeline stages --------------------------------------------------------

def generate_cypher(question: str, schema_str: str, *, history: str = "",
                    prior_issue: str = "") -> dict:
    prompt = (
        "You translate a question into ONE read-only Kinetica Cypher query over a "
        "knowledge graph built from cybersecurity / threat-intel news.\n\n"
        + _DIALECT + "\nSCHEMA:\n" + schema_str + "\n"
        + (f"\nEarlier turns (for follow-up context):\n{history}\n" if history else "")
        + (f"\nYour previous attempt was rejected — FIX THIS: {prior_issue}\n" if prior_issue else "")
        + f"\nQuestion: {question}\n\n"
        "Return JSON with `cypher` (the query) and `rationale` (one sentence)."
    )
    out = _llm(prompt, schema=_CYPHER_SCHEMA)
    if isinstance(out, str):
        out = json.loads(out)
    return out


def validate_cypher(cypher: str, schema: dict) -> list[str]:
    issues: list[str] = []
    if 'GRAPH "kgr"."kg"' not in cypher:
        issues.append('query must start with GRAPH "kgr"."kg"')
    # read-only: allow CREATE only inside GRAPH_TABLE? No — GRAPH_TABLE doesn't use CREATE.
    w = _WRITE_KW.search(cypher)
    if w:
        issues.append(f"query is not read-only (found {w.group(0).upper()})")
    known_nodes = set(schema["node_types"])
    known_rels = set(schema["relation_types"])
    for lbl in set(_NODE_LABEL.findall(cypher)):
        if lbl not in known_nodes:
            issues.append(f"unknown node label '{lbl}' (not in schema)")
    for rel in set(_REL_LABEL.findall(cypher)):
        # a token after ':' inside [] is a relation type unless it collides with a node label use
        if rel not in known_rels and rel not in known_nodes:
            issues.append(f"unknown relation type '{rel}' (not in schema)")
    return issues


def _decode_rows(rows: list[dict]) -> list[dict]:
    """Expand any column whose value is a node/edge JSON blob into a compact dict."""
    out = []
    for r in rows:
        nr = {}
        for k, v in r.items():
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, dict):
                        nr[k] = {kk: parsed[kk] for kk in ("name_original", "LABEL", "NODE") if kk in parsed}
                        continue
                    if isinstance(parsed, list):
                        nr[k] = parsed[0] if len(parsed) == 1 else parsed
                        continue
                except json.JSONDecodeError:
                    pass
            nr[k] = v
        out.append(nr)
    return out


def synthesize(question: str, cypher: str, rows: list[dict]) -> str:
    sample = _decode_rows(rows)[:50]
    prompt = (
        "Answer the user's question using ONLY the query results below. Be concise and "
        "specific; name the entities/relations involved. If the results are empty, say the "
        "corpus doesn't contain that information — do not invent facts.\n\n"
        f"Question: {question}\n\n"
        f"Cypher used:\n{cypher}\n\n"
        f"Results ({len(rows)} row(s), showing up to 50):\n{json.dumps(sample, default=str, indent=2)}\n\n"
        "Answer:"
    )
    return str(_llm(prompt)).strip()


def answer(question: str, *, history: str = "", show_cypher: bool = False) -> dict:
    """Run the full NL→Cypher→NL pipeline. Returns a result dict."""
    schema = graph_schema()
    schema_str = schema_text(schema)
    cypher, rows, err, prior = "", [], None, ""
    for attempt in range(3):
        gen = generate_cypher(question, schema_str, history=history, prior_issue=prior)
        cypher = (gen.get("cypher") or "").strip().rstrip(";")
        issues = validate_cypher(cypher, schema)
        if issues:
            prior = "; ".join(issues)
            err = prior
            continue
        try:
            rows = fetch(cypher)
            err = None
            break
        except Exception as e:  # noqa: BLE001 — feed the DB error back for one retry
            err = str(e).splitlines()[0][:300]
            prior = f"the query errored: {err}"
    answer_text = (
        synthesize(question, cypher, rows) if err is None
        else f"Couldn't run a valid query after retries. Last issue: {err}"
    )
    result = {"question": question, "cypher": cypher, "rows": len(rows),
              "answer": answer_text, "error": err}
    if show_cypher:
        result["result_rows"] = _decode_rows(rows)[:50]
    return result
