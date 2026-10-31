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
comportamiento de siempre. Un valor desconocido no tumba el servicio: cae a
`todas` y deja constancia del error (ver `aviso_perfil`).
"""

import logging

log = logging.getLogger(__name__)

# Siempre presentes: sin ellas no se puede trabajar en ningún dominio.
# `consultar_memoria` es una de ellas: lo aprendido al corregir una frase vale
# igual en contabilidad que en operaciones, y con ella en SOLO_TODAS un perfil
# de dominio dejaba el entrenamiento inaccesible ("Unknown tool").
CORE = frozenset({
    "list_databases",
    "list_tables",
    "describe_table",
    "run_query",
    "resolve_domain_term",
    "consultar_memoria",
    "run_script",
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
    "detectar_agente",
    "setup_ssh",
})

_TODAS = frozenset({"", "todas", "all", "*"})


def aviso_perfil(perfil: str | None) -> str:
    """Aviso si `MCP_TOOL_PROFILE` no existe; cadena vacía si es válido.

    Antes un valor desconocido lanzaba y el servicio entraba en crash-loop
    (`Restart=on-failure`, `RestartSec=3`): una errata en una env var dejaba el
    endpoint caído en bucle. Ahora no lanza, pero tampoco puede pasar
    desapercibido — el mismo texto va al journal y a `instructions`, que es lo
    que lee el cliente en `initialize`.
    """
    p = (perfil or "").strip().lower()
    if p in _TODAS or p in PERFILES:
        return ""
    validos = ", ".join(sorted(PERFILES)) + ", todas"
    return (
        f"MCP_TOOL_PROFILE={perfil!r} no existe, se sirven las herramientas de "
        f"siempre. Perfiles válidos: {validos}."
    )


def herramientas_activas(perfil: str | None) -> frozenset | None:
    """Nombre del perfil => conjunto de tools; `None` => todas.

    Un perfil desconocido NO lanza: cae a `todas` y deja el error en el log.
    """
    p = (perfil or "").strip().lower()
    if p in _TODAS:
        return None
    if p in PERFILES:
        return PERFILES[p]
    log.error(aviso_perfil(perfil))
    return None
