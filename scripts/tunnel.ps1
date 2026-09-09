# SSH tunnel to the remote MySQL host; MCP connects to 127.0.0.1:13306
# Windows equivalent of tunnel.sh. Uses OpenSSH client (Windows 10+ built-in).
param(
    [int]$LocalPort = 13306,
    [string]$Host = (Get-Item Env:SSH_HOST -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Value)
)

$ErrorActionPreference = "Stop"

if (-not $Host) { $Host = "db-host" }

Write-Host "Tunnel: 127.0.0.1:$LocalPort -> 127.0.0.1:3306 via $Host"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Error "OpenSSH client not found. Install: Windows Settings > Apps > Optional features > OpenSSH Client."
    exit 1
}

ssh -N -L "$LocalPort`:127.0.0.1:3306" $Host