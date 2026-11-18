"""App HTTP: transporte streamable-HTTP + API keys + /healthz.

El middleware es ASGI puro (no BaseHTTPMiddleware) para no romper el streaming
de MCP ni acumular respuestas en memoria.
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict, deque
from typing import Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_bd_readonly.auth import KeyStore
from mcp_bd_readonly.request_ctx import reset_api_key, set_api_key

PUBLIC_PATHS = frozenset({"/healthz", "/healthz/"})


def _json_response(send, status: int, payload: dict, extra_headers: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"),
    ]
    for key, value in (extra_headers or {}).items():
        headers.append((key.encode("latin-1"), str(value).encode("latin-1")))
    return send({"type": "http.response.start", "status": status, "headers": headers}), body


class ApiKeyMiddleware:
    """Exige `Authorization: Bearer mcp_<id>_<secreto>` salvo en /healthz."""

    def __init__(
        self,
        app,
        store: KeyStore,
        rate_limit_per_min: int = 120,
        auth_fail_per_min: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.app = app
        self.store = store
        self.rate_limit_per_min = max(1, int(rate_limit_per_min))
        self.auth_fail_per_min = max(1, int(auth_fail_per_min))
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        # Ventana aparte para fallos de autenticación: el 401 salía ANTES del
        # rate limit, así que una clave inválida podía martillear el endpoint
        # (lookup SQLite + sha256 por petición) sin gastar presupuesto y sin
        # dejar rastro en ningún log.
        self._fails: dict[str, deque] = {}

    # Tope de ventanas de fallo: quien rote tokens inventados no puede hacer
    # crecer este dict sin límite (el unit tiene MemoryMax=512M).
    MAX_FAIL_BUCKETS = 10_000

    def _ip(self, scope) -> str:
        client = scope.get("client") or ("?", 0)
        return str(client[0])

    @staticmethod
    def _keyid(token: str) -> str:
        """`mcp_<8 hex>` del intento, nunca el secreto."""
        return token[:12] if token else "-"

    def _fail_key(self, ip: str, token: str) -> str:
        # Detrás de nginx o del túnel el peer es SIEMPRE loopback: una ventana
        # solo por IP la compartirían todos los usuarios y a la primera clave
        # caducada reintentando el resto recibiría 429 durante un minuto. El
        # cupo va por cliente (peer + keyid), que sí distingue a cada uno.
        return f"{ip}|{self._keyid(token)}"

    def _fail_budget_ok(self, ip: str, token: str) -> bool:
        window = self._fails.get(self._fail_key(ip, token))
        if not window:
            return True
        now = self._clock()
        while window and now - window[0] > 60:
            window.popleft()
        return len(window) < self.auth_fail_per_min

    def _note_fail(self, ip: str, token: str) -> None:
        clave = self._fail_key(ip, token)
        window = self._fails.get(clave)
        if window is None:
            if len(self._fails) >= self.MAX_FAIL_BUCKETS:
                return  # mapa lleno: se deja de registrar antes de crecer sin tope
            window = self._fails[clave] = deque()
        window.append(self._clock())
        # Solo el keyid (`mcp_<8 hex>`), nunca el secreto: sirve para saber si
        # alguien está probando claves o si un cliente tiene una clave vieja.
        print(f"mcp-optima-bd: auth fallida ip={ip} key={self._keyid(token)}", file=sys.stderr)

    def _rate_limited(self, key_id: str) -> bool:
        now = self._clock()
        window = self._hits[key_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.rate_limit_per_min:
            return True
        window.append(now)
        return False

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path in PUBLIC_PATHS:
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        raw = headers.get("authorization", "")
        token = raw[7:].strip() if raw[:7].lower() == "bearer " else ""

        # Presupuesto de fallos ANTES de tocar SQLite: si no, cada intento
        # inválido cuesta una consulta + un sha256 y no hay tope.
        ip = self._ip(scope)
        if not self._fail_budget_ok(ip, token):
            start, body = _json_response(
                send, 429,
                {"error": "too_many_auth_failures",
                 "detail": f"máximo {self.auth_fail_per_min} fallos de autenticación por minuto."},
                {"Retry-After": "60"},
            )
            await start
            await send({"type": "http.response.body", "body": body})
            return

        info = self.store.verify(token) if token else None

        if info is None:
            self._note_fail(ip, token)
            start, body = _json_response(
                send, 401,
                {"error": "unauthorized", "detail": "API key ausente, inválida, caducada o revocada."},
                {"WWW-Authenticate": 'Bearer realm="mcp-optima-bd"'},
            )
            await start
            await send({"type": "http.response.body", "body": body})
            return

        if self._rate_limited(info.key_id):
            start, body = _json_response(
                send, 429,
                {"error": "rate_limited", "detail": f"máximo {self.rate_limit_per_min} peticiones por minuto."},
                {"Retry-After": "60"},
            )
            await start
            await send({"type": "http.response.body", "body": body})
            return

        # El alcance se guardaba, se testeaba con KeyInfo.allows() y jamás se
        # aplicaba aquí: sin esta comprobación, una key sin 'read' tenía el mismo
        # poder que una con él y --scopes era decorativo.
        # Va DESPUÉS del rate limit a propósito: si no, una key con alcance
        # inválido recibiría 403 sin gastar presupuesto y podría martillear el
        # endpoint (lookup SQLite + sha256 por petición) sin límite alguno.
        if not info.allows("read"):
            start, body = _json_response(
                send, 403,
                {"error": "forbidden", "detail": "La API key no tiene el alcance 'read'."},
            )
            await start
            await send({"type": "http.response.body", "body": body})
            return

        scope.setdefault("state", {})
        scope["state"]["api_key_id"] = info.key_id
        scope["state"]["api_key_name"] = info.name

        # Fijado en el contextvar (no solo en scope["state"]) para que
        # AuditLogger.record(), llamado desde dentro de las tools sin acceso
        # al scope ASGI, sepa qué API key disparó la query actual.
        token = set_api_key(info.key_id)
        try:
            return await self.app(scope, receive, send)
        finally:
            reset_api_key(token)


def build_app(mcp, store: KeyStore, router=None, rate_limit_per_min: int = 120,
              auth_fail_per_min: int = 30) -> Starlette:
    """Envuelve la app de MCP con /healthz y autenticación por API key."""

    async def healthz(_: Request) -> JSONResponse:
        # /healthz está en PUBLIC_PATHS (sin auth). El detalle del router de
        # réplica (lag, destino) es topología interna: no debe ser legible por
        # cualquiera que golpee el endpoint. Confirmar réplica/lag vía una
        # tool autenticada (p. ej. auditoria) o el log del servicio.
        return JSONResponse(
            {"status": "ok", "servicio": "mcp-optima-bd"},
            headers={"cache-control": "no-store"},
        )

    app = mcp.streamable_http_app()
    app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    app.add_middleware(
        ApiKeyMiddleware,
        store=store,
        rate_limit_per_min=rate_limit_per_min,
        auth_fail_per_min=auth_fail_per_min,
    )
    return app
