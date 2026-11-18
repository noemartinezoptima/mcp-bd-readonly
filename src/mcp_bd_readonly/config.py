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

    # --- ciclo de vida de conexiones (multiusuario) ---------------------------
    # Tope de sesiones VIVAS **por ejecutor** cuando se usa el pool
    # multiusuario. OJO: con réplica configurada hay dos ejecutores (primario y
    # réplica, ver router.build_router), así que el total del proceso es 2×.
    # 0 => no se activa (se usa `pool_size`).
    pool_max: int = 0
    # Cierre por inactividad en segundos. 0 => nunca expira (pool clásico).
    # Es la pieza que impide que el MCP se quede con el cupo del usuario MySQL
    # (error 1203 para el resto de usuarios) mientras nadie consulta.
    pool_idle_s: float = 0.0
    # Cupo de conexiones por API key (0 => sin cupo por clave). Evita que una
    # persona con queries lentas deje sin conexión a las demás.
    pool_max_per_key: int = 0
    # Espera máxima por un hueco del pool antes de fallar (s).
    pool_wait_s: float = 10.0
    # Tope de filas materializadas por query. En HTTP conviene bajarlo: 50.000
    # filas anchas pueden agotar MemoryMax=512M del unit y tumbar el servicio
    # para todos los usuarios.
    max_rows: int = 50_000
    # run_script ejecuta Python enviado por el cliente. Tri-estado: None =>
    # habilitado en stdio y DESHABILITADO en HTTP (fail-closed), que es el modo
    # donde el código viene de la red. `MCP_ENABLE_RUN_SCRIPT=1` lo reactiva.
    enable_run_script: bool | None = None
    # Fallos de autenticación por IP y minuto antes de responder 429: sin esto
    # el 401 se comprobaba antes del rate limit y se podía martillear el
    # endpoint (lookup SQLite + sha256 por petición) sin límite.
    auth_fail_per_min: int = 30

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

    def as_tri_bool(key: str) -> bool | None:
        """None si la variable no está definida (el default depende del modo)."""
        raw = get(key, "").strip().lower()
        if raw == "":
            return None
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
        pool_max=as_int("MYSQL_POOL_MAX", 0),
        pool_idle_s=as_float("MYSQL_POOL_IDLE_S", 0.0),
        pool_max_per_key=as_int("MYSQL_POOL_MAX_PER_KEY", 0),
        pool_wait_s=as_float("MYSQL_POOL_WAIT_S", 10.0),
        max_rows=as_int("MYSQL_MAX_ROWS", 50_000),
        enable_run_script=as_tri_bool("MCP_ENABLE_RUN_SCRIPT"),
        auth_fail_per_min=as_int("MCP_AUTH_FAIL_PER_MIN", 30),
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
        f"MYSQL_POOL_MAX={cfg.pool_max}",
        f"MYSQL_POOL_IDLE_S={cfg.pool_idle_s:g}",
        f"MYSQL_POOL_MAX_PER_KEY={cfg.pool_max_per_key}",
        f"MYSQL_POOL_WAIT_S={cfg.pool_wait_s:g}",
        f"MYSQL_MAX_ROWS={cfg.max_rows}",
        "MCP_ENABLE_RUN_SCRIPT=" + (
            "" if cfg.enable_run_script is None else ("1" if cfg.enable_run_script else "0")
        ),
        f"MCP_AUTH_FAIL_PER_MIN={cfg.auth_fail_per_min}",
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
