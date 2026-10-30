"""App HTTP: transporte streamable-HTTP + API keys + /healthz.

El middleware es ASGI puro (no BaseHTTPMiddleware) para no romper el streaming
de MCP ni acumular respuestas en memoria.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from typing import Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_bd_readonly.auth import KeyStore

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
        clock: Callable[[], float] = time.monotonic,
    ):
        self.app = app
        self.store = store
        self.rate_limit_per_min = max(1, int(rate_limit_per_min))
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)

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
        info = self.store.verify(token) if token else None

        if info is None:
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
        return await self.app(scope, receive, send)


def build_app(mcp, store: KeyStore, router=None, rate_limit_per_min: int = 120) -> Starlette:
    """Envuelve la app de MCP con /healthz y autenticación por API key."""

    async def healthz(_: Request) -> JSONResponse:
        estado = router.estado() if hasattr(router, "estado") else {"destino": "primario"}
        return JSONResponse(
            {"status": "ok", "servicio": "mcp-optima-bd", "replica": estado},
            headers={"cache-control": "no-store"},
        )

    app = mcp.streamable_http_app()
    app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    app.add_middleware(ApiKeyMiddleware, store=store, rate_limit_per_min=rate_limit_per_min)
    return app
