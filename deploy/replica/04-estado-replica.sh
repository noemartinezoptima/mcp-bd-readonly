#!/usr/bin/env bash
# Estado de la réplica y código de salida para alertas.
#   0 = sana (IO y SQL en Yes, lag por debajo del umbral)
#   1 = hay que avisar
#
# Uso:   bash 04-estado-replica.sh
# Cron:  */5 * * * * bash /opt/mcp-optima-bd/deploy/replica/04-estado-replica.sh \
#          || logger -t replica-back "ALERTA réplica back"
#
# SHOW REPLICA STATUS no es una tabla: se parsea su salida vertical.

set -euo pipefail

LAG_MAX="${LAG_MAX:-60}"
STATUS="$(mysql -e "SHOW REPLICA STATUS\G" 2>/dev/null)" || {
    echo "ALERTA: no se pudo consultar la réplica" >&2
    exit 1
}

campo() { awk -F': ' -v k="$1" '$1 == k {print $2; exit}' <<<"$STATUS"; }

io="$(campo Replica_IO_Running)"
sql_thread="$(campo Replica_SQL_Running)"
lag="$(campo Seconds_Behind_Source)"
err="$(campo Last_SQL_Error)"
fuente="$(campo Source_Host)"

printf 'fuente=%s io=%s sql=%s lag=%s\n' "${fuente:-?}" "${io:-?}" "${sql_thread:-?}" "${lag:-?}"

if [ "${io:-}" != "Yes" ] || [ "${sql_thread:-}" != "Yes" ]; then
    echo "ALERTA: replicación parada (io=${io:-?} sql=${sql_thread:-?}) ${err}" >&2
    exit 1
fi
if [ -z "${lag:-}" ]; then
    echo "ALERTA: lag desconocido" >&2
    exit 1
fi
if [ "$lag" -gt "$LAG_MAX" ]; then
    echo "ALERTA: lag ${lag}s > ${LAG_MAX}s" >&2
    exit 1
fi
echo "OK"
