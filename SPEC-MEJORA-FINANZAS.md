# SPEC — Mejora de `mcp-bd-readonly` para análisis financiero avanzado

Autor: zerocool · Estado: **propuesto** · Fecha: 2026-09-10

---

## 1. Path de proyecto (hechos verificados, no suposiciones)

```
/Volumes/CORSAIR/Proyectos/ZeroCoolNetwork/mcp-bd-readonly/
├── pyproject.toml            # deps: fastmcp, pymysql, openpyxl, formualizer
├── src/mcp_bd_readonly/
│   ├── server.py             # main(): registra los 16 tools
│   ├── config.py             # load_config() → {db, tunnel, data_dir}; fallback ~/.zt-readonly.env
│   ├── db.py                 # QueryExecutor.run(sql, limit) — PyMySQL
│   ├── security.py           # parser: rechaza DML/DDL; barrier #1
│   ├── audit.py              # AuditLogger → data/audit.jsonl
│   ├── dbutils.py            # shape_rows()
│   ├── format_es.py          # formato € ES
│   ├── tunnel.py             # TunnelManager — elevación SSH 13306→3306
│   ├── tools_setup.py        # setup_ssh (solo lectura)
│   ├── tools_core.py         # list_databases, list_tables, describe_table, run_query
│   ├── tools_finanzas.py     # facturas_venta, resumen_iva, remesas_pendientes, cuadre_factura
│   ├── tools_auditoria.py    # conciliar_remesas, saldos_cliente, excepciones, informe_financiero
│   └── tools_excel.py        # leer_excel, check_excel_capabilities (openpyxl + LO/formualizer)
├── scripts/                  # mcp-stdio.sh, tunnel.ps1, tunnel.sh
├── tests/                    # 102 tests green (pytest, 0.8s)
└── README.md / SETUP-WINDOWS.md / client-notes.md
```

**BD real** (MySQL 8.4.9): `back` vía `127.0.0.1:13306` (ssh tunnel `optimaback-active`).
Usuario `back_readonly` con GRANT SELECT. Tablas clave: `clientes` (`razon_social`/`nombre_comercial`, NO `nombre_fiscal`), `facturas_venta` (sin `canal_venta`; tiene `base_moneda`, `iva_euros`, `total_euros`, `fecha_factura`, `deleted_at`, `estado_id`, `tipo_factura`?), `efectos_pago` (**polimórfico**: `modelo_id` 11→FacturaCompra / 12→FacturaVenta + `relacion_id`; **sin `cliente_id`**, sin `fecha_pago` → es `fecha_pagado`), `remesas` (`documento_pago_id`, `banco_id`, `es_nacional`), `bancos` (`nombre`, `iban`, `include_in_balance`), `modelos`.

**Hechos medidos** (16 queries reales): top-5 clientes 2026 = 22,62% concentración; DPO real 70,5 días; 22,04 M€ remesas pendientes; 82.472 pagos tardíos (17,97 M€, retraso medio +6,1 d); excepciones 2026 = 65 (62 CRITICAL); crecimiento YoY 2026-08 = −2,0%.

**Excel ya soportado**: `leer_excel(xlsx_path, sheet_name, include_formulas, force_recalc, max_cells)` → celdas `{ref, f, v}`; recalc LibreOffice (0 errores/197 fórmulas en test real, incluidos SEQUENCE/FILTER) con fallback formualizer/cached-only; `check_excel_capabilities()`. Nunca modifica el original.

---

## 2. Diagnóstico — por qué la solución actual es "limitada"

| # | Limitación real | Consecuencia observada |
|---|---|---|
| L1 | `run_query` devuelve rows crudas, sin capa de análisis | el LLM adivina columnas y falla (`nombre_fiscal`, `canal_venta`, `fecha_pago` no existen) |
| L2 | Sin catálogo de esquema expuesto al LLM | cada consulta nueva = adivinanza + errores 1054 |
| L3 | Sin modelado de polimorfismo `efectos_pago` | queries sobre pagos/DPO necesitan joins manuales frágiles |
| L4 | Excel y BD son mundos separados | no hay tool de *reconciliación* Excel↔BD |
| L5 | `leer_excel` vuelca celdas; no agrega | no hace pivot/agrupación ni describe el shape |
| L6 | Sin cache, sin paginación/streaming en resultados grandes | queries de 100k filas inutilizables para el LLM |
| L7 | Auditoría no consultable | no hay tool para auditar al propio MCP |
| L8 | Excel lee pero no "entiende" el modelo de cálculo | no expone dependencias entre fórmulas ni predecesores |

