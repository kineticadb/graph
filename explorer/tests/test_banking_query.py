#!/usr/bin/env python3
"""
Smoke tests for the Kinetica Graph Explorer banking use case.

Requires a running Kinetica instance at http://127.0.0.1:9191 with the
expero.banking_graph loaded.

Usage:
    python tests/test_banking_query.py          # run against live server
    python tests/test_banking_query.py --offline # run only fixture-based tests
"""

import json
import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_URL = "http://127.0.0.1:9191"
CREDENTIALS = {"user": "admin", "pass": "***REMOVED***"}
GRAPH_NAME = "expero.banking_graph"

GQL_QUERY = (
    "GRAPH expero.banking_graph "
    "MATCH (a:bank WHERE (a.NODE ='d8d3cb99-0e3b-45b4-8221-79e8425065f3')) "
    "-[ab:performed]-> (b:wire_message) "
    "- [bc:is_for_transaction] -> (c:banking_transaction) "
    "RETURN a.bank_name as bank, b.NODE as wire, ab.LABEL as ablabel, "
    "c.NODE as transaction, c.banking_transaction_amount, b.wire_message_risk_score"
)

EXPECTED_RECORD_COUNT = 65
EXPECTED_HOP_COUNT = 2
EXPECTED_COLUMN_HEADERS_HOP1 = [
    "QUERY_EDGE_ID_HOP_1", "NODE1_HOP_1", "NODE2_HOP_1",
    "PATH_ID_HOP_1", "RING_ID_HOP_1",
    "NODE1_LABELS_HOP_1", "NODE2_LABELS_HOP_1", "EDGE_LABELS_HOP_1",
]
EXPECTED_NODE_LABELS = {"bank", "wire_message", "banking_transaction"}
EXPECTED_EDGE_LABELS = {"performed", "is_for_transaction"}


# --------------- helpers ---------------

def load_fixture(filename):
    with open(os.path.join(TESTS_DIR, filename)) as f:
        return json.load(f)


def parse_data_str(response):
    """Unwrap the double-wrapped data_str from a Kinetica response."""
    ds = response.get("data_str")
    if isinstance(ds, str):
        return json.loads(ds)
    if isinstance(ds, dict):
        return ds
    return response


def parse_gql_result(inner):
    """Extract gql_result from the unwrapped response."""
    info = inner.get("info", {})
    raw = info.get("gql_result")
    if raw:
        return json.loads(raw) if isinstance(raw, str) else raw
    return None


