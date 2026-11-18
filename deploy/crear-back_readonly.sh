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
# Cuota explícita del servicio. El pool del MCP abre como máximo
# `MYSQL_POOL_MAX` sesiones (8 por defecto), así que 40 deja holgura para picos
# y para reconexiones sin poder agotar `max_connections` del servidor.
MAX_CONN="${MAX_CONN:-40}"

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
-- SHOW REPLICA STATUS exige REPLICATION CLIENT. Sin este grant el healthcheck
-- del router falla con 1227, la réplica se marca caída y TODAS las lecturas
-- van al primario (se pierde el réplica-first y sube la carga del pool).
GRANT REPLICATION CLIENT ON *.* TO 'back_readonly'@'localhost';
GRANT REPLICATION CLIENT ON *.* TO 'back_readonly'@'127.0.0.1';
-- Cuota por cuenta: el MCP nunca debe poder agotar max_connections.
ALTER USER 'back_readonly'@'localhost' WITH MAX_USER_CONNECTIONS ${MAX_CONN};
ALTER USER 'back_readonly'@'127.0.0.1' WITH MAX_USER_CONNECTIONS ${MAX_CONN};
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'back_readonly'@'localhost';
SHOW GRANTS FOR 'back_readonly'@'127.0.0.1';
SQL

printf '%s\n' "$SQL" | sudo mysql
echo "OK: back_readonly creado en este primario (SELECT + REPLICATION CLIENT, "
 echo "    MAX_USER_CONNECTIONS=${MAX_CONN}); espera a que la réplica lo aplique."
