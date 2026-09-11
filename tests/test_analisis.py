from decimal import Decimal

from mcp_bd_readonly.tools_analisis import (
    dso_dpo_evolutivo,
    aging_efectos,
    build_analisis_tools,
)


class FakeEx:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, params, limit))
        return self.responses.pop(0)


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_dso_dpo_evolutivo_calcula_medias():
    dpo_rows = (["mes", "dias", "n"], [
        {"mes": "2026-01", "dias": 60.0, "n": 10},
        {"mes": "2026-02", "dias": 80.0, "n": 10},
    ])
    dso_rows = (["mes", "dias", "n"], [
        {"mes": "2026-01", "dias": 30.0, "n": 5},
    ])
    ex = FakeEx([dpo_rows, dso_rows])
    out = dso_dpo_evolutivo(ex, 2025, 2026)
    assert out["dpo_mensual"] == [
        {"mes": "2026-01", "mes_es": "01/2026", "dpo_dias": 60.0, "dpo_dias_es": "60,0 d", "n": 10},
        {"mes": "2026-02", "mes_es": "02/2026", "dpo_dias": 80.0, "dpo_dias_es": "80,0 d", "n": 10},
    ]
    assert out["dso_mensual"] == [
        {"mes": "2026-01", "mes_es": "01/2026", "dso_dias": 30.0, "dso_dias_es": "30,0 d", "n": 5},
    ]
    assert out["dpo_medio"] == 70.0
    assert out["dpo_medio_es"] == "70,0 d"
    assert len(ex.calls) == 2
    assert ex.calls[0][1] == [2025, 2026]


def test_dso_dpo_evolutivo_sin_datos():
    ex = FakeEx([(["mes", "dias", "n"], []), (["mes", "dias", "n"], [])])
    out = dso_dpo_evolutivo(ex)
    assert out["dpo_mensual"] == []
    assert out["dpo_medio"] is None
    assert out["dpo_medio_es"] is None


def test_aging_efectos_agrupa_por_bucket():
    rows = (["banco_id", "cliente_id", "bucket", "n", "importe"], [
        {"banco_id": 1, "cliente_id": 100, "bucket": "0-30", "n": 3, "importe": Decimal("150.00")},
        {"banco_id": 1, "cliente_id": 100, "bucket": "+90", "n": 1, "importe": Decimal("999.99")},
    ])
    ex = FakeEx([rows])
    out = aging_efectos(ex)
    assert out["aging"][0]["importe"] == Decimal("150.00")
    assert out["aging"][0]["importe_es"] == "150,00 €"
    assert out["aging"][1]["bucket"] == "+90"


def test_build_analisis_tools_registra_auditoria():
    ex = FakeEx([
        (["mes", "dias", "n"], []),
        (["mes", "dias", "n"], []),
        (["banco_id", "cliente_id", "bucket", "n", "importe"], []),
    ])
    audit = FakeAudit()
    tool_dso, tool_aging = build_analisis_tools(ex, audit)
    tool_dso()
    tool_aging()
    assert [c[0] for c in audit.calls] == ["dso_dpo_evolutivo", "aging_efectos"]
