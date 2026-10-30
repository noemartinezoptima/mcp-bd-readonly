import argparse
import atexit
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_bd_readonly import file_guard
from mcp_bd_readonly.config import load_config
from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.router import build_router
from mcp_bd_readonly.tools_core import build_tools, build_glosario_tools
from mcp_bd_readonly.esquema_snapshot import build_schema_tools
from mcp_bd_readonly.catalogo_queries import build_queries_tools
from mcp_bd_readonly.memoria import build_memoria_tools
from mcp_bd_readonly.prompts import build_prompts
from mcp_bd_readonly.tools_finanzas import build_finanzas_tools
from mcp_bd_readonly.tools_auditoria import build_auditoria_tools
from mcp_bd_readonly.tools_catalogo import build_catalogo_tools
from mcp_bd_readonly.tools_analisis import build_analisis_tools
from mcp_bd_readonly.tools_gastos import build_gastos_tools
from mcp_bd_readonly.tools_stock import build_stock_tools
from mcp_bd_readonly.tools_balance import build_balance_tools
from mcp_bd_readonly.tools_meta import build_meta_tools
from mcp_bd_readonly.tunnel import TunnelManager
from mcp_bd_readonly.tools_setup import setup_ssh
from mcp_bd_readonly.agente import detectar_agente
from mcp_bd_readonly.tools_excel import (
    check_excel_capabilities, leer_excel, resumen_excel, reconciliar_excel_bd,
)

# Se envía en CADA initialize, así que aquí solo caben las trampas duras y el
# puntero a los guiones; el detalle vive en prompts.py, que se carga bajo demanda.
INSTRUCTIONS = (
    "MCP Optima BD — acceso SOLO-LECTURA a la BD de Optima (back): facturas, OT, "
    "cobros, remesas, establecimientos. Guard read-only: jamás ejecuta "
    "INSERT/UPDATE/DELETE/DDL. Consulta en lenguaje natural; usa run_query o las "
    "tools del catálogo.\n"
    "ANTES de escribir SQL llama resolve_domain_term(tu pregunta en español): te "
    "devuelve tabla, tool y trampas. Tres errores que se repiten: base_euros solo "
    "existe en la tabla ots; efectos_pago es polimórfico (12=venta, 11=compra) y no "
    "tiene cliente_id, su fecha es fecha_pagado; no existe cobros_remesas. "
    "Guiones completos en prompts/list: sql_seguro, iva_trimestral, riesgo_cobros, "
    "ot_abiertas."
)


def excel_paths_allowed(remote: bool, cfg) -> bool:
    """Si en este modo se admiten rutas de fichero para las tools de Excel.

    En remoto, por defecto NO: el Excel llega en `contenido_b64` y se procesa en
    memoria, sin escribir nada en el servidor. Con MCP_FILES_DIR se permite
    además leer ficheros de ese directorio (p. ej. un drop de conciliaciones).
    """
    if not remote:
        return True
    return bool((getattr(cfg, "files_dir", "") or "").strip())


def allowed_hosts(cfg, port: int) -> list[str]:
    raw = [h.strip() for h in (getattr(cfg, "allowed_hosts", "") or "").split(",") if h.strip()]
    if raw:
        return raw
    return [f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"]


def build_mcp(cfg, executor, audit, *, remote: bool = False) -> FastMCP:
    kwargs = {}
    if remote:
        kwargs = dict(
            host=cfg.http_host,
            port=cfg.http_port,
            streamable_http_path="/mcp",
            # JSON puntual en vez de SSE largo: evita cortes detrás de
            # Cloudflare/nginx y simplifica el proxy.
            json_response=True,
            # Sin sesiones en memoria: permite varios workers y no deja
            # sesiones huérfanas si un cliente muere.
            stateless_http=True,
            session_idle_timeout=300,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=allowed_hosts(cfg, cfg.http_port),
            ),
        )
    mcp = FastMCP("mcp-optima-bd", instructions=INSTRUCTIONS, **kwargs)

    for fn in build_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_glosario_tools(audit):
        mcp.tool()(fn)
    for fn in build_finanzas_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_auditoria_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_catalogo_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_analisis_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_gastos_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_stock_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_balance_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_meta_tools(cfg, audit):
        mcp.tool()(fn)
    for fn in build_schema_tools(executor, audit, cfg.data_dir):
        mcp.tool()(fn)
    for fn in build_queries_tools(audit):
        mcp.tool()(fn)
    for fn in build_memoria_tools(audit, cfg.data_dir):
        mcp.tool()(fn)
    # setup_ssh escribe en el sistema de ficheros y en ~/.ssh/config: en el
    # servidor remoto lo usa el operador por SSH, no un cliente MCP.
    if not remote:
        mcp.tool()(setup_ssh)
    mcp.tool()(detectar_agente)

    # Guiones MCP: el agente los pide con prompts/get, no viajan en el handshake.
    build_prompts(mcp)

    # Excel: en remoto no se leen rutas del servidor; el contenido llega en
    # base64 y se procesa en memoria (cero escritura en disco).
    file_guard.configure(cfg.files_dir or None, allow_paths=excel_paths_allowed(remote, cfg))
    mcp.tool()(leer_excel)
    mcp.tool()(check_excel_capabilities)
    mcp.tool()(resumen_excel)
    mcp.tool()(reconciliar_excel_bd)
    return mcp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Servidor MCP de solo lectura sobre MySQL (back).")
    ap.add_argument("--transport", choices=("stdio", "http"), default="stdio",
                    help="stdio (local, default) o http (servicio remoto con API keys)")
    ap.add_argument("--host", default=None, help="host de escucha en modo http")
    ap.add_argument("--port", type=int, default=None, help="puerto de escucha en modo http")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.host:
        cfg.http_host = args.host
    if args.port:
        cfg.http_port = args.port
    remote = args.transport == "http"

    if not remote and cfg.tunnel_enabled:
        state = TunnelManager(cfg).ensure()
        if state.startswith("error"):
            print(f"TUNNEL ERROR: {state}", file=sys.stderr)

    executor = build_router(cfg)
    audit = AuditLogger(cfg.data_dir)
    mcp = build_mcp(cfg, executor, audit, remote=remote)
    atexit.register(getattr(executor, "close", lambda: None))

    if not remote:
        mcp.run()
        return 0

    import uvicorn

    from mcp_bd_readonly.auth import KeyStore
    from mcp_bd_readonly.http_app import build_app

    store = KeyStore(cfg.api_keys_path)
    app = build_app(mcp, store, router=executor, rate_limit_per_min=cfg.rate_limit_per_min)
    uvicorn.run(
        app,
        host=cfg.http_host,
        port=cfg.http_port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
