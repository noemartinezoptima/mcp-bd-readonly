# Plan — Setup MCP + reconexión

Proyecto personal/interno → entregable local (sin Jira). Sin proceso formal de cambios (no `openspec/` ni `CLAUDE.md`).

## Alcance

- CLI wizard `scripts/setup.sh` + `scripts/setup.ps1`
- Registrar MCP en 4 agentes: Claude Code, OpenCode, Cursor, Claude Desktop
- Windows completo
- Reconexión = túnel SSH reactivo (ya implementado, solo verificar)

## Estado

- C1 ✅ `config.write_config()` + tests
- C2 ✅ `scripts/setup-ssh.ps1` (verificado end-to-end, idempotente)
- C4 ✅ `src/mcp_bd_readonly/register.py` + CLI + tests
- C3 ✅ `src/mcp_bd_readonly/setup.py` + `scripts/setup.sh`/`.ps1`
- C5 ✅ reconexión túnel ya cubierta por tests existentes

## Changes

### C1 — Generador de `.zt-readonly.env` (writer) · Pequeño · BASE

- **Existe:** `config.py:29 load_config()` — solo lee. No hay writer.
- **Construir:** `write_config()` que serializa Config → `Path.home()/.zt-readonly.env`.
- **AC:** 9 campos; `chmod 0600`; idempotente (no pisa salvo `--force`); cross-platform.

### C2 — `scripts/setup-ssh.ps1` · Pequeño-Mediano · BASE

- **Existe:** `scripts/setup-ssh.sh` (bash). No hay `.ps1`.
- **Construir:** port a PowerShell: genera ed25519 si falta, añade bloque `Host db-host` a `~/.ssh/config`, imprime pubkey.
- **AC:** misma salida que bash; idempotente; usa `$SSH_HOST/$SSH_HOSTNAME/$SSH_USER/$SSH_KEY`.

### C4 — Registro MCP↔agente (4 formatos) · Mediano · INDEPENDIENTE

- **Existe:** manual en `client-notes.md`. Sin tool.
- **Construir:** escribir entry `mcp-optima-bd` en:
  - Claude Code → `~/.claude.json`
  - OpenCode → `~/.config/opencode/opencode.jsonc`
  - Cursor → `~/.cursor/mcp.json`
  - Claude Desktop → `~/Library/Application Support/Claude/claude_desktop_config.json` (mac) / `%APPDATA%\Claude\...` (win)
- **AC:** entry presente en los 4; merge idempotente; sin contraseña en config.

### C3 — Wizard `scripts/setup.sh` + `scripts/setup.ps1` · Mediano · ORQUESTA

- **Deps:** C1, C2, C4.
- **Construir:** (1) setup-ssh → (2) probar túnel → (3) pedir credenciales MySQL → (4) write_config → (5) registrar 4 agentes → (6) verificar `SELECT 1`.
- **AC:** un comando deja el MCP conectado en los 4 agentes; idempotente; cross-platform.

### C5 — Reconexión túnel reactiva · NO CONSTRUIR · VERIFICAR

- **Existe:** `tunnel.py:24 ensure()` (ServerAlive=15, atexit close) + `db.py:78 _connect()` retry en 2002/2003/2013.
- **AC:** tests `test_run_auto_relanza_tunel_si_conexion_rota` y `test_run_reintenta_select_una_vez_si_conn_se_perde` verdes.

## Orden

C1 + C2 + C4 en paralelo → C3 orquesta. C5 = solo confirmar tests.

## Riesgos

- Rutas exactas `~/.claude.json` (Claude Code) y Claude Desktop en Windows → verificar en implementación, no inventar.
