# Despliegue remoto del MCP (réplica + API keys)

Objetivo: el MCP lee de la **réplica** de `back` en `optimaback-standby`
(10.0.0.6) y nunca toca producción para consultar. `optimaback-active`
(10.0.0.5) solo alimenta la réplica por binlog.

```
Cliente ──HTTPS──▶ Cloudflare ──▶ nginx (standby) ──▶ uvicorn 127.0.0.1:8443
                                                          │
                                                          ├─▶ MySQL réplica (loopback)
                                                          └─▶ MySQL primario (fallback, solo si lag>umbral)
```

## 0. Prerrequisitos ya verificados

- MySQL 8.4.9 en ambos; `log_bin=1`, `gtid_mode=ON`, `binlog_format=ROW` en el primario.
- `back` = 55.4 GB, 394 tablas. Disco libre en standby: 122 GB.
- 3306 no responde desde internet en ninguno de los dos.
- **No existe réplica todavía**: ni esquema ni canal. El script anterior
  (`replica_nocturna.sh`) falló y se desactivó; no se reutiliza.

## 1. Réplica (en el standby)

> **En `optimaback-standby` esta sección ya está cumplida**: la réplica existe y
> está sana (lag 1 s). Salta a §2. Los pasos de abajo son para reconstruirla
> desde cero.

```bash
# 1.1 usuario de replicación (en el PRIMARIO, como root)
mysql < deploy/replica/01-usuario-replicacion.sql

# 1.2 abrir el firewall PRIVADO del primario solo para el standby
#     (verificar el estado actual antes de tocar nada)
sudo ufw allow from 10.0.0.6 to any port 3306 proto tcp

# 1.3 sembrado (en el standby, pide el password de repl_mcp)
SRC_HOST=10.0.0.5 SRC_USER=repl_mcp bash deploy/replica/02-sembrar-replica.sh

# 1.4 arrancar la replicación (en el standby)
mysql < deploy/replica/03-iniciar-replicacion.sql

# 1.5 verificar
bash deploy/replica/04-estado-replica.sh   # exit 0 = sana
```

Aceptación:

```sql
SHOW REPLICA STATUS;                    -- IO=Yes, SQL=Yes, lag 0
SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='back';  -- 394
INSERT INTO back.facturas_venta (id) VALUES (0);  -- ERROR 1290: super_read_only
```

Usuario de lectura del MCP: hoy el servicio usa **`direccion`** (el de Maruan,
9-oct-2026): `SELECT`/`SHOW VIEW` en `back` y `oo`, **máx. 3 conexiones y 5 min
por consulta** → `MYSQL_POOL_SIZE=2`.

Endurecimiento opcional (`back_readonly`, cuenta propia del servicio). **Se crea en
el PRIMARIO**, no en la réplica: con `super_read_only` el `CREATE USER` local
falla con `ERROR 1290` (probado el 30-oct-2026). Llega al standby por replicación
y allí solo se verifica. Lo hace todo `deploy/crear-back_readonly.sh`.

```bash
# en el PRIMARIO (pide la contraseña de sudo)
ssh -t optimaback-active 'bash ~/crear-back_readonly.sh'

# y en el STANDBY, comprobar que replicó y que solo lee
SELECT user, host FROM mysql.user WHERE user = 'back_readonly';
SHOW GRANTS FOR 'back_readonly'@'127.0.0.1';   -- solo SELECT ON back.*
```

Sin `REQUIRE SSL`: el cliente (`pymysql`) no negocia TLS y la conexión es de
loopback, en el mismo host. Con SSL obligatorio el servicio no podría autenticarse.

Ya hay un secreto generado y guardado en el standby (`/home/forge/.mcp-back_readonly.pass`,
modo 0600); se puede reutilizar en el primario en vez de generar otro.

### 1.5 Cómo se conecta el MCP (por qué en el servidor no hay túnel)

El MCP vive **en el mismo host que MySQL**, así que habla con `127.0.0.1:3306`
y punto: no hay túnel, ni SSH, ni puerto que abrir (`TUNNEL_ENABLED=false`).

```
[ MCP (systemd) ] --TCP 127.0.0.1:3306--> [ mysqld réplica ]     mismo host, sin túnel
```

El túnel es solo para **tu portátil**, porque MySQL no está publicado:

```bash
ssh -L 3306:127.0.0.1:3306 forge@167.233.70.237   # abre el puerto en TU máquina
mysql -h 127.0.0.1 -P 3306 -u direccion -p         # aquí sí: el tráfico va cifrado por SSH
```

Si algún día el MCP se mueve a otro host:

