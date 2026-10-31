"""API keys para el MCP remoto.

Solo se guarda el SHA-256 del secreto: una copia de la base de claves no permite
usar las claves. El `keyid` va en claro únicamente para poder buscar sin recorrer
la tabla y para revocar sin ambigüedad.

Formato: mcp_<keyid>_<secreto>
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

TOKEN_PREFIX = "mcp_"
SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    key_hash      TEXT NOT NULL,
    scopes        TEXT NOT NULL DEFAULT 'read',
    created_at    REAL NOT NULL,
    last_used_at  REAL,
    expires_at    REAL,
    revoked_at    REAL
);
"""


@dataclass(frozen=True)
class KeyInfo:
    key_id: str
    name: str
    scopes: tuple[str, ...]

    def allows(self, scope: str) -> bool:
        return scope in self.scopes or "admin" in self.scopes


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class KeyStore:
    """Almacén SQLite de claves. Cada operación abre su propia conexión."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute(SCHEMA)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        return conn

    # ---------------------------------------------------------------- alta
    def create(self, name: str, scopes: tuple[str, ...] = ("read",), ttl_days: int = 90) -> dict:
        if not name.strip():
            raise ValueError("el nombre de la clave no puede estar vacío")
        key_id = secrets.token_hex(4)
        secret = secrets.token_hex(24)
        now = time.time()
        expires = now + ttl_days * 86400 if ttl_days and ttl_days > 0 else None
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO api_keys (id, name, key_hash, scopes, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (key_id, name.strip(), _hash(secret), ",".join(scopes), now, expires),
            )
        return {
            "id": key_id,
            "name": name.strip(),
            "key": f"{TOKEN_PREFIX}{key_id}_{secret}",
            "scopes": list(scopes),
            "expires_at": expires,
        }

    # ---------------------------------------------------------------- uso
    def verify(self, token: str, now: float | None = None) -> KeyInfo | None:
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        key_id, _, secret = token[len(TOKEN_PREFIX):].partition("_")
        if not key_id or not secret:
            return None
        now = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, key_hash, scopes, expires_at, revoked_at, last_used_at"
                " FROM api_keys WHERE id = ?",
                (key_id,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None
            if row["expires_at"] is not None and now >= row["expires_at"]:
                return None
            if not hmac.compare_digest(row["key_hash"], _hash(secret)):
                return None
            # No escribir en cada petición: basta con una marca cada minuto.
            if row["last_used_at"] is None or now - row["last_used_at"] > 60:
                conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, key_id))
            scopes = tuple(s for s in (row["scopes"] or "").split(",") if s)
        return KeyInfo(key_id=row["id"], name=row["name"], scopes=scopes)

    # ---------------------------------------------------------------- gestión
    def revoke(self, key_id: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (now, key_id),
            )
            return cur.rowcount > 0

    def list_keys(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, scopes, created_at, last_used_at, expires_at, revoked_at"
                " FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Gestiona las API keys de mcp-optima-bd.")
    ap.add_argument("--db", default="data/api_keys.db", help="ruta al SQLite de claves")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="crea una clave (se muestra una sola vez)")
    c.add_argument("--name", required=True)
    c.add_argument("--scopes", default="read")
    c.add_argument("--ttl-days", type=int, default=90)

    sub.add_parser("list", help="lista claves (sin secretos)")

    r = sub.add_parser("revoke", help="revoca una clave por id")
    r.add_argument("--id", required=True)

    args = ap.parse_args(argv)
    store = KeyStore(args.db)

    if args.cmd == "create":
        scopes = tuple(s.strip() for s in args.scopes.split(",") if s.strip())
        created = store.create(args.name, scopes=scopes, ttl_days=args.ttl_days)
        print(created["key"])
        print(f"id={created['id']} scopes={','.join(created['scopes'])}", flush=True)
        return 0
    if args.cmd == "list":
        for row in store.list_keys():
            state = "revocada" if row["revoked_at"] else "activa"
            print(f"{row['id']}  {row['name']:<24} {row['scopes']:<16} {state}")
        return 0
    if args.cmd == "revoke":
        print("revocada" if store.revoke(args.id) else "no encontrada o ya revocada")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
