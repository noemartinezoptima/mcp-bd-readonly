#!/bin/bash
# SSH tunnel to optimaback Forge host; MCP connects to 127.0.0.1:13306
set -euo pipefail
PORT="${LOCAL_PORT:-13306}"
echo "Tunnel: 127.0.0.1:$PORT -> 127.0.0.1:3306 via db-host"
exec ssh -N -L "$PORT:127.0.0.1:3306" db-host