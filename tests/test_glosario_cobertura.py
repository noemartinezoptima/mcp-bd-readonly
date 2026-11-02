"""Test de cobertura: ¿qué tablas reales no tiene el glosario cubiertas?

Hasta ahora, los gaps de `resolve_domain_term` (términos sin canónico, o
canónicos que apuntan a la tabla equivocada) se descubrían probando frases en
vivo contra producción, sesión tras sesión -- un proceso manual que nunca
termina porque el esquema sigue creciendo (el módulo `bonus_*` se creó en
paralelo a la sesión del 1/2-nov-2026 que generó la mayoría de los fixes de
`glosario.py`).

Este test convierte ese proceso manual en un chequeo automático de CI: carga
la lista real de tablas de `data/schema_snapshot.json` y falla si aparece
alguna que el glosario no menciona (ni como "tabla" de un canónico, ni como
entrada de "otras_tools") Y que tampoco está en la lista de exclusión de
abajo. No sustituye probar frases reales -- el glosario puede seguir
mapeando una tabla al concepto equivocado -- pero sí elimina la clase de bug
"faltaba por completo": toda tabla nueva que aparezca en el esquema real
obliga a decidir EXPLÍCITAMENTE (en este fichero) si merece término propio o
si es ruido de infraestructura/catálogo, en vez de depender de que alguien
la pregunte en una sesión de pruebas.

Si este test falla tras una actualización de `schema_snapshot.json` (tabla
nueva en producción):
  1. Si es un concepto de negocio real -> añadir un canónico en glosario.py
     (ver CANONICOS_INFO) siguiendo el patrón de los fixes de esta sesión.
  2. Si es infraestructura/catálogo/framework sin valor de glosario directo
     -> añadir el nombre a TABLAS_EXCLUIDAS de abajo, con el motivo en el
     comentario del bloque correspondiente.
"""

import json
import re
from pathlib import Path

SCHEMA_SNAPSHOT = Path(__file__).parent.parent / "data" / "schema_snapshot.json"
GLOSARIO_SRC = Path(__file__).parent.parent / "src" / "mcp_bd_readonly" / "glosario.py"

# Patrones: tablas que por su nombre son claramente vistas, copias de
# seguridad o volcados temporales, nunca el "dueño" canónico de un concepto.
_PATRONES_EXCLUIDOS = (
    re.compile(r"^vista_"),
    re.compile(r"^bak_"),
    re.compile(r"^temp_"),
    re.compile(r"backup", re.I),
    re.compile(r"_\d{8}$"),
)

# Tablas de infraestructura, Laravel/framework, integraciones SSO/OAuth,
# auditoría técnica y telemetría: nunca son la respuesta a una pregunta de
# negocio, son mecanismo interno del propio sistema.
_INFRAESTRUCTURA = frozenset({
    "migrations", "jobs", "failed_jobs", "password_reset_tokens", "password_histories",
    "personal_access_tokens", "permission_role", "permissions", "roles", "role_user",
    "permiso_accion_role", "permiso_accions", "permiso_campo_role", "permiso_campos",
    "estado_role", "telescope_entries", "telescope_entries_tags", "telescope_monitoring",
    "dispositivos_recordados", "claves_recuperacion", "user_auth_tmp_tokens",
    "users_identificadores_sso", "proveedores_sso", "teams_graph_tokens", "jira_tokens",
    "graph_subscriptions", "graph_subscription_notification_channel",
    "tenant_proveedores_sso_configuraciones", "tenants", "email_preferences",
    "notification_channels", "notify_statuses", "outlook_service_settings",
    "archivo_notificacion_outlook", "notificaciones_outlook", "plantillas_outlook",
    "ot_graph_emails", "audit_logs", "excel_exports", "excel_staging", "export_jobs",
    "export_logs", "looker_studio_reports", "importacion_archivos_fixner",
    "integraciones", "integration_mappings", "external_platforms", "features", "constantes",
    "filtros", "codigos_siguientes", "series",
})

