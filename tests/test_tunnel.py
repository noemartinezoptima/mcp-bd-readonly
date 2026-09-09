import socket

from mcp_bd_readonly.config import Config
from mcp_bd_readonly.tunnel import TunnelManager, _port_open


def make_cfg(port):
    return Config(
        host="127.0.0.1", port=port, db="back",
        user="u", password="p", data_dir=object(),
        tunnel_host="db-host",
    )


def test_port_open_true_when_listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert _port_open("127.0.0.1", port, timeout=1) is True
    finally:
        srv.close()


def test_port_open_false_empty():
    assert _port_open("127.0.0.1", 1, timeout=0.2) is False


def test_ensure_ok_when_port_up():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        tm = TunnelManager(make_cfg(port))
        assert tm.ensure() == "ok"
        assert tm.owned is False
        assert tm._proc is None
    finally:
        srv.close()


def test_ensure_started_spawns_ssh(monkeypatch):
    class FakeProc:
        def __init__(self, args, **kw):
            self.args = args
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.killed = True

        def wait(self, timeout=None):
            pass

        def kill(self):
            self.killed = True

    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: spawned.append(args) or FakeProc(args))
    state = {"port": False}
    def fake_port_open(host, port, timeout=2.0):
        if spawned:
            return True
        return state["port"]
    monkeypatch.setattr("mcp_bd_readonly.tunnel._port_open", fake_port_open)
    monkeypatch.setattr("mcp_bd_readonly.tunnel.time.sleep", lambda s: None)

    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tm = TunnelManager(make_cfg(port))
    assert tm.ensure() == "started"
    assert tm.owned is True
    assert spawned and spawned[0][0] == "ssh"
    assert any("-L" in s for s in spawned[0])
    tm.close()
    assert spawned[0][-1] == "db-host"


def test_ensure_error_when_ssh_missing(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr("subprocess.Popen", boom)
    monkeypatch.setattr("mcp_bd_readonly.tunnel._port_open", lambda *a, **k: False)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tm = TunnelManager(make_cfg(port))
    assert tm.ensure().startswith("error")