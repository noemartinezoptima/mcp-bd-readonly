#!/usr/bin/env bash
# Crea (o rota) el usuario MySQL de solo lectura del MCP. Se ejecuta EN EL PRIMARIO:
# en la réplica cualquier CREATE USER falla con ERROR 1290 (--super-read-only);
# lo creado aquí llega al standby por replicación.
#
#   bash crear-back_readonly.sh          # pide la contraseña de sudo
#   PW_FILE=/ruta/secreto DB=back bash crear-back_readonly.sh
#
# Sin REQUIRE SSL a propósito: el cliente (pymysql) no negocia TLS y la conexión
# es de loopback, dentro del mismo host.
set -euo pipefail

PW_FILE="${PW_FILE:-$HOME/.mcp-back_readonly.pass}"
DB="${DB:-back}"

[ -s "$PW_FILE" ] || { echo "FALTA el secreto en $PW_FILE" >&2; exit 1; }
PW=$(cat "$PW_FILE")
[ -n "$PW" ] || { echo "el secreto de $PW_FILE está vacío" >&2; exit 1; }

read -r -d '' SQL <<SQL || true
CREATE USER IF NOT EXISTS 'back_readonly'@'localhost' IDENTIFIED BY '${PW}';
CREATE USER IF NOT EXISTS 'back_readonly'@'127.0.0.1' IDENTIFIED BY '${PW}';
ALTER USER 'back_readonly'@'localhost' IDENTIFIED BY '${PW}';
ALTER USER 'back_readonly'@'127.0.0.1' IDENTIFIED BY '${PW}';
REVOKE IF EXISTS ALL PRIVILEGES, GRANT OPTION FROM 'back_readonly'@'localhost';
REVOKE IF EXISTS ALL PRIVILEGES, GRANT OPTION FROM 'back_readonly'@'127.0.0.1';
GRANT SELECT ON \`${DB}\`.* TO 'back_readonly'@'localhost';
GRANT SELECT ON \`${DB}\`.* TO 'back_readonly'@'127.0.0.1';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'back_readonly'@'localhost';
SHOW GRANTS FOR 'back_readonly'@'127.0.0.1';
SQL

printf '%s\n' "$SQL" | sudo mysql
echo "OK: back_readonly creado en este primario; espera a que la réplica lo aplique."
