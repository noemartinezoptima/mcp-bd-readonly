"""Multiusuario y seguridad: TTL del pool, cupo por API key, run_script y topes.

Cubre el SDD `docs/SDD-MULTIUSUARIO.md`:
- RF-1 cierre por inactividad (el MCP no retiene el cupo del usuario MySQL).
- RF-2 cupo por API key y tope global de sesiones vivas.
- RF-3 `run_script` fail-closed en HTTP.
- RF-4 fallos de autenticación limitados por IP y registrados.
- RF-5 topes de memoria: `MYSQL_MAX_ROWS` y base64 del Excel.
"""

import asyncio
import base64
import time
from types import SimpleNamespace

import pymysql
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_bd_readonly.auth import KeyStore
from mcp_bd_readonly.config import load_config, write_config
from mcp_bd_readonly.db import ConnectionPool, PoolExhausted, QueryExecutor
from mcp_bd_readonly.http_app import ApiKeyMiddleware
from mcp_bd_readonly.server import build_mcp


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [(c,) for c in conn.cols] if conn.cols else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)

    def fetchall(self):
        cols = [c[0] for c in self.description] if self.description else []
        return [tuple(r[c] for c in cols) if isinstance(r, dict) else r for r in self.conn.rows]


class FakeConn:
    def __init__(self, rows=None, cols=("a",)):
        self.open = True
        self.closed = False
        self.rows = rows if rows is not None else [{"a": 1}]
        self.cols = list(cols)
        self.executed = []

    def ping(self, reconnect=False):
        if not self.open:
            raise pymysql.err.OperationalError(2013, "conexión perdida")

    def close(self):
        self.closed = True
        self.open = False

    def cursor(self):
        return FakeCursor(self)


# --------------------------------------------------------------- RF-1 / RF-2
def test_pool_cierra_conexiones_ociosas():
    """Sin TTL, una sesión se queda aparcada hasta el wait_timeout de MySQL y
    el MCP se come el cupo del usuario (1203 para el resto)."""
    creadas = []

    def factory():
        conn = FakeConn()
        creadas.append(conn)
        return conn

    pool = ConnectionPool(factory, size=4, timeout=0.05, idle_s=30)
    conn = pool.acquire("ana")
    pool.release(conn, "ana")
    assert pool.stats()["ociosas"] == 1

    # Aún dentro del TTL: no se cierra nada.
    assert pool.sweep(now=time.monotonic() + 10) == 0
    assert creadas[0].closed is False

    # Pasado el TTL: se cierra y deja de contar como sesión viva.
    assert pool.sweep(now=time.monotonic() + 31) == 1
    assert creadas[0].closed is True
    assert pool.stats()["vivas"] == 0


def test_pool_no_entrega_conexion_caducada_aunque_no_haya_barrido():
    creadas = []

    def factory():
        conn = FakeConn()
        creadas.append(conn)
        return conn

    pool = ConnectionPool(factory, size=4, timeout=0.05, idle_s=0.01)
    conn = pool.acquire("ana")
    pool.release(conn, "ana")
    time.sleep(0.05)
    nueva = pool.acquire("ana")
    assert nueva is not conn
    assert creadas[0].closed is True


def test_cupo_por_api_key_no_bloquea_a_las_demas():
    pool = ConnectionPool(FakeConn, size=4, timeout=0.05, per_key=1)
    de_ana = pool.acquire("ana")
    with pytest.raises(PoolExhausted) as exc:
        pool.acquire("ana")
    assert "API key" in str(exc.value)

    # Otra persona entra sin esperar: el cupo es por clave, no global.
    de_luis = pool.acquire("luis")
    assert de_luis is not de_ana
    pool.release(de_ana, "ana")
    pool.release(de_luis, "luis")


def test_pool_no_comparte_la_conexion_entre_claves():
    """Una conexión ociosa de Ana no puede acabar sirviendo la request de Luis:
    el cupo y la trazabilidad dejarían de significar nada."""
    pool = ConnectionPool(FakeConn, size=4, timeout=0.05, idle_s=30)
    de_ana = pool.acquire("ana")
    pool.release(de_ana, "ana")
    de_luis = pool.acquire("luis")
    assert de_luis is not de_ana
    pool.release(de_luis, "luis")


