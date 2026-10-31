from mcp_bd_readonly.glosario import normalizar_texto, resolver
from mcp_bd_readonly.tools_core import build_glosario_tools


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_facturamos_mapea_a_facturas_venta():
    out = normalizar_texto("Cuánto facturamos a Kiko")
    assert out
    assert out[0]["canonico"] == "facturas_venta"
    assert out[0]["info"]["tabla"] == "facturas_venta"
    assert out[0]["info"]["herramienta_mcp"] == "facturas_venta"
    assert any("base_euros" in t for t in out[0]["info"]["trampas"])


def test_tienda_local_retail_pdv_a_establecimiento():
    frases = [
        "quién es el responsable de la tienda valencia",
        "ventas del local de madrid",
        "punto de venta barcelona",
        "PDV norte",
        "centro de girona",
    ]
    for frase in frases:
        out = normalizar_texto(frase)
        assert any(c["canonico"] == "establecimiento" for c in out), frase


def test_cobros_remesas_a_efectos_pago():
    for frase in ["qué cobros tenemos pendientes", "remesas pendientes", "efectos sin cobrar"]:
        out = normalizar_texto(frase)
        assert any(c["canonico"] == "efectos_pago" for c in out), frase
    out = normalizar_texto("cuánto nos queda por cobrar")
    assert any(c["canonico"] == "efectos_pago" for c in out)


def test_iva_a_liquidar_a_resumen_iva():
    out = normalizar_texto("cuánto IVA nos falta por liquidar")
    assert any(c["canonico"] == "resumen_iva" for c in out)


def test_obra_ot_a_ots():
    out = normalizar_texto("facturación de las obras del trimestre")
    assert any(c["canonico"] == "ots" for c in out)
    out = normalizar_texto("OT 1234")
    assert any(c["canonico"] == "ots" for c in out)


def test_cliente_a_razon_social():
    out = normalizar_texto("cuánto facturamos al cliente kiko")
    assert any(c["canonico"] == "cliente" for c in out)


def test_resolver_recomienda_canonico_correcto():
    casos = {
        "cuánto facturamos a kiko": "facturas_venta",
        "quién es el responsable de la tienda valencia": "establecimiento",
        "cobros pendientes": "efectos_pago",
        "IVA a liquidar": "resumen_iva",
    }
    for frase, esperado in casos.items():
        r = resolver(frase)
        assert r["recomendado"] == esperado, frase
        assert r["normalizado"]


def test_resolver_coincidencias_traen_herramienta():
    r = resolver("remesas pendientes de ventas de la tienda")
    tools = {c["canonico"]: c["info"]["herramienta_mcp"] for c in r["coincidencias"]}
    assert tools["efectos_pago"] == "remesas_pendientes"
    assert tools["establecimiento"] == "detalle_establecimiento"
    assert tools["facturas_venta"] == "facturas_venta"
    assert r["coincidencias"][0]["canonico"] == "establecimiento"


def test_resolver_sin_coincidencias():
    r = resolver("hola que tal")
    assert r["recomendado"] is None
    assert r["coincidencias"] == []
    assert "sugerencias" not in r


def test_tool_registra_auditoria():
    audit = FakeAudit()
    tools = build_glosario_tools(audit)
    assert len(tools) == 1
    res = tools[0]("cobros pendientes")
    assert res["recomendado"] == "efectos_pago"
    assert audit.calls[0][0] == "resolve_domain_term"
    assert "cobros pendientes" in audit.calls[0][2]