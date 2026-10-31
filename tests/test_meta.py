import socket

from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.config import Config
from mcp_bd_readonly.tools_meta import estado_tunel, auditoria, build_meta_tools


def make_cfg(port, data_dir):
    return Config(
        host="127.0.0.1", port=port, db="back",
        user="u", password="p", data_dir=data_dir,
        tunnel_host="db-host",
    )


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_estado_tunel_abierto():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        cfg = make_cfg(port, "/tmp")
        r = estado_tunel(cfg)
        assert r["abierto"] is True
        assert r["port"] == port
        assert r["tunnel_host"] == "db-host"
        assert "password" not in r
    finally:
        srv.close()


def test_estado_tunel_cerrado():
    cfg = make_cfg(1, "/tmp")
    r = estado_tunel(cfg)
    assert r["abierto"] is False


def test_auditoria_lee_entradas(tmp_path):
    log = AuditLogger(tmp_path)
    log.record("run_query", "nobody", "SELECT 1")
    log.record("describe_table", "nobody", "DESCRIBE clientes")
    r = auditoria(tmp_path, max_n=100)
    assert r["total"] == 2
    assert len(r["entradas"]) == 2
    assert r["entradas"][0]["tool"] == "run_query"
    assert "ts_es" in r["entradas"][0]


def test_auditoria_respeta_max_n(tmp_path):
    log = AuditLogger(tmp_path)
    for i in range(5):
        log.record("run_query", "x", f"SELECT {i}")
    r = auditoria(tmp_path, max_n=2)
    assert r["total"] == 5
    assert len(r["entradas"]) == 2
    assert r["entradas"][-1]["sql"] == "SELECT 4"


def test_auditoria_sin_fichero(tmp_path):
    r = auditoria(tmp_path / "no_existe", max_n=100)
    assert r == {"entradas": [], "total": 0}


def test_build_meta_tools_registra_auditoria(tmp_path):
    cfg = make_cfg(1, tmp_path)
    audit = FakeAudit()
    tool_estado, tool_auditoria = build_meta_tools(cfg, audit)
    tool_estado()
    tool_auditoria()
    assert [c[0] for c in audit.calls] == ["estado_tunel", "auditoria"]
