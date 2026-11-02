"""Glosario de dominio Optima: lenguaje de negocio en español → términos canónicos del catálogo.

Mapea frases de una usuaria no técnica ("cuánto facturamos a X", "cobros pendientes")
a términos canónicos verificados (tabla + herramienta MCP + trampas). Los mapeos se
apoyan en ESQUEMA-BD.md (info_schema real, 2026-09): no se asume ninguna columna.
"""

import re
import unicodedata
from collections import Counter

SINONIMOS = {
    "establecimiento": [
        "establecimiento", "establecimientos", "tienda", "tiendas", "local", "locales",
        "punto de venta", "punto venta", "pdv", "retail", "centro", "centros",
    ],
    "facturas_venta": [
        "factura", "facturas", "facturación", "facturo", "facturado", "facturados",
        "facturamos", "venta", "ventas", "vendido", "vendidos", "vendimos",
    ],
    "efectos_pago": [
        "cobro", "cobros", "cobrado", "cobrados", "cobramos", "cobrar",
        "pago", "pagos", "pagado", "pagados", "remesa", "remesas", "efecto", "efectos",
    ],
    "resumen_iva": [
        "iva", "liquidar", "liquidación", "liquidado", "liquidados", "liquidamos",
        "líquido", "liquidada",
    ],
    "ots": [
        "ot", "ots", "obra", "obras", "parte de trabajo", "partes de trabajo",
    ],
    "responsable": [
        "responsable", "encargado", "encargada", "a cargo", "de quién es",
        "quién lleva",
    ],
    "cliente": [
        "cliente", "clientes", "razón social",
    ],
    "facturas_compra": [
        "gasto", "gastos", "compra", "compras", "comprado", "proveedor", "proveedores",
        "subcontrata", "subcontratado", "subcontratación",
    ],
    "margen": [
        "margen", "beneficio", "ganancia", "rentabilidad",
    ],
    "pnl": [
        "pnl", "p&l", "pyg", "cuenta de resultados", "pérdidas y ganancias",
        "perdidas y ganancias", "ebitda", "resultado", "resultado del ejercicio",
    ],
    "stock": [
        "stock", "inventario", "existencia", "existencias", "artículo", "articulo",
        "articulos", "almacen", "almacén", "producto", "productos",
    ],
    "balance": [
        "balance", "hoja de balance", "activo", "pasivo", "patrimonio",
        "patrimonio neto", "situación", "situacion",
    ],
    "tecnico": [
        "tecnico", "tecnicos", "instalador", "instaladores", "profesional",
        "profesionales", "operario", "operarios",
    ],
    "bono": [
        "bono", "bonos", "comision", "comisiones", "bonus",
    ],
    "presupuesto": [
        "presupuesto", "presupuestos",
    ],
    "activo_fijo": [
        "activo fijo", "activos fijos", "inmovilizado", "inmovilizados",
    ],
    "tarifa": [
        "tarifa", "tarifas",
    ],
    "evaluacion": [
        "evaluacion", "evaluaciones", "valoracion", "valoraciones",
        "desempeño", "desempeno",
    ],
    "contrato": [
        "contrato", "contratos",
    ],
    "ticket": [
        "ticket", "tickets",
    ],
    "centro_coste": [
        "centro de coste", "centros de coste", "centro de costes", "centros de costes",
    ],
    "tipo_cambio": [
        "tipo de cambio", "tipos de cambio", "divisa", "divisas",
    ],
    # OJO: NO se incluye "iteracion"/"iteraciones" aqui a proposito. Pese al
    # nombre parecido (iteration=sprint en ingles), la tabla real
    # "iteraciones" es sobre recurrencia de generacion de OTs preventivas
    # desde un contrato (contrato_id/periodicidad/dias_semana), un dominio
    # totalmente distinto de los sprints de desarrollo. Ver trampa en
    # CANONICOS_INFO["sprint"]. Gap real detectado en vivo (2-nov-2026).
    "sprint": [
        "sprint", "sprints",
    ],
}

