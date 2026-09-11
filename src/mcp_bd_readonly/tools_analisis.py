from decimal import Decimal

from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.format_es import fmt_money, fmt_mes, fmt_dias


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


_JOIN_EFECTOS_FACTURAS = (
    "FROM efectos_pago ep "
    "JOIN facturas_venta fv ON fv.id = ep.relacion_id AND ep.modelo_id = 12 "
    "WHERE ep.deleted_at IS NULL AND fv.deleted_at IS NULL"
)


def dso_dpo_evolutivo(ex: QueryExecutor, anio_desde: int = 2025, anio_hasta: int = 2026) -> dict:
    sql_dpo = (
        "SELECT DATE_FORMAT(ep.fecha_pagado, '%%Y-%%m') mes, "
        "AVG(DATEDIFF(ep.fecha_pagado, ep.fecha_vencimiento)) dias, COUNT(*) n "
        + _JOIN_EFECTOS_FACTURAS
        + " AND ep.fecha_pagado IS NOT NULL AND YEAR(ep.fecha_pagado) BETWEEN %s AND %s "
        "GROUP BY mes ORDER BY mes"
    )
    _, dpo_rows = ex.run(sql_dpo, [anio_desde, anio_hasta], limit=None)
    dpo = [{"mes": r["mes"], "mes_es": fmt_mes(r["mes"]), "dpo_dias": round(float(r["dias"]), 1),
            "dpo_dias_es": fmt_dias(r["dias"]), "n": r["n"]} for r in dpo_rows]

    sql_dso = (
        "SELECT DATE_FORMAT(fv.fecha_factura, '%%Y-%%m') mes, "
        "AVG(DATEDIFF(ep.fecha_pagado, fv.fecha_factura)) dias, COUNT(*) n "
        + _JOIN_EFECTOS_FACTURAS
        + " AND ep.fecha_pagado IS NOT NULL AND YEAR(fv.fecha_factura) BETWEEN %s AND %s "
        "GROUP BY mes ORDER BY mes"
    )
    _, dso_rows = ex.run(sql_dso, [anio_desde, anio_hasta], limit=None)
    dso = [{"mes": r["mes"], "mes_es": fmt_mes(r["mes"]), "dso_dias": round(float(r["dias"]), 1),
            "dso_dias_es": fmt_dias(r["dias"]), "n": r["n"]} for r in dso_rows]

    n_total = sum(d["n"] for d in dpo)
    dpo_medio = round(sum(d["dpo_dias"] * d["n"] for d in dpo) / n_total, 1) if n_total else None

    return {"dpo_mensual": dpo, "dso_mensual": dso, "dpo_medio": dpo_medio,
            "dpo_medio_es": fmt_dias(dpo_medio) if dpo_medio is not None else None}


def aging_efectos(ex: QueryExecutor) -> dict:
    sql = (
        "SELECT ep.banco_id, fv.cliente_id, "
        "CASE "
        "WHEN DATEDIFF(CURDATE(), ep.fecha_vencimiento) <= 30 THEN '0-30' "
        "WHEN DATEDIFF(CURDATE(), ep.fecha_vencimiento) <= 60 THEN '30-60' "
        "WHEN DATEDIFF(CURDATE(), ep.fecha_vencimiento) <= 90 THEN '60-90' "
        "ELSE '+90' END bucket, "
        "COUNT(*) n, COALESCE(SUM(ep.total_euros),0) importe "
        + _JOIN_EFECTOS_FACTURAS
        + " AND ep.fecha_pagado IS NULL "
        "GROUP BY ep.banco_id, fv.cliente_id, bucket"
    )
    _, rows = ex.run(sql, limit=None)
    out = []
    for r in rows:
        importe = _dec(r["importe"]).quantize(Decimal("0.01"))
        out.append({
            "banco_id": r["banco_id"],
            "cliente_id": r["cliente_id"],
            "bucket": r["bucket"],
            "n": r["n"],
            "importe": importe,
            "importe_es": fmt_money(importe),
        })
    return {"aging": out}


def build_analisis_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("dso_dpo_evolutivo", "Serie mensual de DPO (retraso de pago vs vencimiento) y DSO (días desde factura hasta cobro), rango de años inclusive")
    def tool_dso_dpo(anio_desde: int = 2025, anio_hasta: int = 2026):
        audit and audit.record("dso_dpo_evolutivo", "mcp", "dso_dpo_evolutivo")
        return dso_dpo_evolutivo(executor, anio_desde, anio_hasta)

    @_tool("aging_efectos", "Efectos de pago pendientes agrupados por antigüedad (0-30/30-60/60-90/+90 días), banco y cliente")
    def tool_aging():
        audit and audit.record("aging_efectos", "mcp", "aging_efectos")
        return aging_efectos(executor)

    return [tool_dso_dpo, tool_aging]
