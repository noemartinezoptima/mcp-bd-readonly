import time

from mcp_bd_readonly.auth import TOKEN_PREFIX, KeyStore


def make_store(tmp_path):
    return KeyStore(tmp_path / "api_keys.db")


def test_create_and_verify(tmp_path):
    store = make_store(tmp_path)
    created = store.create("finanzas", scopes=("read",), ttl_days=30)
    assert created["key"].startswith(TOKEN_PREFIX)
    info = store.verify(created["key"])
    assert info is not None
    assert info.key_id == created["id"]
    assert info.name == "finanzas"
    assert info.allows("read")
    assert not info.allows("admin")


def test_rechaza_secreto_incorrecto(tmp_path):
    store = make_store(tmp_path)
    created = store.create("x")
    key_id = created["id"]
    assert store.verify(f"{TOKEN_PREFIX}{key_id}_" + "0" * 48) is None


def test_rechaza_id_desconocido(tmp_path):
    store = make_store(tmp_path)
    store.create("x")
    assert store.verify(f"{TOKEN_PREFIX}deadbeef_" + "a" * 48) is None


def test_rechaza_token_sin_formato(tmp_path):
    store = make_store(tmp_path)
    for token in ("", "abc", TOKEN_PREFIX, "mcp_sinid"):
        assert store.verify(token) is None


def test_rechaza_clave_revocada(tmp_path):
    store = make_store(tmp_path)
    created = store.create("temporal")
    assert store.revoke(created["id"]) is True
    assert store.verify(created["key"]) is None
    assert store.revoke(created["id"]) is False


def test_rechaza_clave_caducada(tmp_path):
    store = make_store(tmp_path)
    created = store.create("vieja", ttl_days=1)
    future = time.time() + 2 * 86400
    assert store.verify(created["key"], now=future) is None


def test_clave_sin_caducidad_ttl_cero(tmp_path):
    store = make_store(tmp_path)
    created = store.create("permanente", ttl_days=0)
    assert created["expires_at"] is None
    assert store.verify(created["key"]) is not None


def test_no_guarda_el_secreto_en_claro(tmp_path):
    store = make_store(tmp_path)
    created = store.create("secreto")
    secret = created["key"].rsplit("_", 1)[1]
    raw = (tmp_path / "api_keys.db").read_bytes()
    # En modo WAL la fila puede vivir todavía en el fichero -wal.
    wal = tmp_path / "api_keys.db-wal"
    if wal.exists():
        raw += wal.read_bytes()
    assert secret.encode() not in raw
    # El id sí se guarda, para poder buscar y revocar.
    assert created["id"].encode() in raw


def test_list_no_expone_hash_ni_secreto(tmp_path):
    store = make_store(tmp_path)
    created = store.create("listado")
    rows = store.list_keys()
    assert len(rows) == 1
    assert "key_hash" not in rows[0]
    assert created["key"] not in str(rows)


def test_repositorio_sobrevive_a_reabrir(tmp_path):
    store = make_store(tmp_path)
    created = store.create("persistente")
    otro = KeyStore(tmp_path / "api_keys.db")
    assert otro.verify(created["key"]) is not None


def test_scope_admin_incluye_read(tmp_path):
    store = make_store(tmp_path)
    created = store.create("root", scopes=("admin",))
    info = store.verify(created["key"])
    assert info.allows("read")
    assert info.allows("admin")
