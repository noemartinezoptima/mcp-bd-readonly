import pytest

from mcp_bd_readonly.memoria import Memoria, build_memoria_tools


def test_recordar_y_consultar(tmp_path):
    tools = {fn.__name__: fn for fn in build_memoria_tools(audit=None, data_dir=tmp_path)}
    out = tools["recordar_consulta"](
        frase="cuantas facturas emitimos en agosto",
        query="SELECT COUNT(*) FROM facturas_venta",
        resumen="3.684 facturas · 3.501.609,43 €",
    )
    assert out["guardado"] is True
    hit = tools["consultar_memoria"]("facturas de agosto")
    assert any(e["frase"].startswith("cuantas facturas") for e in hit["resultados"])


def test_memoria_persiste(tmp_path):
    m = Memoria(tmp_path)
    m.guardar({"frase": "x", "query": "select 1", "resumen": "y", "usuaria": "zerocool"})
    m2 = Memoria(tmp_path)
    assert len(m2.consultar("x")) >= 1


def test_usuaria_por_defecto(tmp_path):
    tools = {fn.__name__: fn for fn in build_memoria_tools(audit=None, data_dir=tmp_path)}
    out = tools["recordar_consulta"]("frase", "select 1", "resumen")
    assert out["usuaria"] == "zerocool"


def test_consultar_sin_memoria(tmp_path):
    tools = {fn.__name__: fn for fn in build_memoria_tools(audit=None, data_dir=tmp_path)}
    out = tools["consultar_memoria"]("nada que ver")
    assert out["resultados"] == []