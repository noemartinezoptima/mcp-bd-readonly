import pytest
from mcp_bd_readonly.security import enforce_read_only, ReadOnlyViolation


def test_allows_select():
    enforce_read_only("SELECT * FROM facturas_venta LIMIT 5;")


def test_allows_with_cte():
    enforce_read_only("with cte as (select 1) select * from cte")


@pytest.mark.parametrize("ok", [
    "SHOW TABLES",
    "DESCRIBE facturas_venta",
    "DESC facturas_venta",
    "EXPLAIN SELECT * FROM facturas_venta",
])
def test_allows_read_commands(ok):
    enforce_read_only(ok)


@pytest.mark.parametrize("bad", [
    "UPDATE facturas_venta SET total_euros=0",
    "DELETE FROM facturas_venta",
    "DROP TABLE facturas_venta",
    "TRUNCATE TABLE facturas_venta",
    "ALTER TABLE facturas_venta ADD COLUMN x INT",
    "INSERT INTO facturas_venta (id) VALUES (1)",
    "REPLACE INTO facturas_venta (id) VALUES (1)",
    "CREATE TABLE x (id INT)",
    "GRANT SELECT ON back.* TO 'x'",
    "REVOKE SELECT ON back.* FROM 'x'",
    "RENAME TABLE x TO y",
    "  UPDATE facturas SET x=1",
    "update facturas SET x=1",
    "SELECT * FROM facturas_venta; DROP TABLE facturas_venta;",
    "SELECT 1; UPDATE facturas SET x=1",
])
def test_rejects_dml(bad):
    with pytest.raises(ReadOnlyViolation):
        enforce_read_only(bad)