def request_kinetica(endpoint, body):
    """Make a POST request to Kinetica. Returns parsed JSON."""
    import urllib.request
    import base64
    headers = {"Content-Type": "application/json"}
    if CREDENTIALS["user"] or CREDENTIALS["pass"]:
        cred = base64.b64encode(
            (CREDENTIALS["user"] + ":" + CREDENTIALS["pass"]).encode()
        ).decode()
        headers["Authorization"] = "Basic " + cred
    req = urllib.request.Request(
        SERVER_URL + endpoint,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def server_available():
    try:
        import urllib.request
        urllib.request.urlopen(SERVER_URL, timeout=3)
    except Exception:
        return False
    return True


# --------------- fixture tests (always run) ---------------

class TestFixtureParsing(unittest.TestCase):
    """Tests that run against saved fixture files — no server needed."""

    @classmethod
    def setUpClass(cls):
        cls.response = load_fixture("banking_query_response.json")
        cls.inner = parse_data_str(cls.response)
        cls.gql = parse_gql_result(cls.inner)

    def test_data_str_unwrap(self):
        """data_str should parse into a dict with expected keys."""
        self.assertIsInstance(self.inner, dict)
        self.assertIn("info", self.inner)
        self.assertIn("response_schema_str", self.inner)

    def test_record_count(self):
        """info.count should equal expected record count."""
        count = int(self.inner["info"]["count"])
        self.assertEqual(count, EXPECTED_RECORD_COUNT)

    def test_gql_result_structure(self):
        """gql_result should be a dict with column_headers, column_datatypes, and column_N arrays."""
        self.assertIsInstance(self.gql, dict)
        self.assertIn("column_headers", self.gql)
        self.assertIn("column_datatypes", self.gql)
        headers = self.gql["column_headers"]
        self.assertIsInstance(headers, list)
        self.assertGreater(len(headers), 0)
        # Each header should have a corresponding column_N
        for i in range(1, len(headers) + 1):
            key = "column_" + str(i)
            self.assertIn(key, self.gql, f"Missing {key}")
            self.assertIsInstance(self.gql[key], list)
            self.assertEqual(len(self.gql[key]), EXPECTED_RECORD_COUNT)

    def test_hop_detection(self):
        """Should detect exactly 2 hops from column headers."""
        headers = self.gql["column_headers"]
        hops = set()
        for h in headers:
            if "_HOP_" in h:
                hops.add(int(h.split("_HOP_")[1]))
        self.assertEqual(hops, set(range(1, EXPECTED_HOP_COUNT + 1)))

    def test_hop1_columns_present(self):
        """All expected HOP_1 columns should be present."""
        headers = self.gql["column_headers"]
        for col in EXPECTED_COLUMN_HEADERS_HOP1:
            self.assertIn(col, headers)

    def test_node_labels_in_results(self):
        """Node labels in the results should match expected labels."""
        headers = self.gql["column_headers"]
        found_labels = set()
        for h in headers:
            if h.startswith("NODE") and "LABELS" in h:
                col_idx = headers.index(h)
                col_key = "column_" + str(col_idx + 1)
                for val in self.gql[col_key]:
                    if val:
                        labels = json.loads(val) if isinstance(val, str) and val.startswith("[") else [val]
                        found_labels.update(labels)
        self.assertEqual(found_labels, EXPECTED_NODE_LABELS)

    def test_edge_labels_in_results(self):
        """Edge labels in the results should match expected labels."""
        headers = self.gql["column_headers"]
        found_labels = set()
        for h in headers:
            if "EDGE_LABELS" in h:
                col_idx = headers.index(h)
                col_key = "column_" + str(col_idx + 1)
                for val in self.gql[col_key]:
                    if val:
                        labels = json.loads(val) if isinstance(val, str) and val.startswith("[") else [val]
                        found_labels.update(labels)
        self.assertEqual(found_labels, EXPECTED_EDGE_LABELS)

    def test_source_node_consistent(self):
        """NODE1_HOP_1 should be the same source node for all rows (single WHERE clause)."""
        headers = self.gql["column_headers"]
        idx = headers.index("NODE1_HOP_1")
        col = self.gql["column_" + str(idx + 1)]
        unique = set(col)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique.pop(), "d8d3cb99-0e3b-45b4-8221-79e8425065f3")

    def test_path_continuity(self):
        """NODE2_HOP_1 should equal NODE1_HOP_2 for each row (path continuity)."""
        headers = self.gql["column_headers"]
        n2h1_idx = headers.index("NODE2_HOP_1")
        n1h2_idx = headers.index("NODE1_HOP_2")
        n2h1 = self.gql["column_" + str(n2h1_idx + 1)]
        n1h2 = self.gql["column_" + str(n1h2_idx + 1)]
        for i in range(EXPECTED_RECORD_COUNT):
            self.assertEqual(n2h1[i], n1h2[i], f"Path break at row {i}")

    def test_show_graph_fixture(self):
        """show/graph fixture should contain label info for the banking graph."""
        resp = load_fixture("banking_show_graph_response.json")
        ds = resp.get("data_str")
        inner = json.loads(ds) if isinstance(ds, str) else ds
        self.assertIn("info", inner)


# --------------- session fixture tests (always run) ---------------

SESSION_FILE = "expero_banking_graph_session.json"

