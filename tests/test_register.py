import json

import mcp_bd_readonly.register as register
from mcp_bd_readonly.register import (
    MCP_NAME,
    _merge_mcp_servers,
    _merge_opencode,
    register_mcp,
)


def _patch_home(monkeypatch, tmp_path):
    monkeypatch.setattr(register, "_home", lambda: tmp_path)


def test_merge_mcp_servers_creates(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    status = _merge_mcp_servers(
        tmp_path / ".claude.json",
        "/x/mcp",
        {"type": "stdio", "command": "/x/mcp", "args": []},
        False,
    )
    assert status == "ok"
    data = json.loads((tmp_path / ".claude.json").read_text())
    assert data["mcpServers"][MCP_NAME]["command"] == "/x/mcp"


def test_merge_mcp_servers_idempotent(monkeypatch, tmp_path):
    p = tmp_path / ".claude.json"
    p.write_text(json.dumps({"mcpServers": {MCP_NAME: {"command": "/x/mcp"}}}))
    status = _merge_mcp_servers(p, "/x/mcp", {"command": "/x/mcp"}, False)
    assert status == "ya_presente"


def test_merge_mcp_servers_preserves_others(monkeypatch, tmp_path):
    p = tmp_path / ".cursor" / "mcp.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    status = _merge_mcp_servers(p, "/x/mcp", {"command": "/x/mcp", "args": []}, False)
    assert status == "ok"
    data = json.loads(p.read_text())
    assert "other" in data["mcpServers"]
    assert MCP_NAME in data["mcpServers"]


def test_merge_opencode_inserts_preserving_comments(monkeypatch, tmp_path):
    p = tmp_path / ".config" / "opencode" / "opencode.jsonc"
    p.parent.mkdir(parents=True)
    p.write_text(
        '{\n  // comentario que debe sobrevivir\n'
        '  "mcp": {\n    "x": {"type": "local", "command": ["a"]}\n  }\n}\n'
    )
    status = _merge_opencode(p, "/x/mcp", False)
    assert status == "ok"
    text = p.read_text()
    assert MCP_NAME in text
    assert "// comentario que debe sobrevivir" in text
    # el entry insertado lleva command como ARRAY
    assert '"/x/mcp"' in text


def test_merge_opencode_idempotent(monkeypatch, tmp_path):
    p = tmp_path / "opencode.jsonc"
    p.write_text('{"mcp": {"mcp-optima-bd": {"type": "local"}}}')
    assert _merge_opencode(p, "/x/mcp", False) == "ya_presente"


def test_register_mcp_unknown_target(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    res = register_mcp("/x/mcp", targets=["nope"])
    assert res["nope"]["status"] == "error"


def test_register_mcp_dry_run_does_not_write(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    res = register_mcp("/x/mcp", targets=["claude-code"], dry_run=True)
    assert res["claude-code"]["status"] == "dry_run"
    assert not (tmp_path / ".claude.json").exists()


def test_register_mcp_all_targets(monkeypatch, tmp_path):
    _patch_home(monkeypatch, tmp_path)
    res = register_mcp("/x/mcp")
    assert set(res) == {"claude-code", "opencode", "cursor", "claude-desktop"}
    # claude-code y cursor crean archivo; opencode y desktop también
    for t in ("claude-code", "opencode", "cursor", "claude-desktop"):
        assert res[t]["status"] in ("ok", "ya_presente", "dry_run")
