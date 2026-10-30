#!/usr/bin/env bash
# Publica el MCP tras nginx en el standby (fase D2). NO toca el site de la
# plataforma: añade un vhost con su propio server_name y reutiliza el
# certificado wildcard que ya existe.
#
#   sudo bash instalar-nginx.sh
#
# Si `nginx -t` falla, se deshace el enlace y nginx no se recarga.
set -euo pipefail

CONF="mcp-back.optimaonline.eu.conf"
AVAIL="/etc/nginx/sites-available/$CONF"
ENABLED="/etc/nginx/sites-enabled/$CONF"
SNIPPET="/etc/nginx/snippets/cloudflare-ips.conf"
# El vhost se busca junto a este script (copia suelta) o en el checkout del
# servicio, para no depender de haber actualizado /opt todavía.
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC:-$HERE/$CONF}"
[ -f "$SRC" ] || SRC="/opt/mcp-optima-bd/deploy/nginx/$CONF"

[ "$(id -u)" -eq 0 ] || { echo "ejecuta con sudo: sudo bash $0" >&2; exit 1; }
[ -f "$SRC" ] || { echo "falta $SRC" >&2; exit 1; }

# Mismas rutas de certificado que el vhost de la plataforma (wildcard Origin CA).
CERT="/etc/nginx/ssl/back.optimaonline.eu/3521089/server.crt"
[ -f "$CERT" ] || { echo "no encuentro el certificado $CERT" >&2; exit 1; }

# 1. Lista de IPs de Cloudflare (fail-closed: si no se descarga, no seguimos).
if [ ! -s "$SNIPPET" ]; then
    echo "== descargando rangos de Cloudflare =="
    tmp=$(mktemp)
    { curl -fsS --max-time 15 https://www.cloudflare.com/ips-v4
      curl -fsS --max-time 15 https://www.cloudflare.com/ips-v6; } \
        | grep -E '^[0-9a-fA-F:.]+/[0-9]+$' | sed 's/^/allow /; s/$/;/' > "$tmp"
    [ "$(wc -l < "$tmp")" -ge 20 ] || { echo "descarga de rangos sospechosa; abortando" >&2; rm -f "$tmp"; exit 1; }
    install -m 644 "$tmp" "$SNIPPET"
    rm -f "$tmp"
fi

# 2. Vhost. Si ya existía, se guarda copia para poder volver.
if [ -f "$AVAIL" ]; then
    cp -a "$AVAIL" "$AVAIL.bak.$(date +%s)"
fi
install -m 644 "$SRC" "$AVAIL"
ln -sfn "$AVAIL" "$ENABLED"

# 3. Validar antes de recargar. Si falla, se retira el vhost y se sale.
if ! nginx -t; then
    echo "nginx -t FALLÓ: retiro el vhost y no recargo." >&2
    rm -f "$ENABLED"
    exit 1
fi
systemctl reload nginx

echo "== verificación local (sin DNS todavía) =="
curl -s --resolve mcp-back.optimaonline.eu:443:127.0.0.1 \
     -o /dev/null -w 'healthz HTTP %{http_code}\n' \
     https://mcp-back.optimaonline.eu/healthz || true
curl -s --resolve mcp-back.optimaonline.eu:443:127.0.0.1 \
     -o /dev/null -w 'mcp sin clave HTTP %{http_code} (esperado 401)\n' \
     -X POST -H 'content-type: application/json' -d '{}' \
     https://mcp-back.optimaonline.eu/mcp || true

echo
echo "Falta solo el DNS: A  mcp-back  ->  167.233.70.237  (proxied en Cloudflare)."
echo "Para deshacer todo:  rm $ENABLED && nginx -t && systemctl reload nginx"