CANONICOS_INFO = {
    "establecimiento": {
        "tabla": "establecimientos",
        "herramienta_mcp": "detalle_establecimiento",
        "nota_uso": ("Tienda/local/punto de venta. Responsable = responsable_id → users.name; "
                     "cliente = cliente_facturacion_id → clientes.razon_social. Filtrar deleted_at IS NULL."),
        "trampas": [
            "NO existe columna 'responsable' ni 'detalle': JOIN users por responsable_id.",
            "El cliente real es clientes.razon_social, no nombre_comercial.",
        ],
    },
    "facturas_venta": {
        "tabla": "facturas_venta",
        "herramienta_mcp": "facturas_venta",
        "otras_tools": {
            "cuadre_factura": "comprobar que suma de líneas == total de cabecera de UNA factura",
            "excepciones": "facturas sobre un umbral, clasificadas por materialidad",
            "informe_financiero": "informe Markdown+CSV de un periodo (para compartir/exportar)",
        },
        "nota_uso": ("Facturación/ventas. Dinero en total_euros e iva_euros; base = total_euros − iva_euros. "
                     "Filtrar deleted_at IS NULL."),
        "trampas": [
            "NO existe base_euros: la base se deriva (total_euros − iva_euros).",
            "Los totales van en *_euros; *_moneda es la divisa de la factura.",
        ],
    },
    "efectos_pago": {
        "tabla": "efectos_pago",
        "herramienta_mcp": "remesas_pendientes",
        "otras_tools": {
            "conciliar_remesas": "total emitido vs acreditado (cuadre global, no por efecto)",
            "aging_efectos": "pendientes agrupados por antigüedad (0-30/30-60/60-90/+90 días)",
            "dso_dpo_evolutivo": "serie mensual de DSO (cobro) y DPO (pago) en días",
        },
        "nota_uso": "Cobros/pagos/remesas/efectos. Pendiente = regularizado=0 (SUM(total_euros), canónico).",
        "trampas": [
            "Polimórfico: modelo_id=12 → FacturaVenta, 11 → FacturaCompra; relacion_id apunta al id de esa tabla, NO es FK.",
            "NO tiene cliente_id directo: pasar por relacion_id → facturas_venta.cliente_id.",
            "Fecha de pago = fecha_pagado (no fecha_pago); NUNCA usar cobros_remesas (error 1146).",
        ],
    },
    "resumen_iva": {
        "tabla": "facturas_venta (agregado trimestral)",
        "herramienta_mcp": "resumen_iva",
        "nota_uso": "IVA a liquidar = SUM(iva_euros) de facturas_venta por trimestre + anio.",
        "trampas": [
            "Solo existe iva_euros: no hay impuestos adicionales separados.",
            "Es un agregado: llamar resumen_iva(trimestre, anio), no hay tabla aparte.",
        ],
    },
    "ots": {
        "tabla": "ots",
        "herramienta_mcp": "run_query",
        "nota_uso": "OT / partes de trabajo. Unica tabla de la BD con base_euros real.",
        "trampas": [
            "base_euros SI existe aqui (unica excepcion; fuera de ots es inexistente).",
            "OT por tienda: establecimiento_id → establecimientos.id.",
            "Puente factura ↔ OT: facturas_venta_lineas.ot_id.",
        ],
    },
    "responsable": {
        "tabla": "users (via establecimientos.responsable_id / ots.responsable_id)",
        "herramienta_mcp": "detalle_establecimiento",
        "nota_uso": "Persona a cargo de una tienda/OT: es un usuario (users.name), no una columna.",
        "trampas": [
            "No es columna 'responsable': JOIN users por responsable_id.",
            "Vive en establecimientos.responsable_id y ots.responsable_id.",
        ],
    },
    "cliente": {
        "tabla": "clientes",
        "herramienta_mcp": "detalle_establecimiento",
        "otras_tools": {
            "saldos_cliente": "facturado vs cobrado y pendiente de UN cliente concreto",
        },
        "nota_uso": "Cliente de facturacion = clientes.razon_social.",
        "trampas": [
            "Usar razon_social; NO existe columna nombre_fiscal.",
            "nombre_comercial puede diferir de la razon social.",
        ],
    },
    "facturas_compra": {
        "tabla": "facturas_compra",
        "herramienta_mcp": "facturas_compra",
        "otras_tools": {
            "resumen_gastos_por_tipo": "gastos agregados por categoría (tipo_de_gasto) en un rango",
        },
        "nota_uso": ("Gastos/compras. Dinero en base_euros/iva_euros/total_euros/total_coste_euros "
                     "(aquí base_euros SÍ existe). coste_directo=1 es coste directo (COGS), 0 es indirecto. "
                     "proveedor_nombre viene denormalizado; proveedor_id -> proveedores. pagada=0 pendiente, 1 pagada."),
        "trampas": [
            "Gastos viven en facturas_compra, NO en facturas_venta.",
            "Fecha de pago = fecha_pago (aquí SÍ, distinto a efectos_pago.fecha_pagado).",
            "Hay basura de fechas (ej. 1921): filtrar SIEMPRE por rango.",
        ],
    },
    "margen": {
        "tabla": "facturas_venta + facturas_compra (coste_directo=1)",
        "herramienta_mcp": "margen",
        "nota_uso": ("Margen bruto = ventas netas (total − iva) − SUM(facturas_compra.total_coste_euros "
                     "WHERE coste_directo=1) en el mismo rango de fechas."),
        "trampas": [
            "Usar total_coste_euros (no base_euros) para el coste directo.",
            "Ventas NETAS (total_euros − iva_euros); facturas_venta no tiene base_euros.",
            "Mismo rango de fechas en ventas y compras; si no, el margen no cuadra.",
        ],
    },
    "pnl": {
        "tabla": "facturas_venta + facturas_compra",
        "herramienta_mcp": "pnl",
        "nota_uso": ("Cuenta de resultados: ingresos netos → costes directos (COGS) → margen bruto → "
                     "costes indirectos (OPEX, coste_directo=0) → resultado. Todo en euros netos de IVA."),
        "trampas": [
            "Resultado ≠ margen: resultado resta también los costes indirectos.",
            "coste_directo=1 = COGS, coste_directo=0 = OPEX/indirectos.",
        ],
    },
    "stock": {
        "tabla": "stock_articles + stock_locations + stock_movements",
        "herramienta_mcp": "stock_actual",
        "otras_tools": {
            "stock_por_ubicacion": "stock agrupado por ubicación/almacén",
            "movimientos_stock": "histórico de movimientos de un artículo/ubicación",
        },
        "nota_uso": ("Stock actual = último resulting_stock por (article_id, location_id). "
                     "stock_articles = productos; stock_locations = ubicaciones/almacenes."),
        "trampas": [
            "No hay columna 'stock' en stock_articles: el stock vive en stock_movements.resulting_stock.",
            "Ubicaciones típicas: Interno / Externo / Material defectuoso / OPTIMA RETAIL.",
        ],
    },
    "balance": {
        "tabla": "accounting_entry_lines + accounting_accounts",
        "herramienta_mcp": "balance",
        "nota_uso": ("Balance de situación desde contabilidad PGC: saldo (debe−haber) por cuenta, "
                     "clasificado en activo/pasivo/patrimonio/ingreso/gasto. Cuadra: activo − (pasivo+patrimonio) = resultado."),
        "trampas": [
            "balance_nature está vacío en la BD: se clasifica por pgc_group (subgrupo PGC).",
            "Grupo 3 (existencias) está vacío en esta contabilidad.",
        ],
    },
    "tecnico": {
        "tabla": "tecnicos (asignación a una OT vía la tabla puente ot_tecnico)",
        "herramienta_mcp": "run_query",
        "nota_uso": ("Técnico/instalador. tecnicos.nombre_comercial / nombre_fiscal / telefono. "
                     "Asignación a una OT: ot_tecnico.tecnico_id + ot_id, con seleccionado=1 marcando "
                     "el técnico elegido para esa OT (puede haber varias filas por ronda de llamadas)."),
        "trampas": [
            "NO hay columna tecnico_id en ots: pasar siempre por ot_tecnico.",
            "ot_tecnico.seleccionado=1 es el técnico confirmado; otras filas son candidatos descartados.",
            "El teléfono vive en tecnicos.telefono, sin prefijo país salvo que se añada.",
        ],
    },
    "bono": {
        "tabla": "bonus_cierres",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "bonus_config": "parámetros de cálculo del bono (clave/valor, tabla key-value)",
            "bonus_asignaciones_equipo": "quién pertenece a qué equipo/TL/manager y desde cuándo",
            "bonus_modificadores": "ajustes manuales aplicados al bono de un usuario/mes",
            "bonus_ajustes_coo": "ajuste del COO fuera del bruto",
            "bonus_contratos_perdidos": "contratos perdidos que penalizan el bono",
        },
        "nota_uso": ("Bono/comisión mensual de un usuario. bonus_cierres.bonus_month (formato 'YYYY-MM') + "
                     "user_id es la clave; final_amount es el importe ya cerrado, closed_at/closed_by marcan "
                     "si está cerrado (NULL = aún abierto/editable). Feature nueva (nov-2026): sin tool "
                     "dedicada en el catálogo todavía, solo run_query directo sobre las tablas bonus_*."),
        "trampas": [
            "NO confundir con efectos_pago/cobros: el bono es una comisión de empleado, no un cobro de cliente.",
            "bonus_cierres.version es versión del cálculo (recalculado), no revisar por fecha sino por version/closed_at.",
            "bonus_config es key-value genérico (columnas key/value), no una tabla de parámetros tipada.",
        ],
    },
    "presupuesto": {
        "tabla": "presupuestos",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "presupuestos_lineas_facturacion": "líneas (artículo/cantidad/precio) de UN presupuesto",
            "presupuestos_solicitados": "solicitudes de precio a varios técnicos/proveedores para un presupuesto, con seleccionado=1 marcando la elegida",
        },
        "nota_uso": ("Presupuesto/oferta a cliente. presupuestos.ot_id la liga a una OT; estado_id -> estados "
                     "(enviado/aceptado/rechazado...). Dinero en total_euros/iva_euros (igual que facturas_venta)."),
        "trampas": [
            "NO tiene cliente_id: el cliente va en cliente_nif (texto), no FK a clientes.",
            "NO existe base_euros: se deriva (total_euros − iva_euros), igual que en facturas_venta.",
            "presupuestos_solicitados.seleccionado=1 es la solicitud ganadora entre varias (mismo patrón que ot_tecnico.seleccionado=1).",
        ],
    },
    "activo_fijo": {
        "tabla": "fixed_assets",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "fixed_asset_movements": "histórico de movimientos (alta/baja/depreciación/deterioro) de UN activo",
            "fixed_asset_categories": "categorías de activo (determinan cuentas contables por defecto)",
            "fixed_asset_schedule_lines": "plan de amortización calculado línea a línea",
        },
        "nota_uso": ("Activo fijo / inmovilizado (submódulo de amortización, distinto del balance contable "
                     "genérico aunque enlaza con accounting_accounts vía asset_account_id/accumulated_account_id/"
                     "expense_account_id). status (draft/active/disposed/...) marca el estado; disposed_on + "
                     "disposal_proceeds es la baja."),
        "trampas": [
            "NO confundir con 'balance' (accounting_*): fixed_assets es el submódulo de inmovilizado, no cuentas contables en sí.",
            "Baja = disposed_on IS NOT NULL (o status='disposed'); el motivo va en fixed_asset_movements.notes/movement_type, no en una columna de fixed_assets.",
            "empresa_id es varchar(32), no un id numérico de la tabla empresas: revisar el tipo antes de hacer JOIN.",
        ],
    },
    "tarifa": {
        "tabla": "tarifas",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "tecnicos_tarifas": "tarifas de PAGO a técnicos (coste por hora/desplazamiento), sentido opuesto a 'tarifas'",
        },
        "nota_uso": ("Tarifa de precio AL CLIENTE por tipo de OT/prioridad: tarifas.cliente_id + ots_tipo_id + "
                     "prioridad_id determina mano_obra/desplazamiento (+ variantes _extra) y horas_sla/vencimiento."),
        "trampas": [
            "'tarifas' y 'tecnicos_tarifas' son tablas DISTINTAS con sentido opuesto: tarifas = precio al cliente; "
            "tecnicos_tarifas = lo que se paga al técnico (por franja: laboral/noche/fin de semana/festivo/urgencia).",
            "No confundir con una tarifa de cambio de divisa (eso es conversion_monedas/exchange_rates, no esta tabla).",
        ],
    },
    "evaluacion": {
        "tabla": "valoraciones_tecnico",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "evaluaciones": "evaluaciones de calidad (QC) de UN ESTABLECIMIENTO (visitas/preguntas), no del técnico",
        },
        "nota_uso": ("Valoración/evaluación de desempeño de un técnico tras una OT concreta: "
                     "valoraciones_tecnico.nota + observaciones, ligada a tecnico_id + ot_id."),
        "trampas": [
            "NO confundir con 'evaluaciones' (tabla de QC de establecimientos, dominio distinto pese al nombre parecido).",
            "Una fila por OT evaluada, no una nota acumulada única por técnico: hay que agregar (AVG/COUNT) si se pide 'la nota' de un técnico.",
        ],
    },
    "contrato": {
        "tabla": "contratos",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "contratos_establecimientos": "pivote contrato↔establecimiento (alternativa/legacy a contratos.establecimientos_id en JSON)",
        },
        "nota_uso": ("Contrato de servicio con un cliente. contratos.cliente_id; contratos.establecimientos_id es "
                     "un JSON con los ids de tienda cubiertos (no una FK simple); fecha_firma/canceled_date marcan vigencia."),
        "trampas": [
            "establecimientos_id es JSON (varias tiendas por contrato), no una columna FK única: no se puede JOIN directo.",
            "Vigente = canceled_date IS NULL; canceled_date NOT NULL es un contrato cancelado, no vencido por fecha.",
            "No confundir con bonus_contratos_perdidos (esa tabla es para el cálculo del bono, dominio distinto).",
        ],
    },
    "ticket": {
        "tabla": "tickets",
        "herramienta_mcp": "run_query",
        "nota_uso": ("Tickets internos de desarrollo/soporte (incidencias del propio sistema: issue_jira, "
                     "sprint_id, epic_id, categoria_id), NO incidencias de cliente/OT."),
        "trampas": [
            "NO es lo mismo que 'incidencias' (quejas/incidencias de cliente o de OT) ni que 'clientes_incidencias'.",
            "check es un booleano (revisado/no), no el estado del ticket: el estado real va en estado_id.",
        ],
    },
    "centro_coste": {
        "tabla": "centros_coste",
        "herramienta_mcp": "run_query",
        "nota_uso": ("Centro de coste (dimensión contable), DISTINTO de 'centro' como sinónimo de tienda/establecimiento. "
                     "Se referencia desde fixed_assets.centro_coste_id y otras tablas de gasto."),
        "trampas": [
            "'centro'/'centros' a secas significan tienda (establecimiento); solo la frase completa 'centro(s) de coste(s)' es esta tabla.",
        ],
    },
    "tipo_cambio": {
        "tabla": "exchange_rates (nuevo) / conversion_monedas (legacy)",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "currencies": "catálogo de divisas NUEVO (ISO 4217: code/numeric_code/symbol)",
            "monedas": "catálogo de divisas LEGACY (texto libre: moneda/codigo_moneda/simbolo)",
        },
        "nota_uso": ("Hay DOS generaciones de tipo de cambio conviviendo: legacy (monedas + conversion_monedas, "
                     "con nombres de moneda en texto libre) y nueva (currencies + exchange_rates, ISO 4217 con "
                     "base_currency_id/quote_currency_id + rate_date). Verificar con describe_table a cuál de las "
                     "dos apunta moneda_id en la tabla de negocio concreta ANTES de hacer el JOIN: no asumir."),
        "trampas": [
            "NO asumir una sola tabla: moneda_id en tablas de negocio (presupuestos, tarifas, facturas) puede "
            "apuntar a monedas O a currencies según cuándo se creó el dato.",
            "conversion_monedas.tasa_conversion es legacy (moneda_inicial/moneda_final en texto); "
            "exchange_rates.rate es la versión nueva con FKs (base_currency_id/quote_currency_id) y rate_date.",
        ],
    },
    "sprint": {
        "tabla": "sprints",
        "herramienta_mcp": "run_query",
        "otras_tools": {
            "ticket": "tickets.sprint_id enlaza cada tarea a su sprint",
        },
        "nota_uso": "Sprint de desarrollo: nombre, fecha_inicio, fecha_fin, activo. Las tareas lo referencian vía tickets.sprint_id.",
        "trampas": [
            "NO usar la tabla 'iteraciones' para esto: pese al nombre parecido (iteration=sprint en inglés), esa "
            "tabla es sobre recurrencia de generación de OTs preventivas desde un contrato "
            "(contrato_id/periodicidad/dias_semana/dias_mes), un dominio totalmente distinto de los sprints de desarrollo.",
        ],
    },
}

