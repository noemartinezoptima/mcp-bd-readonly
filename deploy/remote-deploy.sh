#!/usr/bin/env bash
# Script único y validado para el deploy automático de mcp-optima-bd.
# Se ejecuta COMO ROOT (vía sudo, ver sudoers más abajo), nunca directamente
# por el usuario que conecta por SSH. Toda la superficie de ataque de la
# automatización se reduce a este único fichero: valida estrictamente su
# único argumento (el tag) antes de tocar nada.
set -euo pipefail

TAG="${1:-}"

if [[ ! "$TAG" =~ ^mcp-remote-v[0-9]+\.[0-9]+$ ]]; then
  echo "tag inválido: '${TAG}' (se espera mcp-remote-vX.Y)" >&2
  exit 1
fi

REPO=/opt/mcp-optima-bd

# runuser, no `sudo -u mcp`: ya corremos como root, sudo de nuevo aquí
# añadiría una capa de autenticación innecesaria y potencialmente bloqueante.
runuser -u mcp -- git -C "$REPO" fetch --tags --quiet
runuser -u mcp -- git -C "$REPO" checkout --quiet "$TAG"
runuser -u mcp -- "$REPO/.venv/bin/pip" install -q -e "$REPO"

systemctl restart mcp-optima-bd

sleep 1
if ! curl -sf http://127.0.0.1:8443/healthz > /dev/null; then
  echo "healthz no respondió OK tras el restart (tag ${TAG})" >&2
  exit 1
fi

echo "desplegado ${TAG} OK"
