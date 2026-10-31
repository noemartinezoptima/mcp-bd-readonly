-- Ejecutar EN EL STANDBY, después de 02-sembrar-replica.sh.
-- Sustituye <PASSWORD> por el de repl_mcp.
--
-- SOURCE_AUTO_POSITION=1: con GTID no hace falta fijar binlog file/pos.
-- SOURCE_SSL=1: el tráfico va cifrado aunque viaje por la red privada.

STOP REPLICA;

CHANGE REPLICATION SOURCE TO
    SOURCE_HOST = '10.0.0.5',
    SOURCE_PORT = 3306,
    SOURCE_USER = 'repl_mcp',
    SOURCE_PASSWORD = '<PASSWORD>',
    SOURCE_AUTO_POSITION = 1,
    SOURCE_SSL = 1,
    SOURCE_CONNECT_RETRY = 10,
    SOURCE_RETRY_COUNT = 86400;   -- reintenta ~10 días antes de rendirse

START REPLICA;

-- Verificación inmediata (debe aparecer Replica_IO_Running=Yes y SQL=Yes).
SHOW REPLICA STATUS\G

-- Si IO no arranca: error 1045 (credenciales), 2003 (red/firewall) o
-- 1236 (binlog ya purgado: hay que re-sembrar).
