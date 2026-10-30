# Plan de despliegue — MCP Optima BD remoto

Servicio Python con systemd en `optimaback-standby` (10.0.0.6), leyendo una
réplica local de `back` y publicándose por nginx + Cloudflare con API keys.
No es un site Laravel: Forge no gestiona el proceso, solo (opcionalmente) el vhost.

## 0. Decisiones que ya están tomadas

| Decisión | Valor | Motivo |
|---|---|---|
| Host | `optimaback-standby` | 47 GB RAM libres, no sirve tráfico, réplica local |
| Primario | `optimaback-active` 10.0.0.5 | fuente de verdad; **no se reinicia** |
| Transporte | `streamable-http` + `json_response` | compatible con CF/nginx |
| Auth | API key Bearer (SHA-256) | revocación inmediata sin tocar clientes |
| TLS | cert de origen CF `*.optimaonline.eu` | ya existe en el ecosistema |
| Excel | `contenido_b64` en la petición, procesado en memoria | el servidor no guarda ni lee ficheros |

## Estado verificado del standby (30-oct-2026)

Comprobado por SSH en `optimaback-standby`, sin modificar nada:

- MySQL 8.4.9 con la réplica de `10.0.0.5` **ya activa**: `Replica_IO_Running=Yes`,
  `Replica_SQL_Running=Yes`, `Seconds_Behind_Source=1`, `super_read_only=ON`.
- Disco: **122 GB libres** en `/`. El sembrado no hace falta.
- Python 3.12.3 con `venv` OK; nginx 1.31.1.
- **No** existen el usuario `mcp` ni `/var/lib/mcp-optima-bd`.
- Sigue el vhost viejo de `back.optimaonline.eu` apuntando a
  `/home/forge/back.optimaonline.eu` (retirar antes de D2).

Consecuencia: **D0 queda tachado**; los scripts de `deploy/replica/` se conservan
solo para reconstruir la réplica si se cae más allá de la retención del binlog.

**Hallazgo que bloquea D1**: `CREATE USER` falla en el standby con
`ERROR 1290 (HY000) ... --super-read-only` (probado). El usuario `back_readonly`
tiene que crearse **en el primario** y llega por replicación. En
`optimaback-active` el usuario `forge` no tiene acceso a MySQL
(`ERROR 1045`), así que ese paso requiere una sesión con `sudo mysql` allí.

## 1. Pre-flight (antes de tocar servidores)

```bash
# en el repo
git status --short          # sin cambios pendientes de commit
python -m pytest -q         # 305 tests verdes
git tag -a mcp-remote-v0.1 -m "MCP remoto: replica + API keys"
# push del tag solo con autorización explícita
```

- [ ] Los 305 tests pasan en local y en CI.
- [ ] `deploy/mcp.env.example` revisado; ningún secreto en el repo.
- [x] Réplica del standby verificada (lag 1 s, `super_read_only=ON`, 122 GB libres).
- [ ] `back_readonly` creado **en el primario** con `sudo mysql` (la réplica lo
      rechaza con 1290) y confirmado luego en el standby.
- [ ] Snapshot de usuarios MySQL del primario: `SELECT user,host FROM mysql.user;`
      (para poder revertir con precisión).

## 2. Cómo llega el código al servidor

**Opción A — Git (recomendada).** Nada de rsync: el servidor tiene un checkout
propio y se actualiza con `git fetch && git checkout <tag>`.

```bash
sudo -u mcp git clone <repo> /opt/mcp-optima-bd
sudo -u mcp git -C /opt/mcp-optima-bd checkout <tag>
sudo -u mcp /opt/mcp-optima-bd/.venv/bin/pip install -e /opt/mcp-optima-bd
sudo systemctl restart mcp-optima-bd
```

**Opción B — CI/CD automático** (como nora-think, pero sin Docker): workflow que
en tag hace SSH y ejecuta el bloque anterior. Solo para código; **nunca** para
cambios de réplica o de esquema.

```yaml
# .github/workflows/deploy-mcp.yml (esbozo)
on:
  push:
    tags: ["mcp-remote-*"]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ssh -o BatchMode=yes forge@167.233.70.237 '
            set -e
            cd /opt/mcp-optima-bd && git fetch --tags && git checkout '"$GITHUB_REF_NAME"' &&
            .venv/bin/pip install -e . &&
            sudo systemctl restart mcp-optima-bd'
```

Nota: `sudo systemctl restart` requiere una regla de sudoers acotada a esa unidad.

## 3. Fases, en este orden

### D0 — Réplica ~~(ver `deploy/README.md` §1)~~ — YA HECHA

La réplica de `optimaback-standby` está sana y al día (ver arriba). **No ejecutar
el sembrado**: solo aplica si hubiera que reconstruirla desde cero.

