#!/bin/bash
# setup.sh — wizard de setup del MCP mcp-optima-bd (SSH + config + registro + verificación)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PY="$REPO_DIR/.venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "No existe $PY. Crea el venv: python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
fi

exec "$PY" -m mcp_bd_readonly.setup
