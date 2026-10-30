# mcp-optima-bd  (antes mcp-bd-readonly)

Servidor MCP SOLO-LECTURA sobre la BD de Optima (`back`). Nombre público nuevo: **mcp-optima-bd**; la carpeta del repo conserva el nombre antiguo para no romper rutas de config.

Servidor MCP (Model Context Protocol) de solo lectura sobre una base de datos MySQL (esquema `back`). Expone herramientas para consultas de inventario/facturación sin ningún acceso de escritura.

**Módulo autocontenido**: este servidor es solo MySQL (`back`). No depende de `zero-teams-mcp` (Teams/Graph) ni de ningún otro MCP. En configs de cliente se registra de forma independiente; activar/desactivar otros MCPs no lo afecta.

## Seguridad: combinación de barreras

1. **Parser en MCP** (`security.py`) — toda query pasa por `enforce_read_only()` en `QueryExecutor.run()` *antes* de abrir conexión. Dos barreras: la primera palabra debe ser `SELECT / SHOW / DESCRIBE / DESC / EXPLAIN / WITH`, y **ningún verbo DML/DDL puede aparecer en ninguna posición**. Lo segundo es lo que cierra `WITH c AS (...) DELETE FROM t`, que MySQL 8 acepta y el allowlist de primera palabra por sí solo dejaba pasar. También veta `FOR UPDATE` / `LOCK IN SHARE MODE` y los esquemas `mysql`, `performance_schema` y `sys`.
2. **Driver sin multi-statement** (`pymysql`) — `CLIENT.MULTI_STATEMENTS` desactivado por defecto: siquiera `SELECT 1; SELECT 2` es rechazado por el driver (1064) antes de llegar a MySQL. Un `SELECT 1; DROP TABLE x` además lo veta el parser.
3. **Usuario MySQL dedicado de solo lectura** — con GRANT SELECT únicamente sobre `back.*`, conecta por **TCP** `127.0.0.1:3306` (vía túnel SSH al host configurado en `TUNNEL_HOST`). Cualquier `UPDATE`/`INSERT`/`DELETE` falla incluso si el parser se evadiera: `ERROR 1142 (42000): UPDATE command denied to user '...'@'localhost'`. Verificado contra la BD real.

Si el parser falla, MySQL niega; si MySQL falla, el parser niega. Sin usuario de escritura configurado.

## Modo remoto (HTTP + réplica de solo lectura)

Además del modo local por stdio, el servidor puede correr como servicio HTTP en la misma máquina que la réplica, sin túneles:

```bash
mcp-optima-bd --transport http          # 127.0.0.1:8443, endpoint /mcp con Bearer
```

- **Lecturas a la réplica**; si el lag supera `MYSQL_REPLICA_LAG_MAX_S`, el router hace fallback al primario y lo reporta. Nunca escribe.
- **API keys** con SHA-256 (no se guarda el secreto), scopes, caducidad y revocación: `python -m mcp_bd_readonly.auth --db ... create|list|revoke`.
- `TUNNEL_ENABLED=0` y pool acotado (`MYSQL_POOL_SIZE`) en servidor; `setup_ssh` **no** se registra en modo HTTP.
- **Excel en memoria**: en HTTP el fichero llega en `contenido_b64` y se procesa sobre los bytes, **sin escribir nada en disco** (el recálculo de fórmulas lo hace `formualizer` en memoria). En HTTP no se aceptan rutas del servidor; solo si defines `MCP_FILES_DIR` se permite además leer dentro de ese directorio. En stdio las rutas siguen funcionando y el temporal de recálculo se borra al terminar.
- `/healthz` sin autenticación; `/mcp` exige `Authorization: Bearer mcp_<id>_<secreto>` y limita peticiones por minuto.
- Puesta en marcha: [`deploy/README.md`](deploy/README.md). Plan por fases con rollback: [`deploy/PLAN-DESPLIEGUE.md`](deploy/PLAN-DESPLIEGUE.md).

El modo stdio sigue siendo el **default** y no cambia el flujo local.

## Requisitos

- Python 3.10+ (venv en `.venv`)
- Acceso SSH al host remoto de MySQL (alias `db-host` en `~/.ssh/config`, configurable con `SSH_HOST` / `TUNNEL_HOST`)
- `~/.zt-readonly.env` (modo 600) con las credenciales:
  ```
  MYSQL_HOST=127.0.0.1
  MYSQL_PORT=13306
  MYSQL_DB=back
  MYSQL_USER=back_readonly
  MYSQL_PASSWORD=...
  DATA_DIR=./data
  TUNNEL_HOST=db-host
  ```
  No se invalida si el archivo no existe; las variables de entorno `MYSQL_*`/`DATA_DIR`/`TUNNEL_HOST` ganan sobre el archivo. En Windows el archivo cae en `%USERPROFILE%\.zt-readonly.env`.

