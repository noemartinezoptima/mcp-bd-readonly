from decimal import Decimal
from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.format_es import exact_sum, fmt_money
from mcp_bd_readonly.audit import AuditLogger


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def facturas_venta(ex, fecha_desde, fecha_hasta, cliente=None, max_n: int = 200):
    where = "deleted_at IS NULL AND DATE(fecha_factura) BETWEEN %s AND %s"
    params = [fecha_desde, fecha_hasta]
    if cliente:
        where += " AND cliente_id = %s"
        params.append(cliente)
    sql_total = ("SELECT COALESCE(SUM(total_euros),0) t, COUNT(*) n "
                 "FROM facturas_venta WHERE " + where)
    _, tot = ex.run(sql_total, params, limit=1)
    total = _dec(tot[0]["t"]).quantize(Decimal("0.01"))
    n_total = tot[0]["n"]
    sql = ("SELECT codigo, fecha_factura, base_moneda, iva_euros, total_euros, estado_id "
           "FROM facturas_venta WHERE " + where + " ORDER BY fecha_factura ASC LIMIT %s")
    _, rows = ex.run(sql, params + [int(max_n)], limit=None)
    out = []
    for r in rows:
        out.append({
            "codigo": r["codigo"],
            "fecha": str(r["fecha_factura"]),
            "base": _dec(r["base_moneda"]).quantize(Decimal("0.01")),
            "iva": _dec(r["iva_euros"]).quantize(Decimal("0.01")),
            "total": _dec(r["total_euros"]).quantize(Decimal("0.01")),
            "estado_id": r["estado_id"],
        })
    return {"facturas": out, "total_periodo": total, "total_periodo_es": fmt_money(total),
            "n_total": n_total, "limit_aplicado": int(max_n)}


def resumen_iva(ex, trimestre: int, anio: int):
    m0 = (anio, trimestre*3-2)
    m1 = (anio, trimestre*3)
    from datetime import date as _d, timedelta as _td
    base_end = (_d(anio, m1[1], 1) + _td(days=32)).replace(day=1)
    sql = ("SELECT base_moneda, iva_euros, total_euros FROM facturas_venta "
           "WHERE deleted_at IS NULL AND fecha_factura >= %s AND fecha_factura < %s")
    _, rows = ex.run(sql, [f"{anio}-{m0[1]:02d}-01 00:00:00", base_end.strftime("%Y-%m-%d 00:00:00")], limit=None)
    base = exact_sum(_dec(r["base_moneda"]) for r in rows)
    iva = exact_sum(_dec(r["iva_euros"]) for r in rows)
    total = exact_sum(_dec(r["total_euros"]) for r in rows)
    return {"base": base, "iva": iva, "total": total,
            "base_es": fmt_money(base), "iva_es": fmt_money(iva), "total_es": fmt_money(total)}


def remesas_pendientes(ex, max_n: int = 50) -> dict:
    sql_count = ("SELECT COUNT(*) n FROM efectos_pago "
                 "WHERE deleted_at IS NULL AND regularizado = 0")
    _, cnt = ex.run(sql_count)
    sql = ("SELECT codigo, fecha_emision, fecha_vencimiento, total_euros, estado_id, regularizado "
           "FROM efectos_pago WHERE deleted_at IS NULL AND regularizado = 0 "
           "ORDER BY fecha_vencimiento ASC LIMIT %s")
    _, rows = ex.run(sql, [int(max_n)], limit=None)
    out = []
    for r in rows:
        out.append({
            "codigo": r["codigo"],
            "fecha_vencimiento": str(r["fecha_vencimiento"]) if r["fecha_vencimiento"] is not None else None,
            "total_euros": _dec(r["total_euros"]).quantize(Decimal("0.01")),
            "estado_id": r["estado_id"],
            "regularizado": r["regularizado"],
        })
    return {"pendientes": out, "total": _dec(cnt[0]["n"]), "limit_aplicado": int(max_n)}


def cuadre_factura(ex, factura_id: int) -> dict:
    _, header = ex.run("SELECT total_euros FROM facturas_venta WHERE id=%s", [factura_id])
    _, lineas = ex.run("SELECT total_euros FROM facturas_venta_lineas WHERE factura_venta_id=%s", [factura_id])
    if not header:
        return {"ok": False, "exists": False, "header_total": Decimal("0"),
                "lineas_sum": Decimal("0.00"), "diff": Decimal("0.00")}
    header_total = _dec(header[0]["total_euros"])
    lineas_sum = exact_sum(_dec(r["total_euros"]) for r in lineas)
    return {"ok": lineas_sum == header_total, "exists": True, "header_total": header_total,
            "lineas_sum": lineas_sum, "diff": lineas_sum - header_total}


def build_finanzas_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("facturas_venta", "Facturas en un rango de fechas (max_n filas, default 200) + total_periodo exacto")
    def tool_facturas(fecha_desde: str, fecha_hasta: str, cliente: int | None = None, max_n: int = 200):
        audit and audit.record("facturas_venta", "mcp", "facturas_venta")
        return facturas_venta(executor, fecha_desde, fecha_hasta, cliente, max_n)

    @_tool("resumen_iva", "Base/IVA/Total de un trimestre (anio + trimestre 1-4)")
    def tool_resumen_iva(trimestre: int, anio: int):
        audit and audit.record("resumen_iva", "mcp", "resumen_iva")
        return resumen_iva(executor, trimestre, anio)

    @_tool("remesas_pendientes", "Efectos pendientes (últimos por vencimiento, max_n límite) y total")
    def tool_remesas_pendientes(max_n: int = 50):
        audit and audit.record("remesas_pendientes", "mcp", "remesas_pendientes")
        return remesas_pendientes(executor, max_n)

    @_tool("cuadre_factura", "Comprueba que la suma de líneas == total de cabecera")
    def tool_cuadre(factura_id: int):
        audit and audit.record("cuadre_factura", "mcp", "cuadre_factura")
        return cuadre_factura(executor, factura_id)

    return [tool_facturas, tool_resumen_iva, tool_remesas_pendientes, tool_cuadre]
