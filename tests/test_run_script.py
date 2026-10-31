import time

import pytest

from mcp_bd_readonly import run_script as rs


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_ejecutar_captura_stdout():
    stdout, error = rs.ejecutar("print('hola')", {})
    assert stdout == "hola\n"
    assert error is None


def test_ejecutar_puede_llamar_tools_inyectadas():
    def sumar(a, b):
        return a + b

    stdout, error = rs.ejecutar("print(sumar(2, 3))", {"sumar": sumar})
    assert stdout == "5\n"
    assert error is None


def test_ejecutar_encadena_varias_tools():
    def doblar(n):
        return n * 2

    def triplicar(n):
        return n * 3

    codigo = "x = doblar(4)\nprint(triplicar(x))"
    stdout, error = rs.ejecutar(codigo, {"doblar": doblar, "triplicar": triplicar})
    assert stdout == "24\n"
    assert error is None


def test_ejecutar_bloquea_import():
    stdout, error = rs.ejecutar("import os", {})
    assert error is not None
    assert "ImportError" in error


def test_ejecutar_bloquea_open():
    stdout, error = rs.ejecutar("open('/etc/passwd')", {})
    assert error is not None
    assert "NameError" in error


def test_ejecutar_reporta_excepcion_sin_relanzar():
    stdout, error = rs.ejecutar("1 / 0", {})
    assert error == "ZeroDivisionError: division by zero"


def test_ejecutar_trunca_stdout_largo(monkeypatch):
    monkeypatch.setattr(rs, "MAX_STDOUT", 10)
    stdout, error = rs.ejecutar("print('x' * 100)", {})
    assert len(stdout) < 100
    assert "truncado" in stdout
    assert error is None


def test_ejecutar_timeout(monkeypatch):
    monkeypatch.setattr(rs, "TIMEOUT_S", 0.2)
    stdout, error = rs.ejecutar("while True: pass", {})
    assert error is not None
    assert "timeout" in error


def test_build_run_script_tools_registra_auditoria_y_excluye_denegadas():
    audit = FakeAudit()

    def facturas_venta():
        return "ok"

    def setup_ssh():
        return "nope"

    tools = {"facturas_venta": facturas_venta, "setup_ssh": setup_ssh}
    (run_script,) = rs.build_run_script_tools(audit, tools)

    out = run_script("print(facturas_venta())")
    assert out["stdout"] == "ok\n"
    assert out["error"] is None
    assert "facturas_venta" in out["tools_disponibles"]
    assert "setup_ssh" not in out["tools_disponibles"]
    assert audit.calls[0][0] == "run_script"

    out2 = run_script("setup_ssh()")
    assert out2["error"] is not None
    assert "NameError" in out2["error"]