# Conexión de clientes al servidor MCP `mcp-optima-bd`

Servidor: stdio, comando `.venv/bin/mcp-optima-bd` dentro del repo `mcp-bd-readonly/` (Windows: `.venv\Scripts\mcp-optima-bd.exe`, ver `SETUP-WINDOWS.md`).
Requisito previo: túnel SSH activo (`scripts/tunnel.sh`, puerto local 13306 → MySQL remoto 3306; en Windows `scripts/tunnel.ps1`) y
credenciales en `~/.zt-readonly.env` (modo 600). Las variables de entorno `MYSQL_*`/`DATA_DIR` sobreescriben al archivo.

> **Módulos independientes**: este MCP es SOLO MySQL (`back`). No depende de `zero-teams-mcp` (Teams/Graph) ni viceversa.
> Se registran como servidores MCP separados; activar/desactivar uno no afecta al otro. No comparten credenciales ni procesos.

## OpenCode (`opencode.jsonc` global o del proyecto)

Ya configurado globalmente en `~/.config/opencode/opencode.jsonc`:

```jsonc
"mcp": {
  "mcp-optima-bd": {
    "type": "local",
    "command": ["/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-optima-bd"],
    "enabled": true,
    "timeout": 60000
  }
}
```

El proceso hereda las variables de entorno de la sesión de OpenCode; si arrancas OpenCode desde un shell
que ya tiene las variables cargadas no necesitas `env`. Opcional: para forzar variables por servidor:

```jsonc
"mcp": {
  "mcp-optima-bd": {
    "type": "local",
    "command": ["/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-optima-bd"],
    "enabled": true,
    "timeout": 60000,
    "env": {
      "MYSQL_HOST": "127.0.0.1",
      "MYSQL_PORT": "13306",
      "MYSQL_DB": "back",
      "MYSQL_USER": "back_readonly",
      "MYSQL_PASSWORD": "…"
    }
  }
}
```

> No pongas la contraseña real en el config si el archivo puede compartirse; `~/.zt-readonly.env` a pie de
> sesión es la vía segura (el `config.py` lo lee por defecto).

## Cursor (`~/.cursor/mcp.json` o `.cursor/mcp.json` del proyecto)

```json
{
  "mcpServers": {
    "mcp-optima-bd": {
      "command": "/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-optima-bd",
      "args": [],
      "env": {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": "13306",
        "MYSQL_DB": "back",
        "MYSQL_USER": "back_readonly",
        "MYSQL_PASSWORD": "…"
      }
    }
  }
}
```

(Claude Code / Cursor Command aceptan la misma forma; ajusta la ruta del `.venv` si el repo vive en otra máquina.)

## Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "mcp-optima-bd": {
      "command": "/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-optima-bd",
      "args": [],
      "env": {
        "MYSQL_HOST": "127.0.0.1",
        "MYSQL_PORT": "13306",
        "MYSQL_DB": "back",
        "MYSQL_USER": "back_readonly",
        "MYSQL_PASSWORD": "…"
      }
    }
  }
}
```

## Comprobación

- `scripts/tunnel.sh` escuchando: `lsof -iTCP:13306 -sTCP:LISTEN` muestra la entrada ssh (Windows: `netstat -ano | findstr 13306` o `Test-NetConnection 127.0.0.1 -Port 13306`).
- Consumidor MCP: `tools/list` expone herramientas (29 total): `list_databases`, `list_tables`, `describe_table`,
  `run_query`, `facturas_venta`, `resumen_iva`, `remesas_pendientes`, `cuadre_factura`,
  `conciliar_remesas`, `saldos_cliente`, `excepciones`, `informe_financiero`,
  `describe_tablas_clave`, `detalle_establecimiento`, `dso_dpo_evolutivo`, `aging_efectos`,
  `estado_tunel`, `auditoria`, `setup_ssh`([ADMIN]), `leer_excel`, `check_excel_capabilities`,
  `resumen_excel`, `reconciliar_excel_bd`, `resolve_domain_term`, `schema_snapshot`,
  `refresh_schema`([ADMIN]), `find_related_queries`, `recordar_consulta`, `consultar_memoria`.
- `resolve_domain_term` traduce lenguaje-negocio ES a canónicos (tabla+tool+trampas). `schema_snapshot` devuelve
  el esquema desde caché local (`data/schema_snapshot.json`) sin tocar la BD; `refresh_schema` lo reconstruye ([ADMIN], `confirm=True`).
- `find_related_queries` descubre queries del catálogo afines + otras que tocan la MISMA tabla; `recordar_consulta`/
  `consultar_memoria` guardan/buscan consultas hechas por usuaria en `data/memoria.json`.
- `describe_tablas_clave` / `detalle_establecimiento` son tools de CONOCIMIENTO (esquema y JOINs del catálogo),
  no de consulta: `run_query` ejecuta SQL crudo read-only. `detalle_establecimiento` ya hace los JOINs que el
  SQL crudo no sabe (responsable_id→users.name, cliente_facturacion_id→clientes.razon_social, detalle compuesto).
- Todo `UPDATE`/DML devuelve un error de solo lectura (barreras #1 parser + #2 `back_readonly`).