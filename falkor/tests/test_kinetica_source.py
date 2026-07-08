from graph_loader.kinetica_source import KineticaSource


class _Resp:
    """Mimics the decoded Kinetica response: `.records` is a row-major list,
    and `has_more_records` is read via item access (a response key)."""

    def __init__(self, records, has_more_records):
        self.records = records
        self._data = {"has_more_records": has_more_records}

    def __getitem__(self, key):
        return self._data[key]


class _FakeDB:
    """Fake GPUdb client that serves canned pages from execute_sql_and_decode,
    keyed off the offset/limit kwargs the real Kinetica API uses for paging.
    """

    def __init__(self, pages):
        # pages: list of (records, has_more_records) tuples, consumed in
        # call order -- one per expected execute_sql_and_decode call.
        self._pages = list(pages)
        self.calls = []

    def execute_sql_and_decode(self, sql, **kwargs):
        self.calls.append((sql, kwargs))
        records, has_more_records = self._pages.pop(0)
        return _Resp(records, has_more_records)


def _row(n):
    return {"node_id": f"b{n}", "label": "bank"}


def test_rows_yields_plain_dicts_single_page():
    fake = _FakeDB([([_row(1)], False)])
    src = KineticaSource(fake, page_size=10000)
    out = list(src.rows("SELECT ..."))
    assert out == [{"node_id": "b1", "label": "bank"}]
    assert fake.calls[0][0] == "SELECT ..."
    assert fake.calls[0][1] == {"offset": 0, "limit": 10000, "get_column_major": False}


def test_rows_pages_through_full_result_set():
    # 3 rows total, page_size=2 -> page [2 rows, has_more=True] then
    # [1 row, has_more=False]. Must yield all 3 rows in order, as plain
    # dicts, without silently stopping after the first page.
    rows = [_row(1), _row(2), _row(3)]
    fake = _FakeDB([(rows[0:2], True), (rows[2:3], False)])
    src = KineticaSource(fake, page_size=2)
    out = list(src.rows("SELECT ..."))

    assert out == rows
    assert all(isinstance(r, dict) for r in out)
    assert len(fake.calls) == 2
    assert fake.calls[0][1] == {"offset": 0, "limit": 2, "get_column_major": False}
    assert fake.calls[1][1] == {"offset": 2, "limit": 2, "get_column_major": False}


def test_rows_termination_driven_by_has_more_not_page_length():
    # Regression guard: a FULL page (len == page_size) with has_more=False
    # must terminate; and we must NOT stop merely because a page is "short"
    # (that would truncate when the server cap is below our page_size).
    rows = [_row(1), _row(2), _row(3), _row(4)]
    fake = _FakeDB([(rows[0:2], True), (rows[2:4], False)])
    src = KineticaSource(fake, page_size=2)
    out = list(src.rows("SELECT ..."))
    assert out == rows
    assert len(fake.calls) == 2  # stopped on has_more=False, not on short page


def test_rows_stops_on_empty_page_even_if_has_more_true():
    # Infinite-loop guard: an empty page ends iteration even if the server
    # (incorrectly) still reports has_more_records=True.
    fake = _FakeDB([([_row(1), _row(2)], True), ([], True)])
    src = KineticaSource(fake, page_size=2)
    out = list(src.rows("SELECT ..."))
    assert out == [_row(1), _row(2)]
    assert len(fake.calls) == 2