def test_pool_desaloja_la_ociosa_mas_vieja_al_llegar_al_tope():
    pool = ConnectionPool(FakeConn, size=1, timeout=0.05, idle_s=30)
    vieja = pool.acquire("ana")
    pool.release(vieja, "ana")
    nueva = pool.acquire("luis")  # no hay hueco: se desaloja la de Ana
    assert nueva is not vieja
    assert vieja.closed is True
    assert pool.stats()["vivas"] == 1
    pool.release(nueva, "luis")


def test_pool_tope_global_sigue_siendo_duro():
    pool = ConnectionPool(FakeConn, size=2, timeout=0.05)
    a = pool.acquire("ana")
    b = pool.acquire("luis")
    with pytest.raises(PoolExhausted):
        pool.acquire("marta")
    pool.release(a, "ana")
    pool.release(b, "luis")


def test_close_all_respeta_las_conexiones_en_uso():
    """El apagado ordenado cierra lo ocioso pero no la conexión que está
    sirviendo una query: cerrarla en caliente rompería la respuesta en curso.
    Al devolverla, como el pool ya está cerrado, se cierra también."""
    pool = ConnectionPool(FakeConn, size=2, timeout=0.05)
    en_uso = pool.acquire("ana")
    ociosa = pool.acquire("luis")
    pool.release(ociosa, "luis")
    assert pool.stats()["ociosas"] == 1

    pool.close_all()
    assert ociosa.closed is True
    assert en_uso.closed is False
    stats = pool.stats()
    assert (stats["vivas"], stats["en_uso"], stats["ociosas"]) == (1, 1, 0)

    pool.release(en_uso, "ana")
    assert en_uso.closed is True
    assert pool.stats()["vivas"] == 0


def test_el_hilo_de_barrido_cierra_lo_ocioso_sin_llamar_a_sweep():
    """El TTL no puede depender de que alguien invoque `sweep()`: con el
    servicio parado entre consultas tiene que encargarse el hilo daemon."""
    creadas = []

    def factory():
        conn = FakeConn()
        creadas.append(conn)
        return conn

    pool = ConnectionPool(factory, size=2, timeout=0.05, idle_s=0.2)
    conn = pool.acquire("ana")
    pool.release(conn, "ana")

    limite = time.monotonic() + 5
    while time.monotonic() < limite and not creadas[0].closed:
        time.sleep(0.05)

    assert creadas[0].closed is True, "el barrido automático no cerró la conexión ociosa"
    assert pool.stats()["vivas"] == 0
    pool.close_all()


def test_stats_coherentes_tras_desalojo():
    """Tras desalojar la ociosa de una clave, `stats()` no puede seguir
    contándola ni mostrarla en `por_clave`."""
    pool = ConnectionPool(FakeConn, size=1, timeout=0.05, idle_s=30)
    vieja = pool.acquire("ana")
    pool.release(vieja, "ana")
    assert pool.stats()["por_clave"] == {"ana": {"en_uso": 0, "ociosas": 1}}

    nueva = pool.acquire("luis")  # desaloja la de Ana
    stats = pool.stats()
    assert (stats["vivas"], stats["en_uso"], stats["ociosas"]) == (1, 1, 0)
    assert stats["por_clave"] == {"luis": {"en_uso": 1, "ociosas": 0}}
    assert "ana" not in stats["por_clave"]
    assert vieja.closed is True

    pool.release(nueva, "luis")
    assert pool.stats()["por_clave"] == {"luis": {"en_uso": 0, "ociosas": 1}}


def test_fallos_de_factory_no_inflan_los_huecos():
    """Si abrir la conexión falla, el hueco reservado debe devolverse: si no,
    dos errores dejarían el pool creyéndose lleno para siempre."""
    intentos = {"n": 0}

    def factory():
        intentos["n"] += 1
        if intentos["n"] <= 2:
            raise RuntimeError("no se pudo conectar")
        return FakeConn()

    pool = ConnectionPool(factory, size=2, timeout=0.05)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            pool.acquire("ana")
        stats = pool.stats()
        assert stats["vivas"] == 0, "el hueco fallido quedó contado como vivo"
        assert stats["en_uso"] == 0, "la clave quedó con una conexión en uso fantasma"

    # La capacidad sigue intacta: dos conexiones simultáneas y la tercera espera.
    a = pool.acquire("ana")
    b = pool.acquire("luis")
    assert pool.stats()["vivas"] == 2
    with pytest.raises(PoolExhausted):
        pool.acquire("marta")
    pool.release(a, "ana")
    pool.release(b, "luis")


