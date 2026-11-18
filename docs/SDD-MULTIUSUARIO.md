# SDD — MCP multiusuario: seguridad y ciclo de vida de conexiones

| Campo | Valor |
|---|---|
| Fecha | 2026-11-17 |
| Autor | Buffy (Codebuff) con perfil `security-reviewer` de ECC |
| Estado | **Fase 1 y 2 implementadas y verificadas en local**. Sin desplegar. |
| Alcance | `src/mcp_bd_readonly/`, `deploy/`, documentación |
| Verificación | `461 passed` (435 previos + 26 nuevos) con Python 3.11 en venv limpio |

Este documento es el contrato de la funcionalidad y el punto de reanudación: si otra
sesión de agente retoma el trabajo, **debe leer primero las secciones 7 (estado real),
8 (pendientes) y 10 (handoff)**.

---

## 1. Contexto y problema

El MCP se desplegó con `MYSQL_POOL_SIZE=4`. El pool **reutiliza y nunca expira** las
conexiones (`ConnectionPool.release()` las devuelve a una cola LIFO), así que el
servicio mantiene 4 sesiones MySQL abiertas de forma permanente — 8 si hay réplica,
porque `build_router()` crea **dos** `QueryExecutor` (primario y réplica), cada uno con
su pool.

Consecuencia reportada en producción: un compañero se quedó **sin poder conectar**
(error de cupo de 4 conexiones) mientras el MCP no estaba consultando nada. Encaja con
`ERROR 1203 (HY000): User ... already has more than 'max_user_connections'` cuando el
usuario MySQL compartido (`direccion`, máx. 3) queda monopolizado por sesiones ociosas
del MCP.

Hallazgos adicionales de la revisión (evidencia en código):

1. `_configure()` (`SET SESSION max_execution_time`) solo se ejecutaba en la ruta
   **sin** pool, porque el pool se construía con `_open` y no con `_connect`. En HTTP
   ninguna conexión pooled tenía timeout de servidor: una SELECT lenta se quedaba
   ocupando el slot hasta el `read_timeout` de 20 s.
2. `run_script` ejecuta `exec()` del código que manda el cliente. Los builtins
   recortados **no son un sandbox**: `().__class__.__bases__[0].__subclasses__()`
   llega al grafo de objetos y de ahí a `os`. En HTTP eso es ejecución de código con
   una clave de solo lectura.
3. El 401 se devolvía **antes** del rate limit: intentos inválidos no gastaban
   presupuesto ni dejaban rastro en logs (lookup SQLite + sha256 por petición).
4. `MAX_ROWS=50_000` filas materializadas en memoria contra `MemoryMax=512M` del unit:
   una consulta ancha puede provocar OOM y reinicio del servicio para todos.
5. Excel: `b64decode(..., validate=False)` sin tope previo y 400 MB de expansión
   descomprimida (bomba zip) con el mismo límite de 512 MB.

## 2. Objetivos

- **RF-1** Que ninguna sesión del MCP quede retenida por inactividad.
- **RF-2** Que el consumo de conexiones sea justo entre personas: cupo por API key y
  tope global de sesiones vivas por proceso.
- **RF-3** Que `run_script` no esté disponible en HTTP salvo activación explícita.
- **RF-4** Que los fallos de autenticación estén limitados por IP y registrados.
- **RF-5** Topes de memoria explícitos y configurables (`MYSQL_MAX_ROWS`, base64).
- **RF-6** Que un fallo de cupo produzca un mensaje accionable, no un error crudo.

**No objetivos** (decididos en §5): pool dedicado por persona, usuario MySQL por
persona, límite compartido entre workers, sandbox de proceso para `run_script`.

## 3. Requisitos y trazabilidad

