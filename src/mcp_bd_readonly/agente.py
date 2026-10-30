"""Detección dinámica del agente/harness MCP conectado al servidor.

Primario (canónico): `clientInfo.name` del handshake MCP `initialize` — todos los
clientes conformes lo envían (Claude Code → "claude", OpenCode → "opencode",
Cursor → "cursor", etc.). Se lee del contexto de la petición vía
`ctx.request_context.session.client_params.clientInfo.name`.

Fallback (heurístico, frágil): variables de entorno que cada agente setea al
spawn. Puede dar falsos positivos si varios agentes conviven en la misma shell.

NOTA: sin `from __future__ import annotations` a propósito: FastMCP detecta el
parámetro de Context por identidad (`param.annotation is Context`), y las
anotaciones diferidas (strings) rompen esa detección.
"""

import os

from mcp.server.fastmcp import Context


def detectar_por_contexto(ctx: Context | None) -> str | None:
    """Nombre del cliente MCP desde clientInfo.name del handshake initialize."""
    if ctx is None:
        return None
    try:
        session = ctx.request_context.session
    except Exception:
        return None
    for attr in ("client_params", "_client_params"):
        cp = getattr(session, attr, None)
        if cp is None:
            continue
        ci = getattr(cp, "clientInfo", None)
        if ci is not None:
            name = getattr(ci, "name", None)
            if name:
                return str(name)
    return None


def detectar_por_env(env: dict | None = None) -> str | None:
    """Heurística por variables de entorno. Marcar como no-canónico."""
    env = env if env is not None else os.environ
    if env.get("__CFBundleIdentifier") == "ai.opencode.desktop" or any(
        k.startswith("OPENCODE_") for k in env
    ):
        return "opencode"
    if any(k.startswith("CURSOR_") for k in env) or "VSCODE_NLS_CONFIG" in env:
        return "cursor"
    if any(k.startswith("CLAUDE_") for k in env):
        return "claude"
    return None


def detectar_agente(ctx: Context = None) -> dict:
    """Detecta el agente MCP conectado.

    Devuelve {'agente', 'fuente'} sin secretos. fuente ∈ {clientInfo, env, None}.
    """
    nombre = detectar_por_contexto(ctx)
    if nombre:
        return {"agente": nombre, "fuente": "clientInfo"}
    nombre = detectar_por_env()
    if nombre:
        return {"agente": nombre, "fuente": "env"}
    return {"agente": "desconocido", "fuente": None}
