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
        r = tools_setup.setup_ssh(email="test@dev.local")
        assert r["ok"] is True
        assert r["clave_generada"] is True
        assert r["email"] == "test@dev.local"
        assert r["host"] == "db-host"
        assert r["clave_publica"].startswith("ssh-ed25519")
        cfg = open(os.path.join(self.home, ".ssh", "config"), encoding="utf-8").read()
        assert "Host db-host" in cfg
        assert "db-host.example.com" in cfg

    def test_idempotent_no_regenerate(self):
        tools_setup.setup_ssh(email="a@b.c")
        r2 = tools_setup.setup_ssh(email="d@e.f")
        assert r2["clave_generada"] is False

    def test_errors_without_email(self):
        with self.assertRaises(ValueError):
            tools_setup.setup_ssh(email=None)


if __name__ == "__main__":
    unittest.main()