# Conexión de clientes al servidor MCP `mcp-bd-readonly`

Servidor: stdio, comando `.venv/bin/mcp-bd-readonly` dentro del repo `mcp-bd-readonly/`.
Requisito previo: túnel SSH activo (`scripts/tunnel.sh`, puerto local 13306 → MySQL remoto 3306) y
credenciales en `~/.zt-readonly.env` (modo 600). Las variables de entorno `MYSQL_*`/`DATA_DIR` sobreescriben al archivo.

## OpenCode (`opencode.jsonc` global o del proyecto)

Ya configurado globalmente en `~/.config/opencode/opencode.jsonc`:

```jsonc
"mcp": {
  "mcp-bd-readonly": {
    "type": "local",
    "command": ["/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-bd-readonly"],
    "enabled": true,
    "timeout": 60000
  }
}
```

El proceso hereda las variables de entorno de la sesión de OpenCode; si arrancas OpenCode desde un shell
que ya tiene las variables cargadas no necesitas `env`. Opcional: para forzar variables por servidor:

```jsonc
"mcp": {
  "mcp-bd-readonly": {
    "type": "local",
    "command": ["/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-bd-readonly"],
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
    "mcp-bd-readonly": {
      "command": "/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-bd-readonly",
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
    "mcp-bd-readonly": {
      "command": "/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/.venv/bin/mcp-bd-readonly",
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

- `scripts/tunnel.sh` escuchando: `lsof -iTCP:13306 -sTCP:LISTEN` muestra la entrada ssh.
- Consumidor MCP: `tools/list` expone 11 herramientas (`list_databases`, `list_tables`, `describe_table`,
  `run_query`, `facturas_venta`, `resumen_iva`, `remesas_pendientes`, `cuadre_factura`,
  `conciliar_remesas`, `saldos_cliente`, `excepciones`, `informe_financiero`).
- Todo `UPDATE`/DML devuelve un error de solo lectura (barreras #1 parser + #2 `back_readonly`).