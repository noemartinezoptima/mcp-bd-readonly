"""Contextvar con la API key de la request HTTP en curso.

`ApiKeyMiddleware` (http_app.py) ya resuelve `api_key_id`/`api_key_name` por
request pero los guardaba solo en `scope["state"]`, invisible para las tools
(funciones planas sin acceso al scope ASGI). Un contextvar fijado en el mismo
task asyncio que despacha la request sí es visible desde cualquier código que
se ejecute dentro de ella, incluidas las tools — sin tener que added un
parámetro `Context` a las ~37 tools existentes.

En modo stdio (sin HTTP, sin API key) nunca se fija: `get_api_key()` devuelve
`None` y el llamador cae a su valor por defecto.
"""

from __future__ import annotations

import contextvars

_current_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_api_key", default=None
)


def set_api_key(key_id: str | None) -> contextvars.Token:
    return _current_api_key.set(key_id)


def reset_api_key(token: contextvars.Token) -> None:
    _current_api_key.reset(token)


def get_api_key() -> str | None:
    return _current_api_key.get()