| Requisito | Implementación | Test |
|---|---|---|
| RF-1 TTL de inactividad | `ConnectionPool.sweep()` + barrido en hilo daemon + descarte en `_take()` | `test_pool_cierra_conexiones_ociosas`, `test_pool_no_entrega_conexion_caducada_aunque_no_haya_barrido` |
| RF-1/2 Tope duro global | `ConnectionPool._reserve()` con desalojo de la ociosa más vieja | `test_pool_tope_global_sigue_siendo_duro`, `test_pool_desaloja_la_ociosa_mas_vieja_al_llegar_al_tope` |
| RF-2 Cupo por API key | `per_key` + `_pool_key()` (contextvar `get_api_key()`) | `test_cupo_por_api_key_no_bloquea_a_las_demas`, `test_pool_no_comparte_la_conexion_entre_claves` |
| RF-3 `run_script` fail-closed | `server.build_mcp()` + `Config.enable_run_script` tri-estado | `test_run_script_no_se_registra_en_http_por_defecto`, `test_run_script_se_reactiva_explicitamente_en_http`, `test_run_script_desactivado_tambien_en_stdio` |
| RF-4 Fallos de auth | `ApiKeyMiddleware._fail_budget_ok()` + `_note_fail()`; ventana por **peer + keyid** | `test_fallos_de_auth_se_cortan_por_cliente`, `test_fallo_de_auth_queda_registrado_sin_filtrar_el_secreto`, `test_una_clave_valida_no_gasta_el_presupuesto_de_fallos`, `test_los_fallos_de_una_clave_no_bloquean_a_las_demas` |
| RF-5a Tope de filas | `QueryExecutor.max_rows` + `_acotar(..., max_rows)` | `test_max_rows_es_configurable` |
| RF-5b Excel | `b64decode(validate=True)` + tope previo + `MAX_UNZIP_MB=150` | `test_contenido_b64_gigante_se_rechaza_antes_de_decodificar`, `test_contenido_b64_invalido_se_rechaza`, `test_contenido_b64_con_saltos_de_linea_se_acepta` |
| RF-6 Mensaje accionable | `PoolExhausted` distingue cupo por clave de saturación global | `test_cupo_por_api_key_no_bloquea_a_las_demas` |
| Bordes del ciclo de vida | `close_all` con conexiones en uso, barrido por el hilo daemon, `stats()` tras desalojo, slots devueltos si la factory falla, conexión muerta en ocioso | `test_close_all_respeta_las_conexiones_en_uso`, `test_el_hilo_de_barrido_cierra_lo_ocioso_sin_llamar_a_sweep`, `test_stats_coherentes_tras_desalojo`, `test_fallos_de_factory_no_inflan_los_huecos`, `test_conexion_muerta_en_ocioso_no_consume_el_cupo_de_la_clave` |
| Configuración | `load_config`/`write_config` para las 7 variables nuevas | `test_enable_run_script_es_tri_estado`, `test_pool_multiusuario_se_lee_del_entorno`, `test_write_config_escribe_las_variables_nuevas` |
| A3 timeout de servidor | pool construido con `self._connect` (aplica `_configure`) | cubierto por los 17 tests existentes de `test_db.py` y `test_pool.py` |

## 4. Diseño

### 4.1 Pool como caché con TTL y cupo (no como propietario de sesiones)

```
                 acquire(key)                          release(conn, key)
  ┌────────────┐ ───────────▶ idle[key] (LIFO) ─────────────┐
  │ _reserve   │ ◀── vacío ──┐                               │
  │ vivo < max │             │ sólo si ping() OK y           │
  └─────┬──────┘             │ queda cupo de esa clave       │
        │ no hay hueco       └───────────────────────────────┘
        ▼
  desaloja la ociosa más vieja (LRU) ─▶ cierra ─▶ abre nueva
        │ sigue sin hueco
        ▼
  espera hasta pool_wait_s ─▶ PoolExhausted accionable
```

Invariantes:

- `vivas = en_uso + ociosas ≤ pool_max`. Nunca se abre una conexión más.
- Una conexión ociosa de una clave **no** se entrega a otra clave (cupo y auditoría).
- Con `pool_idle_s=0` y `pool_max_per_key=0` el pool replica el comportamiento clásico
  (reutiliza, no expira); así el modo stdio no cambia.
- `pool_size` (clásico) y `pool_max` (multiusuario) son excluyentes en la práctica:
  si ambos están, manda `pool_max`.
