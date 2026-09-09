import os
import subprocess

HOST = os.environ.get("SSH_HOST", "db-host")
HOST_NAME = os.environ.get("SSH_HOSTNAME", "db-host.example.com")
USER = os.environ.get("SSH_USER", "forge")


def _key_path() -> str:
    return os.path.expanduser("~/.ssh/id_ed25519")


def _ssh_cfg_path() -> str:
    return os.path.expanduser("~/.ssh/config")


def _config_block(key: str) -> str:
    return f"\nHost {HOST}\n  HostName {HOST_NAME}\n  User {USER}\n  IdentityFile {key}\n"


def _host_configured() -> bool:
    cfg = _ssh_cfg_path()
    if not os.path.exists(cfg):
        return False
    with open(cfg, encoding="utf-8") as f:
        for line in f:
            if line.strip() == f"Host {HOST}":
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


def setup_ssh(email: str | None = None) -> dict:
    """Prepara SSH para el túnel de BD: genera clave ed25519 si falta, añade el host al config, y devuelve la clave pública lista para Forge."""
    key = _key_path()
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
    if _host_configured():
        steps.append(f"Host {HOST} ya definido en {cfg}")
    else:
        with open(cfg, "a", encoding="utf-8") as f:
            f.write(_config_block(key))
        os.chmod(cfg, 0o600)
        steps.append(f"Añadido host {HOST} ({HOST_NAME}, user {USER}) a {cfg}")

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
        "host": HOST,
        "hostname": HOST_NAME,
        "clave_publica": public_key,
        "en_portapapeles": copied,
        "pendiente": f"Añadir la clave pública al servidor ({HOST}): configúralo en el panel del proveedor (Forge u otro), luego prueba: ssh {HOST} 'echo OK'",
    }