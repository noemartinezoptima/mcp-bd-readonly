from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_bd_readonly.auth import KeyStore
from mcp_bd_readonly.http_app import ApiKeyMiddleware, build_app


async def ok(_request):
    return JSONResponse({"ok": True})


def make_client(store, rate_limit_per_min=120):
    app = Starlette(routes=[
        Route("/mcp", ok, methods=["POST"]),
        Route("/healthz", ok, methods=["GET"]),
    ])
    app.add_middleware(ApiKeyMiddleware, store=store, rate_limit_per_min=rate_limit_per_min)
    return TestClient(app)


def test_sin_token_devuelve_401(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    with make_client(store) as client:
        resp = client.post("/mcp")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"].startswith("Bearer")
    assert resp.json()["error"] == "unauthorized"


def test_token_invalido_devuelve_401(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    with make_client(store) as client:
        resp = client.post("/mcp", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_token_valido_pasa(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("test")
    with make_client(store) as client:
        resp = client.post("/mcp", headers={"Authorization": f"Bearer {created['key']}"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_healthz_no_requiere_auth(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    with make_client(store) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200


def test_rate_limit_devuelve_429(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("limitada")
    headers = {"Authorization": f"Bearer {created['key']}"}
    with make_client(store, rate_limit_per_min=2) as client:
        assert client.post("/mcp", headers=headers).status_code == 200
        assert client.post("/mcp", headers=headers).status_code == 200
        resp = client.post("/mcp", headers=headers)
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "60"


def test_clave_revocada_deja_de_pasar(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("revocable")
    store.revoke(created["id"])
    with make_client(store) as client:
        resp = client.post("/mcp", headers={"Authorization": f"Bearer {created['key']}"})
    assert resp.status_code == 401


def test_key_sin_alcance_read_devuelve_403(tmp_path):
    """El alcance tiene que aplicarse en el HTTP: antes de esto, --scopes era
    decorativo y una key sin 'read' pasaba igual que cualquier otra."""
    store = KeyStore(tmp_path / "k.db")
    created = store.create("parcial", scopes=("nada",))
    with make_client(store) as client:
        resp = client.post("/mcp", headers={"Authorization": f"Bearer {created['key']}"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden"


def test_key_sin_scopes_devuelve_403(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("vacia", scopes=())
    with make_client(store) as client:
        resp = client.post("/mcp", headers={"Authorization": f"Bearer {created['key']}"})
    assert resp.status_code == 403


def test_key_con_admin_incluye_read_y_pasa(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("root", scopes=("admin",))
    with make_client(store) as client:
        resp = client.post("/mcp", headers={"Authorization": f"Bearer {created['key']}"})
    assert resp.status_code == 200


def test_key_sin_alcance_tambien_consume_rate_limit(tmp_path):
    """El 403 no puede saltarse el rate limit: si el alcance se comprueba antes,
    una key con alcance inválido recibe 403 sin gastar presupuesto y puede
    martillear el endpoint sin límite."""
    store = KeyStore(tmp_path / "k.db")
    created = store.create("parcial", scopes=("nada",))
    headers = {"Authorization": f"Bearer {created['key']}"}
    with make_client(store, rate_limit_per_min=2) as client:
        assert client.post("/mcp", headers=headers).status_code == 403
        assert client.post("/mcp", headers=headers).status_code == 403
        assert client.post("/mcp", headers=headers).status_code == 429


def test_healthz_no_mira_alcances(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    created = store.create("parcial", scopes=("nada",))
    with make_client(store) as client:
        resp = client.get("/healthz", headers={"Authorization": f"Bearer {created['key']}"})
    assert resp.status_code == 200


class FakeMCP:
    def streamable_http_app(self):
        return Starlette(routes=[Route("/mcp", ok, methods=["POST"])])


class FakeRouter:
    def estado(self):
        return {"destino": "replica", "replica": {"ok": True, "lag_s": 0.0}}


def test_build_app_expone_healthz_y_protege_mcp(tmp_path):
    store = KeyStore(tmp_path / "k.db")
    app = build_app(FakeMCP(), store, router=FakeRouter(), rate_limit_per_min=10)
    with TestClient(app) as client:
        salud = client.get("/healthz")
        assert salud.status_code == 200
        body = salud.json()
        assert body["status"] == "ok"
        assert body["replica"]["destino"] == "replica"
        assert client.post("/mcp").status_code == 401