- El barrido corre en un hilo daemon (`mcp-pool-sweeper`, intervalo
  `max(1, min(5, idle_s/2))`: una ociosa vive `idle_s` + ≤5 s) y además `_take()`
  descarta caducadas aunque el barrido no haya llegado: nunca se entrega una conexión
  fuera de TTL.
- Toda conexión descartada (por TTL o por `ping` fallido al sacarla de la ociosa)
  descuenta a la vez `vivas` y `en_uso` de su clave: `stats()` nunca muestra
  `vivas=0` con `en_uso>0` y un descarte no puede gastar el cupo de nadie.

### 4.2 Variables

| Variable | Default | Recomendado en HTTP | Efecto |
|---|---|---|---|
| `MYSQL_POOL_SIZE` | `0` | `0` | Pool clásico de tamaño fijo (sin TTL) |
| `MYSQL_POOL_MAX` | `0` | `4` | Tope de sesiones vivas **por ejecutor** (×2 con réplica) |
| `MYSQL_POOL_IDLE_S` | `0` | `60` | Cierre por inactividad (0 = nunca) |
| `MYSQL_POOL_MAX_PER_KEY` | `0` | `2` | Cupo por API key |
| `MYSQL_POOL_WAIT_S` | `10` | `10` | Espera máxima por hueco |
| `MYSQL_MAX_ROWS` | `50000` | `10000` | Tope de filas materializadas |
| `MCP_ENABLE_RUN_SCRIPT` | *(sin definir)* | `0` | Sin definir: ON en stdio, **OFF en HTTP** |
| `MCP_AUTH_FAIL_PER_MIN` | `30` | `30` | Fallos de auth por IP y minuto antes de 429 |

Presupuesto de conexiones con los valores recomendados y réplica configurada
(`build_router()` crea **dos** ejecutores, primario y réplica, cada uno con su pool):
**2 × 4 = 8 sesiones máximas, 0 en reposo** (~60 s de inactividad, +≤5 s de barrido). Reparto: 2 por
persona y ejecutor, 4 personas simultáneas sin cola; la quinta espera como mucho 10 s y
recibe un mensaje claro. Sin réplica el presupuesto baja a 4.

### 4.3 Capas de seguridad (defensa en profundidad)

| Capa | Estado |
|---|---|
| Parser solo-lectura (primera palabra + verbos vetados + comentarios `/*!`) | ya existía |
| Driver sin `MULTI_STATEMENTS` | ya existía |
| `GRANT SELECT` sobre `back.*` | ya existía; **falta** `REPLICATION CLIENT` (§8) |
| API keys SHA-256 + `compare_digest` + scopes + TTL + revocación | ya existía |
| Rate limit por clave | ya existía |
| **Rate limit de fallos de auth por cliente (peer + keyid) + log** | **nuevo (RF-4)** |
| **`run_script` fail-closed en HTTP** | **nuevo (RF-3)** |
| **TTL/cupo de conexiones** | **nuevo (RF-1/2)** |
| **Timeout de servidor en conexiones pooled** | **corregido (A3)** |
| **Topes de memoria (filas, base64, descompresión)** | **nuevos (RF-5)** |
| TLS, HSTS, allowlist Cloudflare en nginx | ya existía |
| Endurecimiento systemd | ya existía |

## 5. Decisiones y alternativas descartadas

1. **«Una conexión persistente por usuario» — descartada tal cual.** El transporte HTTP
   es `stateless_http=True`: no hay sesión a la que atar la conexión, así que «por
   usuario» solo puede ser «por clave y por proceso», y con N workers serían N×usuarios
   conexiones. Además la ganancia de latencia en loopback sin TLS es de milisegundos
   frente a queries de cientos de ms. Se sustituye por caché con TTL y cupo, que da la
   misma comodidad sin apropiarse del cupo ajeno.
2. **Subir el pool a 12.** Rechazada: reparte el dolor un poco más tarde y retiene más
   sesiones; no resuelve la falta de cupo por persona.
3. **Un usuario MySQL por persona.** Viable pero costoso (alta, rotación, `GRANT` y
   cuota por cuenta) y MySQL limita por cuenta, no por conexión. Se deja como opción de
   hardening si un día hace falta aislamiento por persona a nivel de BD.