| Escenario | Cómo se conecta |
|---|---|
| Otro host de la red privada (`10.0.0.x`) | MySQL escucha además en su IP privada + `GRANT` para ese host + firewall cerrado a todo lo demás |
| Fuera de esa red | Túnel SSH o VPN; **nunca** abrir 3306 a internet |

Nota: el `.env` del MCP (`/home/forge/mcp-optima-bd/.env`) es independiente del
`.env` de la plataforma (`back.optimaonline.eu`), que no se toca.

## 2. Servicio (en el standby)

```bash
sudo useradd --system --home /opt/mcp-optima-bd --shell /usr/sbin/nologin mcp
sudo mkdir -p /opt/mcp-optima-bd /etc/mcp-optima-bd /var/lib/mcp-optima-bd
sudo chown -R mcp:mcp /opt/mcp-optima-bd /var/lib/mcp-optima-bd
sudo chmod 750 /etc/mcp-optima-bd

# código + venv (git clone al directorio del servicio)
sudo -u mcp python3 -m venv /opt/mcp-optima-bd/.venv
sudo -u mcp /opt/mcp-optima-bd/.venv/bin/pip install -e /opt/mcp-optima-bd

# entorno: 0600, root:mcp
sudo install -m 600 -o root -g mcp deploy/mcp.env.example /etc/mcp-optima-bd/mcp.env
sudoedit /etc/mcp-optima-bd/mcp.env

sudo install -m 644 deploy/systemd/mcp-optima-bd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-optima-bd

# API key (se muestra una sola vez)
sudo -u mcp /opt/mcp-optima-bd/.venv/bin/python -m mcp_bd_readonly.auth \
     --db /var/lib/mcp-optima-bd/api_keys.db create --name finanzas --ttl-days 90
```

### 2.1 Actualizar el servicio (ya instalado)

El checkout del servicio está en `/opt/mcp-optima-bd` y pertenece a `mcp`:

```bash
sudo -u mcp git -C /opt/mcp-optima-bd fetch --tags
sudo -u mcp git -C /opt/mcp-optima-bd checkout <tag>
sudo -u mcp /opt/mcp-optima-bd/.venv/bin/pip install -q -e /opt/mcp-optima-bd
sudo systemctl restart mcp-optima-bd
curl -s http://127.0.0.1:8443/healthz
```

El `.env` de producción vive en `/etc/mcp-optima-bd/mcp.env` (0640 root:mcp) y
**no** se toca al actualizar el código.

## 3. nginx + Cloudflare

### Estado: ya instalado en `optimaback-standby` (recipe de Forge)

El vhost y el `geo` están instalados desde el 2026-10-30 por la recipe
`install-mcp-back-nginx` (org `optima-retail-sl`, id **172549**), que corre
**como root** en el servidor. Ejecución verificada: run `576069`.

Para re-ejecutarla (es idempotente: hace backup en `/root/mcp-back-nginx-backup`
y revierte si `nginx -t` falla):

```bash
TOKEN=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.laravel-forge/config.json')))['token'])")
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
     -H 'Content-Type: application/json' -d '{"servers":[1216161]}' \
     https://forge.laravel.com/api/orgs/optima-retail-sl/recipes/172549/runs
# el log de la ejecución:
curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
     https://forge.laravel.com/api/orgs/optima-retail-sl/recipes/172549/runs | head -c 800
```

`forge command` **no** sirve para esto: el CLI de Forge ejecuta como el usuario
del site (`forge`), y `/etc/nginx` es `root:root`; el CLI no tiene ningún comando
que escriba vhosts. La vía root es la recipe (o tu `sudo`).

### Alternativa con sudo

Equivalente, por si prefieres no depender de la recipe:

```bash
scp deploy/instalar-nginx.sh deploy/nginx/mcp-back.optimaonline.eu.conf optimaback-standby:~
ssh -t optimaback-standby 'sudo bash ~/instalar-nginx.sh'
```

El instalador escribe **dos** ficheros y los quita juntos si algo falla:

| Fichero | Para qué |
|---|---|
| `/etc/nginx/sites-available/mcp-back.optimaonline.eu.conf` | vhost (proxy a `127.0.0.1:8443`) |
| `/etc/nginx/conf.d/mcp-cloudflare-geo.conf` | `geo` con los rangos de Cloudflare |

Si `nginx -t` falla, borra ambos enlaces y **no recarga** nada: nginx sigue con la
configuración anterior.

### Por qué hay un fichero `geo` y no `allow`/`deny`