---

## 3. Escenarios a cubrir (matriz completa)

### 3.1 Consulta / investigación
- S1. Interrogatorio "explica esta factura / este cuadre" → narrativa + cifras
- S2. Búsqueda por campo desconocido → resolver sinónimos automáticos (razon_social/nombre_comercial/nombre_fiscal)
- S3. Rango temporal arbitrario + consolidación mensual/trimestral/anual
- S4. Serie larga (5 años) → agregar por mes/persistir agregaciones
- S5. Cruce de dimensiones: cliente × banco × mes × estado
- S6. Sin datos en el rango → responder vacío distinto de error

### 3.2 Conciliación / cuadre
- S7. Cuadre factura vs líneas (ya existe) → generalizar a documento por tipo
- S8. Excel vs BD: el mismo importe salta en ambos → tool `reconciliar_excel_bd` ✓ (recibe rows ya obtenidas de ambos lados, cruza por key_col obligatorio)
- S9. Cifra del Excel con fórmula compleja (XLOOKUP/SUMIFS) → recalcular contra BD y mostrar diff
- S10. Descuadre base+IVA−retención vs total → detectar y clasificar (ya existe parcial)
- S11. Conciliar remesas por banco con % acreditado (existe) → matricular por mes

### 3.3 Riesgo / excepciones
- S12. Excepciones con materialidad (existe) → añadir tendencia temporal + cartera afectada
- S13. Pagos tardíos → evolución mensual DPO, no solo media
- S14. Efectos impagados antiguos (pre-2026 76% del pendiente) → reporte por antigüedad
- S15. Concentración de clientes (top-N %, HHI) → tool dedicada
- S16. Anomalías iva≠base×tipo → por tipo de IVA real (0,21/0,10/0,04/exento), no solo 21%

### 3.4 Excel (todos los formatos y patologías)
- S17. `.xlsx` con fórmulas dinámicas (LO resuelve) ✓ probado
- S18. `.xls` legacy → convertir con LO (hoy `_safety_checks` solo admite xlsx/xlsm)
- S19. `.xlsm` con macros → abrir sin ejecutar VBA
- S20. CSV/TSV/parquet → preprocesado simple
- S21. Workbook con sexenios: hoja por mes, consolidación dinámica
- S22. Archivo protegido/cerrado con contraseña → error claro "password required"
- S23. Muy grande (25–500 MB) → recalc parcial, streaming de hojas, límite por hoja
- S24. Celdas combinadas → detectar (ya se hace) y propagar valor al rango
- S25. Referencias externas a otro workbook → resolver o marcar "EXTERNAL"
- S26. Rangos con nombre / tablas de Excel → exponer como entidades
- S27. Fórmulas con LET/LAMBDA → LO sí, formualizer no; degradación explícita
- S28. Pivote / tablas dinámicas → LO las recalcula; formualizer no (warning)
- S29. #REF!/#DIV/0! → NO error global; reporte por celda con contexto
- S30. Fechas como número serial → formato ISO automático

### 3.5 Robustez / seguridad
- S31. Query con timeout (default 30 s) y kill de conexión
- S32. Consultas tipo `SELECT * FROM tabla ENTERA` si >1M filas → bloqueo con sugerencia de agregación
- S33. Engine crawl (páginas/s) por si CI o uso masivo
- S34. Auditoría consultable (`auditoria`, `data/audit.jsonl` expuesto como tool read-only) ✓
- S35. SQL con trailing `;` en medio / multi-statement → ya rechazado por driver
- S36. Inyección vía nombres de tabla → ya `_quote_id`
- S37. Estado del túnel consultable → tool `estado_tunel` (+ healthcheck) ✓
- S38. Config traceable: decir qué config está en uso sin revelar secretos

