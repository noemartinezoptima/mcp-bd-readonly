import json
from datetime import datetime
from pathlib import Path

from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.config import Config
from mcp_bd_readonly.tunnel import TunnelManager, _port_open


def estado_tunel(cfg: Config) -> dict:
    """Healthcheck read-only del túnel SSH: comprueba si el puerto local está abierto,
    sin intentar levantar uno nuevo. No expone credenciales."""
    abierto = _port_open(cfg.host, cfg.port)
    return {
        "abierto": abierto,
        "host": cfg.host,
        "port": cfg.port,
        "tunnel_host": cfg.tunnel_host,
    }


def auditoria(data_dir: Path, max_n: int = 100) -> dict:
    """Lee las últimas max_n líneas de data/audit.jsonl (read-only). No filtra ni
    modifica el fichero; AuditLogger nunca registra credenciales, solo tool/who/sql/note."""
    path = Path(data_dir) / "audit.jsonl"
    if not path.exists():
        return {"entradas": [], "total": 0}
    lines = path.read_text().splitlines()
    tail = lines[-max_n:] if max_n else lines
    entradas = []
    for line in tail:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row["ts_es"] = datetime.fromtimestamp(row["ts"]).strftime("%d/%m/%Y %H:%M:%S")
        entradas.append(row)
    return {"entradas": entradas, "total": len(lines)}


def build_meta_tools(cfg: Config, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("estado_tunel", "Healthcheck read-only del túnel SSH (host/puerto/estado, sin credenciales)")
    def tool_estado_tunel() -> dict:
        audit and audit.record("estado_tunel", "mcp", "estado_tunel")
        return estado_tunel(cfg)

    @_tool("auditoria", "Lee las últimas max_n entradas de auditoría (data/audit.jsonl), read-only")
    def tool_auditoria(max_n: int = 100) -> dict:
        audit and audit.record("auditoria", "mcp", "auditoria")
        return auditoria(cfg.data_dir, max_n)

    return [tool_estado_tunel, tool_auditoria]
