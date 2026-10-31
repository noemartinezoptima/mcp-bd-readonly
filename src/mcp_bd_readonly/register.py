"""Registro idempotente del servidor MCP `mcp-optima-bd` en los agentes.

Soporta 4 targets con formatos reales verificados:
- claude-code      ~/.claude.json            -> mcpServers  (JSON)
- opencode         ~/.config/opencode/opencode.jsonc -> mcp (JSONC, con comentarios)
- cursor           ~/.cursor/mcp.json        -> mcpServers  (JSON)
- claude-desktop   claude_desktop_config.json -> mcpServers (JSON)

Sin contraseña en el config: el servidor lee credenciales de ~/.zt-readonly.env.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MCP_NAME = "mcp-optima-bd"


def _home() -> Path:
    return Path.home()


# ---------------------------------------------------------------- paths

def _claude_code_path() -> Path:
    return _home() / ".claude.json"


def _opencode_path() -> Path:
    return _home() / ".config" / "opencode" / "opencode.jsonc"


def _cursor_path() -> Path:
    return _home() / ".cursor" / "mcp.json"


def _claude_desktop_path() -> Path:
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else _home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    return _home() / ".config" / "Claude" / "claude_desktop_config.json"


TARGETS = {
    "claude-code": _claude_code_path,
    "opencode": _opencode_path,
    "cursor": _cursor_path,
    "claude-desktop": _claude_desktop_path,
}


# ---------------------------------------------------------------- entries

def _mcp_servers_entry(command: str) -> dict:
    return {"type": "stdio", "command": command, "args": []}


def _cursor_entry(command: str) -> dict:
    return {"command": command, "args": []}


def _desktop_entry(command: str) -> dict:
    return {"command": command}


# ---------------------------------------------------------------- JSON merge

def _merge_mcp_servers(path: Path, command: str, entry: dict, dry_run: bool) -> str:
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    if MCP_NAME in servers:
        return "ya_presente"
    if dry_run:
        return "dry_run"
    servers[MCP_NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return "ok"


# ---------------------------------------------------------------- OpenCode JSONC

def _opencode_entry_block(command: str) -> str:
    return (
        '    "mcp-optima-bd": {\n'
        '      "type": "local",\n'
        f'      "command": [{json.dumps(command)}],\n'
        '      "enabled": true,\n'
        '      "timeout": 60000\n'
        '    },\n'
    )


def _merge_opencode(path: Path, command: str, dry_run: bool) -> str:
    if path.exists():
        text = path.read_text()
    else:
        text = ""
    if MCP_NAME in text:
        return "ya_presente"
    if dry_run:
        return "dry_run"
    block = _opencode_entry_block(command)
    m = re.search(r'"mcp"\s*:\s*\{', text)
    if m:
        text = text[: m.end()] + "\n" + block + text[m.end():]
    else:
        # sin bloque "mcp": añadir clave antes del cierre final
        entry = '  "mcp": {\n' + block + '  },\n'
        stripped = text.rstrip()
        if stripped.endswith("}"):
            text = stripped[: stripped.rfind("}")] + entry + "}\n"
        else:
            text = stripped + "\n" + entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return "ok"


# ---------------------------------------------------------------- API

def register_mcp(command: str, targets: list[str] | None = None, dry_run: bool = False) -> dict:
    """Registra `mcp-optima-bd` (comando `command`) en los targets pedidos.

    Devuelve {target: {"status", "path"}} con status en
    ok | ya_presente | dry_run | error.
    """
    if targets is None:
        targets = list(TARGETS)
    result = {}
    for t in targets:
        path_fn = TARGETS.get(t)
        if path_fn is None:
            result[t] = {"status": "error", "path": "", "message": f"target desconocido: {t}"}
            continue
        path = path_fn()
        try:
            if t == "opencode":
                status = _merge_opencode(path, command, dry_run)
            elif t == "claude-code":
                status = _merge_mcp_servers(path, command, _mcp_servers_entry(command), dry_run)
            elif t == "cursor":
                status = _merge_mcp_servers(path, command, _cursor_entry(command), dry_run)
            elif t == "claude-desktop":
                status = _merge_mcp_servers(path, command, _desktop_entry(command), dry_run)
            else:
                status = "error"
            result[t] = {"status": status, "path": str(path)}
        except Exception as e:  # noqa: BLE001 — registro no debe tumbar el wizard
            result[t] = {"status": "error", "path": str(path), "message": str(e)}
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Registra mcp-optima-bd en los agentes.")
    ap.add_argument("--command", required=True, help="ruta absoluta al ejecutable del MCP")
    ap.add_argument("--targets", nargs="*", default=None, help="claude-code opencode cursor claude-desktop")
    ap.add_argument("--dry-run", action="store_true", help="solo reporta, no escribe")
    args = ap.parse_args(argv)

    for t, r in register_mcp(args.command, args.targets, args.dry_run).items():
        print(f"{t}: {r['status']} ({r['path']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
