"""Guiones MCP: el "entrenamiento" del agente, cargado bajo demanda.

Los prompts NO viajan en el handshake: el cliente los pide con `prompts/get`
cuando los necesita, así que enseñar cueste cero tokens de contexto mientras no
se usen. Esa es la razón de existir de este módulo frente a `INSTRUCTIONS`, que
sí se envía en cada `initialize`.

Todo lo que hay aquí está verificado contra la BD real (`describe_table` sobre
la réplica), no contra suposiciones: columnas que existen, columnas que NO
existen y errores concretos que ya se han producido (1054, 1146).
"""

from mcp.server.fastmcp import FastMCP

# Trampas de esquema verificadas con describe_table (no son adivinanzas):
#   - `base_euros` existe SOLO en `ots` (columna 41 de 100). En `facturas_venta`
#     no existe: la base se deriva de `total_euros - iva_euros`.
#   - `efectos_pago` es polimórfico (modelo_id 12=venta / 11=compra) y NO tiene
#     `cliente_id`; su fecha de pago es `fecha_pagado`, y `cobros_remesas` no
#     existe (error 1146).
#   - `estados_ot` está VACÍA: los estados de OT viven en `estados`.
#   - Dos columnas con el mismo nombre salen desambiguadas (`nombre`, `nombre_2`).

SQL_SEGURO = """Protocolo para consultar la BD de Optima sin fallar:

1. resolve_domain_term(<tu pregunta en español>) devuelve tabla + tool + trampas.
   Llámalo ANTES de escribir SQL: es la diferencia entre acertar y un error 1054.
2. describe_tablas_clave si necesitas el esquema; no adivines nombres de columna.
3. run_query(query, limit): limit debe ser None o un entero >= 1 (limit=0 es error).
   Por defecto devuelve 100 filas. Si recibes exactamente `limit` filas puede haber
   más: cuenta con COUNT(*), no cuentes las filas recibidas.
4. Trampas verificadas que provocan error 1054:
   - base_euros NO existe. Solo está en la tabla `ots`. En facturas_venta usa
     total_euros / iva_euros.
   - Los totales van en *_euros; *_moneda es la divisa de la factura
     (base_moneda, iva_moneda, total_moneda).
   - efectos_pago no tiene cliente_id: relacion_id -> facturas_venta.cliente_id
     (modelo_id 12 = venta, 11 = compra, y relacion_id NO es una foreign key).
   - La fecha de pago es fecha_pagado. No existe cobros_remesas (error 1146).
5. Solo lectura: INSERT/UPDATE/DELETE/DDL se rechazan en la barrera de seguridad.
6. Si dos columnas se llaman igual, la segunda aparece como <nombre>_2: no se
   pierde, pero nómbrala así en el resultado."""

IVA_TRIMESTRAL = """IVA de {anio} T{trimestre}:

1. Llama resumen_iva(trimestre={trimestre}, anio={anio}). Es un agregado: no hay
   una tabla de impuestos aparte que puedas consultar.
2. Trampas verificadas:
   - Solo existe iva_euros; no hay impuestos adicionales separados.
   - En facturas_venta NO existe base_euros: la base es total_euros - iva_euros.
   - Las columnas *_moneda son la divisa de la factura, no los importes en euros.
   - Hay iva_incluido e iva_valor: compruébalos antes de asumir IVA desglosado.
3. Para el detalle filtra por fecha_factura dentro del trimestre y respeta
   deleted_at IS NULL.
4. Si algo no cuadra, pasa a cuadre_factura sobre las líneas del periodo."""

RIESGO_COBROS = """Cartera de cobro, remesas, saldos y aging:

1. Usa primero las tools ya hechas: remesas_pendientes, saldos_cliente,
   excepciones, conciliar_remesas, aging_efectos, dso_dpo_evolutivo. Solo escribe
   SQL si ninguna cubre lo que piden.
2. Tablas verificadas:
   - efectos_pago: modelo_id 12 -> facturas_venta, 11 -> facturas_compra;
     relacion_id apunta al id de esa tabla y NO es foreign key.
     NO tiene cliente_id: pasa por relacion_id -> facturas_venta.cliente_id.
     Fecha de pago = fecha_pagado. También tiene banco_id, remesa_id,
     documento_pago_id, fecha_vencimiento y estado_id.
   - remesas: solo id, documento_pago_id, banco_id, es_nacional.
   - No existe cobros_remesas (error 1146).
3. Para antigüedad agrupa por tramos sobre fecha_vencimiento
   (0-30 / 30-60 / 60-90 / +90) en vez de devolver la lista entera."""

OT_ABIERTAS = """OT abiertas de un mes concreto:

1. La tabla es `ots` (100 columnas). OJO: `estados_ot` está VACÍA — los estados
   están en `estados` y `ots.estado_id` apunta ahí.
2. Abierta = fecha_cierre IS NULL. El mes se filtra por fecha_recibida entre
   'YYYY-MM-01' y el primer día del mes siguiente.
3. Desglose por estado: JOIN estados e ON e.id = o.estado_id
   GROUP BY e.nombre ORDER BY n DESC.
4. Distingue "sin cerrar" de "en curso": hay OT con estado terminal pero
   fecha_cierre NULL (p. ej. 'Finalizada - Cliente No informado'), así que si te
   piden las de verdad en curso, exclúyelas y di cuántas has excluido.
5. Relaciones verificadas: ots.establecimiento_id -> establecimientos.id;
   puente factura <-> OT = facturas_venta_lineas.ot_id.
6. En `ots` SÍ existe base_euros (es la única tabla donde existe)."""


def build_prompts(mcp: FastMCP) -> None:
    """Registra los guiones en el servidor MCP."""

    @mcp.prompt(name="sql_seguro", description="Protocolo de consulta y trampas de esquema antes de escribir SQL.")
    def sql_seguro() -> str:
        return SQL_SEGURO

    @mcp.prompt(name="iva_trimestral", description="Guion para revisar el IVA de un trimestre.")
    def iva_trimestral(anio: int, trimestre: int) -> str:
        return IVA_TRIMESTRAL.format(anio=anio, trimestre=trimestre)

    @mcp.prompt(name="riesgo_cobros", description="Guion de cartera de cobro, remesas, saldos y aging de efectos.")
    def riesgo_cobros() -> str:
        return RIESGO_COBROS

    @mcp.prompt(name="ot_abiertas", description="Guion para contar y desglosar OT abiertas de un mes.")
    def ot_abiertas() -> str:
        return OT_ABIERTAS
