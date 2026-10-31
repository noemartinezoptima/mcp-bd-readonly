-- Ejecutar en optimaback-active (primario) como root/administrador.
-- Requiere binlog + GTID, que ya están activos (verificado: log_bin=1, gtid_mode=ON,
-- binlog_format=ROW). No requiere reiniciar mysqld.
--
-- Sustituye el password por uno generado: openssl rand -hex 32
-- y guárdalo en el gestor de secretos, no en este fichero.

CREATE USER IF NOT EXISTS 'repl_mcp'@'10.0.0.6'
    IDENTIFIED BY '<PASSWORD>' REQUIRE SSL;

-- REPLICATION SLAVE: leer el binlog. SELECT sobre back: necesario solo para el
-- sembrado inicial (mysqldump). Ambos se pueden retirar tras la siembra.
GRANT REPLICATION SLAVE ON *.* TO 'repl_mcp'@'10.0.0.6';
GRANT SELECT ON back.* TO 'repl_mcp'@'10.0.0.6';

FLUSH PRIVILEGES;

-- Verificación: debe devolver la fila con REQUIRE SSL en ssl_type.
SELECT user, host, ssl_type FROM mysql.user WHERE user = 'repl_mcp';
