from decimal import Decimal

import pymysql

from mcp_bd_readonly.security import enforce_read_only, LEADING_COMMENTS
from mcp_bd_readonly.tunnel import TunnelManager


def _first_stmt(sql: str) -> str:
    return LEADING_COMMENTS.sub("", sql, count=1).strip()


def _single_select(sql: str) -> bool:
    stmt = _first_stmt(sql)
    return sql.count(";") == 0 and stmt.lower().startswith(("select", "with"))


class QueryExecutor:
    def __init__(self, cfg):
        self.cfg = cfg

    def _connect(self):
        try:
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
        except pymysql.err.OperationalError as e:
            code = e.args[0] if e.args else None
            if code in (2002, 2003, 2013):
                TunnelManager(self.cfg).ensure()
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
            raise

    def _conn(self):
        return self._connect()

    def run(self, sql, params=None, limit=100):
        enforce_read_only(sql)
        stmt = _first_stmt(sql)
        clamped = sql
        if limit and "limit" not in stmt.lower():
            if _single_select(sql):
                clamped = f"{sql.rstrip().rstrip(';')} LIMIT {int(limit)}"
        for attempt in (1, 2):
            with self._conn() as c:
                with c.cursor() as cur:
                    try:
                        cur.execute(clamped, params or None)
                    except pymysql.err.OperationalError as e:
                        code = e.args[0] if e.args else None
                        if attempt == 2 or code not in (2013, 2006):
                            raise
                        TunnelManager(self.cfg).ensure()
                        continue
                    cols = [d[0] for d in cur.description] if cur.description else []
                    rows = [_convert(r) for r in cur.fetchall()]
                    break
        if limit and rows and not clamped.lower().endswith(f"limit {int(limit)}"):
            rows = rows[: int(limit)]
        return cols, rows

    def databases(self):
        return self.run("SHOW DATABASES", limit=None)

    def tables(self):
        return self.run("SHOW TABLES", limit=None)

    def describe(self, table):
        safe = table.replace("`", "``")
        return self.run(f"DESCRIBE `{safe}`", limit=None)


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