### 3.6 Análisis avanzado (deseado)
- S39. DSO/DPO/DFO mensual evolutivo (no solo media) ✓
- S40. Aging de efectos por bucket (0-30/30-60/60-90/+90) por banco y cliente ✓
- S41. Previsión de tesorería (remesas pendientes × fecha vencimiento)
- S42. Recurrentes: detectar facturas periódicas (mismo importe/cliente/mes)
- S43. Comparativas interanuales automáticas (delta YoY por mes)
- S44. Presupuesto vs real (si Excel trae presupuesto)
- S45. Conciliación bancaria completa (movimientos vs efectos acreditados) — requiere tabla movimientos (¿existe `movimientos_bancarios`?)

---

## 4. Arquitectura propuesta (evolución)

```
tools_core      → + describe_tablas_clave (catálogo real de columnas, caches de 1 h) ✓ implementado en tools_catalogo.py
                → + ejecutar_sql_seguro(sql) (L2/L3: resuelve sinónimos, político de agregación)
tools_meta      → + auditoria() ✓, estado_tunel() ✓ (tools_meta.py), config_visible()
tools_analisis  → + top_clientes, dso_dpo_evolutivo ✓ (tools_analisis.py), aging_efectos ✓ (tools_analisis.py), forecast_tesoro,
                   recurrentes, concentracion_hhi, comparativa_yoy, anomalias_iva_tipo
tools_excel     → + reconciliar_excel_bd(excel_rows, bd_rows, key_col, importe_col, fecha_col) ✓ (tools_excel.py)
                   + resumen_excel (shape: dims, tipos, nulos, agrupación sugerida) ✓ (tools_excel.py, probado contra .xlsx real)
                   + soporte .xls/.csv, password error, external refs, named ranges
infra           → + cache por query (hash SQL, TTL 5 min), paginación (limit/offset en run_query)
                → + timeout query, estimación de filas antes de materializar
```

### Política de capas
1. **Semántica**: `security.py` sigue siendo la barrera dura (S35/S36).
2. **Aislamiento**: todo nuevo tool es 100% SELECT; nada escribe en BD.
3. **No-destruccion Excel**: `leer_excel` nunca toca el original (invariante ya testeado).
4. **Grado de opacidad**: el LLM puede llamar `describe_tablas_clave` antes de SQL; no se permite que la semántica quede en el prompt.

---

## 5. Criterios de aceptación (medibles)

- AC1. 100% de los queries de la batería avanzada (L2/L3) responden sin error 1054 (resolver vía catálogo).
- AC2. `reconciliar_excel_bd` cuadra un Excel real de finanzas contra `back` con diff ≤ 0,01 € o reporta la línea concreta.
- AC3. `dso_dpo_evolutivo` devuelve serie mensual 2025–2026 con el mismo DPO real que la medida manual (70,5 d).
- AC4. `leer_excel` en `.xls`, CSV y workbook con password devuelve respuestas correctas o errores con causa exacta.
- AC5. Query de 500k+ filas: o se agrega o devuelve 413 con sugerencia; nunca crashea el server.
- AC6. Suite completa sigue verde (102 + tests nuevos).
- AC7. `estado_tunel`/`auditoria` responden read-only y no filtran secretos.

---

## 6. Fuera de alcance (v1 de mejora)
- Escritura BD (nunca; es read-only por diseño).
- Ejecución de VBA macros.
- Conectar a más BD (solo `back`).
- Interfaz web.

---

## 7. Riesgos conocidos
- **R1**: LO en Windows ausente → degrada; mitigado con formualizer + doc SETUP-WINDOWS (Paso 1.5).
- **R2**: `efectos_pago` polimórfico → el catálogo debe documentarlo y los tools encargarse del join.
- **R3**: cifras con abono/negativo (`facturas_venta` Q3 contiene negativos) → normalizar signos explícitamente.
- **R4**: los `run_query` directos sin catálogo reintroducen L1 → política AC1.
- **R5**: LibreOffice recalc sobre .xlsm exige convertir y escribe cache en temp → siempre en tmpdir.