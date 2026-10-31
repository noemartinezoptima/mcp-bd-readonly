#!/usr/bin/env bash
# Script único y validado para el deploy automático de mcp-optima-bd.
# Se ejecuta COMO ROOT (vía sudo, ver sudoers más abajo), nunca directamente
# por el usuario que conecta por SSH. Toda la superficie de ataque de la
# automatización se reduce a este único fichero: valida estrictamente su
# único argumento (el tag) antes de tocar nada.
set -euo pipefail

# Log persistente: un fallo silencioso del deploy automático (confirmado:
# 4º disparo real, 31-oct-2026, exit 1 sin NINGÚN output visible ni por SSH
# directo ni por el workflow) no se puede diagnosticar sin rastro en disco.
LOG=/var/lib/mcp-optima-bd/deploy.log
exec > >(tee -a "$LOG") 2> >(tee -a "$LOG" >&2)
echo "=== deploy $(date -Is) tag=${1:-<ninguno>} ==="
set -x

TAG="${1:-}"

if [[ ! "$TAG" =~ ^mcp-remote-v[0-9]+\.[0-9]+$ ]]; then
  echo "tag inválido: '${TAG}' (se espera mcp-remote-vX.Y)" >&2
  exit 1
fi

REPO=/opt/mcp-optima-bd

# runuser, no `sudo -u mcp`: ya corremos como root, sudo de nuevo aquí
# añadiría una capa de autenticación innecesaria y potencialmente bloqueante.
#
# core.fileMode=false + checkout --force: este checkout es un DEPLOY TARGET,
# no un workspace de desarrollo. Un chmod/chown manual posterior al deploy
# (como el que se hizo a mano para dejar remote-deploy.sh en root:root) deja
# el bit de ejecución "modificado" a ojos de git y el siguiente checkout
# aborta con "local changes would be overwritten" (confirmado: 2º disparo
# real, 31-oct-2026). Nunca debe bloquear un deploy por eso.
runuser -u mcp -- git -C "$REPO" config core.fileMode false
runuser -u mcp -- git -C "$REPO" fetch --tags --quiet
runuser -u mcp -- git -C "$REPO" checkout --quiet --force "$TAG"
runuser -u mcp -- "$REPO/.venv/bin/pip" install -q -e "$REPO"

systemctl restart mcp-optima-bd

# Reintenta en vez de un sleep fijo: el arranque en frío (pool de conexiones,
# registro de ~37 tools) es variable y los dos primeros disparos reales
# (31-oct-2026) dieron falsos negativos aquí con el servicio ya sano (uno con
# 1s fijo, otro con 10s de margen). 30s de margen, con early-exit en cuanto
# responde.
ok=0
for _ in $(seq 1 30); do
  sleep 1
  if curl -sf --max-time 2 http://127.0.0.1:8443/healthz > /dev/null; then
    ok=1
    break
  fi
done

if [[ "$ok" -ne 1 ]]; then
  echo "healthz no respondió OK tras 30s del restart (tag ${TAG})" >&2
  exit 1
fi

echo "desplegado ${TAG} OK"