# Catálogos/dimensiones genéricas (id+nombre, o poco más) referenciadas por FK
# desde tablas de negocio ya cubiertas: demasiado granulares para merecer un
# término de glosario propio. Si una pregunta real necesita una de estas
# tablas por su nombre explícito (p. ej. "qué país..."), añadir un canónico
# y SACARLA de aquí.
_CATALOGOS = frozenset({
    "paises", "provincias", "poblaciones", "idiomas", "lugares", "origenes",
    "origenes_notificacion", "formas_de_pago", "tipos_de_gasto", "tipos_establecimiento",
    "tipos_contactos", "tipos_comentarios", "tipos_incidencia", "tipos_llamada",
    "tipos_materiales", "tipos_movimientos", "tipos_relacion_ticket", "tipos_servicios",
    "tipos_servicios_globales", "tipos_ticket", "tipos_valoracion", "tipos_felicitacion",
    "prioridades", "prioridades_ticket", "clientes_prioridades", "tecnicos_prioridades",
    "incidencias_prioridades", "incidencia_qc_subtipos", "estados_ot", "estimate_statuses",
    "presupuesto_estados", "ticket_mgr_tipos", "ticket_categorias", "ticket_epics",
    "ticket_impacto_personas", "ticket_impacto_trabajos", "tecnicos_estados",
    "tecnicos_tipos_servicios", "tecnicos_tipos_servicios_globales",
    "tecnicos_incidencias_tipos", "tecnico_tipos_confirmacion_asistencia",
    "ots_tipos", "ots_tipos_plantillas", "ots_tipos_tipos_servicios", "ot_tipo_categorias",
    "costes_indirectos_tipo", "other_expense_types", "stock_subtypes",
    "stock_adjustment_types", "country_levels", "geographic_zones", "tipo_plantilla_mails",
    "departamentos_ticket", "metodos_cambio_estado", "metodo_cambio_estado_transicion_estado",
    "transiciones_estado", "modelos", "zonas_horarias", "dias_festivos",
    "prl_tickets_prioridades",
})

# "informaciones_pagos_tipos" ya está cubierta como otras_tools del canónico
# "forma_pago" (ver glosario.py), pero es en esencia un catálogo id/nombre
# como los de arriba -- no necesita su propio canónico.

# Pivotes/tablas puente ya cubiertas implícitamente por la nota_uso del
# canónico "padre" (igual patrón que ot_tecnico dentro de "tecnico").
_PIVOTES = frozenset({
    "establecimiento_tecnico", "establecimiento_tecnico_fav", "establecimiento_plantilla",
    "establecimientos_users", "clientes_users", "contact_deal", "deal_country",
    "deal_pipeline_entry_rules", "deal_tracks", "marcas_usuarios", "movimiento_relacion",
    "personas_contacto", "personas_de_contacto", "peticion_tecnico",
    "tecnico_incidencia_factura_compra", "tickets_relacionados",
    "usuario_tipos_avisos_incidencias", "hubspot_company_map", "hubspot_contact_map",
    "hubspot_deal_map", "hubspot_deal_track_map", "articulo_cliente", "articulo_idiomas",
})

# Módulo CRM/comercial (deals/empresas/contactos): bounded context separado
# del dominio financiero/operativo que cubre hoy el glosario. Si se empieza a
# preguntar por él en vivo, dar de alta canónicos propios (mismo criterio que
# "bono" cuando apareció el feature de bonus).
_CRM = frozenset({
    "companies", "company_contact", "contacts", "contactos", "brand_contact", "deals",
    "deal_pipelines", "deal_docs", "estimates",
})

# Infra de comunicaciones/notificaciones internas (chat, avisos in-app,
# gamificación, IA de llamadas): no son conceptos de negocio consultables
# directamente, son mecanismo de UX/engagement.
_COMMS_Y_GAMIFICACION = frozenset({
    "chats", "chats_pendientes", "chats_silenciados", "lineas_chats", "correos",
    "notificaciones", "notificaciones_whatsapp", "mensajes_marca", "marcas",
    "avisos_app", "avisos_app_tipos", "aviso_app_estados", "felicitacion_usuario",
    "felicitaciones", "historial_qcoins", "agent_conversations",
    "agent_conversation_messages", "registro_llamadas_aws_connect",
    "registro_llamadas_ringover", "nora_call_logs", "nora_settings",
})