class TestSessionFixture(unittest.TestCase):
    """Tests that validate the session file structure and content."""

    @classmethod
    def setUpClass(cls):
        cls.session = load_fixture(SESSION_FILE)

    def test_session_version(self):
        """Session file should have version 1."""
        self.assertEqual(self.session["version"], 1)

    def test_session_has_required_keys(self):
        """Session should have all required top-level keys."""
        for key in ["version", "savedAt", "connection", "graph"]:
            self.assertIn(key, self.session)

    def test_session_savedAt_is_iso8601(self):
        """savedAt should be a valid ISO 8601 timestamp."""
        from datetime import datetime
        ts = self.session["savedAt"]
        # Should parse without error
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_session_connection(self):
        """Connection should have url and user, no password."""
        conn = self.session["connection"]
        self.assertIn("url", conn)
        self.assertIn("user", conn)
        self.assertNotIn("pass", conn)
        self.assertTrue(conn["url"].startswith("http"))

    def test_session_graph_name(self):
        """Graph name should be the banking graph."""
        self.assertEqual(self.session["graph"]["name"], GRAPH_NAME)

    def test_session_graph_labels(self):
        """Graph should have selectedNodeLabels and selectedEdgeLabels arrays."""
        graph = self.session["graph"]
        self.assertIsInstance(graph.get("selectedNodeLabels", []), list)
        self.assertIsInstance(graph.get("selectedEdgeLabels", []), list)

    def test_session_ontology_dot(self):
        """ontologyDot should be a valid DOT string if present."""
        dot = self.session["graph"].get("ontologyDot")
        if dot is not None:
            self.assertIsInstance(dot, str)
            self.assertIn("digraph", dot)
            self.assertIn("->", dot)

    def test_session_data_fetched_flag(self):
        """dataFetched flag should be a boolean."""
        graph = self.session["graph"]
        if "dataFetched" in graph:
            self.assertIsInstance(graph["dataFetched"], bool)

    def test_session_show_force_graph_flag(self):
        """showForceGraph flag should be a boolean."""
        graph = self.session["graph"]
        if "showForceGraph" in graph:
            self.assertIsInstance(graph["showForceGraph"], bool)

    def test_session_queries_structure(self):
        """Queries should be an array of objects with sql and activeTab."""
        queries = self.session.get("queries", [])
        self.assertIsInstance(queries, list)
        for q in queries:
            self.assertIn("sql", q)
            self.assertIsInstance(q["sql"], str)
            self.assertGreater(len(q["sql"].strip()), 0)
            if "activeTab" in q:
                self.assertIn(q["activeTab"], [None, "results", "graph"])

    def test_session_queries_are_valid_gql(self):
        """Each query should contain GRAPH and MATCH keywords (GQL pattern)."""
        queries = self.session.get("queries", [])
        for i, q in enumerate(queries):
            sql_upper = q["sql"].upper()
            self.assertIn("GRAPH", sql_upper, f"Query {i} missing GRAPH keyword")
            self.assertIn("MATCH", sql_upper, f"Query {i} missing MATCH keyword")

    def test_session_queries_reference_correct_graph(self):
        """Each query should reference the session's graph name."""
        graph_name = self.session["graph"]["name"]
        queries = self.session.get("queries", [])
        for i, q in enumerate(queries):
            self.assertIn(graph_name, q["sql"], f"Query {i} does not reference {graph_name}")

    def test_session_schema_validation(self):
        """Session should conform to the session_schema.json structure."""
        schema = load_fixture("session_schema.json")
        # Validate required fields from schema
        for prop in schema.get("required", []):
            self.assertIn(prop, self.session, f"Missing required field: {prop}")
        # Validate connection required fields
        conn_required = schema["properties"]["connection"].get("required", [])
        for prop in conn_required:
            self.assertIn(prop, self.session["connection"], f"Missing connection field: {prop}")
        # Validate graph required fields
        graph_required = schema["properties"]["graph"].get("required", [])
        for prop in graph_required:
            self.assertIn(prop, self.session["graph"], f"Missing graph field: {prop}")


# --------------- session live server tests ---------------

