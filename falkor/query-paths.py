#!/usr/bin/env python3
"""Trace the parties behind a bank's wire-transfer transactions in FalkorDB.

Path traversed:
    (a:bank)-[:performed]->(b:wire_message)-[:is_for_transaction]->
    (c:banking_transaction)-[:involved]->(e:internal_account)<-[:manages]-(g:party)

Both the starting bank id and the wire-risk threshold are passed as query
PARAMETERS (never interpolated), so this is safe to run with arbitrary input.

Usage:
    .venv/bin/python query-paths.py <bank_node_id>
    .venv/bin/python query-paths.py <bank_node_id> --min-risk 20
    .venv/bin/python query-paths.py <bank_node_id> --min-risk 20 --graph banking_graph
"""
import argparse
import os

from dotenv import load_dotenv

from graph_loader.falkordb_sink import FalkorDBSink

# Per-hop constraints from a Kinetica-style query collapse into one WHERE
# after the MATCH; the reversed edge (e)<-[:manages]-(g) is kept as-is.
QUERY = """
MATCH (a:bank)-[ab:performed]->(b:wire_message)
      -[bc:is_for_transaction]->(c:banking_transaction)
      -[d:involved]->(e:internal_account)<-[f:manages]-(g:party)
WHERE a.NODE = $bank_id
  AND b.wire_message_risk_score > $min_risk
RETURN g.party_name AS person, g.party_risk_score AS risk_score,
       c.banking_transaction_amount AS amount
ORDER BY person
"""


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Trace parties behind a bank's wire-transfer transactions")
    parser.add_argument("bank_id", help="starting bank NODE id")
    parser.add_argument("--min-risk", type=float, default=-1.0,
                        help="only wire_messages with risk_score strictly greater "
                             "than this (default: -1, i.e. include all)")
    parser.add_argument("--graph", default="banking_graph",
                        help="target graph (default: banking_graph)")
    args = parser.parse_args(argv)

    load_dotenv()
    sink = FalkorDBSink.connect(
        args.graph,
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", "6379")),
        password=os.environ.get("FALKORDB_PASSWORD"),
    )

    rows = sink.run(QUERY, {"bank_id": args.bank_id,
                            "min_risk": args.min_risk}).result_set

    print(f"{len(rows)} path(s) for bank {args.bank_id} "
          f"(wire risk > {args.min_risk}):\n")
    if rows:
        width = max(len(str(r[0])) for r in rows)
        print(f"{'person':<{width}}  {'risk':>5}  amount")
        print(f"{'-' * width}  {'-' * 5}  {'-' * 12}")
        for person, risk, amount in rows:
            print(f"{person:<{width}}  {risk:>5}  {amount}")


if __name__ == "__main__":
    main()
