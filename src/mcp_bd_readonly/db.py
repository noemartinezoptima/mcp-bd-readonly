from decimal import Decimal

import pymysql

from mcp_bd_readonly.security import enforce_read_only


class QueryExecutor:
    def __init__(self, cfg):
        self.cfg = cfg

    def _conn(self):
        return pymysql.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.db,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            read_timeout=30,
            connect_timeout=10,
        )

    def run(self, sql, params=None, limit=100):
        enforce_read_only(sql)
        clamped = sql
        if "limit" not in sql.lower():
            clamped = f"{sql.rstrip().rstrip(';')} LIMIT {int(limit)}"
        with self._conn() as c:
            with c.cursor() as cur:
                cur.execute(clamped, params or ())
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = [_convert(r) for r in cur.fetchall()]
        return cols, rows

    def databases(self):
        return self.run("SHOW DATABASES")

    def tables(self):
        return self.run("SHOW TABLES")

    def describe(self, table):
        return self.run(f"DESCRIBE `{table}`")


def _convert(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, (int, float)) and v is not None:
            out[k] = v
        elif isinstance(v, Decimal):
            out[k] = v
        else:
            out[k] = v
    return out