class TestSessionLiveRestore(unittest.TestCase):
    """Tests that simulate restoring a session against a live server."""

    @classmethod
    def setUpClass(cls):
        if not server_available():
            raise unittest.SkipTest("Kinetica server not available at " + SERVER_URL)
        cls.session = load_fixture(SESSION_FILE)

    def test_session_connection_reachable(self):
        """Session's server URL should be reachable."""
        import urllib.request
        try:
            urllib.request.urlopen(self.session["connection"]["url"], timeout=5)
        except Exception as e:
            self.fail(f"Cannot reach session server: {e}")

    def test_session_graph_exists(self):
        """Session's graph should exist on the server."""
        resp = request_kinetica("/show/graph", {
            "graph_name": self.session["graph"]["name"], "options": {},
        })
        inner = parse_data_str(resp)
        info = inner.get("info", {})
        self.assertIn("labeljson", info)

    def test_session_queries_execute(self):
        """Each query in the session should execute successfully and return results."""
        queries = self.session.get("queries", [])
        self.assertGreater(len(queries), 0, "No queries in session to test")
        for i, q in enumerate(queries):
            resp = request_kinetica("/execute/sql", {
                "statement": q["sql"],
                "offset": 0, "limit": 10000, "encoding": "json",
            })
            inner = parse_data_str(resp)
            info = inner.get("info", {})
            count = int(info.get("count", "0"))
            self.assertGreater(count, 0, f"Query {i} returned 0 records")
            # Verify gql_result has hop structure for visualization
            gql = parse_gql_result(inner)
            self.assertIsNotNone(gql, f"Query {i} missing gql_result")
            headers = gql.get("column_headers", [])
            has_hops = any("_HOP_" in h for h in headers)
            self.assertTrue(has_hops, f"Query {i} has no hop columns for visualization")

    def test_session_selected_labels_valid(self):
        """Selected labels in the session should exist in the graph's label set."""
        resp = request_kinetica("/show/graph", {
            "graph_name": self.session["graph"]["name"], "options": {},
        })
        inner = parse_data_str(resp)
        labeljson = json.loads(inner["info"]["labeljson"])
        all_node_labels = set()
        for item in labeljson.get("node_labels", []):
            all_node_labels.update(item.get("labels", []))
        all_edge_labels = set()
        for item in labeljson.get("edge_labels", []):
            all_edge_labels.update(item.get("labels", []))

        for label in self.session["graph"].get("selectedNodeLabels", []):
            self.assertIn(label, all_node_labels, f"Node label '{label}' not found in graph")
        for label in self.session["graph"].get("selectedEdgeLabels", []):
            self.assertIn(label, all_edge_labels, f"Edge label '{label}' not found in graph")


# --------------- live server tests ---------------

class TestLiveServer(unittest.TestCase):
    """Tests that require a running Kinetica server."""

    @classmethod
    def setUpClass(cls):
        if not server_available():
            raise unittest.SkipTest("Kinetica server not available at " + SERVER_URL)

    def test_execute_sql_query(self):
        """Execute the banking GQL query and verify record count."""
        resp = request_kinetica("/execute/sql", {
            "statement": GQL_QUERY,
            "offset": 0, "limit": 10000, "encoding": "json",
        })
        inner = parse_data_str(resp)
        count = int(inner["info"]["count"])
        self.assertEqual(count, EXPECTED_RECORD_COUNT)

    def test_show_graph(self):
        """show/graph should return label data for the banking graph."""
        resp = request_kinetica("/show/graph", {
            "graph_name": GRAPH_NAME, "options": {},
        })
        inner = parse_data_str(resp)
        info = inner.get("info", {})
        self.assertIn("labeljson", info)
        labeljson = json.loads(info["labeljson"])
        self.assertIn("node_labels", labeljson)
        self.assertIn("edge_labels", labeljson)
        self.assertGreater(len(labeljson["node_labels"]), 0)

    def test_gql_result_matches_fixture(self):
        """Live gql_result column_headers should match the saved fixture."""
        resp = request_kinetica("/execute/sql", {
            "statement": GQL_QUERY,
            "offset": 0, "limit": 10000, "encoding": "json",
        })
        inner = parse_data_str(resp)
        gql = parse_gql_result(inner)
        fixture = load_fixture("banking_query_response.json")
        fixture_inner = parse_data_str(fixture)
        fixture_gql = parse_gql_result(fixture_inner)
        self.assertEqual(gql["column_headers"], fixture_gql["column_headers"])
        self.assertEqual(gql["column_datatypes"], fixture_gql["column_datatypes"])


if __name__ == "__main__":
    offline = "--offline" in sys.argv
    if offline:
        sys.argv.remove("--offline")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestFixtureParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestSessionFixture))
    if not offline:
        suite.addTests(loader.loadTestsFromTestCase(TestLiveServer))
        suite.addTests(loader.loadTestsFromTestCase(TestSessionLiveRestore))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
