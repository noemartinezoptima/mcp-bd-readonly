#!/usr/bin/env pwsh
# setup.ps1 — wizard de setup del MCP mcp-optima-bd (Windows / pwsh)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoDir = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $RepoDir '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host "No existe $Py. Crea el venv: python -m venv .venv; .venv\Scripts\pip install -e ."
    exit 1
}

& $Py -m mcp_bd_readonly.setup
exit $LASTEXITCODE
