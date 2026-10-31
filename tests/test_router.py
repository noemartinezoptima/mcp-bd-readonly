import pytest

from mcp_bd_readonly.router import ReplicaRouter, ReplicaState


class FakeExec:
    def __init__(self, status_rows=None, rows=None, cols=("a",), error=None, status_error=None):
        self.status_rows = status_rows
        self.rows = rows if rows is not None else [{"a": 1}]
        self.cols = list(cols)
        self.error = error
        self.status_error = status_error
        self.sqls = []

    def run(self, sql, params=None, limit=100):
        self.sqls.append(sql)
        upper = sql.upper()
        if "REPLICA STATUS" in upper or "SLAVE STATUS" in upper:
            if self.status_error:
                raise self.status_error
            return ["x"], self.status_rows or []
        if self.error:
            raise self.error
        return self.cols, self.rows

    def close(self):
        pass


def healthy_status(lag=0, io="Yes", sql_thread="Yes"):
    return [{
        "Replica_IO_Running": io,
        "Replica_SQL_Running": sql_thread,
        "Seconds_Behind_Source": lag,
    }]


def make_router(status_rows, lag_max_s=60, ttl_s=10, clock=None):
    replica = FakeExec(status_rows=status_rows)
    primary = FakeExec(rows=[{"a": "primario"}])
    kwargs = {"lag_max_s": lag_max_s, "ttl_s": ttl_s}
    if clock is not None:
        kwargs["clock"] = clock
    return ReplicaRouter(primary, replica, **kwargs), primary, replica


def test_usa_replica_cuando_esta_al_dia():
    router, primary, replica = make_router(healthy_status(lag=0))
    cols, rows = router.run("SELECT a FROM t")
    assert rows == replica.rows
    assert "SELECT a FROM t" in replica.sqls
    assert primary.sqls == []
    assert router.last_destino == "replica"


def test_fallback_al_primario_por_lag_alto():
    router, primary, replica = make_router(healthy_status(lag=90), lag_max_s=60)
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert router.last_destino == "primario"
    assert "lag" in router.replica_state().reason


def test_fallback_si_la_replica_no_tiene_canal():
    router, primary, _ = make_router([])
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert "canal" in router.replica_state().reason


def test_fallback_si_la_replicacion_esta_parada():
    router, primary, _ = make_router(healthy_status(io="No"))
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert "parada" in router.replica_state().reason


def test_fallback_si_no_hay_lag_conocido():
    router, primary, _ = make_router([{
        "Replica_IO_Running": "Yes",
        "Replica_SQL_Running": "Yes",
        "Seconds_Behind_Source": None,
    }])
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert "desconocido" in router.replica_state().reason


def test_fallback_si_la_replica_esta_inaccesible():
    replica = FakeExec(status_error=RuntimeError("conexión rechazada"))
    primary = FakeExec(rows=[{"a": "primario"}])
    router = ReplicaRouter(primary, replica)
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert "inaccesible" in router.replica_state().reason


def test_fallback_si_la_consulta_falla_en_la_replica():
    router, primary, replica = make_router(healthy_status(lag=0))
    replica.error = RuntimeError("conexión perdida")
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert router.last_destino == "primario"


def test_estado_de_replica_se_cachea_por_ttl():
    now = [1000.0]
    router, primary, replica = make_router(healthy_status(lag=0), ttl_s=10, clock=lambda: now[0])
    router.run("SELECT a FROM t")
    router.run("SELECT a FROM t")
    checks = [s for s in replica.sqls if "STATUS" in s.upper()]
    assert len(checks) == 1
    now[0] += 11
    router.run("SELECT a FROM t")
    checks = [s for s in replica.sqls if "STATUS" in s.upper()]
    assert len(checks) == 2


def test_sin_replica_configurada_usa_primario():
    primary = FakeExec(rows=[{"a": "primario"}])
    router = ReplicaRouter(primary, None)
    _, rows = router.run("SELECT a FROM t")
    assert rows == [{"a": "primario"}]
    assert router.estado()["replica_configurada"] is False


def test_estado_expone_lag_y_destino():
    router, _, _ = make_router(healthy_status(lag=3))
    router.run("SELECT a FROM t")
    estado = router.estado()
    assert estado["destino"] == "replica"
    assert estado["replica"]["lag_s"] == 3.0
    assert estado["replica"]["ok"] is True
    assert estado["lag_max_s"] == 60.0


def test_replica_state_es_inmutable():
    state = ReplicaState(True, 0.0, "", 1.0)
    with pytest.raises(Exception):
        state.ok = False
