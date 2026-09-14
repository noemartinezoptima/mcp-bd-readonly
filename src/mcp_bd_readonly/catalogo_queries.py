import unicodedata


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


QUERIES = [
    {"id": "B1", "nombre": "Cifras de un cliente", "tabla": "facturas_venta",
     "topicos": ["cliente", "factura", "facturas", "mes", "cifras", "normal retail"],
     "sql": "facturas_venta por cliente (fecha + SUM total)"
            " — NO existe base_euros: usar total_euros/iva_euros"},
    {"id": "B2", "nombre": "Cliente top del mes", "tabla": "facturas_venta",
     "topicos": ["top", "ranking", "quien", "facturacion"],
     "sql": "GROUP BY cliente_nombre ORDER BY SUM(total_euros) DESC LIMIT 10"},
    {"id": "B3", "nombre": "DSO real hoy", "tabla": "efectos_pago",
     "topicos": ["dso", "dias", "cobrar", "media", "pendiente", "acreedores"],
     "sql": "pendiente = efectos_pago.fecha_pagado IS NULL (no remesas.total_efectos)"},
    {"id": "B4", "nombre": "Cobrado por rango", "tabla": "efectos_pago",
     "topicos": ["cobrado", "rango", "periodo", "pagado", "ano", "monto"],
     "sql": "efectos_pago.fecha_pagado rango + SUM total_euros (no cobros_remesas)"},
    {"id": "B5", "nombre": "Aging vencidos", "tabla": "efectos_pago",
     "topicos": ["aging", "vencido", "90", "mora", "por cobrar", "atraso"],
     "sql": "efectos_pago.fecha_vencimiento < CURDATE()-90; por-cliente exige JOIN"},
    {"id": "B6", "nombre": "IVA liquidable", "tabla": "facturas_venta",
     "topicos": ["iva", "liquidar", "periodo", "trimestre"],
     "sql": "SUM(iva_euros) rango periodo"},
    {"id": "B7", "nombre": "Comparativa mes a mes", "tabla": "facturas_venta",
     "topicos": ["comparativa", "mes a mes", "evolucion", "historial", "tendencia"],
     "sql": "GROUP BY YEAR-MONTH(fecha_factura) ORDER BY"},
    {"id": "B8", "nombre": "Presupuesto vs ots", "tabla": "presupuestos",
     "topicos": ["presupuesto", "ots", "cuadre", "estimado"],
     "sql": "presupuestos LEFT JOIN ots(presupuesto_id)"},
    {"id": "B9", "nombre": "Pendiente remesas", "tabla": "efectos_pago",
     "topicos": ["remesa", "remesas", "pendiente", "total a cobrar", "adeudo"],
     "sql": "conciliar_remesas (emitido - acreditado; total = efectos_pago)"},
    {"id": "B10", "nombre": "Detalle/responsable establecimiento", "tabla": "establecimientos",
     "topicos": ["establecimiento", "tienda", "responsable", "detalle", "cliente tienda"],
     "sql": "responsable_id->users.name, cliente=clientes.razon_social"},
]


def find_related(texto: str) -> dict:
    tokens = _norm(texto).split()
    scored = []
    for q in QUERIES:
        hit = sum(1 for t in tokens if t in _norm(" ".join(q["topicos"])))
        if hit:
            scored.append((hit, q))
    scored.sort(key=lambda x: -x[0])
    matches = [{"id": q["id"], "nombre": q["nombre"], "tabla": q["tabla"]} for _, q in scored[:4]]
    tablas = {q["tabla"] for _, q in scored}
    compartir = [
        {"id": q["id"], "nombre": q["nombre"], "tabla": q["tabla"]}
        for q in QUERIES
        if q["tabla"] in tablas and not any(m["id"] == q["id"] for m in matches)
    ]
    return {"consulta": texto[:100], "matches": matches, "comparten_tabla": compartir}


def build_queries_tools(audit):
    def find_related_queries(texto: str) -> dict:
        """Descubre queries del catálogo relacionadas con tu pregunta (matching) + otras que tocan la MISMA tabla (cross-links)."""
        audit and audit.record("find_related_queries", "mcp", texto)
        return find_related(texto)

    return [find_related_queries]