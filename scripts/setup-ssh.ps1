#!/usr/bin/env pwsh
# setup-ssh.ps1 — prepara SSH para mcp-optima-bd (Windows / pwsh)
# Uso: pwsh scripts/setup-ssh.ps1   (solo pide email si falta la clave)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# NOTE: evitar $Host y $HOME como variables de script (reservadas/read-only en PowerShell).
$SshKey  = if ($env:SSH_KEY)      { $env:SSH_KEY }      else { Join-Path $HOME '.ssh\id_ed25519' }
$SshHost = if ($env:SSH_HOST)     { $env:SSH_HOST }     else { 'db-host' }
$SshName = if ($env:SSH_HOSTNAME) { $env:SSH_HOSTNAME } else { 'db-host.example.com' }
$SshUser = if ($env:SSH_USER)     { $env:SSH_USER }     else { 'forge' }
$SshCfg  = if ($env:SSH_CONFIG)   { $env:SSH_CONFIG }   else { Join-Path $HOME '.ssh\config' }

if (-not (Get-Command ssh-keygen -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: ssh-keygen no encontrado en PATH. Instala OpenSSH Client.'
    exit 1
}

# 1) Clave SSH: generar solo si no existe
if (-not (Test-Path -LiteralPath $SshKey)) {
    Write-Host "No existe clave $SshKey."
    $email = Read-Host -Prompt 'Email'
    if ([string]::IsNullOrWhiteSpace($email)) {
        Write-Host "abortando: usa 'pwsh scripts/setup-ssh.ps1' desde la raíz del repo"
        exit 1
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SshKey) | Out-Null
    ssh-keygen -t ed25519 -C $email -N "" -f $SshKey
    Write-Host "Generada clave ed25519 en $SshKey (comentario: $email)"
} else {
    Write-Host "Clave OK: $SshKey (ya existía)"
}

# 2) Bloque en ~/.ssh/config: añadir si falta
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SshCfg) | Out-Null
$block = "`nHost $SshHost`n  HostName $SshName`n  User $SshUser`n  IdentityFile $SshKey`n"

if (-not (Test-Path -LiteralPath $SshCfg)) {
    Set-Content -LiteralPath $SshCfg -Value $block -Encoding utf8
    Write-Host "Añadido host $SshHost ($SshName, user $SshUser) a $SshCfg"
} else {
    $content = Get-Content -LiteralPath $SshCfg -Raw
    if ($content -match ("(?m)^Host " + [regex]::Escape($SshHost) + "$")) {
        Write-Host "Config OK: host $SshHost ya definido"
    } else {
        Add-Content -LiteralPath $SshCfg -Value $block -Encoding utf8
        Write-Host "Añadido host $SshHost ($SshName, user $SshUser) a $SshCfg"
    }
}

# 3) Clave pública (copiar al servidor, 1 paso manual)
$publicKey = (Get-Content -LiteralPath "$SshKey.pub" -Raw).Trim()
Write-Host ''
Write-Host '===== PENDIENTE (1 paso manual) ====='
Write-Host 'Añade la clave pública al servidor (no puedo hacerlo sin credenciales):'
Write-Host "1. Web: panel del proveedor (p.ej. Forge) > servidor $SshHost > SSH Keys > Add Key"
Write-Host "2. O con un CLI del proveedor: 'forge server:ssh-keys --server $SshHost'"
Write-Host ''
Write-Host '===== CLAVE PÚBLICA (copiar) ====='
Write-Host $publicKey
Write-Host ''
Write-Host "Cuando esté añadida, prueba: ssh $SshHost 'echo OK'"
Write-Host 'Después levanta el túnel: pwsh scripts/tunnel.ps1'
