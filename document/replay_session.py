#!/usr/bin/env python3
"""Replay a Kinetica Graph Explorer session JSON offline: run every query against
Kinetica and emit frozen artifacts — ontology PNG + per-query network PNG when
the result has a graph shape. Per-query tabular results come from the Explorer
screenshots (see screenshot_session.py), not from this script.

Usage:
    python3 replay_session.py <session.json> [-o out_dir]

Requires the venv (gpudb, matplotlib, networkx, graphviz) and the Kinetica
credentials from .env (same as generate_usecase_images.py).
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CLI = "/home/kkaramete/.claude/plugins/cache/kinetica-skills/kineticadb/1.0.27/skills/kinetica-execute/scripts/kinetica-cli.py"


def run_query(sql: str, timeout_ms: int = 120000) -> dict:
    env = {**os.environ, "KINETICA_DB_SKILL_TIMEOUT": str(timeout_ms)}
    r = subprocess.run(
        ["python3", CLI, "query", sql],
        capture_output=True, text=True, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:500])
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"non-JSON CLI output: {e}: {r.stdout[:200]}")


def render_ontology(dot: str, out_png: Path) -> None:
    try:
        import graphviz
    except ImportError:
        r = subprocess.run(
            ["dot", "-Tpng", "-o", str(out_png)],
            input=dot, text=True, capture_output=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"dot failed: {r.stderr.strip()}")
        return
    src = graphviz.Source(dot, format="png")
    tmp = out_png.with_suffix("")
    src.render(filename=tmp.name, directory=str(out_png.parent), cleanup=True)
    produced = out_png.parent / f"{tmp.name}.png"
    if produced != out_png:
        produced.replace(out_png)


def detect_node_columns(cols: list[str]) -> list[str]:
    """Pick columns that look like node identifiers, preserving order.
    Heuristic: columns ending in `_node`, or starting with `NODE1_`/`NODE2_`,
    or named exactly `node`/`source`/`target`.
    """
    low = [c.lower() for c in cols]
    picked = [c for c, l in zip(cols, low)
              if l.endswith("_node") or l in ("node", "source", "target")
              or l.startswith("node1_") or l.startswith("node2_")]
    return picked


def render_graph(records: list[dict], out_png: Path, title: str) -> bool:
    if not records:
        return False
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    cols = list(records[0].keys())
    node_cols = detect_node_columns(cols)
    if len(node_cols) < 2:
        return False

    G = nx.DiGraph()
    for r in records:
        for a, b in zip(node_cols, node_cols[1:]):
            u, v = r.get(a), r.get(b)
            if u in (None, "") or v in (None, ""):
                continue
            G.add_edge(str(u), str(v))

    if G.number_of_edges() == 0:
        return False
    if G.number_of_nodes() > 400:
        print(f"  (graph too large: {G.number_of_nodes()} nodes — PNG skipped)")
        return False

    fig, ax = plt.subplots(figsize=(12, 8))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    pos = nx.spring_layout(G, seed=42, k=2.0 / max(1, G.number_of_nodes() ** 0.5))
    nx.draw_networkx_nodes(G, pos, node_color="#58a6ff", node_size=350, alpha=0.85, ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#8b949e", arrows=True, arrowsize=8, alpha=0.45, ax=ax)
    if G.number_of_nodes() <= 60:
        nx.draw_networkx_labels(G, pos, font_size=7, font_color="white", ax=ax)
    ax.set_title(f"{title} ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)",
                 color="white", fontsize=12, pad=10)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches="tight", facecolor="#0d1117")
    plt.close()
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", type=Path, help="Path to session .json")
    ap.add_argument("-o", "--out", type=Path, default=Path("out"))
    ap.add_argument("--timeout", type=int, default=120000, help="Query timeout in ms")
    args = ap.parse_args()

    session = json.loads(args.session.read_text())
    graph_name = (session.get("graph") or {}).get("name") or "session"
    safe = graph_name.replace(".", "_").replace("/", "_")
    out = args.out / safe
    out.mkdir(parents=True, exist_ok=True)
    print(f"Replaying session for graph: {graph_name}  →  {out}/")

    dot = (session.get("graph") or {}).get("ontologyDot")
    if dot:
        try:
            render_ontology(dot, out / "ontology.png")
            print(f"  ontology  → {out/'ontology.png'}")
        except Exception as e:
            print(f"  ontology skipped: {e}")

    queries = session.get("queries") or []
    for i, q in enumerate(queries):
        sql = (q.get("sql") or "").strip()
        if not sql:
            continue
        print(f"Query {i}:")
        try:
            res = run_query(sql, timeout_ms=args.timeout)
        except Exception as e:
            print(f"  ERROR: {e}")
            (out / f"query_{i}.error.txt").write_text(str(e))
            continue
        records = res.get("records") or []
        print(f"  {len(records):>6} rows")

        png_path = out / f"query_{i}.networkx.png"
        try:
            if render_graph(records, png_path, title=f"Query {i} — {graph_name}"):
                print(f"  networkx  → {png_path}")
        except Exception as e:
            print(f"  png skipped: {e}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
