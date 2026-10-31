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

    # --- conexión / rendimiento -------------------------------------------------
    # Túnel SSH: True por defecto para no cambiar el flujo local (stdio).
    # En el servicio HTTP del servidor va en 0: MySQL está en loopback/réplica local
    # y un `ssh` fallido enmascararía el error real de conexión.
    tunnel_enabled: bool = True
    # 0 = sin pool (una conexión por llamada, como en stdio).
    # En HTTP: 4-6 acotado, para no competir con Laravel por max_connections.
    pool_size: int = 0
    connect_timeout_s: int = 5
    read_timeout_s: int = 20

    # --- réplica de lectura -----------------------------------------------------
    replica_host: str = ""
    replica_port: int = 0  # 0 => mismo puerto que el primario
    replica_user: str = ""
    replica_password: str = ""
    replica_lag_max_s: float = 60.0

    # --- servicio HTTP / API keys ------------------------------------------------
    http_host: str = "127.0.0.1"
    http_port: int = 8443
    allowed_hosts: str = ""  # separado por comas; vacío => solo loopback
    api_keys_path: Path = Path("./data/api_keys.db")
    rate_limit_per_min: int = 120
    # Directorio permitido para las tools de Excel en modo HTTP. Vacío => esas
    # tools no se registran (fallan cerrado en vez de leer rutas del servidor).
    files_dir: str = ""
    # Perfil de tools a registrar: "" o "todas" => las 37 (comportamiento
    # histórico); "contabilidad" / "operaciones" / "excel" => solo las de ese
    # dominio y el tools/list baja de ~4.000 tokens a ~1.000-2.000.
    tool_profile: str = ""


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

    def as_int(key: str, default: int) -> int:
        raw = get(key, "")
        try:
            return int(raw) if raw != "" else default
        except ValueError:
            return default

    def as_float(key: str, default: float) -> float:
        raw = get(key, "")
        try:
            return float(raw) if raw != "" else default
        except ValueError:
            return default

    def as_bool(key: str, default: bool) -> bool:
        raw = get(key, "").strip().lower()
        if raw == "":
            return default
        return raw in ("1", "true", "yes", "si", "sí", "on")

    return Config(
        host=get("MYSQL_HOST", "127.0.0.1"),
        port=as_int("MYSQL_PORT", 13306),
        db=get("MYSQL_DB"),
        user=get("MYSQL_USER"),
        password=get("MYSQL_PASSWORD"),
        data_dir=Path(get("DATA_DIR", "./data")),
        tunnel_host=get("TUNNEL_HOST"),
        query_timeout_ms=as_int("MYSQL_QUERY_TIMEOUT_MS", 15000),
        slow_query_ms=as_int("MYSQL_SLOW_QUERY_MS", 5000),
        tunnel_enabled=as_bool("TUNNEL_ENABLED", True),
        pool_size=as_int("MYSQL_POOL_SIZE", 0),
        connect_timeout_s=as_int("MYSQL_CONNECT_TIMEOUT_S", 5),
        read_timeout_s=as_int("MYSQL_READ_TIMEOUT_S", 20),
        replica_host=get("MYSQL_REPLICA_HOST"),
        replica_port=as_int("MYSQL_REPLICA_PORT", 0),
        replica_user=get("MYSQL_REPLICA_USER"),
        replica_password=get("MYSQL_REPLICA_PASSWORD"),
        replica_lag_max_s=as_float("MYSQL_REPLICA_LAG_MAX_S", 60.0),
        http_host=get("MCP_HTTP_HOST", "127.0.0.1"),
        http_port=as_int("MCP_HTTP_PORT", 8443),
        allowed_hosts=get("MCP_ALLOWED_HOSTS", ""),
        api_keys_path=Path(get("MCP_API_KEYS_DB", "./data/api_keys.db")),
        rate_limit_per_min=as_int("MCP_RATE_LIMIT_PER_MIN", 120),
        files_dir=get("MCP_FILES_DIR"),
        tool_profile=get("MCP_TOOL_PROFILE"),
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
        f"TUNNEL_ENABLED={1 if cfg.tunnel_enabled else 0}",
        f"MYSQL_POOL_SIZE={cfg.pool_size}",
        f"MYSQL_REPLICA_HOST={cfg.replica_host}",
        f"MYSQL_REPLICA_PORT={cfg.replica_port}",
        f"MYSQL_REPLICA_USER={cfg.replica_user}",
        f"MYSQL_REPLICA_LAG_MAX_S={cfg.replica_lag_max_s}",
        f"MCP_FILES_DIR={cfg.files_dir}",
        f"MCP_TOOL_PROFILE={cfg.tool_profile}",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    try:
        dest.chmod(0o600)
    except OSError:
        pass  # Windows no soporta chmod POSIX
    return dest
