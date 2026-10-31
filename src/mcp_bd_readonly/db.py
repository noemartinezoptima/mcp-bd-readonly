import json
import queue
import re
import sys
import threading
import time
from pathlib import Path

import pymysql

from mcp_bd_readonly.secure_log import open_append_private
from mcp_bd_readonly.security import enforce_read_only, LEADING_COMMENTS
from mcp_bd_readonly.tunnel import TunnelManager


def _first_stmt(sql: str) -> str:
    return LEADING_COMMENTS.sub("", sql, count=1).strip()


# Tope duro de filas materializadas por query. Por encima, se falla con un error
# accionable en lugar de traer la tabla entera a memoria (AC5 del spec).
MAX_ROWS = 50_000

# LIMIT al final del statement, con número o placeholder. Anclado al final para
# no confundir columnas o literales que contengan la palabra 'limit'.
_TRAILING_LIMIT = re.compile(
    r"\blimit\s+(?:(\d+|%s)\s*,\s*)?(\d+|%s)(?:\s+offset\s+(?:\d+|%s))?\s*;?\s*$",
    re.IGNORECASE,
)


def _single_select(sql: str) -> bool:
    stmt = _first_stmt(sql)
    return sql.count(";") <= 1 and stmt.lower().startswith(("select", "with"))


def _limit_clause(stmt: str) -> tuple[bool, int | None]:
    """(hay LIMIT explícito, filas pedidas o None si es un placeholder)."""
    match = _TRAILING_LIMIT.search(stmt)
    if not match:
        return False, None
    raw = match.group(2)
    return True, (int(raw) if raw.isdigit() else None)


def _acotar(stmt: str, sql: str, limit) -> str:
    """Acota la query en SQL antes de ejecutarla.

    - LIMIT explícito por encima de MAX_ROWS: error, no se ejecuta.
    - LIMIT explícito razonable (o con placeholder): se respeta tal cual.
    - sin LIMIT y limit=N: se añade LIMIT N.
    - sin LIMIT y limit=None ("todas"): se añade LIMIT MAX_ROWS+1 para detectar
      el desbordamiento sin materializar la tabla completa.
    """
    if not _single_select(sql):
        return sql
    has_limit, declared = _limit_clause(stmt)
    if has_limit:
        if declared is not None and declared > MAX_ROWS:
            raise ValueError(
                f"run: la query pide {declared} filas y el máximo es {MAX_ROWS}. "
                "Agrega (GROUP BY), filtra o baja el LIMIT; para contar usa COUNT(*)."
            )
        return sql
    cuerpo = sql.rstrip().rstrip(";")
    # El LIMIT va en línea nueva: si la query acaba en un comentario `--`, un
    # LIMIT en la misma línea quedaría comentado y no acotaría nada.
    if limit:
        return f"{cuerpo}\nLIMIT {int(limit)}"
    if limit is None:
        return f"{cuerpo}\nLIMIT {MAX_ROWS + 1}"
    return sql


def _retryable(e: pymysql.err.OperationalError) -> bool:
    """True si el error justifica reintentar (túnel/conexión rota).

    Un timeout a mitad de query (read_timeout => "during query") NO reintenta:
    re-lanzar la misma query lenta duplicaría la carga sobre MySQL.
    """
    code = e.args[0] if e.args else None
    if code not in (2006, 2013):
        return False
    return "during query" not in str(e).lower()


def _warn(msg: str) -> None:
    print(f"mcp-optima-bd: {msg}", file=sys.stderr)


def _unique_cols(names) -> list[str]:
    """Nombres de columna únicos dentro de una misma fila.

    MySQL repite el nombre en `description` cuando la query saca dos columnas
    iguales (`SELECT m.nombre, e.nombre`). Indexar la fila por ese nombre hace
    que la segunda columna se pierda y la primera salga dos veces, sin ningún
    error: el cliente recibe datos falsos. Se desambigua con sufijo _2, _3...
    respetando el orden y sin chocar con nombres que ya existan en la query.
    """
    out: list[str] = []
    used: set[str] = set()
    for name in names:
        candidate = name
        n = 1
        while candidate in used:
            n += 1
            candidate = f"{name}_{n}"
        used.add(candidate)
        out.append(candidate)
    return out


class PoolExhausted(RuntimeError):
    """No hubo conexión libre en el tiempo de espera."""


class ConnectionPool:
    """Pool acotado y thread-safe sobre conexiones pymysql.

    El tope es deliberado: MySQL comparte `max_connections` con Laravel y sus
    workers, así que el MCP nunca debe poder agotarlo por su cuenta.
    """

    def __init__(self, factory, size: int, timeout: float = 10.0):
        if size < 1:
            raise ValueError("ConnectionPool: size debe ser >= 1")
        self._factory = factory
        self._size = size
        self._timeout = timeout
        self._free: queue.LifoQueue = queue.LifoQueue(maxsize=size)
        self._slots = threading.BoundedSemaphore(size)

    def acquire(self):
        if not self._slots.acquire(timeout=self._timeout):
            raise PoolExhausted(
                f"pool de conexiones saturado ({self._size}) tras {self._timeout:.0f}s. "
                "Reintenta en unos segundos o reduce la concurrencia."
            )
        try:
            return self._free.get_nowait()
        except queue.Empty:
            try:
                return self._factory()
            except Exception:
                self._slots.release()
                raise

    def release(self, conn) -> None:
        try:
            # Descarta conexiones muertas o cortadas por wait_timeout de MySQL.
            if getattr(conn, "open", True) is False:
                raise pymysql.err.OperationalError(2013, "conexión perdida")
            conn.ping(reconnect=False)
        except Exception:
            _close_quietly(conn)
            self._slots.release()
            return
        try:
            self._free.put_nowait(conn)
        except queue.Full:
            _close_quietly(conn)
        finally:
            self._slots.release()

    def close_all(self) -> None:
        while True:
            try:
                _close_quietly(self._free.get_nowait())
            except queue.Empty:
                return
            except Exception:
                return


