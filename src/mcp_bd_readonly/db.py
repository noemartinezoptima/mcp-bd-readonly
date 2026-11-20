import json
import re
import sys
import threading
import time
from pathlib import Path

import pymysql

from mcp_bd_readonly.request_ctx import get_api_key
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


def _acotar(stmt: str, sql: str, limit, max_rows: int = MAX_ROWS) -> str:
    """Acota la query en SQL antes de ejecutarla.

    - LIMIT explícito por encima de `max_rows`: error, no se ejecuta.
    - LIMIT explícito razonable (o con placeholder): se respeta tal cual.
    - sin LIMIT y limit=N: se añade LIMIT N.
    - sin LIMIT y limit=None ("todas"): se añade LIMIT max_rows+1 para detectar
      el desbordamiento sin materializar la tabla completa.

    `max_rows` es configurable (`MYSQL_MAX_ROWS`): en el servicio HTTP se baja
    del default porque materializar 50.000 filas anchas puede agotar los 512 MB
    del unit de systemd y tumbar el proceso para TODOS los usuarios.
    """
    if not _single_select(sql):
        return sql
    has_limit, declared = _limit_clause(stmt)
    if has_limit:
        if declared is not None and declared > max_rows:
            raise ValueError(
                f"run: la query pide {declared} filas y el máximo es {max_rows}. "
                "Agrega (GROUP BY), filtra o baja el LIMIT; para contar usa COUNT(*)."
            )
        return sql
    cuerpo = sql.rstrip().rstrip(";")
    # El LIMIT va en línea nueva: si la query acaba en un comentario `--`, un
    # LIMIT en la misma línea quedaría comentado y no acotaría nada.
    if limit:
        return f"{cuerpo}\nLIMIT {int(limit)}"
    if limit is None:
        return f"{cuerpo}\nLIMIT {max_rows + 1}"
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

    Tres garantías, todas deliberadas porque MySQL comparte `max_connections`
    con Laravel y sus workers:

    - `size`: tope de sesiones **vivas** (en uso + ociosas). Nunca se abre una
      más: si no hay hueco se desaloja la ociosa más vieja y, si no hay, se
      espera hasta `timeout` y se falla con `PoolExhausted`.
    - `idle_s > 0`: cierre por inactividad. Sin esto una sesión queda aparcada
      hasta el `wait_timeout` de MySQL (8 h por defecto) y el MCP se queda con
      el cupo del usuario MySQL aunque nadie consulte. Ese fue el bug real que
      dejó a un humano sin conexiones (error 1203).
    - `per_key`: cupo por API key, para que una persona con queries lentas no
      deje sin conexión a las demás.

    Con `idle_s=0` y `per_key=0` se comporta como el pool clásico (reutiliza y
    no expira), que es lo que usa el modo stdio.
    """

    def __init__(self, factory, size: int, timeout: float = 10.0,
                 idle_s: float = 0.0, per_key: int = 0):
        if size < 1:
            raise ValueError("ConnectionPool: size debe ser >= 1")
        self._factory = factory
        self._size = size
        self._timeout = float(timeout)
        self._idle_s = max(0.0, float(idle_s or 0.0))
        self._per_key = max(0, int(per_key or 0))
        self._lock = threading.Lock()
        self._idle: dict[str, list[tuple[float, object]]] = {}
        self._in_use: dict[str, int] = {}
        self._live = 0
        self._closed = False
        self._sweeper: threading.Thread | None = None
        if self._idle_s > 0:
            self._start_sweeper()

    # ------------------------------------------------------------- ciclo
    def acquire(self, key: str = ""):
        key = key or ""
        deadline = time.monotonic() + self._timeout
        while True:
            conn, caducadas = self._take(key)
            for vieja in caducadas:
                self._discard(vieja)
            if conn is not None:
                if self._ping_ok(conn):
                    return conn
                # `_take` ya la contó como en uso para esta clave: hay que
                # devolver también ese contador o el cupo por clave queda
                # gastado para siempre.
                self._discard(conn, key)
                continue
            if self._reserve(key):
                try:
                    return self._factory()
                except Exception:
                    self._free_slot(key)
                    raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PoolExhausted(self._agotado(key))
            # Sondeo corto en vez de Condition: los huecos se liberan desde
            # hilos de anyio y un wait/notify mal emparejado dejaría clientes
            # esperando 10 s sin motivo.
            time.sleep(min(0.05, remaining))

    def release(self, conn, key: str = "") -> None:
        key = key or ""
        # Descarta conexiones muertas o cortadas por wait_timeout de MySQL.
        vivo = self._ping_ok(conn)
        guardar = False
        with self._lock:
            self._in_use[key] = max(0, self._in_use.get(key, 0) - 1)
            if not self._in_use[key]:
                self._in_use.pop(key, None)
            if vivo and not self._closed:
                ociosas = self._idle.setdefault(key, [])
                if self._per_key == 0 or len(ociosas) < self._per_key:
                    ociosas.append((time.monotonic(), conn))
                    guardar = True
        if not guardar:
            self._discard(conn)

    def sweep(self, now: float | None = None) -> int:
        """Cierra las conexiones ociosas más viejas que `idle_s`. Devuelve cuántas."""
        if self._idle_s <= 0:
            return 0
        ahora = time.monotonic() if now is None else now
        caducadas: list = []
        with self._lock:
            for key in list(self._idle):
                vivas = []
                for ts, conn in self._idle[key]:
                    if ahora - ts > self._idle_s:
                        caducadas.append(conn)
                    else:
                        vivas.append((ts, conn))
                if vivas:
                    self._idle[key] = vivas
                else:
                    self._idle.pop(key, None)
        for conn in caducadas:
            self._discard(conn)
        return len(caducadas)

    def stats(self) -> dict:
        """Estado del pool para observabilidad (sin datos de negocio)."""
        with self._lock:
            ociosas = {k: len(v) for k, v in self._idle.items() if v}
            en_uso = {k: n for k, n in self._in_use.items() if n > 0}
            return {
                "tope": self._size,
                "vivas": self._live,
                "en_uso": sum(en_uso.values()),
                "ociosas": sum(ociosas.values()),
                "idle_s": self._idle_s,
                "tope_por_clave": self._per_key,
                "por_clave": {
                    k: {"en_uso": en_uso.get(k, 0), "ociosas": ociosas.get(k, 0)}
                    for k in set(en_uso) | set(ociosas)
                },
            }

    def close_all(self) -> None:
        self._closed = True
        caducadas: list = []
        with self._lock:
            for items in self._idle.values():
                caducadas.extend(conn for _, conn in items)
            self._idle.clear()
        for conn in caducadas:
            self._discard(conn)

    # ------------------------------------------------------------ interno
    def _start_sweeper(self) -> None:
        # Barrido fino: como mucho 5 s, para que el TTL no se estire. Con
        # idle_s=60 una sesión ociosa vive 60-65 s, no 75 (antes el tope del
        # intervalo era 15 s). El coste es un lock + recorrido cada 5 s.
        intervalo = max(1.0, min(5.0, self._idle_s / 2))

        def _loop() -> None:
            while not self._closed:
                time.sleep(intervalo)
                try:
                    self.sweep()
                except Exception as exc:  # noqa: BLE001 — nunca tumbar el servicio
                    _warn(f"barrido de conexiones ociosas falló: {exc}")

        self._sweeper = threading.Thread(target=_loop, name="mcp-pool-sweeper", daemon=True)
        self._sweeper.start()

    def _take(self, key: str):
        """Saca la conexión ociosa más reciente de esa clave (LIFO)."""
        caducadas: list = []
        with self._lock:
            items = self._idle.get(key)
            while items:
                ts, conn = items.pop()
                if self._idle_s > 0 and time.monotonic() - ts > self._idle_s:
                    caducadas.append(conn)
                    continue
                self._in_use[key] = self._in_use.get(key, 0) + 1
                if not items:
                    self._idle.pop(key, None)
                return conn, caducadas
            self._idle.pop(key, None)
        return None, caducadas

    def _reserve(self, key: str) -> bool:
        """Reserva un hueco para abrir una conexión nueva (o desaloja una ociosa)."""
        victima = None
        with self._lock:
            if self._per_key:
                usadas = self._in_use.get(key, 0) + len(self._idle.get(key, ()))
                if usadas >= self._per_key:
                    return False
            if self._live >= self._size:
                victima = self._oldest_idle()
                if victima is None:
                    return False
                self._live -= 1
            self._live += 1
            self._in_use[key] = self._in_use.get(key, 0) + 1
        if victima is not None:
            _close_quietly(victima)
        return True

    def _oldest_idle(self):
        """Saca la conexión ociosa más vieja de todo el pool. Debe llamarse con lock."""
        mejor_key, mejor_ts, mejor_i = None, None, -1
        for key, items in self._idle.items():
            for i, (ts, _conn) in enumerate(items):
                if mejor_ts is None or ts < mejor_ts:
                    mejor_key, mejor_ts, mejor_i = key, ts, i
        if mejor_key is None:
            return None
        items = self._idle[mejor_key]
        _ts, conn = items.pop(mejor_i)
        if not items:
            self._idle.pop(mejor_key, None)
        return conn

    def _discard(self, conn, key: str | None = None) -> None:
        """Cierra y descuenta. `key` solo se pasa si la conexión venía contada
        como en uso de esa clave (`_take`): si no, se descontaría dos veces."""
        _close_quietly(conn)
        with self._lock:
            self._live = max(0, self._live - 1)
            if key is not None:
                self._in_use[key] = max(0, self._in_use.get(key, 0) - 1)
                if not self._in_use[key]:
                    self._in_use.pop(key, None)

    def _free_slot(self, key: str) -> None:
        with self._lock:
            self._in_use[key] = max(0, self._in_use.get(key, 0) - 1)
            self._live = max(0, self._live - 1)

    def _ping_ok(self, conn) -> bool:
        try:
            if getattr(conn, "open", True) is False:
                return False
            conn.ping(reconnect=False)
            return True
        except Exception:
            return False

    def _agotado(self, key: str) -> str:
        if self._per_key:
            with self._lock:
                usadas = self._in_use.get(key, 0) + len(self._idle.get(key, ()))
            if usadas >= self._per_key:
                return (
                    f"cupo por API key alcanzado ({self._per_key} conexiones) tras "
                    f"{self._timeout:.0f}s. Espera a que terminen tus consultas "
                    "anteriores y reintenta."
                )
        return (
            f"pool de conexiones saturado ({self._size}) tras {self._timeout:.0f}s. "
            "Reintenta en unos segundos o reduce la concurrencia."
        )


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
        # Dos modos de pool, ambos acotados:
        #  - `pool_size` (clásico): tamaño fijo, sin expiración por inactividad.
        #  - `pool_max` (multiusuario): tope global + `pool_idle_s` de TTL y
        #    `pool_max_per_key` por API key.
        # La factory es `_connect` (no `_open`) para que TODA conexión pase por
        # `_configure()`: antes las del pool se quedaban sin `max_execution_time`
        # y una SELECT lenta no se abortaba en el servidor.
        size = int(getattr(cfg, "pool_size", 0) or 0)
        tope = int(getattr(cfg, "pool_max", 0) or 0)
        capacidad = tope or size
        self.max_rows = int(getattr(cfg, "max_rows", 0) or MAX_ROWS)
        self._pool = None
        if capacidad > 0:
            self._pool = ConnectionPool(
                self._connect,
                capacidad,
                timeout=float(getattr(cfg, "pool_wait_s", 10.0) or 10.0),
                idle_s=float(getattr(cfg, "pool_idle_s", 0) or 0),
                per_key=int(getattr(cfg, "pool_max_per_key", 0) or 0),
            )

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
                cur.execute("SET SESSION max_execution_time = %s", (timeout_ms,))
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

    @staticmethod
    def _pool_key() -> str:
        """Clave con la que se reparte el pool: la API key de la request HTTP.

        En stdio (sin middleware) vale "" y el pool se comporta como el clásico.
        Se lee del contextvar en cada llamada, no se pasa por parámetro, para no
        cambiar la firma de `_conn`/`_release` que ya usan los dobles de test.
        """
        return get_api_key() or ""

    def _conn(self):
        if self._pool is not None:
            return self._pool.acquire(self._pool_key())
        return self._connect()

    def _release(self, conn) -> None:
        if self._pool is not None:
            self._pool.release(conn, self._pool_key())
            return
        _close_quietly(conn)

    def close(self) -> None:
        """Cierra el pool (apagado ordenado del servicio HTTP)."""
        if self._pool is not None:
            self._pool.close_all()

    def pool_stats(self) -> dict | None:
        """Estado del pool para `estado_cupos`/diagnóstico. None si no hay pool."""
        if self._pool is None:
            return None
        return self._pool.stats()

    def run(self, sql, params=None, limit=100):
        enforce_read_only(sql)
        stmt = _first_stmt(sql)
        clamped = _acotar(stmt, sql, limit, self.max_rows)
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
        if limit is None and len(rows) > self.max_rows:
            raise ValueError(
                f"run: la query devolvió más de {self.max_rows} filas sin límite. "
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
