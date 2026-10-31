#!/usr/bin/env bash
# Comando FORZADO de la clave de despliegue de GitHub Actions (ver
# `command=` en authorized_keys, más abajo en deploy/README.md). Corre como
# `forge`, sin shell libre: lo único que puede hacer quien use esa clave es
# invocar esto, que a su vez solo puede invocar remote-deploy.sh como root
# (sudoers NOPASSWD acotado a ese único script).
#
# El cliente SSH manda el tag como "comando" (`ssh ... forge@host '<tag>'`);
# sshd lo expone en SSH_ORIGINAL_COMMAND en vez de ejecutarlo directamente,
# justamente porque hay un `command=` forzado.
set -euo pipefail

TAG="${SSH_ORIGINAL_COMMAND:-}"

if [[ -z "$TAG" ]]; then
  echo "uso: ssh -i <deploy_key> forge@<host> '<tag>'" >&2
  exit 1
fi

exec sudo /opt/mcp-optima-bd/deploy/remote-deploy.sh "$TAG"