def _close_quietly(conn) -> None:
    close = getattr(conn, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception as exc:  # noqa: BLE001 — cerrar nunca debe tumbar la tool
        _warn(f"no se pudo cerrar una conexión: {exc}")


class QueryExecutor:
    def __init__(self, cfg):
        self.cfg = cfg
        size = int(getattr(cfg, "pool_size", 0) or 0)
        self._pool = ConnectionPool(self._open, size) if size > 0 else None

    def _open(self):
        return pymysql.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.db,
            charset="utf8mb4",
            # Cursor por TUPLAS, no DictCursor: la fila se arma por posición con
            # _unique_cols, así dos columnas homónimas conservan ambas su valor.
            cursorclass=pymysql.cursors.Cursor,
            read_timeout=int(getattr(self.cfg, "read_timeout_s", 20) or 20),
            connect_timeout=int(getattr(self.cfg, "connect_timeout_s", 5) or 5),
            # Sin transacción abierta: una sesión con snapshot viejo impide purgar
            # en la réplica y genera lag.
            autocommit=True,
        )

    def _configure(self, c) -> None:
        # Aborta SELECT lentas en el SERVIDOR (no solo socket) vía max_execution_time.
        # MySQL 5.7.8+; si la variable no existe (MySQL viejo) se ignora (no fatal).
        timeout_ms = int(getattr(self.cfg, "query_timeout_ms", None) or 15000)
        try:
            with c.cursor() as cur:
                cur.execute(f"SET SESSION max_execution_time = {timeout_ms}")
        except pymysql.err.OperationalError as exc:
            # No fatal (MySQL < 5.7.8), pero debe quedar rastro: significa que
            # las queries lentas no se están abortando en el servidor.
            _warn(f"max_execution_time no aplicado ({exc}); las queries lentas no se abortan solas")

    def _note_slow(self, sql: str, elapsed_ms: int) -> None:
        threshold = getattr(self.cfg, "slow_query_ms", None) or 5000
        if elapsed_ms < threshold:
            return
        data_dir = getattr(self.cfg, "data_dir", None)
        if not data_dir:
            return
        try:
            path = Path(data_dir) / "slow_queries.jsonl"
            # 0600: igual que audit.jsonl, puede llevar literales de negocio.
            with open_append_private(path) as f:
                f.write(json.dumps(
                    {"ts": time.time(), "ms": elapsed_ms, "sql": sql},
                    ensure_ascii=False,
                ) + "\n")
        except OSError as exc:
            _warn(f"no se pudo registrar la query lenta ({elapsed_ms} ms): {exc}")

    def _tunnel_enabled(self) -> bool:
        return bool(getattr(self.cfg, "tunnel_enabled", True))

    def _connect(self):
        try:
            c = self._open()
        except pymysql.err.OperationalError as e:
            code = e.args[0] if e.args else None
            # En modo servidor NO se intenta abrir un túnel: no hay clave SSH y
            # el fallo de `ssh` taparía el error real de conexión.
            if code not in (2002, 2003, 2013) or not self._tunnel_enabled():
                raise
            state = TunnelManager(self.cfg).ensure()
            if state.startswith("error"):
                raise
            c = self._open()
        self._configure(c)
        return c

    def _conn(self):
        if self._pool is not None:
            return self._pool.acquire()
        return self._connect()

    def _release(self, conn) -> None:
        if self._pool is not None:
            self._pool.release(conn)
            return
        _close_quietly(conn)

    def close(self) -> None:
        """Cierra el pool (apagado ordenado del servicio HTTP)."""
        if self._pool is not None:
            self._pool.close_all()

    def run(self, sql, params=None, limit=100):
        enforce_read_only(sql)
        stmt = _first_stmt(sql)
        clamped = _acotar(stmt, sql, limit)
        rows: list = []
        cols: list = []
        for attempt in (1, 2):
            c = self._conn()
            try:
                with c.cursor() as cur:
                    try:
                        t0 = time.monotonic()
                        cur.execute(clamped, params or None)
                    except pymysql.err.OperationalError as e:
                        if attempt == 2 or not _retryable(e) or not self._tunnel_enabled():
                            raise
                        TunnelManager(self.cfg).ensure()
                        continue
                    cols = (
                        _unique_cols([d[0] for d in cur.description])
                        if cur.description
                        else []
                    )
                    rows = [_convert(dict(zip(cols, values))) for values in cur.fetchall()]
                    self._note_slow(clamped, int((time.monotonic() - t0) * 1000))
                    break
            finally:
                # La conexión vuelve al pool (o se cierra) también si hubo error.
                self._release(c)
        if limit is None and len(rows) > MAX_ROWS:
            raise ValueError(
                f"run: la query devolvió más de {MAX_ROWS} filas sin límite. "
                "Agrega (GROUP BY), filtra o pide un LIMIT; para contar usa COUNT(*)."
            )
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
    """Preserva los tipos que trae pymysql: int, float y sobre todo Decimal.

    Los DECIMAL de MySQL llegan como Decimal y los importes financieros no se
    redondean aquí: quien formatea es format_es y quien suma es exact_sum.
    Antes llevaba tres ramas (int/float, Decimal, resto) que devolvían idéntico
    valor, así que se colapsa a una sola línea sin cambiar el contrato que
    cubre test_convert_preserves_types.
    """
    return dict(row)
