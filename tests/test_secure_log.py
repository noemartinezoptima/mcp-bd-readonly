import stat

from mcp_bd_readonly.secure_log import open_append_private, write_text_private


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_open_append_private_crea_con_0600(tmp_path):
    path = tmp_path / "sub" / "audit.jsonl"
    with open_append_private(path) as f:
        f.write("a\n")
    assert _mode(path) == 0o600
    assert path.read_text() == "a\n"


def test_open_append_private_corrige_permisos_existentes(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("vieja\n")
    path.chmod(0o644)
    assert _mode(path) == 0o644
    with open_append_private(path) as f:
        f.write("nueva\n")
    assert _mode(path) == 0o600
    assert path.read_text() == "vieja\nnueva\n"


def test_write_text_private_crea_con_0600(tmp_path):
    path = tmp_path / "sub" / "memoria.json"
    write_text_private(path, '{"a": 1}')
    assert _mode(path) == 0o600
    assert path.read_text() == '{"a": 1}'


def test_write_text_private_sobrescribe_y_mantiene_0600(tmp_path):
    path = tmp_path / "memoria.json"
    write_text_private(path, "primero")
    write_text_private(path, "segundo")
    assert _mode(path) == 0o600
    assert path.read_text() == "segundo"
