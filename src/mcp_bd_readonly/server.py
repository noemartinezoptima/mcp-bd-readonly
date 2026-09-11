from fastmcp import FastMCP
from mcp_bd_readonly.config import load_config
from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.tools_core import build_tools
from mcp_bd_readonly.tools_finanzas import build_finanzas_tools
from mcp_bd_readonly.tools_auditoria import build_auditoria_tools
from mcp_bd_readonly.tools_catalogo import build_catalogo_tools
from mcp_bd_readonly.tools_analisis import build_analisis_tools
from mcp_bd_readonly.tools_meta import build_meta_tools
from mcp_bd_readonly.tunnel import TunnelManager
from mcp_bd_readonly.tools_setup import setup_ssh
from mcp_bd_readonly.tools_excel import (
    check_excel_capabilities, leer_excel, resumen_excel, reconciliar_excel_bd,
)

def main():
    cfg = load_config()
    tunnel = TunnelManager(cfg)
    state = tunnel.ensure()
    if state.startswith("error"):
        print(f"TUNNEL ERROR: {state}", file=__import__("sys").stderr)
    executor = QueryExecutor(cfg)
    audit = AuditLogger(cfg.data_dir)
    mcp = FastMCP("mcp-bd-readonly")
    for fn in build_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_finanzas_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_auditoria_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_catalogo_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_analisis_tools(executor, audit):
        mcp.tool()(fn)
    for fn in build_meta_tools(cfg, audit):
        mcp.tool()(fn)
    mcp.tool()(setup_ssh)
    mcp.tool()(leer_excel)
    mcp.tool()(check_excel_capabilities)
    mcp.tool()(resumen_excel)
    mcp.tool()(reconciliar_excel_bd)
    mcp.run()

if __name__ == "__main__":
    main()
