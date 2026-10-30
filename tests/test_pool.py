from types import SimpleNamespace

import pymysql
import pytest

from mcp_bd_readonly.db import ConnectionPool, PoolExhausted, QueryExecutor


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [(c,) for c in conn.cols] if conn.cols else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)

    def fetchall(self):
        return self.conn.rows


class FakeConn:
    def __init__(self, rows=None, cols=("a",)):
        self.open = True
        self.pings = 0
        self.closed = False
        self.rows = rows if rows is not None else [{"a": 1}]
        self.cols = list(cols)
        self.executed = []

    def ping(self, reconnect=False):
        if not self.open:
            raise pymysql.err.OperationalError(2013, "conexión perdida")
        self.pings += 1

    def close(self):
        self.closed = True
        self.open = False

    def cursor(self):
        return FakeCursor(self)


def test_pool_reutiliza_la_misma_conexion():
    creadas = []

    def factory():
        conn = FakeConn()
        creadas.append(conn)
        return conn

    pool = ConnectionPool(factory, size=2, timeout=0.05)
    a = pool.acquire()
    pool.release(a)
    b = pool.acquire()
    assert b is a
    assert len(creadas) == 1
    pool.release(b)


def test_pool_respeta_el_tamano_maximo():
    pool = ConnectionPool(FakeConn, size=1, timeout=0.05)
    conn = pool.acquire()
    with pytest.raises(PoolExhausted):
        pool.acquire()
    pool.release(conn)
    assert pool.acquire() is conn


def test_pool_descarta_conexion_muerta():
    pool = ConnectionPool(FakeConn, size=1, timeout=0.05)
    conn = pool.acquire()
    conn.open = False  # MySQL cerró la sesión por wait_timeout
    pool.release(conn)
    assert conn.closed is True
    nueva = pool.acquire()
    assert nueva is not conn


def test_pool_libera_slot_si_la_factory_falla():
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("no se pudo conectar")
        return FakeConn()

    pool = ConnectionPool(factory, size=1, timeout=0.05)
    with pytest.raises(RuntimeError):
        pool.acquire()
    conn = pool.acquire()
    assert isinstance(conn, FakeConn)


def test_executor_con_pool_reutiliza_y_cierra(monkeypatch):
    creadas = []

    def fake_open(self):
        conn = FakeConn(rows=[{"a": 1}], cols=["a"])
        creadas.append(conn)
        return conn

    monkeypatch.setattr(QueryExecutor, "_open", fake_open)
    cfg = SimpleNamespace(
        host="h", port=1, user="u", password="p", db="d",
        pool_size=1, query_timeout_ms=1000, slow_query_ms=5000, data_dir=None,
    )
    ex = QueryExecutor(cfg)
    ex.run("SELECT a FROM t")
    ex.run("SELECT a FROM t")
    assert len(creadas) == 1
    ex.close()
    assert creadas[0].closed is True


def test_executor_cierra_conexion_si_la_query_falla(monkeypatch):
    conn = FakeConn(rows=[{"a": 1}], cols=["a"])
    original = FakeCursor.execute

    def boom(self, sql, params=None):
        # Solo falla la consulta de negocio: `SET SESSION` debe seguir pasando.
        if sql.strip().upper().startswith("SELECT"):
            raise pymysql.err.ProgrammingError(1064, "syntax error")
        return original(self, sql, params)

    monkeypatch.setattr(QueryExecutor, "_open", lambda self: conn)
    cfg = SimpleNamespace(
        host="h", port=1, user="u", password="p", db="d",
        query_timeout_ms=1000, slow_query_ms=5000, data_dir=None,
    )
    ex = QueryExecutor(cfg)
    monkeypatch.setattr(FakeCursor, "execute", boom, raising=False)
    with pytest.raises(pymysql.err.ProgrammingError):
        ex.run("SELECT a FROM t")
    assert conn.closed is True


def test_sin_tunel_no_lanza_ssh_ni_enmascara_el_error(monkeypatch):
    def sin_conexion(self):
        raise pymysql.err.OperationalError(2003, "Can't connect to MySQL server")

    llamadas = []
    monkeypatch.setattr(QueryExecutor, "_open", sin_conexion)
    monkeypatch.setattr(
        "mcp_bd_readonly.db.TunnelManager.ensure",
        lambda self: llamadas.append("tunnel") or "started",
    )
    cfg = SimpleNamespace(
        host="10.0.0.6", port=3306, user="u", password="p", db="d",
        tunnel_enabled=False, query_timeout_ms=1000, slow_query_ms=5000, data_dir=None,
    )
    with pytest.raises(pymysql.err.OperationalError):
        QueryExecutor(cfg).run("SELECT 1")
    assert llamadas == []


def test_con_tunel_si_intenta_levantarlo(monkeypatch):
    state = {"intentos": 0}

    def sin_conexion(self):
        state["intentos"] += 1
        raise pymysql.err.OperationalError(2003, "Can't connect to MySQL server")

    monkeypatch.setattr(QueryExecutor, "_open", sin_conexion)
    monkeypatch.setattr(
        "mcp_bd_readonly.db.TunnelManager.ensure",
        lambda self: "started",
    )
    cfg = SimpleNamespace(
        host="127.0.0.1", port=13306, user="u", password="p", db="d",
        tunnel_enabled=True, query_timeout_ms=1000, slow_query_ms=5000, data_dir=None,
    )
    with pytest.raises(pymysql.err.OperationalError):
        QueryExecutor(cfg).run("SELECT 1")
    assert state["intentos"] == 2