**Soporte Windows**: el código es portable (pathlib + pymysql + os.environ, sin rutas Unix). Diferencias: entry point en `.venv\Scripts\mcp-optima-bd.exe`, túnel con `scripts/tunnel.ps1`. Instrucción completa para Claude en [`SETUP-WINDOWS.md`](SETUP-WINDOWS.md).

## Uso

0. Setup guiado (SSH + credenciales MySQL + registro en agentes). Un solo comando:
   ```bash
   bash scripts/setup.sh          # macOS/Linux
   pwsh scripts/setup.ps1         # Windows
   ```
   Hace, en orden: genera clave SSH ed25519 (si falta) + bloque `~/.ssh/config`; pide credenciales MySQL y escribe `~/.zt-readonly.env` (modo 600); registra el MCP en Claude Code / OpenCode / Cursor / Claude Desktop; y verifica `SELECT 1`.

   Alternativa manual (solo SSH, sin wizard): `bash scripts/setup-ssh.sh` genera la clave y el host `db-host` — solo pide tu email. Configura valores reales con `SSH_HOST`/`SSH_HOSTNAME`/`SSH_KEY`/`SSH_USER`. Al final imprime la clave pública para añadirla al servidor (1 paso manual). Verificado: `ssh db-host 'echo OK'`.

1. Ejecutar el servidor MCP (stdio). **El túnel SSH se gestiona solo**: si `127.0.0.1:13306` no responde, el MCP lanza `ssh -N -L 13306:127.0.0.1:3306 db-host` como subproceso y lo cierra al terminar:
   ```bash
   .venv/bin/mcp-optima-bd                # macOS/Linux
   .venv\Scripts\mcp-optima-bd.exe        # Windows
   ```
   Para arranque manual previo del túnel (opcional, si quieres voz propia sobre la conexión):
   ```bash
   scripts/tunnel.sh            # macOS/Linux
   ```
   ```powershell
   scripts\tunnel.ps1           # Windows
   ```

El host SSH a usar por el auto-túnel se configura con `TUNNEL_HOST` (default: host en `~/.zt-readonly.env` o `db-host`).

## Herramientas

Núcleo (Tabularis):

- `list_databases` — bases visibles
- `list_tables(schema?)` — tablas de un schema (default `back`)
- `describe_table(table)` — columnas de una tabla
- `run_query(query, limit=100)` — SELECT/SHOW/DESCRIBE libre con límite. Query correctas verificadas contra BD real: `SELECT` (con JOIN, WHERE, GROUP BY, subqueries, `UNION`), `WITH` (CTE), `SHOW TABLES`, `DESCRIBE`/`DESC`, `EXPLAIN SELECT`, y consultas precedidas por comentarios `--`. `EXPLAIN UPDATE` pasa el parser pero lo niega MySQL (1142, barrera #3). El `LIMIT` se inyecta en SQL solo para `SELECT`/`WITH` de un statement; para `SHOW`/`DESCRIBE` trunca en Python tras traer filas.

Finanzas:

- `facturas_venta(fecha_desde, fecha_hasta, cliente?)` — facturas y total del periodo (Decimal exacto + formato es-ES `1.234,56 €`)
- `resumen_iva(trimestre, anio)` — base/IVA/total del trimestre
- `remesas_pendientes(max_n=50)` — efectos de pago sin pagar, por `fecha_vencimiento` ASC (límite `max_n`) + total de pendientes. `fecha_vencimiento` puede ser `null` en BD real (efectos sin vencimiento).
- `cuadre_factura(factura_id)` — comprueba que la suma de líneas == total de cabecera. Factura inexistente → `ok:false`, `exists:false`.

Auditoría:

- `conciliar_remesas()` — total emitido vs acreditado (`fecha_pagado IS NOT NULL`)
- `saldos_cliente(cliente_id)` — facturado vs cobrado (vía `vista_efectos_pago`) y pendiente
- `excepciones(fecha_desde, fecha_hasta, umbral)` — facturas sobre umbral clasificadas por materialidad
- `informe_financiero(fecha_desde, fecha_hasta)` — informe Markdown + CSV (`;`)

## Aritmética

Todo el dinero es `Decimal` (nunca `float`). Sumas exactas con `quantize(0.01, ROUND_HALF_UP)`; strings es-ES separador de miles `.` y decimal `,`.

## Auditoría de acceso

Cada llamada a tool registra una línea JSON en `data_dir/audit.jsonl` (`DATA_DIR`). No contiene credenciales.