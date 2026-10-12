import os
import subprocess

HOST = os.environ.get("SSH_HOST", "db-host")
HOST_NAME = os.environ.get("SSH_HOSTNAME", "db-host.example.com")
USER = os.environ.get("SSH_USER", "forge")
DEFAULT_KEY = os.environ.get("SSH_KEY", "~/.ssh/id_ed25519")


def _key_path(key_path: str | None = None) -> str:
    return os.path.expanduser(key_path or DEFAULT_KEY)


def _ssh_cfg_path() -> str:
    return os.path.expanduser("~/.ssh/config")


def _config_block(key: str, host: str, hostname: str, user: str) -> str:
    return f"\nHost {host}\n  HostName {hostname}\n  User {user}\n  IdentityFile {key}\n"


def _host_configured(host: str) -> bool:
    cfg = _ssh_cfg_path()
    if not os.path.exists(cfg):
        return False
    with open(cfg, encoding="utf-8") as f:
        for line in f:
            if line.strip() == f"Host {host}":
                return True
    return False


def _copy_to_clipboard(text: str) -> bool:
    for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["clip.exe"]):
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False


def setup_ssh(
    email: str | None = None,
    confirmar: bool = False,
    host: str | None = None,
    hostname: str | None = None,
    user: str | None = None,
    key_path: str | None = None,
) -> dict:
    """[ADMIN] Prepara SSH para el túnel de BD.

    Genera clave ed25519 si falta (o usa la ruta dada), añade el host a
    ~/.ssh/config y copia la clave pública al portapapeles. Requiere
    confirmación explícita: confirmar=True.

    host/hostname/user/key_path son DINÁMICOS: si no se pasan, caen a los
    defaults (env SSH_HOST/SSH_HOSTNAME/SSH_USER/SSH_KEY o db-host/forge).
    """
    if not confirmar:
        return {
            "ok": False,
            "error": "setup_ssh es [ADMIN]: escribe en el sistema (clave SSH + ~/.ssh/config + portapapeles). "
                     "Rechazada sin confirmación explícita. Pide aprobación al humano y llama con confirmar=True.",
        }
    host = host or HOST
    hostname = hostname or HOST_NAME
    user = user or USER
    key = _key_path(key_path)
    cfg = _ssh_cfg_path()
    steps = []
    generated = False

    bootstrapped_email = None
    if not os.path.exists(key):
        missing = "No existe clave SSH en {KEY}".replace("{KEY}", key)
        if not email:
            try:
                email = os.environ.get("GIT_AUTHOR_EMAIL") or subprocess.run(
                    ["git", "config", "--global", "user.email"],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()
            except (FileNotFoundError, subprocess.CalledProcessError):
                email = None
        if not email:
            raise ValueError(
                "No existe clave SSH y el parámetro email no llegó. "
                "Pasa email ('setup_ssh(email=\"tu@correo\")') o configúralo global "
                "con 'git config --global user.email'."
            )
        os.makedirs(os.path.dirname(key), exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-C", email, "-N", "", "-f", key],
            check=True,
        )
        bootstrapped_email = email
        generated = True
        steps.append(f"Generada clave ed25519 en {key} (comentario: {email})")
    else:
        steps.append(f"Clave OK: {key} (ya existía)")

    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    if _host_configured(host):
        steps.append(f"Host {host} ya definido en {cfg}")
    else:
        with open(cfg, "a", encoding="utf-8") as f:
            f.write(_config_block(key, host, hostname, user))
        os.chmod(cfg, 0o600)
        steps.append(f"Añadido host {host} ({hostname}, user {user}) a {cfg}")

    with open(key + ".pub", encoding="utf-8") as f:
        public_key = f.read().strip()

    copied = _copy_to_clipboard(public_key)
    if copied:
        steps.append("Clave pública copiada al portapapeles")

    return {
        "ok": True,
        "clave_generada": generated,
        "steps": steps,
        "email": bootstrapped_email,
        "host": host,
        "hostname": hostname,
        "key": key,
        "clave_publica": public_key,
        "en_portapapeles": copied,
        "pendiente": f"Añadir la clave pública al servidor ({host}): configúralo en el panel del proveedor (Forge u otro), luego prueba: ssh {host} 'echo OK'",
    }