El servidor ya aplica `real_ip` de Cloudflare (`/etc/nginx/conf.d/cloudflare.conf`,
22 rangos), así que `$remote_addr` es la IP del **visitante**, no la del proxy.
Un `allow <rangos de Cloudflare>` evaluado contra `$remote_addr` no coincidiría
nunca: la petición llegaría con la IP del cliente y el vhost devolvería 403 a
todo el mundo. Por eso el control va sobre el peer original
(`$realip_remote_addr`) mediante `geo`, y el vhost corta con
`if ($mcp_from_cloudflare = 0) { return 403; }`.

Los rangos **no** se descargan de internet: se derivan de los `set_real_ip_from`
que Forge ya mantiene, y solo si no hubiera ninguno se descargan. Sin rangos
válidos el instalador aborta (fail-closed).

No hace falta emitir certificado: se reutiliza el de origen de Cloudflare que ya
sirve la plataforma (`/etc/nginx/ssl/back.optimaonline.eu/3521089/`,
SAN `*.optimaonline.eu`).

DNS: `mcp-back.optimaonline.eu` proxied (naranja) en Cloudflare, SSL = Full (strict).
**Fijar el nombre antes de crear el site**: renombrar en Forge no actualiza el
nginx raíz.

### Verificación (en el servidor, ya instalado)

- `nginx -t`: `syntax is ok` / `test is successful`; reload aplicado sin cortar
  el servicio.
- `/healthz` → **200**; `HTTP:80` → **301** a HTTPS.
- `POST /mcp` sin clave → **401**.
- `initialize` con clave real → **200** (`serverInfo.mcp-optima-bd` v1.30.0).
- `tools/list` → **37 tools**.
- Peer **no** Cloudflare (conexión directa a la IP desde fuera) → **403**, tanto en
  `/healthz` como en `/mcp`.
- Certificado presentado: `CloudFlare Origin Certificate`, SAN `*.optimaonline.eu`
  (válido hasta 2041). Es Origin CA: los `curl` de prueba necesitan `-k`.
- `back.optimaonline.eu` sigue respondiendo (302 a login), así que la plataforma
  no se vio afectada.

### Verificación pública (hecha, DNS ya creado)

DNS: `A mcp-back → 167.233.70.237`, **Proxied**. Confirmado en los autoritativos
de la zona, en `1.1.1.1` y en `8.8.8.8` (`104.21.42.112`, `172.67.161.165`).

A través de Cloudflare, con TLS validado (sin `-k`):

- `https://mcp-back.optimaonline.eu/healthz` → **200**
  `{"status":"ok","servicio":"mcp-optima-bd",...}`, `server: cloudflare`.
- `POST /mcp` sin clave → **401**.
- `initialize` con clave real → **200** (`serverInfo.mcp-optima-bd`).
- `tools/list` → **37 tools**.

Endurecimiento comprobado: la conexión **directa a la IP**, sin pasar por
Cloudflare, devuelve **403** en `/healthz` y en `/mcp`.

Rollback total:

```bash
sudo rm -f /etc/nginx/sites-enabled/mcp-back.optimaonline.eu.conf \
           /etc/nginx/sites-available/mcp-back.optimaonline.eu.conf \
           /etc/nginx/conf.d/mcp-cloudflare-geo.conf
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Aceptación del servicio

```bash
curl -s http://127.0.0.1:8443/healthz | jq .          # 200
# Ojo: con un solo endpoint, healthz dice "destino":"primario" aunque la BD sea
# la réplica; no hay router a un segundo host porque el usuario tiene tope de 3
# conexiones.
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
     -H 'content-type: application/json' -d '{}' \
     https://mcp-back.optimaonline.eu/mcp              # 401
