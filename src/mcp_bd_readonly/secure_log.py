"""Apertura de ficheros de log append-only con permisos restrictivos.

`audit.jsonl` y `slow_queries.jsonl` guardan el SQL íntegro ejecutado (puede
incluir literales de negocio: NIFs, importes, nombres de cliente). Un
`open(path, "a")` normal crea el fichero con el umask del proceso (típicamente
0644, legible por cualquier usuario del host). Aquí se fuerza 0600 en la
creación, y se corrige si el fichero ya existía con permisos más abiertos.
"""

import os
import stat
from pathlib import Path


def write_text_private(path: Path, content: str) -> None:
    """Como `Path.write_text`, pero crea/corrige el fichero a 0600.

    Usado por `memoria.json`: guarda resúmenes de consultas con cifras de
    negocio reales (importes, IVA), igual de sensible que los audit logs.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)


def open_append_private(path: Path):
    """Abre `path` en modo append, creándolo con 0600 si no existe.

    Si el fichero ya existe con permisos más abiertos que 0600, los corrige
    antes de escribir (por ejemplo, ficheros creados antes de este fix).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        current_mode = stat.S_IMODE(os.fstat(fd).st_mode)
        if current_mode != 0o600:
            os.fchmod(fd, 0o600)
    except OSError:
        pass
    return os.fdopen(fd, "a")
