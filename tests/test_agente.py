from types import SimpleNamespace

from mcp_bd_readonly.agente import detectar_agente, detectar_por_contexto, detectar_por_env


def _ctx(name):
    return SimpleNamespace(
        request_context=SimpleNamespace(
            session=SimpleNamespace(
                client_params=SimpleNamespace(
                    clientInfo=SimpleNamespace(name=name, version="1.0")
                )
            )
        )
    )


def test_detectar_por_contexto_lee_nombre():
    assert detectar_por_contexto(_ctx("cursor")) == "cursor"
    assert detectar_por_contexto(_ctx("claude")) == "claude"


def test_detectar_por_contexto_sin_ctx():
    assert detectar_por_contexto(None) is None


def test_detectar_agente_contexto_gana_sobre_env():
    # aunque env diga cursor, el clientInfo (claude) gana
    r = detectar_agente(_ctx("claude"))
    assert r == {"agente": "claude", "fuente": "clientInfo"}


def test_detectar_por_env_opencode():
    assert detectar_por_env({"__CFBundleIdentifier": "ai.opencode.desktop"}) == "opencode"


def test_detectar_por_env_cursor():
    assert detectar_por_env({"CURSOR_LAYOUT": "glass"}) == "cursor"


def test_detectar_por_env_claude():
    assert detectar_por_env({"CLAUDE_PROJECT_DIR": "/x"}) == "claude"


def test_detectar_por_env_vacio():
    assert detectar_por_env({}) is None


def test_detectar_agente_desconocido(monkeypatch):
    monkeypatch.setattr(
        "mcp_bd_readonly.agente.os.environ", {}
    )
    assert detectar_agente(None) == {"agente": "desconocido", "fuente": None}
