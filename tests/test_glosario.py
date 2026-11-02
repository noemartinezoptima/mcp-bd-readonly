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


def test_que_efectos_no_dispara_efectos_pago():
    """Falso positivo real (probado en vivo, 1-nov-2026): 'efectos' suelto es
    efectos de pago, pero 'que efectos ha tenido' es consecuencias, no cobros."""
    out = normalizar_texto(
        "que efectos ha tenido la subida de precios en la facturacion de este trimestre"
    )
    assert not any(c["canonico"] == "efectos_pago" for c in out)
    assert any(c["canonico"] == "facturas_venta" for c in out)


def test_pyg_mapea_a_pnl():
    """Gap real detectado en vivo (1-nov-2026): 'PyG' es la abreviatura mas
    comun de perdidas y ganancias en jerga financiera española, pero no
    estaba en los sinonimos de pnl ('cuadro de PyG' no devolvia nada)."""
    out = normalizar_texto("necesito el cuadro de pyg del año para la reunión con el banco")
    assert any(c["canonico"] == "pnl" for c in out)


def test_gastado_mapea_a_facturas_compra():
    """Falso negativo real detectado en vivo (2-nov-2026): el participio
    'gastado' no matcheaba facturas_compra porque el matching por prefijo
    (word.startswith('gasto')) no cubre 'gastado' -- 'cuanto hemos gastado
    este mes' no devolvia NADA pese a ser una pregunta de gasto obvia."""
    for frase in ["cuánto hemos gastado este mes", "qué gastamos el mes pasado"]:
        out = normalizar_texto(frase)
        assert any(c["canonico"] == "facturas_compra" for c in out), frase


def test_bono_no_lo_tapa_efectos_pago():
    """Gap real detectado en vivo (1-nov-2026): 'bono' no tenia termino
    canonico (hay 8 tablas bonus_* reales en el esquema), asi que 'cobro el
    bono' recomendaba efectos_pago (cobro de cliente) en vez de bono (comision
    de empleado) -- dominio totalmente distinto."""
    out = normalizar_texto("el tecnico cobro el bono de ese trabajo este mes")
    assert any(c["canonico"] == "bono" for c in out)
    r = resolver("cuanto bono le toca a este tecnico este mes")
    assert r["recomendado"] == "bono"


def test_presupuesto_tiene_termino_canonico():
    """Gap real detectado en vivo (2-nov-2026): 'presupuesto' no mapeaba a nada
    pese a existir tablas reales (presupuestos, presupuestos_solicitados,
    presupuestos_lineas_facturacion)."""
    r = resolver("cuántos presupuestos solicitados siguen sin respuesta del cliente")
    assert r["recomendado"] == "presupuesto"


def test_activo_fijo_no_lo_tapa_balance():
    """Gap real detectado en vivo (2-nov-2026): 'activos fijos' matcheaba solo
    'activo' (sinonimo generico de balance/PGC), pero la tabla real
    (fixed_assets) es un submodulo especifico de inmovilizado, distinto del
    balance contable general."""
    r = resolver("qué activos fijos se han dado de baja este año y por qué motivo")
    assert r["recomendado"] == "activo_fijo"


def test_tarifa_tiene_termino_canonico():
    """Gap real detectado en vivo (2-nov-2026): 'tarifa' no mapeaba a nada
    pese a existir tabla real 'tarifas' (precio al cliente, distinta de
    tecnicos_tarifas que es el coste pagado al tecnico)."""
    r = resolver("quiero el histórico de precios de la tarifa de este cliente")
    assert r["recomendado"] == "tarifa"


def test_evaluacion_desempeno_no_se_queda_en_tecnico_generico():
    """Gap real detectado en vivo (2-nov-2026): 'evaluaciones de desempeño del
    tecnico' solo matcheaba 'tecnico' generico, pero la tabla real especifica
    es valoraciones_tecnico (distinta de 'evaluaciones', que es QC de
    establecimientos pese al nombre parecido)."""
    r = resolver("cual es el historico de evaluaciones de desempeño de este tecnico")
    assert r["recomendado"] == "evaluacion"


def test_contrato_tiene_termino_canonico():
    """Gap real detectado en vivo (2-nov-2026): 'contrato' no mapeaba a nada
    pese a existir tabla real 'contratos' (vigencia, cliente, establecimientos
    en JSON)."""
    r = resolver("quiero ver el contrato vigente de este cliente y cuando vence")
    assert r["recomendado"] == "contrato"


def test_ticket_tiene_termino_canonico():
    """Gap real detectado en vivo (2-nov-2026): 'tickets' no mapeaba a nada
    pese a existir tabla real 'tickets' (tickets internos de desarrollo/soporte,
    distintos de las incidencias de cliente/OT)."""
    r = resolver("cuántos tickets de soporte lleva abiertos este cliente sin resolver")
    assert r["recomendado"] == "ticket"