4. **Rate limit compartido (Redis/SQLite) entre workers.** Aplazado: hoy hay un solo
   worker; el límite en memoria es exacto con N=1. Ver §8.
5. **Sandbox de proceso para `run_script`.** Aplazado: primero se cierra la puerta
   (no registrar en HTTP). Si se quiere reactivar, la vía es subproceso con
   `resource.setrlimit` + sin red, no builtins recortados.

## 6. Archivos tocados

| Archivo | Cambio |
|---|---|
| `src/mcp_bd_readonly/db.py` | Pool con TTL, cupo por clave, LRU, `stats()`, `max_rows`, `_configure` en pooled |
| `src/mcp_bd_readonly/config.py` | 7 campos nuevos, `as_tri_bool`, `write_config` ampliado |
| `src/mcp_bd_readonly/http_app.py` | Presupuesto de fallos de auth por IP + log a stderr |
| `src/mcp_bd_readonly/server.py` | `run_script` fail-closed en HTTP, `auth_fail_per_min` |
| `src/mcp_bd_readonly/tools_excel.py` | `validate=True`, tope antes de decodificar, `MAX_UNZIP_MB` |
| `tests/test_multiusuario.py` | **nuevo**, 26 tests |
| `deploy/mcp.env.example` | Variables nuevas y valores recomendados |
| `deploy/crear-back_readonly.sh` | `REPLICATION CLIENT` + `MAX_USER_CONNECTIONS` |
| `README.md` | Sección de multiusuario y capas de seguridad |
| `docs/SDD-MULTIUSUARIO.md` | **este documento** |

## 7. Estado real (verificado)

```
$ /tmp/mcptest/bin/python -m pytest -q
461 passed, 1 warning in 5.59s
```

- Venv del repo **roto** (`.venv/bin/python3.14 -> /opt/homebrew/opt/python@3.14`, ya no
  existe; el host tiene 3.11 y 3.15). Para pruebas se usó un venv limpio en `/tmp/mcptest`
  con Python 3.11 y `pip install -e ".[dev]"`.
- **No** se ha ejecutado nada contra la base de datos real ni contra el servidor: los
  tests son unitarios con dobles (`FakeConn`). Sin verificación de integración.

## 8. Pendientes (ordenados por riesgo)

| # | Tarea | Criterio de aceptación |
|---|---|---|
| P1 | **Desplegar** las variables del §4.2 en `/etc/mcp-optima-bd/mcp.env` y reiniciar | `PROCESSLIST` sin sesiones del MCP a los ~65 s de inactividad |
| P2 | `GRANT REPLICATION CLIENT` a `back_readonly` (script ya actualizado) | `estado` del router dice `destino: replica` |
| P3 | Usar `back_readonly` en el servicio (dejar de compartir `direccion`) | El humano puede conectar mientras el MCP consulta |
| P4 | `limit_req` en nginx para `/mcp` + fail2ban sobre 401 | 200 peticiones inválidas/min desde una IP → 429 y baneo |
| P5 | Tool `estado_cupos` (autenticada) con `pool_stats()` + estado de réplica | Devuelve `vivas/en_uso/ociosas/por_clave` sin datos de negocio |
| P6 | Scope `script` para reactivar `run_script` con garantías | Una clave `read` recibe error de permiso; una con `script` ejecuta |
| P7 | `MCP_HTTP_WORKERS` + rate limit compartido en la SQLite de claves | 2 workers sin multiplicar el límite por 2 |
| P8 | Medir `connect_ms` antes/después del TTL | Solo mantener `pool_idle_s` distinto de 0 si el dato lo justifica |

## 9. Despliegue (no ejecutado)