# con clave válida: initialize de MCP -> 200
# clave revocada -> 401 inmediato
# lag > umbral -> healthz.replica.ok=false y las lecturas van al primario
```

Comprobaciones de seguridad:

```bash
sudo ss -tulnp | grep 8443        # solo 127.0.0.1
nc -zv mcp-back.optimaonline.eu 8443   # desde fuera: filtrado/timeout
sudo systemctl show mcp-optima-bd -p MemoryMax
```

## 5. Configuración del cliente

```json
{
  "mcpServers": {
    "mcp-optima-bd": {
      "type": "http",
      "url": "https://mcp-back.optimaonline.eu/mcp",
      "headers": { "Authorization": "Bearer mcp_<id>_<secreto>" }
    }
  }
}
```

### Atajo en el servidor: `mcp-key`

[`deploy/bin/mcp-key`](bin/mcp-key) se instala en `~/bin/mcp-key` del usuario
`forge` y avisa al iniciar sesión. Evita tener que buscar la clave a mano:

```bash
mcp-key                 # clave + JSON de cliente + estado de /healthz
mcp-key json            # solo el JSON, para pegar en el cliente
mcp-key probar          # handshake real: initialize 200 + nº de tools
mcp-key listar          # claves del servidor (sin secretos; pide contraseña)
mcp-key nueva <nombre>  # emite una clave y la guarda (pide contraseña)
```

La clave vive en `~/.mcp-api-key-finanzas` (0600), **primera línea**: la segunda
(`id=… scopes=…`) son metadatos y no forman parte del token.

`listar`/`nueva` necesitan `sudo -u mcp` porque `/var/lib/mcp-optima-bd/api_keys.db`
es `0600 mcp:mcp` y las claves están **hasheadas** (SHA-256): no se pueden
recuperar desde la base, solo emitir otra.

Instalación (idempotente):

```bash
scp deploy/bin/mcp-key forge@<host>:bin/mcp-key   # chmod 755
# + bloque de PATH y banner en ~/.profile y ~/.bashrc (ver el propio script)
```

## 6. Rotación y revocación

```bash
# crear nueva, migrar clientes, revocar la vieja
mcp-key nueva finanzas-2026Q4        # equivale al `create` de abajo
python -m mcp_bd_readonly.auth --db /var/lib/mcp-optima-bd/api_keys.db revoke --id <id_viejo>
```

## 7. Rollback

- Servicio: `systemctl stop mcp-optima-bd` (los clientes vuelven al MCP local por stdio).
- Réplica: `STOP REPLICA;` y `DROP DATABASE back;` en el standby. El primario no
  se ha modificado salvo el usuario `repl_mcp` (revocable).
- El primario **nunca** se reinicia en este procedimiento.

## 8. Despliegue automático (GitHub Actions)

`.github/workflows/deploy.yml` crea un tag `mcp-remote-vX.Y` y despliega al
standby en cada push a `main`. La superficie de ataque entera de la
automatización son dos ficheros ya en el repo
(`deploy/remote-deploy.sh`, `deploy/ssh-deploy-entry.sh`) — revísalos antes de
activar esto. **Nada de esta sección se puede automatizar por SSH**: requiere
root interactivo en el servidor (`sudoers`, `authorized_keys`), así que se
aplica a mano, una sola vez.

### 8.1 Clave de despliegue dedicada (en TU máquina, no en el servidor)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/mcp_back_deploy -C "github-actions-mcp-back-deploy" -N ""
```

- La **privada** (`~/.ssh/mcp_back_deploy`) va a un secret de GitHub, nunca al repo.
- La **pública** (`~/.ssh/mcp_back_deploy.pub`) va al servidor, en el siguiente paso.

### 8.2 En el servidor (`optimaback-standby`, como root o con sudo interactivo)

Instalar los scripts (ya están en el repo desplegado en `/opt/mcp-optima-bd`,
solo falta darles los permisos correctos y la propiedad):

```bash
chmod 750 /opt/mcp-optima-bd/deploy/remote-deploy.sh /opt/mcp-optima-bd/deploy/ssh-deploy-entry.sh
chown root:root /opt/mcp-optima-bd/deploy/remote-deploy.sh   # debe ser de root: lo invoca sudo
```

**Sudoers** (`sudo visudo -f /etc/sudoers.d/mcp-back-deploy`) — NOPASSWD acotado a
ese único script, ningún otro comando:

```
forge ALL=(root) NOPASSWD: /opt/mcp-optima-bd/deploy/remote-deploy.sh
```

**Clave de despliegue** en `~/.ssh/authorized_keys` del usuario `forge` — con
`command=` forzado: quien use esta clave NO tiene shell, solo puede disparar
`ssh-deploy-entry.sh` (que a su vez solo puede invocar el script de arriba):

```
command="/opt/mcp-optima-bd/deploy/ssh-deploy-entry.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty,restrict ssh-ed25519 AAAA...(pegar aquí el contenido de mcp_back_deploy.pub) github-actions-mcp-back-deploy
```

### 8.3 Secrets en GitHub (repo `noemartinezoptima/mcp-bd-readonly` → Settings → Secrets)

| Secret | Valor |
|---|---|
| `MCP_DEPLOY_SSH_KEY` | Contenido completo de `~/.ssh/mcp_back_deploy` (la privada) |
| `MCP_DEPLOY_SSH_HOST` | IP del standby (`167.233.70.237`) |

### 8.4 Primer disparo

Un push/merge a `main` dispara el workflow. Revisa la pestaña Actions del repo;
si falla en el paso SSH, el error más probable es `authorized_keys`/sudoers mal
copiado (revisa que no se haya partido la clave en varias líneas).
