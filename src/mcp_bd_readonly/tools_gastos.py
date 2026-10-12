"""Tools de gastos / compras (facturas_compra, proveedores, tipos de gasto, margen).

Completan el "cerebro de finanzas" en el lado de GASTOS (antes solo había ventas).
Esquema real verificado contra la BD: facturas_compra tiene base_euros/iva_euros/
total_euros/total_coste_euros, coste_directo (1=COGS directo, 0=indirecto),
tipo_gasto_id -> tipos_de_gasto, proveedor_nombre (denormalizado) + proveedor_id.
"""

from decimal import Decimal

from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.format_es import fmt_money


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def facturas_compra(
    ex,
    fecha_desde,
    fecha_hasta,
    proveedor=None,
    tipo_gasto_id=None,
    solo_pendientes=False,
    max_n: int = 200,
):
    """Facturas de compra (gastos) en un rango de fechas + total del periodo."""
    where = "deleted_at IS NULL AND DATE(fecha_factura) BETWEEN %s AND %s"
    params = [fecha_desde, fecha_hasta]
    if proveedor:
        where += " AND (proveedor_nombre LIKE %s OR proveedor_id = %s)"
        params += [f"%{proveedor}%", proveedor]
    if tipo_gasto_id:
        where += " AND tipo_gasto_id = %s"
        params.append(tipo_gasto_id)
    if solo_pendientes:
        where += " AND pagada = 0"

    _, tot = ex.run(
        "SELECT COALESCE(SUM(total_euros),0) t, COUNT(*) n FROM facturas_compra WHERE " + where,
        params, limit=1,
    )
    total = _dec(tot[0]["t"]).quantize(Decimal("0.01"))
    n_total = tot[0]["n"]

    _, rows = ex.run(
        "SELECT codigo, fecha_factura, proveedor_nombre, base_euros, iva_euros, total_euros, pagada "
        "FROM facturas_compra WHERE " + where + " ORDER BY fecha_factura DESC LIMIT %s",
        params + [int(max_n)], limit=None,
    )
    out = [
        {
            "codigo": r["codigo"],
            "fecha": str(r["fecha_factura"]),
            "proveedor": r["proveedor_nombre"],
            "base": _dec(r["base_euros"]).quantize(Decimal("0.01")),
            "iva": _dec(r["iva_euros"]).quantize(Decimal("0.01")),
            "total": _dec(r["total_euros"]).quantize(Decimal("0.01")),
            "pagada": bool(r["pagada"]),
        }
        for r in rows
    ]
    return {
        "facturas": out,
        "total_periodo": total,
        "total_periodo_es": fmt_money(total),
        "n_total": n_total,
        "limit_aplicado": int(max_n),
    }


def resumen_gastos_por_tipo(ex, fecha_desde, fecha_hasta):
    """Gastos agregados por tipo_de_gasto en un rango de fechas."""
    _, rows = ex.run(
        "SELECT COALESCE(tg.nombre, '(sin tipo)') tipo, COUNT(*) n, "
        "COALESCE(SUM(fc.total_euros),0) total, COALESCE(SUM(fc.base_euros),0) base "
        "FROM facturas_compra fc LEFT JOIN tipos_de_gasto tg ON tg.id = fc.tipo_gasto_id "
        "WHERE fc.deleted_at IS NULL AND DATE(fc.fecha_factura) BETWEEN %s AND %s "
        "GROUP BY tg.id, tg.nombre ORDER BY total DESC",
        [fecha_desde, fecha_hasta], limit=None,
    )
    out = [
        {
            "tipo": r["tipo"],
            "n": r["n"],
            "total": _dec(r["total"]).quantize(Decimal("0.01")),
            "total_es": fmt_money(r["total"]),
            "base": _dec(r["base"]).quantize(Decimal("0.01")),
        }
        for r in rows
    ]
    return {"por_tipo": out}


def _ventas_netas(ex, fecha_desde, fecha_hasta) -> Decimal:
    _, ventas = ex.run(
        "SELECT COALESCE(SUM(total_euros),0) t, COALESCE(SUM(iva_euros),0) i "
        "FROM facturas_venta WHERE deleted_at IS NULL "
        "AND DATE(fecha_factura) BETWEEN %s AND %s",
        [fecha_desde, fecha_hasta], limit=1,
    )
    # neto de IVA (facturas_venta NO tiene base_euros; derivar total − iva)
    return _dec(ventas[0]["t"]) - _dec(ventas[0]["i"])


