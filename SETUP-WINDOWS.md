# Setup de `mcp-bd-readonly` en Windows (con Claude)

Servidor MCP de solo lectura sobre MySQL `back`. **Independiente**: no requiere
`zero-teams-mcp` (Azure Teams) ni ningún otro MCP; es un módulo autocontenido.

Stack: Python 3.10+, `fastmcp` + `pymysql`. Código 100% portable (sin rutas Unix
hardcodeadas; usa `pathlib` + `os.environ`). Solo difieren en Windows: la ruta del
venv (`Scripts` en vez de `bin`) y el túnel SSH (`tunnel.ps1` en vez de `tunnel.sh`).

---

## Paso 0 — Prerrequisitos

- Python 3.10+ desde https://python.org (marca "Add python to PATH")
- Git for Windows (incluye OpenSSH client; si no, activar feature opcional "OpenSSH Client")
- Acceso SSH al host remoto de MySQL (alias `db-host` en `~/.ssh/config`, configurable con `SSH_HOST`/`TUNNEL_HOST`) con clave privada cargada
- Código clonado: `mcp-bd-readonly/`

Criterio: `python --version` → 3.10+ y `ssh db-host 'echo ok'` responde `ok`.

## Paso 1 — Entorno virtual + instalación

En `mcp-bd-readonly/` (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e .
```

Criterio: existe `.venv\Scripts\mcp-bd-readonly.exe`.

## Paso 1.5 — LibreOffice (recálculo de fórmulas Excel)

`leer_excel` solo puede evaluar fórmulas *dinámicas* (SEQUENCE, FILTER, arrays)
realmente si hay un motor de cálculo con LibreOffice. Sin él, el fallback es
`formualizer` (sin arrays dinámicos) o valores cached.

Instalar (PowerShell, una de estas dos):

```powershell
winget install --id TheDocumentFoundation.LibreOffice -e
# o, vía winget CLI directa:
winget install TheDocumentFoundation.LibreOffice
```

Ruta esperada: `C:\Program Files\LibreOffice\program\soffice.exe`
(variante x86 en `C:\Program Files (x86)\LibreOffice\program\soffice.exe`).

Criterio: `& "C:\Program Files\LibreOffice\program\soffice.exe" --version` devuelve
una línea `LibreOffice x.y`.

Si no quieres instalar nada, el server sigue funcionando (estrategia automática
`formualizer` o `cached_only`), pero las fórmulas bypasses de recálculo completo
pueden reportarse como error.

### Permiso para que Claude instale/verifique LibreOffice

Claude Code pedirá permiso para ejecutar winget. Añadir al `.claude/settings.json`
o `settings.local.json` del proyecto:

```json
{
  "permissions": {
    "allow": [
      "Bash(winget install TheDocumentFoundation.LibreOffice)",
      "Bash(winget install -e --id TheDocumentFoundation.LibreOffice *)",
      "Bash(& \"C:\\Program Files\\LibreOffice\\program\\soffice.exe\" --version)"
    ]
  }
}
```

(En macOS el equivalente ya está permitido: `Bash(brew install --cask libreoffice)`,
la ruta es `/Applications/LibreOffice.app/Contents/MacOS/soffice`.)

## Paso 2 — Credenciales

Copiar `.env.example` a `%USERPROFILE%\.zt-readonly.env` (es el mismo archivo que
en macOS; `load_config()` usa `Path.home()`, portable). Rellenar `MYSQL_PASSWORD`.
El archivo solo se lee como fallback: las variables de entorno `MYSQL_*`/`DATA_DIR`
ganan sobre él.

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=13306
MYSQL_DB=back
MYSQL_USER=back_readonly
MYSQL_PASSWORD=...
```

Criterio: el archivo existe en `%USERPROFILE%` y contiene una contraseña no vacía.

## Paso 3 — Túnel SSH

PowerShell, desde `mcp-bd-readonly/scripts/`:

```powershell
.\tunnel.ps1
```

`tunnel.ps1` abre `127.0.0.1:13306 → 127.0.0.1:3306` vía `ssh -N -L`. Deja la
ventana abierta (comparte el túnel con macOS si el host es el mismo Forge).

Criterio: en otra ventana, `Test-NetConnection 127.0.0.1 -Port 13306` →
`TcpTestSucceeded : True`. (O `netstat -ano | findstr 13306` muestra LISTENING.)

## Paso 4 — Registrar el servidor en Claude

### Claude Desktop (`claude_desktop_config.json`)

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-bd-readonly": {
      "command": "C:\\ruta\\a\\mcp-bd-readonly\\.venv\\Scripts\\mcp-bd-readonly.exe",
      "args": []
    }
  }
}
```

Las credenciales viajan en `%USERPROFILE%\.zt-readonly.env`; no es necesario (ni
recomendado) poner `MYSQL_PASSWORD` en el config JSON.

### Claude Code (CLI)

```powershell
claude mcp add mcp-bd-readonly -- C:\ruta\a\mcp-bd-readonly\.venv\Scripts\mcp-bd-readonly.exe
```

Criterio: `claude mcp list` muestra `mcp-bd-readonly` (health `connected`).

## Paso 5 — Verificación

En Claude, pedir:

- "lista las herramientas de mcp-bd-readonly" → 16 tools
- `run_query` con `SELECT COUNT(*) FROM facturas_venta` → devuelve un número
- `resumen_iva(2, 2026)` → objeto con `base_es`/`iva_es`/`total_es`
- `check_excel_capabilities` → `strategy` = `libreoffice` (si se instaló en 1.5), `formualizer` o `cached_only`
- `leer_excel("C:\\ruta\\a\\libro.xlsx", force_recalc=True)` → celdas con fórmula `f` + valor calculado `v`
- cualquier `UPDATE`/DML → error de solo lectura (barrera #1 parser; barrera #2 = usuario MySQL `back_readonly` con GRANT SELECT)

Criterio: `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN SELECT`, `WITH`(CTE), subqueries, `UNION`,
JOIN/GROUP BY y queries precedidas por comentarios funcionan; todo DML/DDL (`UPDATE`, `INSERT`,
`DELETE`, `TRUNCATE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`, `GRANT`, `RENAME`) siempre falla.
Además: queries multi-statement (`SELECT 1; SELECT 2`) son rechazadas por el driver pymysql
(`MULTI_STATEMENTS` off) antes de llegar a MySQL. Auditoría: crece `data\audit.jsonl` (relativo a `DATA_DIR`) en `mcp-bd-readonly\data\audit.jsonl`.

## Solución de problemas

| Síntoma | Causa | Fix |
|---|---|---|
| `Error: Connection refused` en tool | Túnel cerrado | relanzar `scripts/tunnel.ps1`; ver Paso 3 |
| `Access denied for user` | password en `.zt-readonly.env` mal | corregir `%USERPROFILE%\.zt-readonly.env`; reiniciar Claude |
| `'mcp-bd-readonly' is not recognized` | `.exe` no instalado | repetir Paso 1 (`pip install -e .`) |
| `Local port forward not allowed` / DNS SSH fail | `db-host` no resuelve | verificar `%USERPROFILE%\.ssh\config` tiene el Host y clave cargada (`ssh-add`) |

## Nota sobre módulos

Este MCP es **solo MySQL** (`back`). Se registra de forma independiente de
`zero-teams-mcp` (Teams/Graph). Ambos pueden coexistir como dos entry points
distintos en la misma config de Claude; activar/desactivar uno no afecta al otro.
No comparten credenciales ni procesos.