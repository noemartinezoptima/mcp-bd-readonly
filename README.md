# mcp-bd-readonly

Servidor MCP (Model Context Protocol) de solo lectura sobre la base de datos `back` (MySQL 8.4.9, servidor Forge `db-host`). Expone herramientas Tabularis para consultas de inventario/facturación sin ningún acceso de escritura.

## Seguridad: combinación de barreras

1. **Parser en MCP** (`security.py`) — toda query pasa por `enforce_read_only()` en `QueryExecutor.run()` *antes* de abrir conexión. Veta `insert|update|delete|drop|truncate|alter|replace|create|grant|revoke|rename` en cualquier statement (incluye statements encadenados con `;` y precedidos por comentarios). Solo `SELECT / SHOW / DESCRIBE / DESC / EXPLAIN / WITH`.
2. **Usuario MySQL `back_readonly`** — ya existe en el servidor con GRANT SELECT únicamente sobre `back.*`, conecta por **TCP** `127.0.0.1:3306` (vía túnel SSH a `db-host`). Cualquier `UPDATE`/`INSERT`/`DELETE` falla incluso si el parser se evadiera: `ERROR 1142 (42000): UPDATE command denied to user 'back_readonly'@'localhost'`. Verificado contra la BD real.

Si el parser falla, MySQL niega; si MySQL falla, el parser niega. Sin usuario de escritura configurado.

## Requisitos

- Python 3.10+ (venv en `.venv`)
- Acceso SSH a `db-host` (alias del host Forge)
- `~/.zt-readonly.env` (modo 600) con las credenciales:
  ```
  MYSQL_HOST=127.0.0.1
  MYSQL_PORT=13306
  MYSQL_DB=back
  MYSQL_USER=back_readonly
  MYSQL_PASSWORD=...
  DATA_DIR=./data
  ```
  No se invalida si el archivo no existe; las variables de entorno `MYSQL_*`/`DATA_DIR` ganan sobre el archivo.

## Uso

1. Levantar el túnel (puerto local 13306 → MySQL remoto 3306):
   ```bash
   scripts/tunnel.sh
   ```
2. Ejecutar el servidor MCP (stdio):
   ```bash
   .venv/bin/mcp-bd-readonly
   ```

## Herramientas

Núcleo (Tabularis):

- `list_databases` — bases visibles
- `list_tables(schema?)` — tablas de un schema (default `back`)
- `describe_table(table)` — columnas de una tabla
- `run_query(query, limit=100)` — SELECT/SHOW/DESCRIBE libre con límite

Finanzas:

- `facturas_venta(fecha_desde, fecha_hasta, cliente?)` — facturas y total del periodo (Decimal exacto + formato es-ES `1.234,56 €`)
- `resumen_iva(trimestre, anio)` — base/IVA/total del trimestre
- `remesas_pendientes()` — efectos de pago sin pagar (por `fecha_vencimiento`)
- `cuadre_factura(factura_id)` — comprueba que la suma de líneas == total de cabecera

Auditoría:

- `conciliar_remesas()` — total emitido vs acreditado (`fecha_pagado IS NOT NULL`)
- `saldos_cliente(cliente_id)` — facturado vs cobrado (vía `vista_efectos_pago`) y pendiente
- `excepciones(fecha_desde, fecha_hasta, umbral)` — facturas sobre umbral clasificadas por materialidad
- `informe_financiero(fecha_desde, fecha_hasta)` — informe Markdown + CSV (`;`)

## Aritmética

Todo el dinero es `Decimal` (nunca `float`). Sumas exactas con `quantize(0.01, ROUND_HALF_UP)`; strings es-ES separador de miles `.` y decimal `,`.

## Auditoría de acceso

Cada llamada a tool registra una línea JSON en `data_dir/audit.jsonl` (`DATA_DIR`). No contiene credenciales.