def _costes_por_tipo(ex, fecha_desde, fecha_hasta) -> tuple[Decimal, Decimal]:
    _, rows = ex.run(
        "SELECT coste_directo, COALESCE(SUM(total_coste_euros),0) c "
        "FROM facturas_compra WHERE deleted_at IS NULL "
        "AND DATE(fecha_factura) BETWEEN %s AND %s GROUP BY coste_directo",
        [fecha_desde, fecha_hasta], limit=None,
    )
    directos = Decimal("0")
    indirectos = Decimal("0")
    for r in rows:
        if r["coste_directo"] == 1:
            directos = _dec(r["c"])
        else:
            indirectos = _dec(r["c"])
    return directos, indirectos


def margen(ex, fecha_desde, fecha_hasta):
    """Margen bruto = ventas netas (ex-IVA) − costes directos (coste_directo=1)."""
    v = _ventas_netas(ex, fecha_desde, fecha_hasta)
    c, _ = _costes_por_tipo(ex, fecha_desde, fecha_hasta)
    m = v - c
    pct = (m / v * 100).quantize(Decimal("0.1")) if v else None
    return {
        "ventas_netas": v,
        "ventas_netas_es": fmt_money(v),
        "costes_directos": c,
        "costes_directos_es": fmt_money(c),
        "margen": m,
        "margen_es": fmt_money(m),
        "margen_pct": float(pct) if pct is not None else None,
    }


def pnl(ex, fecha_desde, fecha_hasta):
    """Cuenta de resultados (P&L) simplificada:
    ingresos netos → costes directos → margen bruto → costes indirectos → resultado."""
    ingresos = _ventas_netas(ex, fecha_desde, fecha_hasta)
    directos, indirectos = _costes_por_tipo(ex, fecha_desde, fecha_hasta)
    margen_bruto = ingresos - directos
    resultado = margen_bruto - indirectos
    mb_pct = (margen_bruto / ingresos * 100).quantize(Decimal("0.1")) if ingresos else None
    res_pct = (resultado / ingresos * 100).quantize(Decimal("0.1")) if ingresos else None
    return {
        "ingresos": ingresos,
        "ingresos_es": fmt_money(ingresos),
        "costes_directos": directos,
        "costes_directos_es": fmt_money(directos),
        "margen_bruto": margen_bruto,
        "margen_bruto_es": fmt_money(margen_bruto),
        "margen_bruto_pct": float(mb_pct) if mb_pct is not None else None,
        "costes_indirectos": indirectos,
        "costes_indirectos_es": fmt_money(indirectos),
        "resultado": resultado,
        "resultado_es": fmt_money(resultado),
        "resultado_pct": float(res_pct) if res_pct is not None else None,
    }


def build_gastos_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("facturas_compra", "Facturas de compra (gastos) en un rango de fechas + total del periodo. Filtros opcionales: proveedor (nombre/id), tipo_gasto_id, solo_pendientes (pagada=0).")
    def tool_facturas_compra(fecha_desde: str, fecha_hasta: str, proveedor: str | None = None, tipo_gasto_id: int | None = None, solo_pendientes: bool = False, max_n: int = 200):
        audit and audit.record("facturas_compra", "mcp", "facturas_compra")
        return facturas_compra(executor, fecha_desde, fecha_hasta, proveedor, tipo_gasto_id, solo_pendientes, max_n)

    @_tool("resumen_gastos_por_tipo", "Gastos agregados por tipo_de_gasto en un rango de fechas (desglose por categoría).")
    def tool_resumen_gastos(fecha_desde: str, fecha_hasta: str):
        audit and audit.record("resumen_gastos_por_tipo", "mcp", "resumen_gastos_por_tipo")
        return resumen_gastos_por_tipo(executor, fecha_desde, fecha_hasta)

    @_tool("margen", "Margen bruto = ventas netas (ex-IVA) − costes directos (facturas_compra coste_directo=1) en un rango. Incluye % de margen.")
    def tool_margen(fecha_desde: str, fecha_hasta: str):
        audit and audit.record("margen", "mcp", "margen")
        return margen(executor, fecha_desde, fecha_hasta)

    @_tool("pnl", "Cuenta de resultados (P&L): ingresos netos → costes directos → margen bruto → costes indirectos → resultado, con porcentajes.")
    def tool_pnl(fecha_desde: str, fecha_hasta: str):
        audit and audit.record("pnl", "mcp", "pnl")
        return pnl(executor, fecha_desde, fecha_hasta)

    return [tool_facturas_compra, tool_resumen_gastos, tool_margen, tool_pnl]