```bash
# 1. variables (ver §4.2)
sudoedit /etc/mcp-optima-bd/mcp.env
#   MYSQL_POOL_SIZE=0
#   MYSQL_POOL_MAX=4          # por ejecutor; ×2 con réplica = 8 sesiones
#   MYSQL_POOL_IDLE_S=60
#   MYSQL_POOL_MAX_PER_KEY=2
#   MYSQL_MAX_ROWS=10000
#   MCP_AUTH_FAIL_PER_MIN=30

# 2. usuario de BD (en el PRIMARIO; replica por binlog)
bash deploy/crear-back_readonly.sh   # ahora incluye REPLICATION CLIENT + cuota 40

# 3. servicio
sudo systemctl restart mcp-optima-bd
sudo journalctl -u mcp-optima-bd -n 50 --no-pager

# 4. comprobación
curl -s https://mcp-back.optimaonline.eu/healthz          # {"status":"ok"}
sudo mysql -e "SELECT user,host,COUNT(*) FROM information_schema.PROCESSLIST GROUP BY user,host;"
```

**Rollback:** volver a `MYSQL_POOL_SIZE=4` (y `MYSQL_POOL_MAX=0`) + `systemctl restart`.
El código nuevo es compatible con la configuración antigua: sin `pool_max` ni
`pool_idle_s` el pool se comporta como antes.

**Aviso operativo:** con `MCP_ENABLE_RUN_SCRIPT` sin definir, `run_script` desaparece en
HTTP. Cualquier cliente que lo use recibirá `Unknown tool` — es intencionado.

## 10. Handoff para el siguiente agente

**Qué está hecho y verificado:** §3 completo, 461 tests verdes, sin desplegar.

**Qué NO tocar sin leer esto:**
- `tests/test_db.py` parchea `QueryExecutor._conn` con lambdas sin argumentos. Por eso
  la clave del pool se lee de `_pool_key()` (contextvar) y **no** se pasa como parámetro
  a `_conn`/`_release`. Cambiar esa firma rompe 17 tests legítimamente.
- Los conteos de tools en `tests/test_perfiles.py` (41) son exactos. Añadir una tool
  obliga a actualizarlos **y** a clasificarla en `perfiles.py` (`test_perfiles_cubren_todas_las_tools`).
- `ConnectionPool.release()` debe seguir haciendo `ping(reconnect=False)`: es lo que
  descarta conexiones muertas por `wait_timeout` (test existente).

**Cómo verificar rápido:**
```bash
/opt/homebrew/bin/python3.11 -m venv /tmp/mcptest
/tmp/mcptest/bin/pip install -q -e ".[dev]"
/tmp/mcptest/bin/python -m pytest -q          # 461 passed
/tmp/mcptest/bin/python -m pytest tests/test_multiusuario.py -q
```

**Siguiente tarea recomendada:** P1+P2+P3 (despliegue y grants) — es lo que desbloquea a
las personas; el código ya está listo. Después P5 (`estado_cupos`), que convierte el
diagnóstico en una tool en vez de un `journalctl`.

**Trampas conocidas:**
- `/healthz` es público y no debe filtrar topología (hay test).
- El orden del middleware importa: presupuesto de fallos **antes** de `store.verify`.
- La ventana de fallos de auth va por **(peer, keyid)**, no por IP sola: tras
  nginx/túnel el peer es siempre 127.0.0.1 y una ventana por IP convertía el freno en
  un 429 para todos los usuarios a la primera clave caducada.
- `_configure()` debe seguir llamándose en la factory del pool; si alguien vuelve a
  pasar `self._open`, el timeout de servidor desaparece en silencio.
- El venv del repo está roto por la actualización de Homebrew a Python 3.15.

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| El TTL de 60 s provoca reconexiones frecuentes en uso intenso | Son ~1-3 ms en loopback; si la medición (P8) dice otra cosa, subir `MYSQL_POOL_IDLE_S` |
| `pool_max=4` por ejecutor se queda corto con muchas personas | Es configurable y el error es accionable; subir junto con la cuota de `back_readonly` (el total real es 2× con réplica) |
| Clientes que usaban `run_script` rompen tras el despliegue | Documentado; reactivar con `MCP_ENABLE_RUN_SCRIPT=1` de forma consciente |
| `MAX_ROWS=10000` puede truncar informes grandes | El límite es explícito y el mensaje pide agregar/filtrar; ajustar por entorno |
| El límite de fallos por IP puede afectar a usuarios tras NAT corporativo | Es por ventana de 60 s y 30 fallos; subir `MCP_AUTH_FAIL_PER_MIN` si aparece |
