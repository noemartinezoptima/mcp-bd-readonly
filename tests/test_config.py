import pathlib

from mcp_bd_readonly.config import load_config


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
