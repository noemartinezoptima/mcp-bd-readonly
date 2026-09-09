from decimal import Decimal
from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.format_es import exact_sum, fmt_money
from mcp_bd_readonly.audit import AuditLogger


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def facturas_venta(ex, fecha_desde, fecha_hasta, cliente=None):
    sql = ("SELECT codigo, fecha_factura, base_euros, iva_euros, total_euros, estado_id "
           "FROM facturas_venta WHERE deleted_at IS NULL "
           "AND DATE(fecha_factura) BETWEEN %s AND %s")
    params = [fecha_desde, fecha_hasta]
    if cliente:
        sql += " AND cliente_id = %s"
        params.append(cliente)
    _, rows = ex.run(sql, params)
    out = []
    for r in rows:
        out.append({
            "codigo": r["codigo"],
            "fecha": str(r["fecha_factura"]),
            "base": _dec(r["base_euros"]).quantize(Decimal("0.01")),
            "iva": _dec(r["iva_euros"]).quantize(Decimal("0.01")),
            "total": _dec(r["total_euros"]).quantize(Decimal("0.01")),
            "estado_id": r["estado_id"],
        })
    total = exact_sum(o["total"] for o in out)
    return {"facturas": out, "total_periodo": total, "total_periodo_es": fmt_money(total)}


def resumen_iva(ex, trimestre: int, anio: int):
    m0 = (anio, trimestre*3-2)
    m1 = (anio, trimestre*3)
    from datetime import date as _d, timedelta as _td
    base_end = (_d(anio, m1[1], 1) + _td(days=32)).replace(day=1)
    sql = ("SELECT base_euros, iva_euros, total_euros FROM facturas_venta "
           "WHERE deleted_at IS NULL AND fecha_factura >= %s AND fecha_factura < %s")
    _, rows = ex.run(sql, [f"{anio}-{m0[1]:02d}-01 00:00:00", base_end.strftime("%Y-%m-%d 00:00:00")])
    base = exact_sum(_dec(r["base_euros"]) for r in rows)
    iva = exact_sum(_dec(r["iva_euros"]) for r in rows)
    total = exact_sum(_dec(r["total_euros"]) for r in rows)
    return {"base": base, "iva": iva, "total": total,
            "base_es": fmt_money(base), "iva_es": fmt_money(iva), "total_es": fmt_money(total)}


def remesas_pendientes(ex) -> list:
    sql = ("SELECT codigo, fecha_emision, fecha_vencimiento, total_euros, estado_id, regularizado "
           "FROM efectos_pago WHERE deleted_at IS NULL AND regularizado = 0 "
           "ORDER BY fecha_vencimiento ASC")
    _, rows = ex.run(sql)
    out = []
    for r in rows:
        out.append({
            "codigo": r["codigo"],
            "fecha_vencimiento": str(r["fecha_vencimiento"]),
            "total_euros": _dec(r["total_euros"]).quantize(Decimal("0.01")),
            "estado_id": r["estado_id"],
            "regularizado": r["regularizado"],
        })
    return out


def cuadre_factura(ex, factura_id: int) -> dict:
    _, header = ex.run("SELECT total_euros FROM facturas_venta WHERE id=%s", [factura_id])
    _, lineas = ex.run("SELECT total_euros FROM facturas_venta_lineas WHERE factura_venta_id=%s", [factura_id])
    header_total = _dec(header[0]["total_euros"]) if header else Decimal("0")
    lineas_sum = exact_sum(_dec(r["total_euros"]) for r in lineas)
    return {"ok": lineas_sum == header_total, "header_total": header_total,
            "lineas_sum": lineas_sum, "diff": lineas_sum - header_total}


def build_finanzas_tools(executor: QueryExecutor, audit: AuditLogger):

    def _wrapped(name, fn):
        def wrapper(*args, **kwargs):
            audit and audit.record(name, "mcp", getattr(fn, "_sql_hint", name))
            return fn(executor, *args, **kwargs)
        wrapper.__name__ = name
        return wrapper

    return [
        _wrapped("facturas_venta", facturas_venta),
        _wrapped("resumen_iva", resumen_iva),
        _wrapped("remesas_pendientes", remesas_pendientes),
        _wrapped("cuadre_factura", cuadre_factura),
    ]
