"""Ingest orchestration.

Text path (the primary flow): split a document into paragraphs, and for each
paragraph: extract -> merge_proposal (grow ontology + ALTER TABLE) -> upsert.

SQL path: pre-seed the ontology with the SQL extractor's known types, run the
AST extractor, upsert via the generic helpers.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .extractors import sql as sql_ex
from .extractors import text as text_ex
from .ontology import fold_proposal, load as load_ontology, merge_proposal
from .schema import apply_graph
from .upsert import document_sha256, upsert_document, upsert_edges, upsert_nodes


TEXT_EXTS = {".txt", ".md", ".markdown"}
SQL_EXTS = {".sql"}

_PARA_SPLIT = re.compile(r"\n\s*\n+")


def ingest_path(path: str | Path) -> list[dict]:
    p = Path(path).resolve()
    raw = p.read_bytes()
    ext = p.suffix.lower()
    if ext in SQL_EXTS:
        return _ingest_sql(raw, p.as_uri())
    return ingest_text(p.as_uri(), raw.decode("utf-8", errors="replace"))


def ingest_text(doc_uri: str, text: str) -> list[dict]:
    """Treat `text` as a multi-paragraph document under `doc_uri`."""
    raw = text.encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    if document_sha256(doc_uri) == sha:
        return [{"uri": doc_uri, "status": "unchanged"}]
    return _ingest_text(raw, sha, doc_uri)


def ingest_url(url: str) -> list[dict]:
    """Fetch `url`, extract its article body, and ingest as a text document.

    The article's title becomes the first paragraph; trafilatura's article
    extraction handles the rest. The URL itself is the doc_uri, so re-ingesting
    the same URL with unchanged content is a no-op.
    """
    from .sources import web

    article = web.fetch(url)
    if article.empty and not article.title:
        return [{"uri": url, "status": "no_text_extracted"}]
    return ingest_text(article.url, article.as_document())


def ingest_feed(feed_url: str, *, limit: int | None = None) -> list[dict]:
    """Iterate an RSS/Atom feed and ingest each entry's article body."""
    from .sources import feed as feed_src

    out: list[dict] = []
    for entry in feed_src.iter_entries(feed_url, limit=limit):
        try:
            results = ingest_url(entry.url)
        except Exception as e:
            out.append({"uri": entry.url, "status": "error", "error": str(e)[:200]})
            continue
        # Tag each paragraph result with feed origin for log clarity.
        for r in results:
            r["feed"] = feed_url
            r["feed_title"] = entry.title
        out.extend(results)
    return out


def _ingest_text(raw: bytes, sha: str, doc_uri: str) -> list[dict]:
    text = raw.decode("utf-8", errors="replace")
    paragraphs = [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]
    results: list[dict] = []
    for idx, para in enumerate(paragraphs, start=1):
        para_uri = f"{doc_uri}#p{idx}"
        _append_corpus(para_uri, para)
        ontology = load_ontology()
        proposal = text_ex.extract(para, ontology)
        # Fold labels to canonical forms BEFORE merging — so merge_proposal only
        # ever sees canonical type names and doesn't allocate ontology rows for
        # aliases beyond the alias rows that fold_proposal itself persists.
        fold_map = fold_proposal(proposal, source_uri=para_uri)
        merge_summary = merge_proposal(
            proposal.get("entity_types", []),
            proposal.get("relation_types", []),
            source_uri=para_uri,
        )
        # Build endpoint label map for this batch so upsert_edges can compose
        # the compound LABEL `<srcLabel>_<baseLabel>_<dstLabel>` without an
        # extra round-trip to kgr.nodes.
        entity_labels = {e.get("id"): e.get("label") for e in proposal.get("entities", []) if e.get("id")}
        n_count = upsert_nodes(proposal.get("entities", []), source_uri=para_uri)
        e_count = upsert_edges(proposal.get("relations", []), source_uri=para_uri, entity_labels=entity_labels)
        results.append({
            "uri": para_uri,
            "paragraph": idx,
            "nodes": n_count,
            "edges": e_count,
            "new_types": merge_summary["new_types"],
            "new_node_columns": list(merge_summary["new_node_columns"]),
            "new_edge_columns": list(merge_summary["new_edge_columns"]),
            "folded": {k: v for k, v in fold_map.items() if k.split(":", 1)[1] != v},
        })
    upsert_document(doc_uri, sha, "text", status="ok" if results else "empty")
    apply_graph()  # CREATE OR REPLACE — picks up rows the monitor missed at bootstrap
    return results


_CORPUS_DEFAULT = Path(__file__).resolve().parent.parent / "corpus.txt"


def _append_corpus(para_uri: str, paragraph: str) -> None:
    """Append-only log of every paragraph kgr has read. Provenance / replay aid."""
    path = Path(os.environ.get("KGR_CORPUS_PATH") or _CORPUS_DEFAULT)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha8 = hashlib.sha1(paragraph.encode("utf-8")).hexdigest()[:8]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"\n--- {ts}  {para_uri}  sha8={sha8} ---\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(header)
        f.write(paragraph.rstrip() + "\n")


def _ingest_sql(raw: bytes, doc_uri: str) -> list[dict]:
    text = raw.decode("utf-8", errors="replace")
    sha = hashlib.sha256(raw).hexdigest()
    if document_sha256(doc_uri) == sha:
        return [{"uri": doc_uri, "status": "unchanged"}]
    # Seed the ontology with SQL types so the upsert columns exist before we write.
    merge_proposal(
        proposal_entity_types=[
            {"name": "SqlTable", "attributes": []},
            {"name": "SqlView",  "attributes": []},
            {"name": "SqlColumn", "attributes": [{"name": "datatype", "type": "VARCHAR(64)"}]},
            {"name": "SqlSelect", "attributes": [{"name": "sql", "type": "VARCHAR(2048)"}]},
            {"name": "SqlInsert", "attributes": [{"name": "sql", "type": "VARCHAR(2048)"}]},
            {"name": "SqlUpdate", "attributes": [{"name": "sql", "type": "VARCHAR(2048)"}]},
            {"name": "SqlDelete", "attributes": [{"name": "sql", "type": "VARCHAR(2048)"}]},
            {"name": "SqlCreateTable", "attributes": [{"name": "sql", "type": "VARCHAR(2048)"}]},
            {"name": "SqlCreateView",  "attributes": [{"name": "sql", "type": "VARCHAR(2048)"}]},
        ],
        proposal_relation_types=[
            {"name": "DEFINES", "attributes": []},
            {"name": "READS", "attributes": []},
            {"name": "WRITES", "attributes": []},
            {"name": "DERIVES_FROM", "attributes": []},
        ],
        source_uri=doc_uri,
    )
    entities, relations = sql_ex.extract(text)
    entity_labels = {e.get("id"): e.get("label") for e in entities if e.get("id")}
    n_count = upsert_nodes(entities, source_uri=doc_uri)
    e_count = upsert_edges(relations, source_uri=doc_uri, entity_labels=entity_labels)
    upsert_document(doc_uri, sha, "sql", status="ok" if (n_count or e_count) else "partial")
    apply_graph()
    return [{"uri": doc_uri, "source_type": "sql", "nodes": n_count, "edges": e_count}]
