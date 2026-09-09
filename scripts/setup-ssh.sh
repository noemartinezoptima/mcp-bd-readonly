#!/bin/bash
# setup-ssh.sh — prepara SSH para mcp-bd-readonly
# Uso: bash scripts/setup-ssh.sh   (solo pide email si falta la clave)
set -euo pipefail

KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
HOST="${SSH_HOST:-db-host}"
HOSTNAME="${SSH_HOSTNAME:-db-host.example.com}"
SSH_USER="${SSH_USER:-forge}"
SSHCFG="$HOME/.ssh/config"

EM="abortando: usa 'bash scripts/setup-ssh.sh' desde la raíz del repo"

# 1) Clave SSH: generar solo si no existe
if [ ! -f "$KEY" ]; then
    echo "No existe clave $KEY."
    echo "Solo necesito un email para generarla:"
    read -r -p "Email: " EMAIL
    if [ -z "$EMAIL" ]; then
        echo "$EM"; exit 1
    fi
    echo "Generando ed25519 en $KEY..."
    ssh-keygen -t ed25519 -C "$EMAIL" -N "" -f "$KEY"
else
    echo "Clave OK: $KEY"
fi

# 2) Bloque en ~/.ssh/config: añadir si falta
mkdir -p "$HOME/.ssh"
if grep -q "Host $HOST$" "$SSHCFG" 2>/dev/null; then
    echo "Config OK: host $HOST ya definido"
else
    cat >> "$SSHCFG" << EOF

Host $HOST
  HostName $HOSTNAME
  User $SSH_USER
  IdentityFile $KEY
EOF
    chmod 600 "$SSHCFG"
    echo "Añadido host $HOST a $SSHCFG"
fi

echo
echo "===== PENDIENTE (1 paso manual) ====="
echo "Añade la clave pública al servidor (no puedo hacerlo sin credenciales):"
echo "1. Web: panel del proveedor (p.ej. Forge) > servidor $HOST > SSH Keys > Add Key"
echo "2. O con un CLI del proveedor: 'forge server:ssh-keys --server $HOST'"
echo
echo "===== CLAVE PÚBLICA (copiar) ====="
cat "$KEY.pub"
echo
echo "Cuando esté añadida, prueba: ssh $HOST 'echo OK'"
echo "Después levanta el túnel: bash scripts/tunnel.sh"