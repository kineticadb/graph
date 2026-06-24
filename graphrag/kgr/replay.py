"""Replay corpus.txt — re-run every logged paragraph through the CURRENT
extraction pipeline, rebuilding the graph without re-fetching the originals.

`corpus.txt` is the append-only provenance log written by
`ingest._append_corpus`: each record is a header line

    --- <iso-ts>  <para_uri>  sha8=<8hex> ---

followed by the paragraph text (until the next header). We parse those back into
(para_uri, text) pairs and feed each through extract -> fold -> merge -> upsert,
exactly as `_ingest_text` does per paragraph, then re-apply the graph once.

Use after an ontology/extractor change (e.g. multi-label facets): a deterministic
re-derivation from the same text the graph was originally built from — no network,
no feed drift. Runs serially (the ontology evolves per paragraph; concurrent
`merge_proposal` calls would race).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from .extractors import text as text_ex
from .ingest import _CORPUS_DEFAULT
from .ontology import fold_proposal, load as load_ontology, merge_proposal
from .schema import apply_graph
from .upsert import upsert_edges, upsert_nodes

# --- <ts>  <para_uri>  sha8=<hex> ---
_HEADER = re.compile(r"^---\s+(\S+)\s+(\S+)\s+sha8=([0-9a-f]+)\s+---\s*$")


def parse_corpus(path: str | Path) -> list[tuple[str, str]]:
    """Parse corpus.txt into [(para_uri, paragraph_text), …] in log order."""
    records: list[tuple[str, str]] = []
    cur_uri: str | None = None
    buf: list[str] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = _HEADER.match(line)
        if m:
            if cur_uri and buf:
                records.append((cur_uri, "\n".join(buf).strip()))
            cur_uri = m.group(2)
            buf = []
        elif cur_uri is not None:
            buf.append(line)
    if cur_uri and buf:
        records.append((cur_uri, "\n".join(buf).strip()))
    return [(u, t) for (u, t) in records if t]


def replay_corpus(
    path: str | Path | None = None,
    *,
    refresh_every: int = 5,
    progress: Callable[[int, int, str, dict], None] | None = None,
) -> dict:
    """Replay each logged paragraph through the current pipeline.

    The graph is re-applied (`CREATE OR REPLACE`) every `refresh_every` paragraphs
    so `kgr.kg` tracks the growing tables during a long replay (the table monitor
    lags under bulk load) — and always once more at the end. Set refresh_every=0
    to re-apply only at the end.
    """
    src = Path(path or os.environ.get("KGR_CORPUS_PATH") or _CORPUS_DEFAULT)
    records = parse_corpus(src)
    total = len(records)
    n_nodes = n_edges = 0
    failures: list[dict] = []
    for i, (para_uri, para) in enumerate(records, start=1):
        # Resilient per-paragraph: one bad value (e.g. a year emitted for a DATE
        # column) must not abort the whole replay — log it and carry on.
        dn = de = 0
        err = None
        try:
            ontology = load_ontology()
            proposal = text_ex.extract(para, ontology)
            fold_proposal(proposal, source_uri=para_uri)
            merge_proposal(
                proposal.get("entity_types", []),
                proposal.get("relation_types", []),
                source_uri=para_uri,
            )
            entity_labels = {e.get("id"): e.get("label") for e in proposal.get("entities", []) if e.get("id")}
            dn = upsert_nodes(proposal.get("entities", []), source_uri=para_uri)
            de = upsert_edges(proposal.get("relations", []), source_uri=para_uri, entity_labels=entity_labels)
            n_nodes += dn
            n_edges += de
        except Exception as e:  # noqa: BLE001 — keep replaying the rest
            err = str(e)[:300]
            failures.append({"i": i, "uri": para_uri, "error": err})
        refreshed = bool(refresh_every) and (i % refresh_every == 0)
        if refreshed:
            apply_graph()  # snapshot current tables into the live graph
        if progress:
            ev = {"nodes": dn, "edges": de, "graph_refreshed": refreshed}
            if err:
                ev["error"] = err
            progress(i, total, para_uri, ev)
    apply_graph()
    return {"status": "replayed", "paragraphs": total, "nodes": n_nodes,
            "edges": n_edges, "failures": len(failures), "failed": failures,
            "source": str(src)}
