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
        "margen", "beneficio", "ganancia", "rentabilidad", "resultado",
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
        "nota_uso": "Cliente de facturacion = clientes.razon_social.",
        "trampas": [
            "Usar razon_social; NO existe columna nombre_fiscal.",
            "nombre_comercial puede diferir de la razon social.",
        ],
    },
    "facturas_compra": {
        "tabla": "facturas_compra",
        "herramienta_mcp": "facturas_compra",
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
        "nota_uso": ("Margen bruto = SUM(facturas_venta.total_euros) − SUM(facturas_compra.total_coste_euros "
                     "WHERE coste_directo=1) en el mismo rango de fechas."),
        "trampas": [
            "Usar total_coste_euros (no base_euros) para el coste directo.",
            "Mismo rango de fechas en ventas y compras; si no, el margen no cuadra.",
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
}


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def normalizar_texto(texto: str) -> list[dict]:
    """Busca sinónimos del dominio en `texto` (sin acentos) y devuelve coincidencias
    {termino, canonico, info} ordenadas por relevancia: canonico más específico primero."""
    if not texto:
        return []
    ntexto = _norm(texto)
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
    sugerencias = [
        {
            "termino": c["termino"],
            "canonico": c["canonico"],
            "tabla": c["info"]["tabla"],
            "herramienta_mcp": c["info"]["herramienta_mcp"],
            "nota_uso": c["info"]["nota_uso"],
        }
        for c in coincidencias
    ]
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
        "sugerencias": sugerencias,
        "recomendado": recomendado,
    }