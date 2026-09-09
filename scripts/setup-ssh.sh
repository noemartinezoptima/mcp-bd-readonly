#!/bin/bash
# setup-ssh.sh — prepara SSH para mcp-bd-readonly (Forge optimaback)
# Uso: bash scripts/setup-ssh.sh   (solo pide email si falta la clave)
set -euo pipefail

KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
HOST="db-host"
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
  HostName db-host.example.com
  User forge
  IdentityFile $KEY
EOF
    chmod 600 "$SSHCFG"
    echo "Añadido host $HOST a $SSHCFG"
fi

echo
echo "===== PENDIENTE (1 paso manual) ====="
echo "Añade la clave pública a Forge (no puedo hacerlo sin credenciales):"
echo "1. Web: forge.laravel.com > db-host > SSH Keys > Add Key"
echo "2. O con forge-cli: 'forge server:ssh-keys --server db-host'"
echo
echo "===== CLAVE PÚBLICA (copiar) ====="
cat "$KEY.pub"
echo
echo "Cuando esté añadida, prueba: ssh db-host 'echo OK'"
echo "Después levanta el túnel: bash scripts/tunnel.sh"