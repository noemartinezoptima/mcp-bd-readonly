from decimal import Decimal
from types import SimpleNamespace

import pytest

from mcp_bd_readonly.db import QueryExecutor, _convert, _retryable
from mcp_bd_readonly.security import ReadOnlyViolation


def make_executor():
    return QueryExecutor(
        SimpleNamespace(
            host="127.0.0.1", port=13306, user="u", password="p", db="d",
        )
    )


class FakeCursor:
    def __init__(self, rows, cols=None):
        self.rows = rows
        self.description = [(c,) for c in cols] if cols is not None else None
        self.executed = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed = sql
        self.params = params

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cursor


def test_run_returns_cols_and_rows(monkeypatch):
    ex = make_executor()
    cur = FakeCursor(
        [{"id": 1, "total_euros": Decimal("10.50")}], ["id", "total_euros"]
    )
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    cols, rows = ex.run("SELECT id, total_euros FROM t")
    assert cols == ["id", "total_euros"]
    assert rows == [{"id": 1, "total_euros": Decimal("10.50")}]


def test_run_appends_limit(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([{"a": 1}], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SELECT a FROM t")
    assert cur.executed == "SELECT a FROM t LIMIT 100"


def test_run_appends_custom_limit(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SELECT a FROM t", limit=5)
    assert cur.executed == "SELECT a FROM t LIMIT 5"


def test_run_keeps_existing_limit(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SELECT a FROM t LIMIT 3")
    assert cur.executed == "SELECT a FROM t LIMIT 3"


def test_run_parametrized(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SELECT a FROM t WHERE id=%s AND n=%s", [7, "x"])
    assert cur.params == [7, "x"]


def test_run_no_params_passes_none_not_empty_tuple(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SELECT DATE_FORMAT(now(), '%Y-%m')")
    assert cur.params is None


@pytest.mark.parametrize(
    "bad",
    [
        "UPDATE t SET x=1",
        "DELETE FROM t",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE t",
    ],
)
def test_run_veto_before_conn(monkeypatch, bad):
    ex = make_executor()
    touched = []

    def boom():
        touched.append(1)
        raise AssertionError("connection touched before veto")

    monkeypatch.setattr(ex, "_conn", boom)
    with pytest.raises(ReadOnlyViolation):
        ex.run(bad)
    assert touched == []


def test_convert_preserves_types():
    row = {
        "dec": Decimal("10.99"),
        "i": 5,
        "f": 1.5,
        "s": "text",
        "nil": None,
    }
    out = _convert(row)
    assert isinstance(out["dec"], Decimal)
    assert isinstance(out["i"], int)
    assert isinstance(out["f"], float)
    assert out["s"] == "text"
    assert out["nil"] is None


def test_databases_wrapper(monkeypatch):
    ex = make_executor()
    seen = []

    def fake_run(sql, params=None, limit=100):
        seen.append(sql)
        return ["Database"], [{"Database": "back"}]

    monkeypatch.setattr(ex, "run", fake_run)
    cols, rows = ex.databases()
    assert seen == ["SHOW DATABASES"]
    assert cols == ["Database"]


def test_tables_wrapper(monkeypatch):
    ex = make_executor()
    seen = []

    def fake_run(sql, params=None, limit=100):
        seen.append(sql)
        return ["Tables_in_back"], [{"Tables_in_back": "facturas_venta"}]

    monkeypatch.setattr(ex, "run", fake_run)
    cols, rows = ex.tables()
    assert seen == ["SHOW TABLES"]
    assert rows[0]["Tables_in_back"] == "facturas_venta"


def test_describe_wrapper(monkeypatch):
    ex = make_executor()
    seen = []

    def fake_run(sql, params=None, limit=100):
        seen.append(sql)
        return ["Field", "Type"], [{"Field": "id", "Type": "int"}]

    monkeypatch.setattr(ex, "run", fake_run)
    cols, rows = ex.describe("clientes")
    assert seen == ["DESCRIBE `clientes`"]
    assert rows[0]["Field"] == "id"


def test_run_skips_clamp_when_limit_none(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SELECT a FROM t", limit=None)
    assert cur.executed == "SELECT a FROM t"


def test_run_no_sql_limit_on_show(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["t"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("SHOW TABLES", limit=5)
    assert cur.executed == "SHOW TABLES"


def test_run_no_sql_limit_on_describe(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["Field"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("DESCRIBE t", limit=5)
    assert cur.executed == "DESCRIBE t"
    ex.run("DESC t", limit=5)
    assert cur.executed == "DESC t"


def test_run_no_sql_limit_on_explain(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["id"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    ex.run("EXPLAIN SELECT * FROM t", limit=5)
    assert cur.executed == "EXPLAIN SELECT * FROM t"


def test_run_py_slices_when_no_sql_limit(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([{"x": 1}, {"x": 2}, {"x": 3}], ["x"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    cols, rows = ex.run("SHOW TABLES", limit=2)
    assert len(rows) == 2


def test_run_rejects_multistatement(monkeypatch):
    ex = make_executor()
    cur = FakeCursor([], ["a"])
    monkeypatch.setattr(ex, "_conn", lambda: FakeConn(cur))
    with pytest.raises(ReadOnlyViolation):
        ex.run("SELECT 1; SELECT 2", limit=5)
    assert cur.executed is None


def test_describe_escapes_backticks(monkeypatch):
    ex = make_executor()
    seen = []

    def fake_run(sql, params=None, limit=100):
        seen.append(sql)
        return [], []

    monkeypatch.setattr(ex, "run", fake_run)
    ex.describe("x`; DROP TABLE y; --")
    assert seen == ["DESCRIBE `x``; DROP TABLE y; --`"]


def test_run_auto_relanza_tunel_si_conexion_rota(monkeypatch):
    import mcp_bd_readonly.db as db_mod
    import pymysql

    ex = make_executor()
    cur = FakeCursor([{"x": 1}], ["x"])

    state = {"connect_calls": 0, "ensure": 0}

    class FakeTM:
        def __init__(self, cfg):
            self.cfg = cfg

        def ensure(self):
            state["ensure"] += 1
            return "started"

    def fake_connect(*a, **k):
        state["connect_calls"] += 1
        if state["connect_calls"] == 1:
            raise pymysql.err.OperationalError(2003, "can't connect")
        return FakeConn(cur)

    monkeypatch.setattr(db_mod.pymysql, "connect", fake_connect)
    monkeypatch.setattr(db_mod, "TunnelManager", FakeTM)

    cols, rows = ex.run("SELECT x FROM t")
    assert rows == [{"x": 1}]
    assert state["ensure"] == 1


def test_run_reintenta_select_una_vez_si_conn_se_pierde(monkeypatch):
    import mcp_bd_readonly.db as db_mod
    import pymysql

    ex = make_executor()
    cur = FakeCursor([{"x": 2}], ["x"])

    state = {"ensure": 0}

    class FakeTM:
        def __init__(self, cfg):
            self.cfg = cfg

        def ensure(self):
            state["ensure"] += 1
            return "ok"

    class FailingCursor(FakeCursor):
        def execute(self, sql, params=None):
            if not getattr(self, "boom_done", False):
                self.boom_done = True
                raise pymysql.err.OperationalError(2013, "Lost connection")
            return super().execute(sql, params)

    failing = FailingCursor([{"x": 2}], ["x"])
    monkeypatch.setattr(db_mod, "TunnelManager", FakeTM)
    monkeypatch.setattr(ex, "_connect", lambda: FakeConn(failing))

    cols, rows = ex.run("SELECT x FROM t")
    assert rows == [{"x": 2}]
    assert state["ensure"] == 1


def test_retryable_timeout_during_query_not_retried():
    import pymysql

    e = pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")
    assert _retryable(e) is False


def test_retryable_lost_connection_retried():
    import pymysql

    e = pymysql.err.OperationalError(2013, "Lost connection to MySQL server")
    assert _retryable(e) is True


def test_retryable_other_code_not_retried():
    import pymysql

    e = pymysql.err.OperationalError(3024, "Query execution was interrupted")
    assert _retryable(e) is False


def test_run_no_retry_on_during_query_timeout(monkeypatch):
    import mcp_bd_readonly.db as db_mod
    import pymysql

    ex = make_executor()

    state = {"ensure": 0}

    class FakeTM:
        def __init__(self, cfg):
            self.cfg = cfg

        def ensure(self):
            state["ensure"] += 1
            return "ok"

    class TimeoutCursor(FakeCursor):
        def execute(self, sql, params=None):
            raise pymysql.err.OperationalError(
                2013, "Lost connection to MySQL server during query"
            )

    monkeypatch.setattr(db_mod, "TunnelManager", FakeTM)
    monkeypatch.setattr(ex, "_connect", lambda: FakeConn(TimeoutCursor([], ["x"])))

    with pytest.raises(pymysql.err.OperationalError):
        ex.run("SELECT x FROM t")
    assert state["ensure"] == 0


def test_configure_sets_max_execution_time(monkeypatch):
    ex = make_executor()
    seen = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            seen.append(sql)

    class Conn:
        def cursor(self):
            return Cur()

    ex._configure(Conn())
    assert seen == ["SET SESSION max_execution_time = 15000"]


def test_note_slow_writes_when_slow(tmp_path):
    from types import SimpleNamespace

    ex = QueryExecutor(SimpleNamespace(data_dir=tmp_path, slow_query_ms=1))
    ex._note_slow("SELECT 1", 5000)
    lines = (tmp_path / "slow_queries.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert '"ms": 5000' in lines[0]


def test_note_slow_skips_when_fast(tmp_path):
    from types import SimpleNamespace

    ex = QueryExecutor(SimpleNamespace(data_dir=tmp_path, slow_query_ms=5000))
    ex._note_slow("SELECT 1", 10)
    assert not (tmp_path / "slow_queries.jsonl").exists()
