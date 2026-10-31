import json
from pathlib import Path

from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.request_ctx import reset_api_key, set_api_key


def test_audit_writes(tmp_path):
    log = AuditLogger(tmp_path)
    log.record("run_query", "nobody", "SELECT 1")
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["sql"] == "SELECT 1"
    assert json.loads(lines[0])["tool"] == "run_query"


def test_audit_rows(tmp_path):
    log = AuditLogger(tmp_path / "nested" / "dir")
    log.record("list_tables", "alice", "SHOW TABLES", note="manual")
    log.record("run_query", "bob", "SELECT * FROM facturas LIMIT 5")
    lines = Path(tmp_path / "nested" / "dir" / "audit.jsonl").read_text().splitlines()
    first, second = (json.loads(l) for l in lines)
    assert first["who"] == "alice"
    assert first["note"] == "manual"
    assert isinstance(first["ts"], (int, float))
    assert second["who"] == "bob"
    assert second["note"] == ""
    assert second["sql"] == "SELECT * FROM facturas LIMIT 5"


def test_audit_append(tmp_path):
    log = AuditLogger(tmp_path)
    log.record("run_query", "x", "SELECT 1")
    log.record("run_query", "y", "SELECT 2")
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["who"] == "y"


def test_audit_unicode(tmp_path):
    log = AuditLogger(tmp_path)
    log.record("run_query", "root", "SELECT '€ → ½'", note="precio")
    row = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
    assert "€ → ½" in row["sql"]
    assert "€" in (tmp_path / "audit.jsonl").read_text()


def test_audit_usa_api_key_del_contexto_si_who_es_mcp(tmp_path):
    """Las tools siempre pasan who="mcp" literal (tools_core.py etc). Si hay
    una API key fijada en el contextvar (request HTTP en curso), debe
    prevalecer sobre ese literal para poder saber quién hizo la query."""
    log = AuditLogger(tmp_path)
    token = set_api_key("key_abc123")
    try:
        log.record("run_query", "mcp", "SELECT 1")
    finally:
        reset_api_key(token)
    row = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
    assert row["who"] == "key_abc123"


def test_audit_mantiene_who_explicito_si_no_es_mcp(tmp_path):
    """Un `who` explícito (como en stdio o en tests) no debe ser pisado por
    el contextvar, aunque este esté fijado."""
    log = AuditLogger(tmp_path)
    token = set_api_key("key_abc123")
    try:
        log.record("run_query", "alice", "SELECT 1")
    finally:
        reset_api_key(token)
    row = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
    assert row["who"] == "alice"


def test_audit_sin_contextvar_fijado_usa_mcp(tmp_path):
    """Modo stdio: nunca se fija el contextvar, debe mantenerse el 'mcp' de
    siempre."""
    log = AuditLogger(tmp_path)
    log.record("run_query", "mcp", "SELECT 1")
    row = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
    assert row["who"] == "mcp"
