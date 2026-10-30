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

Usuario de lectura para el MCP (en la réplica):

```sql
CREATE USER 'back_readonly'@'127.0.0.1' IDENTIFIED BY '<PASSWORD>';
GRANT SELECT ON back.* TO 'back_readonly'@'127.0.0.1';
```

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

## 3. nginx + Cloudflare

```bash
sudo cp deploy/nginx/mcp-back.optimaonline.eu.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/mcp-back.optimaonline.eu.conf /etc/nginx/sites-enabled/
# certificado de origen ya existente en /etc/nginx/ssl/
sudo nginx -t && sudo systemctl reload nginx
```

DNS: `mcp-back.optimaonline.eu` proxied (naranja) en Cloudflare, SSL = Full (strict).
**Fijar el nombre antes de crear el site**: renombrar en Forge no actualiza el
nginx raíz.

## 4. Aceptación del servicio

```bash
curl -s http://127.0.0.1:8443/healthz | jq .          # 200, replica.ok
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

## 6. Rotación y revocación

```bash
# crear nueva, migrar clientes, revocar la vieja
python -m mcp_bd_readonly.auth --db /var/lib/mcp-optima-bd/api_keys.db create --name finanzas-2026Q4
python -m mcp_bd_readonly.auth --db /var/lib/mcp-optima-bd/api_keys.db revoke --id <id_viejo>
```

## 7. Rollback

- Servicio: `systemctl stop mcp-optima-bd` (los clientes vuelven al MCP local por stdio).
- Réplica: `STOP REPLICA;` y `DROP DATABASE back;` en el standby. El primario no
  se ha modificado salvo el usuario `repl_mcp` (revocable).
- El primario **nunca** se reinicia en este procedimiento.
