from mcp_bd_readonly.setup import mcp_command


def test_mcp_command_ends_in_venv_bin():
    cmd = mcp_command()
    assert cmd.endswith(".venv/bin/mcp-optima-bd") or cmd.endswith(
        ".venv\\Scripts\\mcp-optima-bd.exe"
    )


def test_mcp_command_is_absolute():
    from pathlib import Path

    assert Path(mcp_command()).is_absolute()


def test_run_setup_dry_run_no_writes(monkeypatch, tmp_path):
    import mcp_bd_readonly.register as register
    from mcp_bd_readonly import setup as s

    monkeypatch.setattr(register, "_home", lambda: tmp_path)

    answers = iter([
        "n",                     # generar clave? no
        "",                      # ruta clave -> default
        "optimaback-active",     # alias SSH
        "88.198.105.152",        # hostname
        "",                      # user -> forge
        "",                      # MYSQL_HOST -> 127.0.0.1
        "",                      # MYSQL_PORT -> 13306
        "",                      # MYSQL_DB -> back
        "",                      # MYSQL_USER -> back_readonly
        "",                      # TUNNEL_HOST -> hereda alias (optimaback-active)
        "",                      # DATA_DIR -> ./data
    ])

    def fake_input(prompt=""):
        return next(answers)

    summary = s.run_setup(
        dry_run=True, _input=fake_input, _secret=lambda p: "s3cret"
    )

    assert summary["ssh"]["dry_run"] is True
    assert summary["ssh"]["host"] == "optimaback-active"
    assert summary["config"]["dry_run"] is True
    assert summary["verify"].startswith("DRY-RUN")
    for t, r in summary["register"].items():
        assert r["status"] == "dry_run"
    # nada escrito
    assert not (tmp_path / ".claude.json").exists()
    assert not (tmp_path / ".zt-readonly.env").exists()
    assert not (tmp_path / ".ssh").exists()
