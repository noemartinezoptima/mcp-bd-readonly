"""Perfiles de tools: exponer solo las de un dominio para ahorrar contexto.

`tools/list` se envía al conectar y lo paga el cliente en CADA sesión. Medido
sobre el endpoint real, las 37 tools cuestan ~16.000 chars (~4.000 tokens), de
los cuales el 52% son `inputSchema`: recortar descripciones apenas mueve la
aguja. Limitar el número de tools es lo que de verdad reduce el consumo.

Elegir perfil NO es un control de seguridad: `run_query` sigue pudiendo tocar
cualquier tabla. Es únicamente optimización de contexto. Las tools que quedan
fuera no se registran, así que un `tools/call` sobre ellas responde "Unknown
tool": es el comportamiento esperado, no un fallo.

El perfil se fija con `MCP_TOOL_PROFILE` en el arranque y vale para todas las
conexiones de esa instancia. Vacío o `todas` => las 37, es decir el
comportamiento de siempre.
"""

# Siempre presentes: sin ellas no se puede trabajar en ningún dominio.
CORE = frozenset({
    "list_databases",
    "list_tables",
    "describe_table",
    "run_query",
    "resolve_domain_term",
})

CONTABILIDAD = frozenset({
    "facturas_venta", "resumen_iva", "remesas_pendientes", "cuadre_factura",
    "conciliar_remesas", "saldos_cliente", "excepciones", "informe_financiero",
    "facturas_compra", "resumen_gastos_por_tipo", "margen", "pnl",
    "dso_dpo_evolutivo", "aging_efectos",
    "balance",
})

OPERACIONES = frozenset({
    "stock_actual", "stock_por_ubicacion", "movimientos_stock",
    "describe_tablas_clave", "detalle_establecimiento",
})

EXCEL = frozenset({
    "leer_excel", "check_excel_capabilities", "resumen_excel",
    "reconciliar_excel_bd",
})

PERFILES = {
    "contabilidad": CORE | CONTABILIDAD,
    "operaciones": CORE | OPERACIONES,
    "excel": CORE | EXCEL,
}

# Tools de mantenimiento y meta que no pertenecen a ningún dominio de negocio:
# solo se registran con el perfil `todas`. Deben seguir aquí y en ningún otro
# sitio, o test_perfiles_cubren_todas_las_tools salta en cuanto se añada una.
SOLO_TODAS = frozenset({
    "estado_tunel",
    "auditoria",
    "schema_snapshot",
    "refresh_schema",
    "find_related_queries",
    "recordar_consulta",
    "consultar_memoria",
    "detectar_agente",
    "setup_ssh",
})

_TODAS = frozenset({"", "todas", "all", "*"})


def herramientas_activas(perfil: str | None) -> frozenset | None:
    """Nombre del perfil => conjunto de tools; `None` => todas.

    Un perfil desconocido lanza en el arranque: un `MCP_TOOL_PROFILE` mal
    escrito no debe pasar por alto y dejar al cliente con las 37 tools creyendo
    que las había limitado.
    """
    p = (perfil or "").strip().lower()
    if p in _TODAS:
        return None
    if p in PERFILES:
        return PERFILES[p]
    validos = ", ".join(sorted(PERFILES)) + ", todas"
    raise ValueError(
        f"MCP_TOOL_PROFILE={perfil!r} no existe. Perfiles válidos: {validos}."
    )
