"""Wizard interactivo de setup del MCP `mcp-optima-bd`.

Orquesta, en orden:
1. SSH (clave ed25519 + bloque ~/.ssh/config)  -> tools_setup.setup_ssh
2. Credenciales MySQL                          -> config.write_config
3. Registro en los agentes                     -> register.register_mcp
4. Verificación best-effort (SELECT 1)         -> db.QueryExecutor

Invocable como:  python -m mcp_bd_readonly.setup
(o vía scripts/setup.sh y scripts/setup.ps1).
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from mcp_bd_readonly.config import Config, write_config
from mcp_bd_readonly.register import register_mcp
from mcp_bd_readonly.tools_setup import setup_ssh


def mcp_command() -> str:
    """Ruta absoluta al ejecutable del MCP dentro del venv."""
    repo = Path(__file__).resolve().parent.parent.parent
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    return str(repo / ".venv" / bin_dir / "mcp-optima-bd")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def _step_ssh() -> tuple[str, dict]:
    """Pregunta todo dinámicamente: generar clave (s/N), ruta, alias/hostname/user SSH."""
    gen = _ask("¿Generar clave SSH nueva? (s/N)", "n").strip().lower().startswith("s")
    email = None
    if gen:
        email = _ask("Email para la clave SSH")
        if not email:
            return "", {"ok": False, "error": "Email requerido para generar la clave SSH."}
    key_path = _ask("Ruta de la clave SSH", "~/.ssh/id_ed25519")
    host = _ask("Alias SSH del servidor", "db-host")
    hostname = _ask("Hostname/IP del servidor", "")
    user = _ask("Usuario SSH", "forge")
    res = setup_ssh(
        email=email,
        confirmar=True,
        host=host,
        hostname=hostname,
        user=user,
        key_path=key_path,
    )
    return host, res


def _step_config(tunnel_default: str = "db-host") -> Config:
    print("\n-- Credenciales MySQL (se guardan en ~/.zt-readonly.env, modo 600) --")
    host = _ask("MYSQL_HOST", "127.0.0.1")
    port = int(_ask("MYSQL_PORT", "13306"))
    db = _ask("MYSQL_DB", "back")
    user = _ask("MYSQL_USER", "back_readonly")
    password = getpass.getpass("MYSQL_PASSWORD: ")
    tunnel_host = _ask("TUNNEL_HOST (alias SSH)", tunnel_default)
    data_dir = _ask("DATA_DIR", "./data")
    return Config(
        host=host,
        port=port,
        db=db,
        user=user,
        password=password,
        data_dir=Path(data_dir),
        tunnel_host=tunnel_host,
    )


def _step_verify(cfg: Config) -> str:
    from mcp_bd_readonly.db import QueryExecutor

    try:
        cols, rows = QueryExecutor(cfg).run("SELECT 1", limit=1)
        if rows:
            return f"OK: SELECT 1 -> {rows[0]}"
        return "OK: SELECT 1 devolvió 0 filas (inesperado)"
    except Exception as e:  # noqa: BLE001 — best-effort
        return f"NO verificado: {e}"


def run_setup() -> dict:
    summary = {}

    print("=== 1/4 SSH ===")
    host_alias, ssh = _step_ssh()
    summary["ssh"] = ssh
    if not ssh.get("ok"):
        return summary
    if ssh.get("clave_publica"):
        print("\nAñade esta clave pública al servidor (1 paso manual):")
        print(f"  {ssh['clave_publica'][:64]}…")
        print(f"  Luego prueba: ssh {ssh.get('host', host_alias)} 'echo OK'")
        _ask("Pulsa Enter cuando la clave esté añadida (o Ctrl+C para salir)", "")

    print("\n=== 2/4 Config MySQL ===")
    cfg = _step_config(tunnel_default=host_alias)
    dest = write_config(cfg, force=True)
    summary["config"] = {"path": str(dest)}

    print("\n=== 3/4 Registro en agentes ===")
    command = mcp_command()
    reg = register_mcp(command)
    summary["register"] = reg
    for t, r in reg.items():
        print(f"  {t}: {r['status']} ({r['path']})")

    print("\n=== 4/4 Verificación ===")
    verify = _step_verify(cfg)
    summary["verify"] = verify
    print(f"  {verify}")

    print("\nSetup completo." if "NO verificado" not in verify else "\nSetup casi completo: levanta el túnel y vuelve a probar.")
    return summary


def main() -> int:
    run_setup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
