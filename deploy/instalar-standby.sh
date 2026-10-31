#!/usr/bin/env bash
# Instala mcp-optima-bd como servicio systemd en el standby (fase D1).
#
#   sudo bash instalar-standby.sh
#
# Prerrequisito: el checkout ya clonado por forge en /home/forge/mcp-optima-bd
# (con su .venv y su .env, que este script reutiliza y adapta).
# Idempotente: se puede relanzar tras un `git checkout` de otra versión.
set -euo pipefail

SRC="${SRC:-/home/forge/mcp-optima-bd}"
DST="${DST:-/opt/mcp-optima-bd}"
DATA="${DATA:-/var/lib/mcp-optima-bd}"
ENVDIR="${ENVDIR:-/etc/mcp-optima-bd}"
UNIT="/etc/systemd/system/mcp-optima-bd.service"

[ "$(id -u)" -eq 0 ] || { echo "ejecuta con sudo: sudo bash $0" >&2; exit 1; }
[ -d "$SRC/.git" ] || { echo "no hay checkout en $SRC" >&2; exit 1; }
[ -s "$SRC/.env" ] || { echo "falta $SRC/.env (MYSQL_* y MCP_*)" >&2; exit 1; }

id -u mcp >/dev/null 2>&1 || useradd --system --home "$DST" --shell /usr/sbin/nologin mcp

mkdir -p "$DST" "$DATA" "$ENVDIR"

# Claves ya emitidas: se conservan, o el cliente que las tenga deja de funcionar.
if [ -s "$SRC/data/api_keys.db" ] && [ ! -s "$DATA/api_keys.db" ]; then
    install -o mcp -g mcp -m 600 "$SRC/data/api_keys.db" "$DATA/api_keys.db"
fi

# Código: copia sin el .venv del home (tiene rutas absolutas) ni el log de pruebas.
if [ "$SRC" != "$DST" ]; then
    cp -a "$SRC/." "$DST/"
fi
rm -rf "$DST/.venv" "$DST/data"

# python3-venv no viene instalado en este Ubuntu; sin él `python3 -m venv` falla.
if ! python3 -m venv "$DST/.venv" 2>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq python3.12-venv
    python3 -m venv "$DST/.venv"
fi
"$DST/.venv/bin/pip" -q install --upgrade pip
"$DST/.venv/bin/pip" -q install -e "$DST"

# .env: los datos van al único directorio escribible que permite el unit.
sed -e "s#^DATA_DIR=.*#DATA_DIR=${DATA}#" \
    -e "s#^MCP_API_KEYS_DB=.*#MCP_API_KEYS_DB=${DATA}/api_keys.db#" \
    "$SRC/.env" > "$ENVDIR/mcp.env"
chown root:mcp "$ENVDIR/mcp.env"
chmod 640 "$ENVDIR/mcp.env"

install -m 644 "$DST/deploy/systemd/mcp-optima-bd.service" "$UNIT"
chown -R mcp:mcp "$DST" "$DATA"

systemctl daemon-reload
systemctl enable --now mcp-optima-bd
sleep 2
systemctl --no-pager --lines=0 status mcp-optima-bd || true

echo "== healthz =="
curl -s -m 5 -w '\nHTTP %{http_code}\n' http://127.0.0.1:8443/healthz || true

# Clave propia del servicio, guardada en el home de forge (no se imprime aquí).
if [ ! -s /home/forge/.mcp-api-key-finanzas ]; then
    ( umask 077
      sudo -u mcp "$DST/.venv/bin/python" -m mcp_bd_readonly.auth \
          --db "$DATA/api_keys.db" create --name finanzas > /home/forge/.mcp-api-key-finanzas )
    chown forge:forge /home/forge/.mcp-api-key-finanzas
fi
echo "clave del servicio: /home/forge/.mcp-api-key-finanzas (0600, usuario forge)"
