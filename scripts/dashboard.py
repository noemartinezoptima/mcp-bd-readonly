#!/usr/bin/env python3
"""Dashboard web local de mcp-bd-readonly: estado del MCP, túnel y motor Excel.

Uso:
    python scripts/dashboard.py            # puerto 5180 (o PORT=xxxx)
    open http://127.0.0.1:5180

Solo stdlib (http.server). Read-only salvo los botones de acción explícitos.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = ROOT / ".venv" / "bin" / "mcp-bd-readonly"
if not VENV_BIN.exists():  # Windows
    VENV_BIN = ROOT / ".venv" / "Scripts" / "mcp-bd-readonly.exe"
PORT = int(os.environ.get("PORT", "5180"))
TUNNEL_HOST = os.environ.get("TUNNEL_HOST", "optimaback-active")
LOCAL = ("127.0.0.1", 13306)

sys.path.insert(0, str(ROOT / "src"))
from mcp_bd_readonly.tunnel import _port_open  # noqa: E402


def port_open(host: str = LOCAL[0], port: int = LOCAL[1]) -> bool:
    return _port_open(host, port, timeout=2.0)


def ssh_pids() -> list[int]:
    try:
        out = subprocess.run(["pgrep", "-f", "ssh -N -L"], capture_output=True,
                             text=True, timeout=5).stdout
        return [int(x) for x in out.split() if x.strip()]
    except Exception:
        return []


def mcp_processes() -> int:
    try:
        out = subprocess.run(["pgrep", "-f", "mcp-bd-readonly"], capture_output=True,
                             text=True, timeout=5).stdout
        return len([x for x in out.split() if x.strip()])
    except Exception:
        return 0


def _mcp_handshake() -> dict:
    """Spawn del binario con initialize/tools-list/exit; mide respuesta."""
    t0 = time.time()
    if not VENV_BIN.exists():
        return {"ok": False, "error": f"binario no existe: {VENV_BIN}"}
    payload = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":'
        '"2024-11-05","capabilities":{},"clientInfo":{"name":"dash","version":"1"}}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n'
    )
    try:
        p = subprocess.Popen([str(VENV_BIN)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = p.communicate(payload, timeout=20)
        ok_lines = [l for l in out.strip().splitlines() if l.strip().startswith("{")]
        id2 = next((json.loads(l) for l in ok_lines
                    if json.loads(l).get("id") == 2), None)
        rc = p.returncode
        ntools = len((id2 or {}).get("result", {}).get("tools", []))
        return {
            "ok": rc == 0 and ntools > 0,
            "tools": ntools,
            "rc": rc,
            "ms": round((time.time() - t0) * 1000),
            "error": (err.strip()[:200] if not id2 else None),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "ms": round((time.time() - t0) * 1000),
                "error": "timeout 20s en handshake"}
    except Exception as e:
        return {"ok": False, "ms": round((time.time() - t0) * 1000), "error": str(e)}


def excel_status() -> dict:
    try:
        from mcp_bd_readonly.tools_excel import check_excel_capabilities
        c = check_excel_capabilities()
        return {
            "strategy": c.get("strategy", "?"),
            "lo": c.get("libreoffice", {}).get("available", False),
            "lo_version": c.get("libreoffice", {}).get("version", ""),
            "formualizer": c.get("formualizer", {}).get("available", False),
        }
    except Exception as e:
        return {"strategy": "error", "error": str(e)}


def conn_log_tail(lines: int = 6) -> list[str]:
    """Últimos eventos del MCP en el log de opencode (no bloqueante)."""
    log = Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"
    if not log.exists():
        return ["(log de opencode no encontrado)"]
    hits = []
    try:
        with open(log, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            tail_b = f.read()
        for line in tail_b.decode("utf-8", "replace").splitlines():
            if "mcp-bd-readonly" in line or "MCP connection closed" in line:
                hits.append(line[:220])
        return hits[-lines:]
    except Exception as e:
        return [f"(error leyendo log: {e})"]


def run_status() -> dict:
    hand = _mcp_handshake()
    return {
        "ts": time.strftime("%H:%M:%S"),
        "mcp": {
            "bin": str(VENV_BIN),
            "handshake_ok": hand.get("ok"),
            "tools": hand.get("tools"),
            "ms": hand.get("ms"),
            "error": hand.get("error"),
            "processes": mcp_processes(),
        },
        "tunnel": {
            "open": port_open(),
            "local": f"{LOCAL[0]}:{LOCAL[1]}",
            "host": TUNNEL_HOST,
            "ssh_pids": ssh_pids(),
        },
        "excel": excel_status(),
        "events": conn_log_tail(),
    }


def start_tunnel() -> dict:
    if port_open():
        return {"ok": True, "msg": "túnel ya estaba abierto"}
    nul = open(os.devnull, "w")
    cmd = ["ssh", "-N", "-L", f"{LOCAL[1]}:127.0.0.1:3306", TUNNEL_HOST]
    try:
        p = subprocess.Popen(cmd, stdout=nul, stderr=nul, start_new_session=True)
        time.sleep(2)
        if p.poll() is not None:
            return {"ok": False, "msg": f"ssh salió con rc={p.returncode}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": port_open(), "msg": f"lanzado pid {p.pid}"}


def kill_tunnels() -> list[int]:
    pids = ssh_pids()
    for pid in pids:
        try:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True,
                           text=True, timeout=5)
        except Exception:
            pass
    return pids


HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCP BD Readonly — Dashboard</title>
<style>
  :root { --bg:#0d1117; --card:#161b22; --line:#30363d; --tx:#e6edf3; --mut:#8b949e;
          --ok:#3fb950; --bad:#f85149; --warn:#d29922; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--tx); }
  header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:16px; }
  h1 { font-size:18px; margin:0; }
  #ts { color:var(--mut); font-size:12px; }
  main { padding:20px 24px; display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; max-width:1200px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .card h2 { margin:0 0 10px; font-size:14px; display:flex; justify-content:space-between; align-items:center; }
  .dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
  .ok { background:var(--ok); } .bad { background:var(--bad); } .warn { background:var(--warn); }
  .row { font-size:12px; color:var(--mut); margin:3px 0; }
  .row b { color:var(--tx); font-weight:600; }
  .btns { margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; }
  button { background:#21262d; color:var(--tx); border:1px solid var(--line); border-radius:6px;
           padding:6px 12px; cursor:pointer; font-size:12px; }
  button:hover { border-color:var(--mut); }
  button:disabled { opacity:.5; cursor:default; }
  pre { background:#0a0e14; border:1px solid var(--line); border-radius:6px; padding:8px;
        font-size:11px; white-space:pre-wrap; word-break:break-all; max-height:160px; overflow:auto; color:var(--mut);}
  #msg { position:fixed; bottom:14px; right:14px; background:var(--card); border:1px solid var(--line);
         padding:10px 14px; border-radius:8px; font-size:13px; display:none; }
</style></head>
<body>
<header><h1>MCP BD Readonly</h1><span id="ts">…</span></header>
<main>
  <div class="card" id="c-mcp">
    <h2>MCP server <span class="dot" id="d-mcp"></span></h2>
    <div class="row">Binario: <b id="m-bin"></b></div>
    <div class="row">Handshake: <b id="m-hand"></b></div>
    <div class="row">Tools: <b id="m-tools"></b></div>
    <div class="row">Procesos: <b id="m-proc"></b></div>
    <div class="row">Latencia: <b id="m-ms"></b></div>
    <div class="btns"><button data-act="mcp">Probar handshake</button></div>
  </div>
  <div class="card" id="c-tun">
    <h2>Túnel BD <span class="dot" id="d-tun"></span></h2>
    <div class="row">Local: <b id="t-local"></b></div>
    <div class="row">Host SSH: <b id="t-host"></b></div>
    <div class="row">PIDs ssh: <b id="t-pids"></b></div>
    <div class="btns">
      <button data-act="tunnel-up">Levantar túnel</button>
      <button data-act="tunnel-kill" class="danger">Matar túneles</button>
    </div>
  </div>
  <div class="card" id="c-xls">
    <h2>Motor Excel <span class="dot" id="d-xls"></span></h2>
    <div class="row">Estrategia: <b id="x-strat"></b></div>
    <div class="row">LibreOffice: <b id="x-lo"></b></div>
    <div class="row">formualizer: <b id="x-fm"></b></div>
  </div>
</main>
<pre id="events"></pre>
<div id="msg"></div>
<script>
const $=id=>document.getElementById(id);
async function get(url,opts){const r=await fetch(url,opts);return r.json();}
let busy=false;
async function refresh(){
  const s=await get("/api/status");
  $("ts").textContent="última comprobación "+s.ts;
  const set=(id,ok,txt)=>{$(id).textContent=txt??"";$(id).className="dot "+(ok?"ok":"bad");};
  set("d-mcp",s.mcp.handshake_ok,"");
  $("m-bin").textContent=s.mcp.bin;
  $("m-hand").textContent=s.mcp.handshake_ok===true?"OK":("FALLO "+(s.mcp.error||""));
  $("m-tools").textContent=s.mcp.tools;
  $("m-proc").textContent=s.mcp.processes;
  $("m-ms").textContent=(s.mcp.ms??"-")+" ms";
  set("d-tun",s.tunnel.open,"");
  $("t-local").textContent=s.tunnel.local;
  $("t-host").textContent=s.tunnel.host;
  $("t-pids").textContent=(s.tunnel.ssh_pids||[]).join(", ")||"—";
  set("d-xls",s.excel.strategy!=="error","");
  $("x-strat").textContent=s.excel.strategy;
  $("x-lo").textContent=(s.excel.lo?(s.excel.lo_version||"sí"):"no");
  $("x-fm").textContent=s.excel.formualizer?"sí":"no";
  $("events").textContent="Últimos eventos del MCP en opencode.log:\n"+(s.events||[]).join("\n");
}
async function act(a){
  if(busy)return; busy=true;
  const msg=$("msg");
  msg.style.display="block";
  msg.textContent="Ejecutando "+a+"…";
  try{
    const r=await get("/api/action?act="+a,{method:"POST"});
    msg.textContent=r.msg||"hecho";
    msg.style.borderColor="var(--ok)";
  }catch(e){ msg.textContent="error: "+e; msg.style.borderColor="var(--bad)"; }
  busy=false;
  setTimeout(refresh,1500);
}
document.querySelectorAll("button[data-act]").forEach(b=>{
  b.addEventListener("click",()=>act(b.dataset.act));
});
refresh();
setInterval(refresh,5000);
fetch("/api/status").catch(()=>{});
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silenciar
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, HTML.encode(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._send(200, json.dumps(run_status(), ensure_ascii=False).encode())
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path.startswith("/api/action"):
            act = self.path.split("act=", 1)[-1].split("&")[0]
            if act == "tunnel-up":
                r = start_tunnel()
            elif act == "tunnel-kill":
                pids = kill_tunnels()
                r = {"ok": True, "msg": f"matados {len(pids)} proceso(s) ssh: {pids}"}
            elif act == "mcp":
                r = _mcp_handshake()
                r = {"ok": r.get("ok"), "msg": f"handshake: {'OK' if r.get('ok') else r.get('error')}"}
            else:
                r = {"ok": False, "msg": f"acción desconocida: {act}"}
            return self._send(200, json.dumps(r, ensure_ascii=False).encode())
        self._send(404, b'{"error":"not found"}')


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Dashboard: http://127.0.0.1:{PORT}  (Ctrl+C para salir)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\napagando")


if __name__ == "__main__":
    main()