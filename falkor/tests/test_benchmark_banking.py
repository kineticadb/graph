"""Benchmark: the loaded FalkorDB `banking_graph` must reproduce Kinetica's
own graph-query result for a known bank.

Ground truth captured from Kinetica running the equivalent GQL query against
`expero.banking_graph` (see the reference explorer project's
tests/test_banking_query.py): 65 result paths for bank
d8d3cb99-0e3b-45b4-8221-79e8425065f3 ("Effertz, Ernser and Schmeler"),
traversing bank -[performed]-> wire_message -[is_for_transaction]-> banking_transaction.

This is a LIVE benchmark: it queries the persistent `banking_graph` produced by
`build-graph.py`. It SKIPs (does not fail) if FalkorDB is unreachable or the
graph has not been loaded yet.
"""
import os

import pytest

from graph_loader.falkordb_sink import FalkorDBSink

BANK_ID = "d8d3cb99-0e3b-45b4-8221-79e8425065f3"
EXPECTED_RECORD_COUNT = 65
EXPECTED_BANK_NAME = "Effertz, Ernser and Schmeler"

# A few exact (wire, transaction, amount, risk) rows confirmed against the
# Kinetica result, used as spot-checks that values map through correctly.
EXPECTED_SPOT_CHECK_ROWS = {
    ("73ce2930-edd6-4d38-bae8-552344cc0a0d",
     "76d6fb36-f425-49ed-9d97-7b9068d63d68", 4441980.78, 0.0),
    ("70a20b54-2726-4de5-b824-907242de00db",
     "f5649af2-7c32-43ec-930d-b3bf239b37f5", 9325618.68, 13.0),
}

BENCHMARK_QUERY = """
MATCH (a:bank)-[ab:performed]->(b:wire_message)-[bc:is_for_transaction]->(c:banking_transaction)
WHERE a.NODE = $bank_id
RETURN a.bank_name AS bank, b.NODE AS wire, ab.LABEL AS ablabel,
       c.NODE AS transaction, c.banking_transaction_amount AS amount,
       b.wire_message_risk_score AS risk
"""


@pytest.fixture
def banking_graph():
    try:
        sink = FalkorDBSink.connect(
            "banking_graph",
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            password=os.environ.get("FALKORDB_PASSWORD"),
        )
        # Confirm the graph is actually loaded (has bank nodes).
        loaded = sink.run("MATCH (a:bank) RETURN count(a) AS n").result_set[0][0]
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"FalkorDB not reachable: {exc}")
    if not loaded:
        pytest.skip("banking_graph not loaded — run `build-graph.py` first")
    return sink


def test_benchmark_bank_matches_kinetica_ground_truth(banking_graph):
    rows = banking_graph.run(BENCHMARK_QUERY, {"bank_id": BANK_ID}).result_set

    # 1. Same number of paths Kinetica returns.
    assert len(rows) == EXPECTED_RECORD_COUNT

    # 2. Single source bank with the expected name; every hop-1 edge is 'performed'.
    assert {r[0] for r in rows} == {EXPECTED_BANK_NAME}
    assert {r[2] for r in rows} == {"performed"}

    # 3. Known rows carry through with the correct amount/risk values.
    got = {(r[1], r[3], r[4], r[5]) for r in rows}
    missing = EXPECTED_SPOT_CHECK_ROWS - got
    assert not missing, f"expected benchmark rows absent from result: {missing}"


# A longer path with per-hop filters -- Kinetica's inline node WHEREs
# (a.NODE = ... and b.wire_message_risk_score > 20) become one AND-joined
# WHERE after the MATCH; the reversed edge (e)<-[:manages]-(g) is kept.
# Ground truth from Kinetica: exactly 8 paths.
FILTERED_PATH_QUERY = """
MATCH (a:bank)-[ab:performed]->(b:wire_message)-[bc:is_for_transaction]->(c:banking_transaction)-[d:involved]->(e:internal_account)<-[f:manages]-(g:party)
WHERE a.NODE = $bank_id
  AND b.wire_message_risk_score > 20
RETURN g.party_name AS person, g.party_risk_score AS risk_score,
       c.banking_transaction_amount AS amount
"""