```bash
mysql < deploy/replica/01-usuario-replicacion.sql            # primario
sudo ufw allow from 10.0.0.6 to any port 3306 proto tcp       # primario
SRC_HOST=10.0.0.5 SRC_USER=repl_mcp bash deploy/replica/02-sembrar-replica.sh
mysql < deploy/replica/03-iniciar-replicacion.sql             # standby
bash deploy/replica/04-estado-replica.sh                      # exit 0
```

**Criterio de aborto**: si el load del primario sube de forma sostenida o el
sembrado no termina en la ventana, `STOP REPLICA; DROP DATABASE back;` en el
standby y se reintenta otro día. El primario solo cambia en usuarios.

### D1 — Servicio en loopback (sin nginx)

Seguir `deploy/README.md` §2, con `MCP_HTTP_HOST=127.0.0.1`.

```bash
curl -s localhost:8443/healthz | jq .
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8443/mcp   # 401
```

### D2 — nginx + DNS + Cloudflare

```bash
sudo nginx -t && sudo systemctl reload nginx
dig +short mcp-back.optimaonline.eu          # IP de Cloudflare
curl -s https://mcp-back.optimaonline.eu/healthz | jq .
```

**Criterio de aborto**: si el TLS falla, el servicio sigue útil por loopback;
no se publica hasta que `/healthz` responda por HTTPS.

### D3 — Claves y clientes

Una clave por consumidor (`--name` distinto). Migrar de uno en uno, verificando
`tools/list` con cada cliente antes de retirar el MCP local por stdio.

### D4 — Cutover

- Retirar el túnel de los clientes migrados.
- Dejar el MCP local solo para desarrollo (Excel ya funciona en remoto vía base64).
- Vigilar 7 días: 401 anómalos, lag, p95.

## 4. Verificación por fase

| Fase | Comprobación | Éxito |
|---|---|---|
| D0 | `04-estado-replica.sh` | IO/SQL Yes, lag 0, exit 0 |
| D0 | `INSERT` en réplica | error 1290 (super_read_only) |
| D1 | `/healthz` local | 200, `replica.ok=true` |
| D1 | `/mcp` sin key | 401 con `WWW-Authenticate` |
| D2 | `ss -tulnp \| grep 8443` | solo 127.0.0.1 |
| D2 | `nc -zv <host> 8443` desde fuera | timeout |
| D2 | Host ajeno a `/mcp` | 421 |
| D3 | tools/list con key | 37 tools, sin `setup_ssh` |
| D3 | key revocada | 401 inmediato |
| D4 | `SELECT` de 3 tablas vs primario | mismos conteos |

## 5. Rollback

| Fase | Reversión | Efecto |
|---|---|---|
| D0 | `STOP REPLICA; DROP DATABASE back;` + `DROP USER repl_mcp@10.0.0.6` | vuelve al estado actual |
| D1 | `systemctl stop mcp-optima-bd` | clientes siguen en stdio |
| D2 | deshabilitar el vhost + DNS | servicio deja de ser público |
| D3 | `auth revoke --id <id>` | acceso cortado al instante |
| D4 | reactivar stdio en clientes | vuelve al túnel |

## 6. Riesgos del despliegue

- **Sembrado**: no aplica en este despliegue (la réplica ya está activa). Si
  hubiera que rehacerla, es el único paso con impacto en el primario (lectura):
  medir con `pv -l` y parar si el load sube de forma sostenida.
- **Binlog retenido 30 días**: una réplica caída más de ese plazo exige re-sembrar.
- **Disco del standby**: 122 GB libres (63 % usado); sin margen para dos
  re-sembrados completos seguidos.
- **Failover**: si el standby asciende a primario, el router debe apuntar a
  Active; hoy lo detecta por `read_only=0` + `SHOW REPLICA STATUS` vacío.
- **App vieja en el standby**: existe un vhost `back.optimaonline.eu` con
  código antiguo y el `.env` de producción. Retirarlo antes de D2.

## 7. Checklist final

- [ ] Réplica sana y `super_read_only=ON`.
- [ ] `back_readonly` solo con SELECT y solo desde 127.0.0.1.
- [ ] Servicio con `MemoryMax=512M`, usuario `mcp`, sin privilegios.
- [ ] Excel verificado en remoto con un `.xlsx` real (respuesta llega y disco intacto: `ls /var/lib/mcp-optima-bd`).
- [ ] nginx solo IPs de Cloudflare; `/healthz` sin auth; 421 verificado.
- [ ] Una clave por consumidor, con caducidad ≤90 días.
- [ ] Alerta de lag cada 5 min (`04-estado-replica.sh`).
- [ ] Runbook de rotación probado una vez.
