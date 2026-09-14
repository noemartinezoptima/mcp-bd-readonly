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