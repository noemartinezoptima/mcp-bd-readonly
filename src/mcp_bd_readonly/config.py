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
        tunnel_host=get("TUNNEL_HOST", "db-host"),
    )
