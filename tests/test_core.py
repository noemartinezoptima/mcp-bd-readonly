import pytest

from mcp_bd_readonly.tools_core import build_tools


class FakeEx:
    def __init__(self):
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, limit))
        return ["x"], [{"x": 1}]


def _run_query(ex=None, audit=None):
    ex = ex or FakeEx()
    return build_tools(ex, audit)[3]


def test_run_query_llama_executor_con_limit():
    ex = FakeEx()
    rq = _run_query(ex=ex)
    out = rq("SELECT 1", limit=7)
    assert out["columns"] == ["x"]
    assert ex.calls[0][1] == 7


def test_run_query_limit_cero_o_negativo_rechazado():
    rq = _run_query()
    for bad in (0, -1, -5):
        with pytest.raises(ValueError) as ei:
            rq("SELECT 1", limit=bad)
        assert "limit" in str(ei.value).lower()


class _Lleno(FakeEx):
    """Devuelve tantas filas como limit pida: el caso en que puede haber más."""

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, limit))
        return ["x"], [{"x": i} for i in range(limit)]


class _SinLimite(FakeEx):
    def run(self, sql, params=None, limit=None):
        self.calls.append((sql, limit))
        return ["x"], [{"x": 1}]


def test_run_query_marca_truncated_cuando_llena_el_limit():
    """Si llegan exactamente `limit` filas puede haber más: el cliente no puede
    saberlo por el número, y contar las filas recibidas como total es un error
    material en contabilidad."""
    rq = _run_query(ex=_Lleno())
    out = rq("SELECT 1", limit=3)
    assert out["truncated"] is True
    assert len(out["rows"]) == 3


def test_run_query_sin_truncated_cuando_sobran_filas_del_limit():
    rq = _run_query()
    out = rq("SELECT 1", limit=100)
    assert out["truncated"] is False
    assert len(out["rows"]) == 1


def test_run_query_limit_none_nunca_trunca():
    """Con limit=None el propio servidor ya falla si supera MAX_ROWS, así que no
    puede haber recorte silencioso."""
    out = _run_query(ex=_SinLimite())("SELECT 1", limit=None)
    assert out["truncated"] is False