# Resto: administración interna, formularios genéricos, sub-detalle de tablas
# ya cubiertas (líneas/motivos), y dominios muy menores (RRHH ligero, flota,
# reuniones) tratados ya como fuera de alcance en sesiones de prueba previas.
_ADMIN_Y_MENORES = frozenset({
    "accion_usuarios", "acciones", "asuntos_ticket", "bancos", "biblias", "budgets",
    "campos_formularios", "campos_plantillas", "cargos", "checklists", "chequeos",
    "clientes_incidencias_mensajes", "colaboradores", "colaboradores_tipos",
    "costes_ots", "customer_experience", "customer_experience_equipo",
    "delegacion_tecnico", "delegaciones", "distancias", "draft_purchase_invoice_lines",
    "draft_purchase_invoices", "empleados247", "entidades_bancarias",
    "facturas_compra_lineas", "facturas_compra_motivos", "fechas_cierre", "formularios",
    "formularios_estados", "formularios_tipos", "historial_cambios_estados", "horarios",
    "inventarios", "lineas_incidencia", "mce", "motivos_error_video_reunion",
    "ot_visita", "ots_lineas_facturacion", "peticiones", "peticiones_tipos_servicios",
    "phones", "planificacion_lineas", "planificaciones", "plantillas", "plataformas",
    "pre_order_visibility_exceptions", "pre_orders", "preferencia_plantillas",
    "presupuestos_trabajos_a_realizar", "prl_tickets", "responsable_reunion",
    "reunion_tipos", "secciones_formularios", "secciones_plantillas", "solicitantes",
    "stock_adjustment_lines", "stock_adjustments", "stock_article_locations",
    "t_clientes_ipc", "tecnicos_incidencias_mensajes", "ticket_mgrs", "ticket_plantillas",
    "ticket_tareas", "trabajos_a_realizar", "vehiculos", "workplaces",
})

TABLAS_EXCLUIDAS = (
    _INFRAESTRUCTURA | _CATALOGOS | _PIVOTES | _CRM | _COMMS_Y_GAMIFICACION | _ADMIN_Y_MENORES
)


def _tablas_reales() -> set[str]:
    data = json.loads(SCHEMA_SNAPSHOT.read_text(encoding="utf-8"))
    return set(data["tables"].keys())


def _patron_excluido(tabla: str) -> bool:
    return any(p.search(tabla) for p in _PATRONES_EXCLUIDOS)


def _mencionada_en_glosario(tabla: str, texto_glosario: str) -> bool:
    return re.search(rf"(?<![a-zA-Z0-9_]){re.escape(tabla)}(?![a-zA-Z0-9_])", texto_glosario) is not None


def test_toda_tabla_real_esta_cubierta_o_explicitamente_excluida():
    tablas = _tablas_reales()
    texto_glosario = GLOSARIO_SRC.read_text(encoding="utf-8")

    sin_cubrir = [
        t for t in sorted(tablas)
        if not _patron_excluido(t)
        and t not in TABLAS_EXCLUIDAS
        and not _mencionada_en_glosario(t, texto_glosario)
    ]

    assert not sin_cubrir, (
        f"{len(sin_cubrir)} tabla(s) nueva(s) en schema_snapshot.json sin cobertura "
        f"en el glosario ni en TABLAS_EXCLUIDAS (tests/test_glosario_cobertura.py): "
        f"{sin_cubrir}. Añade un canónico en glosario.py si es un concepto de negocio "
        f"real, o añade el nombre a TABLAS_EXCLUIDAS con el motivo si es ruido de "
        f"infraestructura/catálogo."
    )


def test_exclusiones_no_contienen_tablas_fantasma():
    """Si una tabla se renombra o se elimina, que el set de exclusión no quede
    citando nombres que ya no existen -- señal de que hay que revisar la lista."""
    tablas = _tablas_reales()
    fantasma = sorted(TABLAS_EXCLUIDAS - tablas)
    assert not fantasma, (
        f"TABLAS_EXCLUIDAS cita tablas que ya no existen en el esquema real: {fantasma}. "
        "Revisa si se renombraron o se eliminaron y actualiza la lista."
    )
