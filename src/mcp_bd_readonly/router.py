"""Enrutado de lecturas: réplica si está sana y al día, primario si no.

El MCP nunca escribe, así que "fallback" aquí significa solo cambiar el destino
de lectura. La regla es fail-closed con el lag: cifras financieras viejas en
silencio son peores que un error explícito.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from mcp_bd_readonly.db import QueryExecutor

# SHOW REPLICA STATUS (8.0.22+) y SHOW SLAVE STATUS (anterior).
_IO_KEYS = ("Replica_IO_Running", "Slave_IO_Running")
_SQL_KEYS = ("Replica_SQL_Running", "Slave_SQL_Running")
_LAG_KEYS = ("Seconds_Behind_Source", "Seconds_Behind_Master")
_ERR_KEYS = ("Last_SQL_Error", "Last_Error")


def _pick(row: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


@dataclass(frozen=True)
class ReplicaState:
    ok: bool
    lag_s: float | None = None
    reason: str = ""
    checked_at: float = 0.0

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "lag_s": self.lag_s,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


class ReplicaRouter:
    """Duck-type de QueryExecutor que elige destino por consulta."""

    def __init__(
        self,
        primary: QueryExecutor,
        replica: QueryExecutor | None = None,
        lag_max_s: float = 60.0,
        ttl_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.primary = primary
        self.replica = replica
        self.lag_max_s = float(lag_max_s)
        self.ttl_s = float(ttl_s)
        self._clock = clock
        self._cached = ReplicaState(False, None, "sin comprobar", 0.0)
        self.last_destino = "primario"

    # ---------------------------------------------------------------- estado
    def _refresh(self) -> ReplicaState:
        now = self._clock()
        if self.replica is None:
            return ReplicaState(False, None, "sin réplica configurada", now)
        try:
            _, rows = self.replica.run("SHOW REPLICA STATUS", limit=None)
            if not rows:
                _, rows = self.replica.run("SHOW SLAVE STATUS", limit=None)
        except Exception as exc:  # noqa: BLE001 — estado, no consulta de negocio
            return ReplicaState(False, None, f"réplica inaccesible: {exc}", now)
        if not rows:
            return ReplicaState(False, None, "sin canal de replicación configurado", now)

        row = rows[0]
        io = _pick(row, _IO_KEYS)
        sql_thread = _pick(row, _SQL_KEYS)
        lag = _pick(row, _LAG_KEYS)
        err = _pick(row, _ERR_KEYS) or ""
        if str(io).lower() != "yes" or str(sql_thread).lower() != "yes":
            return ReplicaState(
                False, None,
                f"replicación parada (IO={io}, SQL={sql_thread}) {err}".strip(), now,
            )
        if lag is None:
            return ReplicaState(False, None, "lag desconocido", now)
        lag_f = float(lag)
        if lag_f > self.lag_max_s:
            return ReplicaState(
                False, lag_f,
                f"lag {lag_f:.0f}s supera el máximo de {self.lag_max_s:.0f}s", now,
            )
        return ReplicaState(True, lag_f, "", now)

    def replica_state(self, force: bool = False) -> ReplicaState:
        if force or (self._clock() - self._cached.checked_at) >= self.ttl_s:
            self._cached = self._refresh()
        return self._cached

    # ---------------------------------------------------------------- routing
    def _target(self) -> tuple[QueryExecutor, ReplicaState]:
        state = self.replica_state()
        if self.replica is not None and state.ok:
            return self.replica, state
        return self.primary, state

    def run(self, sql, params=None, limit=100):
        target, state = self._target()
        self.last_destino = "replica" if target is self.replica else "primario"
        try:
            return target.run(sql, params=params, limit=limit)
        except Exception:
            if target is self.replica:
                # Fallo a mitad: se marca la réplica como no disponible y se
                # reintenta UNA vez en el primario.
                self._cached = ReplicaState(False, state.lag_s, "fallo en consulta", self._clock())
                self.last_destino = "primario"
                return self.primary.run(sql, params=params, limit=limit)
            raise

    def databases(self):
        return self.run("SHOW DATABASES", limit=None)

    def tables(self):
        return self.run("SHOW TABLES", limit=None)

    def describe(self, table):
        safe = table.replace("`", "``")
        return self.run(f"DESCRIBE `{safe}`", limit=None)

    def close(self) -> None:
        for ex in (self.primary, self.replica):
            close = getattr(ex, "close", None)
            if close is not None:
                close()

    def estado(self) -> dict:
        state = self.replica_state()
        return {
            "destino": self.last_destino,
            "replica_configurada": self.replica is not None,
            "replica": state.as_dict(),
            "lag_max_s": self.lag_max_s,
        }


def build_router(cfg) -> ReplicaRouter | QueryExecutor:
    """Primario + réplica opcional según config."""
    primary = QueryExecutor(cfg)
    replica_host = getattr(cfg, "replica_host", "") or ""
    if not replica_host:
        return primary
    replica_cfg = replace(
        cfg,
        host=replica_host,
        port=int(getattr(cfg, "replica_port", 0) or 0) or cfg.port,
        user=getattr(cfg, "replica_user", "") or cfg.user,
        password=getattr(cfg, "replica_password", "") or cfg.password,
        # La réplica se alcanza por loopback o red privada, nunca por túnel.
        tunnel_enabled=False,
    )
    return ReplicaRouter(primary, QueryExecutor(replica_cfg), lag_max_s=cfg.replica_lag_max_s)
