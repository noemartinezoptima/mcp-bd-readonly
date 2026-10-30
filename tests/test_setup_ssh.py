import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__) + "/../src")
from mcp_bd_readonly import tools_setup


class TestSetupSsh(unittest.TestCase):
    def setUp(self):
        self.home = subprocess.run(
            ["mktemp", "-d"], capture_output=True, text=True, check=True
        ).stdout.strip()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.home], check=True)
        if self._old_home:
            os.environ["HOME"] = self._old_home
        else:
            os.environ.pop("HOME", None)

    def test_generates_key_adds_host(self):
        r = tools_setup.setup_ssh(email="test@dev.local", confirmar=True)
        assert r["ok"] is True
        assert r["clave_generada"] is True
        assert r["email"] == "test@dev.local"
        assert r["host"] == "db-host"
        assert r["clave_publica"].startswith("ssh-ed25519")
        cfg = open(os.path.join(self.home, ".ssh", "config"), encoding="utf-8").read()
        assert "Host db-host" in cfg
        assert "db-host.example.com" in cfg

    def test_idempotent_no_regenerate(self):
        tools_setup.setup_ssh(email="a@b.c", confirmar=True)
        r2 = tools_setup.setup_ssh(email="d@e.f", confirmar=True)
        assert r2["clave_generada"] is False

    def test_errors_without_email(self):
        with self.assertRaises(ValueError):
            tools_setup.setup_ssh(email=None, confirmar=True)

    def test_refuses_without_confirmation(self):
        r = tools_setup.setup_ssh(email="test@dev.local")
        assert r["ok"] is False
        assert "confirm" in r["error"]
        assert not os.path.exists(os.path.join(self.home, ".ssh", "config"))
        assert not os.path.exists(os.path.join(self.home, ".ssh", "id_ed25519"))
        assert not os.path.exists(os.path.join(self.home, ".ssh"))

    def test_dynamic_host_user_and_key(self):
        key = os.path.join(self.home, "custom_ed25519")
        r = tools_setup.setup_ssh(
            email="x@y.z",
            confirmar=True,
            host="mi-host",
            hostname="10.0.0.5",
            user="deploy",
            key_path=key,
        )
        assert r["ok"] is True
        assert r["host"] == "mi-host"
        assert r["hostname"] == "10.0.0.5"
        assert os.path.exists(key)
        cfg = open(os.path.join(self.home, ".ssh", "config"), encoding="utf-8").read()
        assert "Host mi-host" in cfg
        assert "HostName 10.0.0.5" in cfg
        assert "User deploy" in cfg
        assert "IdentityFile " + key in cfg

    def test_rechaza_host_con_salto_de_linea(self):
        """Un host con \n inyectaria directivas (ProxyCommand) en ~/.ssh/config."""
        with self.assertRaises(ValueError):
            tools_setup.setup_ssh(
                email="x@y.z",
                confirmar=True,
                host="ok\nHost *\n  ProxyCommand touch /tmp/pwned",
            )
        assert not os.path.exists(os.path.join(self.home, ".ssh", "config"))

    def test_rechaza_user_con_espacios(self):
        with self.assertRaises(ValueError):
            tools_setup.setup_ssh(email="x@y.z", confirmar=True, user="root extra")
        assert not os.path.exists(os.path.join(self.home, ".ssh", "config"))


if __name__ == "__main__":
    unittest.main()