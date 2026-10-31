import json
from datetime import datetime

import pytest

from mcp_bd_readonly.esquema_snapshot import build_snapshot, SchemaSnapshot, build_schema_tools


def _fake(rows):
    class FakeEx:
        queries = []

        def run(self, sql, params=None, limit=100):
            self.queries.append(sql)
            if "information_schema.COLUMNS" in sql:
                return (["TABLE_NAME", "COLUMN_NAME", "COLUMN_TYPE", "IS_NULLABLE", "COLUMN_KEY", "COLUMN_COMMENT"], rows["cols"])
            return (["TABLE_NAME", "ENGINE", "TABLE_ROWS", "TABLE_COMMENT"], rows["tables"])

    return FakeEx()


SAMPLE = {
    "tables": [
        {"TABLE_NAME": "facturas_venta", "ENGINE": "InnoDB", "TABLE_ROWS": 143968, "TABLE_COMMENT": ""},
        {"TABLE_NAME": "ots", "ENGINE": "InnoDB", "TABLE_ROWS": 1090000, "TABLE_COMMENT": "órdenes de trabajo"},
    ],
    "cols": [
        {"TABLE_NAME": "facturas_venta", "COLUMN_NAME": "id", "COLUMN_TYPE": "bigint", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": ""},
        {"TABLE_NAME": "facturas_venta", "COLUMN_NAME": "total_euros", "COLUMN_TYPE": "decimal(15,2)", "IS_NULLABLE": "YES", "COLUMN_KEY": "", "COLUMN_COMMENT": ""},
        {"TABLE_NAME": "ots", "COLUMN_NAME": "id", "COLUMN_TYPE": "bigint", "IS_NULLABLE": "NO", "COLUMN_KEY": "PRI", "COLUMN_COMMENT": ""},
    ],
}


def test_build_snapshot_estructura():
    snap = build_snapshot(_fake(SAMPLE))
    assert "generated_at" in snap
    datetime.fromisoformat(snap["generated_at"])
    tb = snap["tables"]
    assert set(tb) == {"facturas_venta", "ots"}
    assert tb["facturas_venta"]["engine"] == "InnoDB"
    assert tb["facturas_venta"]["rows"] == 143968
    assert tb["ots"]["comment"] == "órdenes de trabajo"
    assert tb["facturas_venta"]["columns"]["total_euros"]["type"] == "decimal(15,2)"
    assert tb["facturas_venta"]["columns"]["id"]["key"] == "PRI"


def test_snapshot_roundtrip(tmp_path):
    sche = SchemaSnapshot(tmp_path)
    sche.save(build_snapshot(_fake(SAMPLE)))
    snap = sche.load()
    assert snap is not None
    assert "facturas_venta" in snap["tables"]


def test_schema_snapshot_tool_usa_cache(tmp_path):
    ex = _fake(SAMPLE)
    tools = {fn.__name__: fn for fn in build_schema_tools(ex, audit=None, data_dir=tmp_path)}
    out1 = tools["schema_snapshot"]()
    assert out1["fuente"] == "fresh"
    assert "facturas_venta" in out1["tables"]
    out2 = tools["schema_snapshot"]()
    assert out2["fuente"] == "cache"
    assert len(ex.queries) == 2  # no consulta BD de nuevo


def test_schema_snapshot_filtra_por_tabla(tmp_path):
    ex = _fake(SAMPLE)
    tools = {fn.__name__: fn for fn in build_schema_tools(ex, audit=None, data_dir=tmp_path)}
    out = tools["schema_snapshot"](tabla="ots")
    assert set(out["tables"]) == {"ots"}


def test_schema_snapshot_filtra_por_prefijo(tmp_path):
    ex = _fake(SAMPLE)
    tools = {fn.__name__: fn for fn in build_schema_tools(ex, audit=None, data_dir=tmp_path)}
    out = tools["schema_snapshot"](prefijo="factura")
    assert set(out["tables"]) == {"facturas_venta"}


def test_schema_snapshot_resumen_omite_columnas(tmp_path):
    ex = _fake(SAMPLE)
    tools = {fn.__name__: fn for fn in build_schema_tools(ex, audit=None, data_dir=tmp_path)}
    out = tools["schema_snapshot"](resumen=True)
    assert set(out["tables"]) == {"facturas_venta", "ots"}
    for info in out["tables"].values():
        assert "columns" not in info
    assert out["tables"]["ots"]["rows"] == 1090000


def test_refresh_schema_exige_confirm(tmp_path):
    ex = _fake(SAMPLE)
    tools = {fn.__name__: fn for fn in build_schema_tools(ex, audit=None, data_dir=tmp_path)}
    with pytest.raises(ValueError):
        tools["refresh_schema"]()
    out = tools["refresh_schema"](confirm=True)
    assert out["status"] == "refrescado"
    assert out["tables"] == 2