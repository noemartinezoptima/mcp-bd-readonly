#!/usr/bin/env bash
# Sembrado inicial de `back` en optimaback-standby desde optimaback-active.
#
# Se ejecuta EN EL STANDBY. Descarga por la red privada (10.0.0.5) y escribe
# directamente en MySQL, sin fichero intermedio de 55 GB.
#
# Requisitos:
#   - Usuario repl_mcp creado en el primario (01-usuario-replicacion.sql)
#   - MySQL del standby PARADO para escritura de otros clientes (super_read_only)
#   - Acceso root local a MySQL en el standby para SET @@GLOBAL.GTID_PURGED
#
# Uso:
#   SRC_HOST=10.0.0.5 SRC_USER=repl_mcp bash 02-sembrar-replica.sh
#   (pide el password por stdin; no se pasa por parámetro)

set -euo pipefail

SRC_HOST="${SRC_HOST:-10.0.0.5}"
SRC_PORT="${SRC_PORT:-3306}"
SRC_USER="${SRC_USER:-repl_mcp}"
DB="${DB:-back}"
TRABAJOS="${TRABAJOS:-400000}"   # tablas pequeñas: 394 tablas, 55.4 GB

echo "== 1/5 comprobando estado del destino =="
mysql -N -e "SELECT CONCAT('read_only=',@@read_only,' super_read_only=',@@super_read_only,' server_id=',@@server_id);"

if [ "$(mysql -N -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='${DB}';")" != "0" ]; then
    echo "ERROR: la base ${DB} ya existe en este host. Aborta para no pisar datos." >&2
    echo "       Si es un re-sembrado consciente, DROP DATABASE ${DB} primero." >&2
    exit 1
fi

CANAL="$(mysql -N -e "SHOW REPLICA STATUS;" | wc -l | tr -d ' ')"
if [ "$CANAL" != "0" ]; then
    echo "ERROR: ya hay un canal de replicación. Deténlo antes (STOP REPLICA)." >&2
    exit 1
fi

echo "== 2/5 creando esquema vacío =="
mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "== 3/5 volcado en streaming desde ${SRC_HOST} (esto tarda; ~55 GB) =="
echo -n "Password de ${SRC_USER}: "
read -rs SRC_PASS
echo
# --set-gtid-purged=ON + SOURCE_AUTO_POSITION=1 evita necesitar --source-data
# (y por tanto el privilegio RELOAD sobre producción).
# --single-transaction: snapshot consistente sin bloquear InnoDB.
# --skip-lock-tables: no bloquea tablas MyISAM (revisar si `back` usa MyISAM).
MYSQL_PWD="$SRC_PASS" mysqldump \
    --host="$SRC_HOST" --port="$SRC_PORT" --user="$SRC_USER" \
    --single-transaction --skip-lock-tables \
    --set-gtid-purged=ON \
    --routines --triggers --events \
    --max-allowed-packet=64M \
    --default-character-set=utf8mb4 \
    --no-tablespaces \
    "$DB" \
  | mysql --max-allowed-packet=64M "$DB"
unset SRC_PASS MYSQL_PWD

echo "== 4/5 comprobando integridad =="
mysql -N -e "SELECT CONCAT('tablas=',COUNT(*)) FROM information_schema.TABLES WHERE TABLE_SCHEMA='${DB}';"

echo "== 5/5 bloqueando escrituras en la réplica =="
mysql -e "SET PERSIST super_read_only = ON;"
mysql -N -e "SELECT CONCAT('super_read_only=',@@super_read_only);"

echo
echo "Sembrado terminado. Siguiente: 03-iniciar-replicacion.sql"