_ESPECIFICIDAD = {
    "establecimiento": 7,
    "facturas_venta": 6,
    "efectos_pago": 5,
    "resumen_iva": 4,
    "ots": 3,
    "responsable": 2,
    "cliente": 1,
    "facturas_compra": 5,
    "margen": 4,
    "pnl": 4,
    "stock": 5,
    "balance": 5,
    "tecnico": 4,
    # 6 (por encima de efectos_pago=5): "cobró el bono" debe recomendar bono,
    # no efectos_pago -- "cobró" ahí es cobro de comisión de empleado, no de
    # cliente. Bug real detectado en vivo (1-nov-2026).
    "bono": 6,
    "presupuesto": 5,
    # 6 (por encima de balance=5): "activos fijos" tambien matchea "activo"
    # (sinonimo de balance) via prefijo -- debe ganar el submodulo especifico
    # de inmovilizado, no el balance contable generico. Gap real detectado en
    # vivo (2-nov-2026).
    "activo_fijo": 6,
    "tarifa": 4,
    "evaluacion": 4,
    "contrato": 5,
    "ticket": 4,
    # 8 (por encima de establecimiento=7): "centro de coste" también matchea
    # "centro" (sinónimo de establecimiento) -- debe ganar el concepto contable
    # especifico, no la tienda. No hace falta excluir la locución: al ser mas
    # especifico ya gana como recomendado, y establecimiento sigue apareciendo
    # como coincidencia secundaria (igual que "activo" junto a activo_fijo).
    # Falso positivo real, detectado en vivo (2-nov-2026).
    "centro_coste": 8,
    # 7 (por encima de facturas_venta=6/facturas_compra=5): "qué tipo de
    # cambio..." es una pregunta explicita sobre divisas, debe ganar sobre el
    # match generico de "facturas"/"proveedores" en la misma frase. Gap real
    # detectado en vivo, repetido en dos frases distintas (2-nov-2026).
    "tipo_cambio": 7,
    "sprint": 4,
}


