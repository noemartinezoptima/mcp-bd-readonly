#!/usr/bin/env bash
# Publica el MCP tras nginx en el standby (fase D2). NO toca el site de la
# plataforma: añade un vhost con su propio server_name y reutiliza el
# certificado wildcard que ya existe.
#
#   sudo bash instalar-nginx.sh
#
# Si `nginx -t` falla, se deshacen los cambios y nginx no se recarga.
#
# Ojo: este servidor ya trae real_ip de Cloudflare en
# /etc/nginx/conf.d/cloudflare.conf, así que $remote_addr es la IP del
# visitante. El control de acceso se hace con `geo $realip_remote_addr`
# (peer original) en /etc/nginx/conf.d/mcp-cloudflare-geo.conf.
set -euo pipefail

CONF="mcp-back.optimaonline.eu.conf"
AVAIL="/etc/nginx/sites-available/$CONF"
ENABLED="/etc/nginx/sites-enabled/$CONF"
GEO="/etc/nginx/conf.d/mcp-cloudflare-geo.conf"
CFSRC="/etc/nginx/conf.d/cloudflare.conf"

# El vhost se busca junto a este script (copia suelta) o en el checkout del
# servicio, para no depender de haber actualizado /opt todavía.
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC:-$HERE/$CONF}"
[ -f "$SRC" ] || SRC="/opt/mcp-optima-bd/deploy/nginx/$CONF"

[ "$(id -u)" -eq 0 ] || { echo "ejecuta con sudo: sudo bash $0" >&2; exit 1; }
[ -f "$SRC" ] || { echo "falta $SRC (copia el vhost junto a este script)" >&2; exit 1; }
echo "vhost de origen: $SRC"

CERT="/etc/nginx/ssl/back.optimaonline.eu/3521089/server.crt"
[ -f "$CERT" ] || { echo "no encuentro el certificado $CERT" >&2; exit 1; }

# 1. Rangos de Cloudflare: se derivan de la configuración que ya usa Forge.
#    Si no existe, se descargan. Fail-closed si no hay nada válido.
tmp=$(mktemp)
if [ -r "$CFSRC" ]; then
    sed -nE 's/^set_real_ip_from[[:space:]]+([0-9a-fA-F:.]+(\/[0-9]+)?);.*/\1/p' "$CFSRC" > "$tmp"
fi
if [ "$(wc -l < "$tmp")" -lt 5 ]; then
    echo "== rangos no encontrados en $CFSRC; descargando de Cloudflare =="
    { curl -fsS --max-time 15 https://www.cloudflare.com/ips-v4
      curl -fsS --max-time 15 https://www.cloudflare.com/ips-v6; } > "$tmp"
fi
grep -E '^[0-9a-fA-F:.]+(/[0-9]+)?$' "$tmp" > "$tmp.ok" || true
n=$(wc -l < "$tmp.ok")
[ "$n" -ge 5 ] || { echo "rangos inválidos ($n líneas); abortando" >&2; rm -f "$tmp" "$tmp.ok"; exit 1; }

{
    echo "# Generado por instalar-nginx.sh — solo Cloudflare (o loopback) puede"
    echo "# entrar al MCP. Se usa el peer original porque real_ip ya reescribe"
    echo "# \$remote_addr con la IP del visitante."
    echo 'geo $realip_remote_addr $mcp_from_cloudflare {'
    echo '    default 0;'
    echo '    127.0.0.1 1;'
    echo '    ::1 1;'
    sed 's/$/ 1;/' "$tmp.ok"
    echo '}'
} > "$GEO"
chmod 644 "$GEO"
rm -f "$tmp" "$tmp.ok"
echo "geo con $n rangos -> $GEO"

# 2. Vhost. Si ya existía, se guarda copia para poder volver.
[ -f "$AVAIL" ] && cp -a "$AVAIL" "$AVAIL.bak.$(date +%s)"
install -m 644 "$SRC" "$AVAIL"
ln -sfn "$AVAIL" "$ENABLED"

# 3. Validar antes de recargar. Si falla, se revierte todo.
if ! nginx -t; then
    echo "nginx -t FALLÓ: revierto el vhost y el geo; no recargo nada." >&2
    rm -f "$ENABLED" "$AVAIL" "$GEO"
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
echo "== la plataforma sigue respondiendo =="
curl -s -o /dev/null -w 'back.optimaonline.eu HTTP %{http_code}\n' \
     --resolve back.optimaonline.eu:443:127.0.0.1 \
     https://back.optimaonline.eu/ || true

echo
echo "Falta solo el DNS: A  mcp-back  ->  167.233.70.237  (proxied en Cloudflare)."
echo "Para deshacer todo:"
echo "  rm -f $ENABLED $AVAIL $GEO && nginx -t && systemctl reload nginx"
