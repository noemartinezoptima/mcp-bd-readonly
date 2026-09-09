import atexit
import socket
import subprocess
import time

from mcp_bd_readonly.config import Config


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class TunnelManager:
    def __init__(self, cfg: Config, remote_port: int = 3306):
        self.cfg = cfg
        self.remote_port = remote_port
        self._proc = None
        self.owned = False

    def ensure(self) -> str:
        """Comprueba que el túnel local está abierto; si no, lo crea.

        Devuelve estado: 'ok' | 'started' | 'error:...'.
        El túnel se lanza como subproceso `ssh` y se cierra con el server.
        """
        if _port_open(self.cfg.host, self.cfg.port):
            return "ok"
        host_key = self.cfg.tunnel_host
        local = f"{self.cfg.port}:127.0.0.1:{self.remote_port}"
        try:
            self._proc = subprocess.Popen(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ExitOnForwardFailure=yes",
                    "-N", "-L", local,
                    host_key,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return "error: ssh no encontrado en PATH"
        self.owned = True
        atexit.register(self.close)
        deadline = time.time() + 15
        while time.time() < deadline:
            if self._proc.poll() is not None:
                return "error: ssh terminó (¿clave ausente en ~/.ssh?)"
            if _port_open(self.cfg.host, self.cfg.port):
                return "started"
            time.sleep(0.3)
        self.close()
        return "error: timeout esperando túnel ssh"

    def close(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None