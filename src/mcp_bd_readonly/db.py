import json
import time
from decimal import Decimal
from pathlib import Path

import pymysql

from mcp_bd_readonly.security import enforce_read_only, LEADING_COMMENTS
from mcp_bd_readonly.tunnel import TunnelManager


def _first_stmt(sql: str) -> str:
    return LEADING_COMMENTS.sub("", sql, count=1).strip()


def _single_select(sql: str) -> bool:
    stmt = _first_stmt(sql)
    return sql.count(";") == 0 and stmt.lower().startswith(("select", "with"))


def _retryable(e: pymysql.err.OperationalError) -> bool:
    """True si el error justifica reintentar (túnel/conexión rota).

    Un timeout a mitad de query (read_timeout => "during query") NO reintenta:
    re-lanzar la misma query lenta duplicaría la carga sobre MySQL.
    """
    code = e.args[0] if e.args else None
    if code not in (2006, 2013):
        return False
    return "during query" not in str(e).lower()


class QueryExecutor:
    def __init__(self, cfg):
        self.cfg = cfg

    def _open(self):
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

    def _configure(self, c) -> None:
        # Aborta SELECT lentas en el SERVIDOR (no solo socket) vía max_execution_time.
        # MySQL 5.7.8+; si la variable no existe (MySQL viejo) se ignora (no fatal).
        timeout_ms = int(getattr(self.cfg, "query_timeout_ms", None) or 15000)
        try:
            with c.cursor() as cur:
                cur.execute(f"SET SESSION max_execution_time = {timeout_ms}")
        except pymysql.err.OperationalError:
            pass

    def _note_slow(self, sql: str, elapsed_ms: int) -> None:
        threshold = getattr(self.cfg, "slow_query_ms", None) or 5000
        if elapsed_ms < threshold:
            return
        data_dir = getattr(self.cfg, "data_dir", None)
        if not data_dir:
            return
        try:
            path = Path(data_dir) / "slow_queries.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps(
                    {"ts": time.time(), "ms": elapsed_ms, "sql": sql},
                    ensure_ascii=False,
                ) + "\n")
        except OSError:
            pass

    def _connect(self):
        try:
            c = self._open()
        except pymysql.err.OperationalError as e:
            code = e.args[0] if e.args else None
            if code not in (2002, 2003, 2013):
                raise
            TunnelManager(self.cfg).ensure()
            c = self._open()
        self._configure(c)
        return c

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
                        t0 = time.monotonic()
                        cur.execute(clamped, params or None)
                    except pymysql.err.OperationalError as e:
                        if attempt == 2 or not _retryable(e):
                            raise
                        TunnelManager(self.cfg).ensure()
                        continue
                    cols = [d[0] for d in cur.description] if cur.description else []
                    rows = [_convert(r) for r in cur.fetchall()]
                    self._note_slow(clamped, int((time.monotonic() - t0) * 1000))
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