def test_conexion_muerta_en_ocioso_no_consume_el_cupo_de_la_clave():
    """Si la conexión ociosa se murió (reinicio de MySQL, red, wait_timeout más
    corto que el TTL), `acquire` la descarta. Ese descarte tiene que devolver
    también el contador de "en uso" de la clave: si no, `stats()` miente
    (`vivas=0`, `en_uso=1`) y el cupo por clave queda gastado para siempre."""
    pool = ConnectionPool(FakeConn, size=4, timeout=0.05, idle_s=30, per_key=1)
    muerta = pool.acquire("ana")
    pool.release(muerta, "ana")
    muerta.open = False  # se murió ya ociosa: el release no la vio

    nueva = pool.acquire("ana")  # con per_key=1 esto debe seguir siendo posible
    assert nueva is not muerta
    assert muerta.closed is True
    stats = pool.stats()
    assert (stats["vivas"], stats["en_uso"], stats["ociosas"]) == (1, 1, 0)
    assert stats["por_clave"] == {"ana": {"en_uso": 1, "ociosas": 0}}

    pool.release(nueva, "ana")
    assert pool.stats()["por_clave"] == {"ana": {"en_uso": 0, "ociosas": 1}}


# --------------------------------------------------------------------- RF-5a
def test_max_rows_es_configurable(monkeypatch):
    """En HTTP se baja de 50.000 filas: materializarlas puede agotar el
    MemoryMax=512M del unit y tumbar el servicio para todos."""
    conn = FakeConn(rows=[{"a": 1}], cols=["a"])
    monkeypatch.setattr(QueryExecutor, "_open", lambda self: conn)
    cfg = SimpleNamespace(
        host="h", port=1, user="u", password="p", db="d", max_rows=10,
        tunnel_enabled=False, query_timeout_ms=1000, slow_query_ms=5000, data_dir=None,
    )
    QueryExecutor(cfg).run("SELECT a FROM t", limit=None)
    assert conn.executed[-1].endswith("LIMIT 11")


# ----------------------------------------------------------------------- RF-4
def _client(store, auth_fail_per_min=30):
    app = Starlette(routes=[Route("/mcp", _ok, methods=["POST"])])
    app.add_middleware(
        ApiKeyMiddleware, store=store, rate_limit_per_min=120,
        auth_fail_per_min=auth_fail_per_min,
    )
    return TestClient(app)


async def _ok(_request):
    return JSONResponse({"ok": True})