# Expresiones donde una palabra-sinónimo pierde su sentido de dominio. "obra"
# sola es "OT/parte de trabajo", pero en "mano de obra" es coste de personal
# (facturas_compra/efectos_pago), no una OT — falso positivo real, detectado
# probando resolve_domain_term en vivo (1-nov-2026). Se quita la locución
# ANTES de buscar sinónimos sueltos, igual que security.py quita literales
# antes de buscar verbos prohibidos: así "obra" dentro de la locución no
# cuenta, pero el resto de la frase (p. ej. "pagado", "subcontratado") sigue
# intacto para las demás coincidencias.
# "que efectos ha tenido X" es el sentido de "consecuencias", no "efectos de
# pago" (letras/pagarés) — otro falso positivo real, probado en vivo
# (1-nov-2026): "que efectos ha tenido el cambio de tarifa en los pagos..."
# disparaba efectos_pago aunque la frase no habla de cobros/remesas.
_LOCUCIONES_EXCLUIDAS = ("mano de obra", "que efectos")


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def normalizar_texto(texto: str) -> list[dict]:
    """Busca sinónimos del dominio en `texto` (sin acentos) y devuelve coincidencias
    {termino, canonico, info} ordenadas por relevancia: canonico más específico primero."""
    if not texto:
        return []
    ntexto = _norm(texto)
    for locucion in _LOCUCIONES_EXCLUIDAS:
        ntexto = ntexto.replace(_norm(locucion), "")
    palabras = [p for p in re.split(r"\W+", ntexto) if p]
    orden = []
    for canonico, sinonimos in SINONIMOS.items():
        info = CANONICOS_INFO[canonico]
        mejor = None
        for syn in sinonimos:
            n = _norm(syn)
            mejor_n = None
            if " " in syn.strip():
                if n in ntexto:
                    mejor_n = (3, len(syn), -ntexto.index(n), syn)
            elif len(n) < 4:
                if n in palabras:
                    mejor_n = (3, len(syn), -palabras.index(n), syn)
            else:
                for i, w in enumerate(palabras):
                    if w.startswith(n):
                        mejor_n = (3 if w == n else 2, len(syn), -i, syn)
                        break
            if mejor_n and (mejor is None or mejor_n[:3] > mejor[:3]):
                mejor = mejor_n
        if mejor:
            _, _, _, syn = mejor
            orden.append((mejor[0], _ESPECIFICIDAD[canonico], mejor[1], mejor[2], syn, canonico, info))
    orden.sort(reverse=True)
    return [
        {"termino": syn, "canonico": canonico, "info": info}
        for _, _, _, _, syn, canonico, info in orden
    ]


def resolver(texto: str) -> dict:
    """Resuelve una frase en español a términos canónicos del catálogo (tabla + tool + nota)."""
    coincidencias = normalizar_texto(texto)
    # `sugerencias` era `coincidencias` aplanado (mismo termino/canonico/tabla/
    # herramienta_mcp/nota_uso, sin `trampas`): una respuesta duplicada para una
    # tool que el agente llama antes de CADA SQL, según las INSTRUCTIONS del
    # servidor. Se eliminó: toda esa info ya está en `coincidencias[].info`.
    if coincidencias:
        cont = Counter(c["canonico"] for c in coincidencias)
        max_n = cont.most_common(1)[0][1]
        candidatos = [c["canonico"] for c in coincidencias if cont[c["canonico"]] == max_n]
        recomendado = candidatos[0]
    else:
        recomendado = None
    return {
        "normalizado": _norm(texto),
        "coincidencias": coincidencias,
        "recomendado": recomendado,
    }