import json
from datetime import datetime, timezone
from pathlib import Path


_TABLES_SQL = (
    "SELECT TABLE_NAME, ENGINE, TABLE_ROWS, TABLE_COMMENT"
    " FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
)
_COLUMNS_SQL = (
    "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,"
    " COLUMN_KEY, COLUMN_COMMENT FROM information_schema.COLUMNS"
    " WHERE TABLE_SCHEMA = DATABASE() ORDER BY ORDINAL_POSITION"
)


def build_snapshot(ex) -> dict:
    _, tables = ex.run(_TABLES_SQL, limit=None)
    _, cols = ex.run(_COLUMNS_SQL, limit=None)
    out = {}
    for t in tables:
        name = str(t["TABLE_NAME"])
        out[name] = {
            "engine": str(t.get("ENGINE") or ""),
            "rows": int(t.get("TABLE_ROWS") or 0),
            "comment": str(t.get("TABLE_COMMENT") or ""),
            "columns": {},
        }
    for c in cols:
        name = str(c["TABLE_NAME"])
        if name not in out:
            continue
        out[name]["columns"][str(c["COLUMN_NAME"])] = {
            "type": str(c.get("COLUMN_TYPE") or ""),
            "nullable": str(c.get("IS_NULLABLE") or "YES") == "YES",
            "key": str(c.get("COLUMN_KEY") or ""),
            "comment": str(c.get("COLUMN_COMMENT") or ""),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": out,
    }


class SchemaSnapshot:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "schema_snapshot.json"

    def save(self, snapshot: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1))

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return None


def _filtrar_tablas(snap: dict, tabla: str | None, prefijo: str | None) -> dict:
    tablas = snap["tables"]
    if tabla:
        tablas = {k: v for k, v in tablas.items() if k == tabla}
    elif prefijo:
        tablas = {k: v for k, v in tablas.items() if k.startswith(prefijo)}
    return dict(snap, tables=tablas)


def _resumir_tablas(snap: dict) -> dict:
    tablas = {
        nombre: {k: v for k, v in info.items() if k != "columns"}
        for nombre, info in snap["tables"].items()
    }
    return dict(snap, tables=tablas)


def build_schema_tools(ex, audit, data_dir):
    store = SchemaSnapshot(data_dir)

    def _fresh():
        snap = build_snapshot(ex)
        store.save(snap)
        return dict(snap, fuente="fresh")

    def schema_snapshot(
        fuerza: bool = False, tabla: str | None = None, prefijo: str | None = None, resumen: bool = False
    ) -> dict:
        """Esquema de la BD (tablas+columnas+comentarios) en caché local; no consulta la BD salvo fuerza=True.
        El snapshot completo son ~500 KB: si solo necesitas una tabla usa `tabla` (nombre exacto) o
        `prefijo` (ej. 'factura'); si solo necesitas saber qué tablas hay (sin columnas) usa resumen=True.
        Sin argumentos devuelve todo, igual que antes."""
        audit and audit.record(
            "schema_snapshot", "mcp", f"fuerza={fuerza} tabla={tabla} prefijo={prefijo} resumen={resumen}"
        )
        cached = store.load()
        snap = dict(cached, fuente="cache") if (cached and not fuerza) else _fresh()
        if tabla or prefijo:
            snap = _filtrar_tablas(snap, tabla, prefijo)
        if resumen:
            snap = _resumir_tablas(snap)
        return snap

    def refresh_schema(confirm: bool = False) -> dict:
        """[ADMIN] Reconstruye el snapshot de esquema desde la BD. Requiere confirm=True."""
        audit and audit.record("refresh_schema", "mcp", f"confirm={confirm}")
        if not confirm:
            raise ValueError("refresh_schema: es [ADMIN]. Pasa confirm=True para reconstruir el snapshot de esquema.")
        out = _fresh()
        out["status"] = "refrescado"
        out["tables"] = len(out["tables"])
        return out

    return [schema_snapshot, refresh_schema]