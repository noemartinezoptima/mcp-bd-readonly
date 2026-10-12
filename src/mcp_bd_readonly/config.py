import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    host: str
    port: int
    db: str
    user: str
    password: str
    data_dir: Path
    tunnel_host: str
    query_timeout_ms: int = 15000
    slow_query_ms: int = 5000


def _load_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def load_config(env_file: Path | None = None) -> Config:
    file = env_file or Path.home() / ".zt-readonly.env"
    base = _load_env_file(file)

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or base.get(key) or default

    return Config(
        host=get("MYSQL_HOST", "127.0.0.1"),
        port=int(get("MYSQL_PORT", "13306")),
        db=get("MYSQL_DB"),
        user=get("MYSQL_USER"),
        password=get("MYSQL_PASSWORD"),
        data_dir=Path(get("DATA_DIR", "./data")),
        tunnel_host=get("TUNNEL_HOST"),
        query_timeout_ms=int(get("MYSQL_QUERY_TIMEOUT_MS", "15000")),
        slow_query_ms=int(get("MYSQL_SLOW_QUERY_MS", "5000")),
    )


def write_config(cfg: Config, path: Path | None = None, force: bool = False) -> Path:
    """Escribe ~/.zt-readonly.env (modo 0600). No pisa si existe salvo force=True.

    Simétrico a load_config(): lo que aquí se escribe es lo que load_config() lee.
    """
    dest = path or Path.home() / ".zt-readonly.env"
    if dest.exists() and not force:
        raise FileExistsError(
            f"{dest} ya existe; usa force=True para sobrescribir"
        )
    lines = [
        "# Generado por mcp-optima-bd (write_config)",
        f"MYSQL_HOST={cfg.host}",
        f"MYSQL_PORT={cfg.port}",
        f"MYSQL_DB={cfg.db}",
        f"MYSQL_USER={cfg.user}",
        f"MYSQL_PASSWORD={cfg.password}",
        f"DATA_DIR={cfg.data_dir}",
        f"TUNNEL_HOST={cfg.tunnel_host}",
        f"MYSQL_QUERY_TIMEOUT_MS={cfg.query_timeout_ms}",
        f"MYSQL_SLOW_QUERY_MS={cfg.slow_query_ms}",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    try:
        dest.chmod(0o600)
    except OSError:
        pass  # Windows no soporta chmod POSIX
    return dest
