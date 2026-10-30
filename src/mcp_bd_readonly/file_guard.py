"""Controla el acceso a rutas de fichero de las tools de Excel.

Tres modos:
- `allow_paths=True, root=None`  → sin restricción (stdio local: son tus rutas).
- `allow_paths=True, root=<dir>` → solo dentro de ese directorio.
- `allow_paths=False`            → ninguna ruta: el contenido debe llegar en la
  petición (base64). Es el modo del servidor remoto, donde una ruta apuntaría al
  disco del servidor y nada debe escribirse en él.

`.resolve()` sigue symlinks a propósito: un enlace dentro del directorio que
apunte fuera se resuelve fuera y se rechaza.
"""

from pathlib import Path

_root: Path | None = None
_allow_paths: bool = True


class OutsideSandbox(ValueError):
    """La ruta pedida cae fuera del directorio permitido."""


class PathsDisabled(ValueError):
    """El acceso a rutas está deshabilitado; hay que enviar el contenido."""


def configure(root: str | Path | None = None, allow_paths: bool = True) -> None:
    """Fija el directorio permitido y si se admiten rutas."""
    global _root, _allow_paths
    _root = Path(root).expanduser().resolve() if root else None
    _allow_paths = bool(allow_paths)


def root() -> Path | None:
    return _root


def paths_allowed() -> bool:
    return _allow_paths


def resolve(path: str | Path) -> Path:
    """Resuelve `path` y verifica que esté dentro del sandbox configurado."""
    if not _allow_paths:
        raise PathsDisabled(
            "este servidor no lee rutas de fichero: envía el Excel en "
            "contenido_b64 (en memoria, sin escribir en disco)."
        )
    resolved = Path(path).expanduser().resolve()
    allowed = _root
    if allowed is None:
        return resolved
    if resolved != allowed and allowed not in resolved.parents:
        raise OutsideSandbox(
            f"ruta no permitida: {resolved} está fuera de {allowed}. "
            "En modo servidor solo se leen ficheros de ese directorio."
        )
    return resolved
