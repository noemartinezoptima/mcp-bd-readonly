import time

from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger

TABLAS_CLAVE = ["clientes", "facturas_venta", "efectos_pago", "remesas", "bancos", "modelos"]

CACHE_TTL = 3600

NOTAS = {
    "efectos_pago": (
        "Polimórfico: modelo_id=11 → FacturaCompra, modelo_id=12 → FacturaVenta, "
        "relacion_id apunta al id de esa tabla. NO tiene cliente_id directo "
        "(hay que pasar por relacion_id → facturas_venta.cliente_id). "
        "La fecha de pago es fecha_pagado (no fecha_pago)."
    ),
    "clientes": "Usar razon_social o nombre_comercial; no existe columna nombre_fiscal.",
}

_cache = {}


def describe_tablas_clave(ex: QueryExecutor, tablas=None) -> dict:
    tablas = tablas or TABLAS_CLAVE
    now = time.monotonic()
    out = {}
    for tabla in tablas:
        cached = _cache.get(tabla)
        if cached and now - cached[0] < CACHE_TTL:
            out[tabla] = cached[1]
            continue
        _, rows = ex.run(f"DESCRIBE `{tabla}`", limit=None)
        entry = {"columnas": rows, "nota": NOTAS.get(tabla, "")}
        _cache[tabla] = (now, entry)
        out[tabla] = entry
    return out


def build_catalogo_tools(executor: QueryExecutor, audit: AuditLogger):

    def tool_describe_tablas_clave(tablas: list[str] | None = None) -> dict:
        """Catálogo de columnas reales (DESCRIBE) de las tablas clave de finanzas, con notas sobre polimorfismo y trampas de nombres. Cache 1h. Llamar SIEMPRE antes de escribir SQL nuevo sobre estas tablas."""
        audit and audit.record("describe_tablas_clave", "mcp", "describe_tablas_clave")
        return describe_tablas_clave(executor, tablas)

    return [tool_describe_tablas_clave]