def test_centro_de_coste_no_lo_tapa_establecimiento():
    """Falso positivo real detectado en vivo (2-nov-2026): 'centro' solo es
    sinonimo de tienda/establecimiento, pero 'centro de coste' es un concepto
    contable totalmente distinto (tabla real centros_coste)."""
    r = resolver("dame el centro de coste al que se imputó esta factura de compra")
    assert r["recomendado"] == "centro_coste"
    # 'centro' sigue apareciendo como coincidencia secundaria (como 'activo'
    # con activo_fijo): no se pierde nada, solo deja de ser el recomendado.
    assert any(c["canonico"] == "establecimiento" for c in resolver(
        "dame el centro de coste al que se imputó esta factura de compra"
    )["coincidencias"])


def test_tipo_de_cambio_gana_sobre_facturas():
    """Gap real detectado en vivo, repetido en dos frases distintas
    (2-nov-2026): 'tipo de cambio' no mapeaba a nada especifico, se quedaba en
    facturas_venta/facturas_compra genericas sin avisar de que hay DOS
    generaciones de tablas de divisa conviviendo (monedas/conversion_monedas
    legacy vs currencies/exchange_rates nuevas)."""
    for frase in [
        "qué tipo de cambio aplicamos a los proveedores extranjeros este mes",
        "a qué tipo de cambio se convirtieron las facturas en dólares este mes",
    ]:
        r = resolver(frase)
        assert r["recomendado"] == "tipo_cambio", frase


def test_sprint_mapea_pero_iteracion_sola_no():
    """Gap real detectado en vivo (2-nov-2026): 'sprint' no mapeaba a nada
    pese a existir tabla real 'sprints' (vinculada via tickets.sprint_id).
    OJO: 'iteracion'/'iteraciones' NO se añaden como sinonimos de sprint a
    proposito -- la tabla real 'iteraciones' es sobre recurrencia de OTs
    preventivas desde un contrato, un dominio totalmente distinto pese al
    nombre parecido (iteration=sprint en ingles)."""
    r = resolver("a qué sprint pertenece esta tarea")
    assert r["recomendado"] == "sprint"
    out = normalizar_texto("cada cuanto se repite esta iteracion de OTs preventivas del contrato")
    assert not any(c["canonico"] == "sprint" for c in out)


def test_incidencia_tiene_termino_canonico():
    """Gap real detectado en vivo, repetido en dos frases distintas
    (2-nov-2026): 'incidencia'/'incidencias' no mapeaba a nada especifico,
    solo a 'tecnico'/'cliente' genericos. Tablas reales: incidencias
    (generica, polimorfica), clientes_incidencias, tecnicos_incidencias y
    work_order_price_reduction_logs (penalizacion economica)."""
    for frase in [
        "qué comentarios ha dejado el técnico al cerrar esta incidencia",
        "cuánto llevamos acumulado este año en incidencias con penalización económica al técnico",
    ]:
        r = resolver(frase)
        assert r["recomendado"] == "incidencia", frase


def test_kpi_gana_sobre_facturas_venta():
    """Gap real detectado en vivo (2-nov-2026): 'kpi' no mapeaba a nada
    especifico, se quedaba en facturas_venta por la palabra 'facturacion' en
    la misma frase. Tabla real: kpis_diarios (columnas _valor/_puntos por
    metrica)."""
    r = resolver("cuál es el kpi de facturación diaria de este equipo")
    assert r["recomendado"] == "kpi"


def test_periodo_fiscal_tiene_termino_canonico():
    """Gap real detectado en vivo (2-nov-2026): 'periodo fiscal' no mapeaba a
    NADA (coincidencias vacias) pese a existir tablas reales
    (accounting_fiscal_years, accounting_periods, accounting_period_locks)."""
    r = resolver("cuál es el periodo fiscal que está abierto ahora mismo en contabilidad")
    assert r["recomendado"] == "periodo_fiscal"


def test_asiento_contable_tiene_termino_canonico():
    """Gap real detectado en vivo (2-nov-2026): 'asiento contable' no mapeaba
    a NADA pese a existir tabla real accounting_entries."""
    r = resolver("quién firmó el último asiento contable de este mes")
    assert r["recomendado"] == "asiento_contable"


def test_tipo_impositivo_no_se_queda_en_stock_ni_resumen_iva():
    """Gap real detectado en vivo (2-nov-2026): 'tipo de iva' de un articulo
    recomendaba 'stock' (por 'articulo'), sin apuntar al modulo real de tipos
    impositivos (tax_rates/tax_categories), distinto de resumen_iva (IVA YA
    liquidado de facturas emitidas)."""
    r = resolver("qué tipo de iva aplica este artículo según la normativa")
    assert r["recomendado"] == "tipo_impositivo"


def test_proveedor_gana_sobre_facturas_venta():
    """Falso positivo real detectado en vivo (2-nov-2026): 'proveedor' es un
    sinonimo exclusivo de facturas_compra, pero la palabra generica
    'facturacion' (presente en ambos canonicos) hacia ganar a facturas_venta
    -- al reves del sentido de la pregunta (es sobre COMPRAS, no ventas)."""
    r = resolver("quién es el proveedor con mayor volumen de facturación este año")
    assert r["recomendado"] == "facturas_compra"


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