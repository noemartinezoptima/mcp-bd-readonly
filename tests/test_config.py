import os
import pathlib

import pytest

from mcp_bd_readonly.config import Config, load_config, write_config


def test_load_config_env(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_PORT", "13306")
    monkeypatch.setenv("MYSQL_DB", "back")
    monkeypatch.setenv("MYSQL_USER", "ro_back")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("DATA_DIR", "/tmp/ztdata")
    cfg = load_config()
    assert cfg.port == 13306
    assert cfg.db == "back"
    assert cfg.user == "ro_back"


def test_load_config_defaults(tmp_path, monkeypatch):
    for key in (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DB",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(env_file=tmp_path / "missing.env")
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 13306
    assert cfg.db == ""
    assert cfg.user == ""
    assert cfg.password == ""
    assert cfg.data_dir == pathlib.Path("./data")


def test_load_config_env_file_overlay(tmp_path, monkeypatch):
    env_file = tmp_path / ".zt-readonly.env"
    env_file.write_text(
        "MYSQL_HOST=db.example.com\n"
        "MYSQL_PORT=3306\n"
        "MYSQL_DB=back\n"
        "MYSQL_USER=envfile_user\n"
        "MYSQL_PASSWORD=envfile_secret\n"
        "# comment line\n"
        "\n"
        "DATA_DIR=/tmp/envfile_data\n"
    )
    for key in (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DB",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(env_file=env_file)
    assert cfg.host == "db.example.com"
    assert cfg.port == 3306
    assert cfg.db == "back"
    assert cfg.user == "envfile_user"
    assert cfg.password == "envfile_secret"
    assert cfg.data_dir == pathlib.Path("/tmp/envfile_data")


def test_load_config_env_takes_precedence_over_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".zt-readonly.env"
    env_file.write_text(
        "MYSQL_HOST=db.example.com\n"
        "MYSQL_PORT=3306\n"
        "MYSQL_DB=envfile_db\n"
        "MYSQL_USER=envfile_user\n"
        "MYSQL_PASSWORD=envfile_secret\n"
        "DATA_DIR=/tmp/envfile_data\n"
    )
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_PORT", "13306")
    monkeypatch.setenv("MYSQL_DB", "env_db")
    monkeypatch.setenv("MYSQL_USER", "env_user")
    monkeypatch.setenv("MYSQL_PASSWORD", "env_secret")
    monkeypatch.setenv("DATA_DIR", "/tmp/env_data")
    cfg = load_config(env_file=env_file)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 13306
    assert cfg.db == "env_db"
    assert cfg.user == "env_user"
    assert cfg.password == "env_secret"
    assert cfg.data_dir == pathlib.Path("/tmp/env_data")


def test_load_config_missing_env_file(tmp_path, monkeypatch):
    for key in (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DB",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(env_file=tmp_path / "does-not-exist.env")
    assert cfg.port == 13306


def test_load_config_query_timeout_defaults(tmp_path, monkeypatch):
    for key in (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DB",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "DATA_DIR",
        "MYSQL_QUERY_TIMEOUT_MS",
        "MYSQL_SLOW_QUERY_MS",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config(env_file=tmp_path / "missing.env")
    assert cfg.query_timeout_ms == 15000
    assert cfg.slow_query_ms == 5000


def test_write_config_roundtrip(tmp_path):
    dest = tmp_path / ".zt-readonly.env"
    cfg = Config(
        host="127.0.0.1",
        port=13306,
        db="back",
        user="ro",
        password="s3cr3t",
        data_dir=pathlib.Path("./data"),
        tunnel_host="db-host",
    )
    out = write_config(cfg, path=dest)
    assert out == dest

    loaded = load_config(env_file=dest)
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 13306
    assert loaded.db == "back"
    assert loaded.user == "ro"
    assert loaded.password == "s3cr3t"
    assert loaded.data_dir == pathlib.Path("./data")
    assert loaded.tunnel_host == "db-host"
    assert loaded.query_timeout_ms == 15000
    assert loaded.slow_query_ms == 5000


def test_write_config_refuses_overwrite(tmp_path):
    dest = tmp_path / ".zt-readonly.env"
    cfg = Config("h", 1, "d", "u", "p", pathlib.Path("./data"), "t")
    write_config(cfg, path=dest)
    with pytest.raises(FileExistsError):
        write_config(cfg, path=dest)


def test_write_config_force_overwrites(tmp_path):
    dest = tmp_path / ".zt-readonly.env"
    cfg = Config("h", 1, "d", "u", "p", pathlib.Path("./data"), "t")
    write_config(cfg, path=dest)
    cfg2 = Config("h2", 2, "d2", "u2", "p2", pathlib.Path("./data2"), "t2")
    write_config(cfg2, path=dest, force=True)
    text = dest.read_text()
    assert "MYSQL_HOST=h2" in text
    assert "MYSQL_USER=u2" in text


def test_write_config_chmod_600(tmp_path):
    if os.name == "nt":
        pytest.skip("chmod POSIX no aplica en Windows")
    dest = tmp_path / ".zt-readonly.env"
    cfg = Config("h", 1, "d", "u", "p", pathlib.Path("./data"), "t")
    write_config(cfg, path=dest)
    assert dest.stat().st_mode & 0o777 == 0o600