def test_fallos_de_auth_se_cortan_por_cliente(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    with _client(store, auth_fail_per_min=2) as client:
        assert client.post("/mcp", headers={"Authorization": "Bearer mcp_x_y"}).status_code == 401
        assert client.post("/mcp", headers={"Authorization": "Bearer mcp_x_y"}).status_code == 401
        resp = client.post("/mcp", headers={"Authorization": "Bearer mcp_x_y"})
    assert resp.status_code == 429
    assert resp.json()["error"] == "too_many_auth_failures"
    assert resp.headers["retry-after"] == "60"


def test_fallo_de_auth_queda_registrado_sin_filtrar_el_secreto(tmp_path, capsys):
    store = KeyStore(tmp_path / "k.db")
    with _client(store) as client:
        client.post("/mcp", headers={"Authorization": "Bearer mcp_deadbeef_secretoqueno"})
    err = capsys.readouterr().err
    assert "auth fallida" in err
    assert "mcp_deadbeef" in err
    assert "secretoqueno" not in err


def test_una_clave_valida_no_gasta_el_presupuesto_de_fallos(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("buena")
    headers = {"Authorization": f"Bearer {created['key']}"}
    with _client(store, auth_fail_per_min=1) as client:
        for _ in range(3):
            assert client.post("/mcp", headers=headers).status_code == 200


def test_los_fallos_de_una_clave_no_bloquean_a_las_demas(tmp_path):
    """Detrás de nginx o del túnel el peer es siempre loopback: con el
    presupuesto por IP, una clave caducada reintentando en el IDE dejaría a
    TODO el mundo con 429 durante un minuto."""
    store = KeyStore(tmp_path / "k.db")
    buena = store.create("buena")
    with _client(store, auth_fail_per_min=2) as client:
        for _ in range(4):
            client.post("/mcp", headers={"Authorization": "Bearer mcp_vieja_vencida"})
        resp = client.post("/mcp", headers={"Authorization": f"Bearer {buena['key']}"})
    assert resp.status_code == 200


# ----------------------------------------------------------------------- RF-3
def _cfg(tmp_path, **extra):
    base = dict(
        files_dir="", data_dir=str(tmp_path), http_host="127.0.0.1", http_port=8443,
        allowed_hosts="", tunnel_enabled=False, tool_profile="",
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _tools(cfg, remote):
    mcp = build_mcp(cfg, executor=object(), audit=None, remote=remote)
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_run_script_sigue_en_stdio(tmp_path):
    assert "run_script" in _tools(_cfg(tmp_path), remote=False)


def test_run_script_no_se_registra_en_http_por_defecto(tmp_path):
    """exec() con builtins recortados no es un sandbox: en HTTP el código llega
    por la red, así que la tool no se registra salvo petición explícita."""
    assert "run_script" not in _tools(_cfg(tmp_path), remote=True)


def test_run_script_se_reactiva_explicitamente_en_http(tmp_path):
    nombres = _tools(_cfg(tmp_path, enable_run_script=True), remote=True)
    assert "run_script" in nombres


def test_run_script_desactivado_tambien_en_stdio(tmp_path):
    nombres = _tools(_cfg(tmp_path, enable_run_script=False), remote=False)
    assert "run_script" not in nombres


# --------------------------------------------------------------------- RF-5b
def test_contenido_b64_gigante_se_rechaza_antes_de_decodificar():
    from mcp_bd_readonly.tools_excel import MAX_FILE_MB, ExcelSafetyError, _load_source

    payload = "A" * (int(MAX_FILE_MB * 1024 * 1024 * 4 / 3) + 100)
    with pytest.raises(ExcelSafetyError):
        _load_source(None, payload)


def test_contenido_b64_invalido_se_rechaza():
    from mcp_bd_readonly.tools_excel import ExcelSafetyError, _load_source

    with pytest.raises(ExcelSafetyError):
        _load_source(None, "no-es-base64!!")


def test_contenido_b64_con_saltos_de_linea_se_acepta():
    from mcp_bd_readonly.tools_excel import _load_source

    crudo = base64.b64encode(b"PK\x03\x04datos").decode()
    src = _load_source(None, crudo[:4] + "\n" + crudo[4:])
    assert src.data == b"PK\x03\x04datos"


# --------------------------------------------------------------- configuración
def test_enable_run_script_es_tri_estado(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_ENABLE_RUN_SCRIPT", raising=False)
    assert load_config(tmp_path / "nada.env").enable_run_script is None
    monkeypatch.setenv("MCP_ENABLE_RUN_SCRIPT", "0")
    assert load_config(tmp_path / "nada.env").enable_run_script is False
    monkeypatch.setenv("MCP_ENABLE_RUN_SCRIPT", "1")
    assert load_config(tmp_path / "nada.env").enable_run_script is True


def test_pool_multiusuario_se_lee_del_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("MYSQL_POOL_MAX", "6")
    monkeypatch.setenv("MYSQL_POOL_IDLE_S", "45")
    monkeypatch.setenv("MYSQL_POOL_MAX_PER_KEY", "2")
    monkeypatch.setenv("MYSQL_MAX_ROWS", "10000")
    cfg = load_config(tmp_path / "nada.env")
    assert (cfg.pool_max, cfg.pool_idle_s, cfg.pool_max_per_key, cfg.max_rows) == (
        6, 45.0, 2, 10_000
    )


def test_write_config_escribe_las_variables_nuevas(tmp_path):
    from mcp_bd_readonly.config import Config

    cfg = Config(
        host="h", port=1, db="d", user="u", password="p", data_dir=tmp_path,
        tunnel_host="", pool_max=6, pool_idle_s=45, pool_max_per_key=2,
        max_rows=10_000, enable_run_script=False, auth_fail_per_min=10,
    )
    texto = write_config(cfg, path=tmp_path / "mcp.env").read_text()
    for linea in (
        "MYSQL_POOL_MAX=6", "MYSQL_POOL_IDLE_S=45", "MYSQL_POOL_MAX_PER_KEY=2",
        "MYSQL_MAX_ROWS=10000", "MCP_ENABLE_RUN_SCRIPT=0", "MCP_AUTH_FAIL_PER_MIN=10",
    ):
        assert linea in texto
