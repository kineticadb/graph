#!/usr/bin/env python3
"""Count nodes by label in a FalkorDB graph.

Reuses the loader's FalkorDBSink (connection + .env creds) and safe_ident
(so the label can't inject Cypher, since labels can't be parameterized).

Usage:
    .venv/bin/python count-nodes.py                    # every label, with counts
    .venv/bin/python count-nodes.py bank               # just the 'bank' label
    .venv/bin/python count-nodes.py --graph banking_graph party
"""
import argparse
import os

from dotenv import load_dotenv

from graph_loader.falkordb_sink import FalkorDBSink
from graph_loader.mapper import safe_ident


def count_for_label(sink, label: str) -> int:
    # Labels can't be Cypher parameters, so validate before interpolating.
    lbl = safe_ident(label)
    result = sink.run(f"MATCH (n:{lbl}) RETURN count(n) AS c")
    return int(result.result_set[0][0])


def list_labels(sink) -> list:
    result = sink.run("CALL db.labels()")
    return [row[0] for row in result.result_set]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Count nodes by label in a FalkorDB graph")
    parser.add_argument("label", nargs="?",
                        help="Label to count; omit to list all labels with counts")
    parser.add_argument("--graph", default="banking_graph",
                        help="Target graph (default: banking_graph)")
    args = parser.parse_args(argv)

    load_dotenv()
    sink = FalkorDBSink.connect(
        args.graph,
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", "6379")),
        password=os.environ.get("FALKORDB_PASSWORD"),
    )

    if args.label:
        print(f"{args.label}: {count_for_label(sink, args.label)}")
        return

    # Every node also carries the shared :Entity label; report the specific
    # labels as the breakdown and :Entity as the grand total.
    labels = [l for l in list_labels(sink) if l != "Entity"]
    rows = sorted(((l, count_for_label(sink, l)) for l in labels),
                  key=lambda r: r[1], reverse=True)
    width = max((len(l) for l, _ in rows), default=5)
    for label, count in rows:
        print(f"{label:<{width}}  {count}")
    total = count_for_label(sink, "Entity")
    print(f"{'-' * width}  {'-' * 6}")
    print(f"{'TOTAL':<{width}}  {total}")


if __name__ == "__main__":
    main()
