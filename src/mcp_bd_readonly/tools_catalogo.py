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


def _filter_establecimiento(ex: QueryExecutor, termino: str, max_n: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
    p = f"%{termino}%"
    where = (
        "FROM establecimientos e "
        "WHERE e.deleted_at IS NULL "
        "AND (e.nombre LIKE %s OR e.codigo LIKE %s OR e.correo LIKE %s OR e.telefono LIKE %s)"
    )
    _, cnt = ex.run(f"SELECT COUNT(*) AS n {where}", [p, p, p, p], limit=None)
    n_total = int(cnt[0]["n"]) if cnt else 0
    sql = (
        "SELECT e.id, e.nombre, e.codigo, e.telefono, e.correo, e.direccion_1, "
        "e.provincia, e.poblacion, e.codigo_postal, e.observaciones, "
        "u.name AS responsable, c.razon_social AS cliente "
        "FROM establecimientos e "
        "LEFT JOIN users u ON u.id = e.responsable_id "
        "LEFT JOIN clientes c ON c.id = e.cliente_facturacion_id "
        "WHERE e.deleted_at IS NULL "
        "AND (e.nombre LIKE %s OR e.codigo LIKE %s OR e.correo LIKE %s OR e.telefono LIKE %s) "
        "ORDER BY e.nombre LIMIT %s OFFSET %s"
    )
    _, rows = ex.run(sql, [p, p, p, p, int(max_n), int(offset)], limit=None)
    return n_total, rows


def detalle_establecimiento(ex: QueryExecutor, termino: str, max_n: int = 50, offset: int = 0) -> dict:
    n_total, rows = _filter_establecimiento(ex, termino, max_n, offset)
    establecimientos = []
    for r in rows:
        establecimientos.append({
            "id": r["id"],
            "nombre": r["nombre"],
            "codigo": r["codigo"],
            "direccion": ", ".join(x for x in (r["direccion_1"], r["poblacion"], r["provincia"]) if x),
            "codigo_postal": r["codigo_postal"],
            "telefono": r["telefono"],
            "correo": r["correo"],
            "observaciones": r["observaciones"],
            "responsable": r["responsable"],
            "cliente": r["cliente"],
        })
    return {"termino": termino, "n_encontrados": n_total, "devueltos": len(establecimientos),
            "offset": int(offset), "max_n": int(max_n), "establecimientos": establecimientos}


def build_catalogo_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("describe_tablas_clave", "Catálogo de columnas reales (DESCRIBE) de las tablas clave de finanzas, con notas sobre polimorfismo y trampas de nombres. Cache 1h. Llamar SIEMPRE antes de escribir SQL nuevo sobre estas tablas.")
    def tool_describe_tablas_clave(tablas: list[str] | None = None) -> dict:
        audit and audit.record("describe_tablas_clave", "mcp", "describe_tablas_clave")
        return describe_tablas_clave(executor, tablas)

    @_tool("detalle_establecimiento", "Detalle y responsable de establecimientos que coinciden con un texto (nombre, codigo, correo o telefono). Usa users.name como responsable y clientes.razon_social como cliente. Paginable: max_n (filas, default 50) + offset (desplazamiento, default 0); n_encontrados = TOTAL de coincidencias, no la página. Cuando n_encontrados > max_n, ofrece al usuario paginar con offset y/o exportar los resultados (reconciliar_excel_bd/leer_excel pueden volcar a Excel). NUNCA escribe: solo SELECT.")
    def tool_detalle_establecimiento(termino: str, max_n: int = 50, offset: int = 0) -> dict:
        audit and audit.record("detalle_establecimiento", "mcp", f"detalle_establecimiento({termino}, max_n={max_n}, offset={offset})")
        return detalle_establecimiento(executor, termino, max_n, offset)

    return [tool_describe_tablas_clave, tool_detalle_establecimiento]
