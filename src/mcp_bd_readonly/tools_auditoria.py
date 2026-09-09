import csv
import io
from decimal import Decimal

from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.format_es import fmt_money
from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.tools_finanzas import facturas_venta


def _d(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def clasificar_materialidad(diff: Decimal, base: Decimal) -> str:
    if base <= 0:
        return "INFO"
    pct = abs(diff) / base
    if pct >= Decimal("0.05"):
        return "CRITICAL"
    if pct >= Decimal("0.01"):
        return "WARNING"
    return "INFO"


def conciliar_remesas(ex) -> dict:
    sql_emitido = "SELECT COALESCE(SUM(total_euros),0) v FROM efectos_pago WHERE deleted_at IS NULL"
    sql_acreditado = sql_emitido + " AND fecha_pagado IS NOT NULL"
    _, emit = ex.run(sql_emitido)
    _, acre = ex.run(sql_acreditado)
    emitido = _d(emit[0]["v"])
    acreditado = _d(acre[0]["v"])
    pendiente = emitido - acreditado
    return {"emitido": emitido, "acreditado": acreditado, "pendiente": pendiente,
            "pendiente_es": fmt_money(pendiente)}


def saldos_cliente(ex, cliente_id) -> dict:
    _, inv = ex.run(
        "SELECT COALESCE(SUM(total_euros),0) v FROM facturas_venta WHERE cliente_id=%s AND deleted_at IS NULL",
        [cliente_id],
    )
    _, cob = ex.run(
        "SELECT COALESCE(SUM(total_euros),0) v FROM vista_efectos_pago "
        "WHERE cliente_id=%s AND fecha_pagado IS NOT NULL AND deleted_at IS NULL",
        [cliente_id],
    )
    facturado = _d(inv[0]["v"])
    cobrado = _d(cob[0]["v"])
    pendiente = facturado - cobrado
    return {"cliente_id": cliente_id, "facturado": facturado, "cobrado": cobrado,
            "pendiente": pendiente, "pendiente_es": fmt_money(pendiente)}


def excepciones(ex, fecha_desde, fecha_hasta, umbral) -> dict:
    sql = ("SELECT codigo, fecha_factura, base_moneda, iva_euros, total_euros, estado_id "
           "FROM facturas_venta WHERE deleted_at IS NULL "
           "AND DATE(fecha_factura) BETWEEN %s AND %s")
    _, rows = ex.run(sql, [fecha_desde, fecha_hasta], limit=None)
    umbral_d = _d(umbral)
    out = []
    resumen = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for r in rows:
        total = _d(r["total_euros"]).quantize(Decimal("0.01"))
        if total < umbral_d:
            continue
        sev = clasificar_materialidad(total - umbral_d, umbral_d)
        resumen[sev] += 1
        out.append({
            "codigo": r["codigo"],
            "fecha": str(r["fecha_factura"]),
            "total": total,
            "total_es": fmt_money(total),
            "severidad": sev,
        })
    return {"excepciones": out, "resumen": resumen}


def informe_financiero(ex, fecha_desde, fecha_hasta) -> dict:
    res = facturas_venta(ex, fecha_desde, fecha_hasta)
    md = (f"# Informe financiero {fecha_desde} → {fecha_hasta}\n\n"
          f"Total periodo: **{res['total_periodo_es']}**\n\n"
          "| Código | Base | IVA | Total |\n|---|---|---|---|\n" +
          "\n".join(f"| {f['codigo']} | {fmt_money(f['base'])} | {fmt_money(f['iva'])} | {fmt_money(f['total'])} |"
                    for f in res["facturas"]))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["codigo", "base", "iva", "total"])
    for f in res["facturas"]:
        w.writerow([f["codigo"], f["base"], f["iva"], f["total"]])
    return {"markdown": md, "csv": buf.getvalue()}


def build_auditoria_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("conciliar_remesas", "Total emitido vs acreditado de remesas (pago = fecha_pagado)")
    def tool_conciliar():
        audit and audit.record("conciliar_remesas", "mcp", "conciliar_remesas")
        return conciliar_remesas(executor)

    @_tool("saldos_cliente", "Facturado vs cobrado y pendiente de un cliente")
    def tool_saldos(cliente_id: int):
        audit and audit.record("saldos_cliente", "mcp", "saldos_cliente")
        return saldos_cliente(executor, cliente_id)

    @_tool("excepciones", "Facturas sobre umbral clasificadas por materialidad")
    def tool_excepciones(fecha_desde: str, fecha_hasta: str, umbral: float):
        audit and audit.record("excepciones", "mcp", "excepciones")
        return excepciones(executor, fecha_desde, fecha_hasta, umbral)

    @_tool("informe_financiero", "Informe Markdown + CSV(;) de un periodo")
    def tool_informe(fecha_desde: str, fecha_hasta: str):
        audit and audit.record("informe_financiero", "mcp", "informe_financiero")
        return informe_financiero(executor, fecha_desde, fecha_hasta)

    return [tool_conciliar, tool_saldos, tool_excepciones, tool_informe]
