import pytest

from mcp_bd_readonly.catalogo_queries import find_related


def _tool(texto):
    return find_related(texto)


def test_facturas_mes_matchea_facturacion():
    out = _tool("facturas de este mes")
    ids = [m["id"] for m in out["matches"]]
    assert "B1" in ids


def test_top_facturacion_matchea_ranking():
    ids = [m["id"] for m in _tool("quien nos da mas facturacion")["matches"]]
    assert "B2" in ids


def test_cobros_matchea_efectos_pago():
    out = _tool("cuanto hemos cobrado este año")
    ids = [m["id"] for m in out["matches"]]
    assert "B4" in ids


def test_remesas_matchea_pendiente():
    ids = [m["id"] for m in _tool("cuanto nos deben en remesas")["matches"]]
    assert "B9" in ids


def test_dso_matchea_pendiente():
    ids = [m["id"] for m in _tool("dias de media para cobrar")["matches"]]
    assert "B3" in ids


def test_array_ocr_no_rompe():
    out = _tool("X; DROP TABLE")
    assert isinstance(out["matches"], list)


def test_cross_links_comparten_tabla():
    out = _tool("facturas de este mes")
    compart = [m["id"] for m in out["comparten_tabla"]]
    assert "B2" in compart  # abeja en otra query de la misma tabla facturas_venta