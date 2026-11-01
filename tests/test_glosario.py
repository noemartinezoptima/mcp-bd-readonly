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


def test_mano_de_obra_no_dispara_ots():
    """Falso positivo real (probado en vivo, 1-nov-2026): 'obra' sola es OT,
    pero dentro de 'mano de obra' es coste de personal, no una OT."""
    out = normalizar_texto("cuánto hemos pagado este mes en mano de obra de los subcontratados")
    assert not any(c["canonico"] == "ots" for c in out)
    # El resto de la frase sigue intacto: no se pierde nada más.
    assert any(c["canonico"] == "efectos_pago" for c in out)
    assert any(c["canonico"] == "facturas_compra" for c in out)


def test_cliente_a_razon_social():
    out = normalizar_texto("cuánto facturamos al cliente kiko")
    assert any(c["canonico"] == "cliente" for c in out)


def test_tecnico_instalador_a_tecnico():
    for frase in [
        "qué técnico está asignado a esta obra",
        "quién es el instalador de la tienda",
        "qué operario hizo la reparación",
    ]:
        out = normalizar_texto(frase)
        assert any(c["canonico"] == "tecnico" for c in out), frase


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


def test_efectos_pago_lista_otras_tools_no_solo_remesas_pendientes():
    """resolve_domain_term solo recomendaba remesas_pendientes para TODO lo que
    toca efectos_pago, aunque la tabla la usan 4 tools distintas (aging,
    conciliación, DSO/DPO evolutivo). otras_tools cubre el resto."""
    out = normalizar_texto("cobros pendientes")
    info = next(c["info"] for c in out if c["canonico"] == "efectos_pago")
    assert info["herramienta_mcp"] == "remesas_pendientes"
    assert set(info["otras_tools"]) == {"conciliar_remesas", "aging_efectos", "dso_dpo_evolutivo"}


def test_tool_registra_auditoria():
    audit = FakeAudit()
    tools = build_glosario_tools(audit)
    assert len(tools) == 1
    res = tools[0]("cobros pendientes")
    assert res["recomendado"] == "efectos_pago"
    assert audit.calls[0][0] == "resolve_domain_term"
    assert "cobros pendientes" in audit.calls[0][2]