EXPECTED_FILTERED_ROWS = {
    ("Efren Swift", 3.0, 1989924.99),
    ("Luna Steuber", 57.0, 2062232.75),
    ("Nathen O'Connell", 2.0, 2062232.75),
    ("Liliane Goldner", 11.0, 4083859.79),
    ("Kaleigh Mertz", 10.0, 2700866.69),
    ("Cooper Gibson", 0.0, 3412509.13),
    ("Megane Jaskolski", 13.0, 1989924.99),
    ("Dolly Fisher", 18.0, 2062232.75),
}


def test_benchmark_multihop_with_per_hop_filters(banking_graph):
    rows = banking_graph.run(FILTERED_PATH_QUERY, {"bank_id": BANK_ID}).result_set

    # Kinetica returns exactly 8 paths for this filtered traversal.
    assert len(rows) == 8

    # Order is not guaranteed, so compare as a set of (person, risk, amount).
    got = {(r[0], r[1], r[2]) for r in rows}
    assert got == EXPECTED_FILTERED_ROWS


# OLAP-on-graph aggregation. Kinetica wraps the MATCH in graph_table(...) then
# runs SQL: `SELECT wire, risk, ROUND(SUM(amount),0) ... GROUP BY 1,2 ORDER BY 3 DESC`.
# In Cypher the non-aggregated RETURN keys (wire, risk) ARE the grouping keys,
# round(sum(...)) is the total, and ORDER BY total DESC gives the ordering.
# Ground truth from Kinetica for bank_name 'Harvey Group': 18 rows.
WIRE_TOTALS_QUERY = """
MATCH (a:bank)-[ab:performed]->(b:wire_message)-[bc:is_for_transaction]->(c:banking_transaction)
WHERE a.bank_name = $bank_name
RETURN b.NODE AS wire, b.wire_message_risk_score AS risk,
       round(sum(c.banking_transaction_amount)) AS total
ORDER BY total DESC
"""

# (wire, risk, total) in exact descending-total order. Totals are all distinct,
# so the ordering is deterministic and can be asserted as an ordered list.
EXPECTED_WIRE_TOTALS = [
    ("e4d0386d-d836-4fc9-9308-a31de08a7c69", 24, 27339261),
    ("e1e7ff92-c615-42f5-b88b-a2d3dc5182f9", 21, 23228582),
    ("38d66907-1628-44df-8d0e-af60cb103de1", 17, 17273365),
    ("34a97335-04c7-4975-87e3-e2609f0955b1", 9, 16936853),
    ("4c2eee79-0847-4f19-be64-be3d77a11429", 5, 16674891),
    ("83dedfe2-252e-49a0-a5c5-693c0dfdb225", 25, 13004956),
    ("3842bd7d-8302-430f-8c49-fcdbf0665d5f", 2, 12919707),
    ("7c8a0629-c86a-4edc-b63f-4e2363d06c2c", 48, 11480990),
    ("30515c4a-4b62-4267-b9cb-33b60dd5ca9d", 19, 8185300),
    ("a0ae1af9-eb44-42be-b934-fcb99fe84cde", 15, 8155358),
    ("46f17164-6190-4199-bc62-b0ec68784b62", 57, 7714730),
    ("aa52bea4-1153-4eb8-b351-00ef182d81fa", 2, 7287303),
    ("cb4b59c9-eaba-478d-9989-c9fb9224404b", 13, 6179321),
    ("45a79b0e-bb1d-41a2-b65f-b2e725895e95", 27, 6000639),
    ("5fb4b8b1-5ebc-44d4-8e1d-ea8acad8c500", 0, 5978403),
    ("2e342d09-b39c-4774-b17a-f23f0058f265", 18, 5302872),
    ("fdc56d78-770d-4019-ba23-3d042e2c1615", 18, 3867234),
    ("c2ede6d6-cd1c-47f0-aab7-e73ecd2e936a", 34, 2548708),
]


def test_benchmark_wire_totals_aggregation(banking_graph):
    rows = banking_graph.run(WIRE_TOTALS_QUERY, {"bank_name": "Harvey Group"}).result_set

    # Kinetica returns exactly 18 grouped rows.
    assert len(rows) == 18

    # Ordered-by-total-desc, so assert the exact ordered list. Normalize the
    # numeric columns to int (Cypher risk/round(sum) come back as floats;
    # ROUND(...,0) in Kinetica shows as whole numbers).
    normalized = [(r[0], int(r[1]), int(r[2])) for r in rows]
    assert normalized == EXPECTED_WIRE_TOTALS
