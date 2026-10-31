"""Perfiles de tools: ahorro de contexto sin dejar herramientas sin clasificar."""

import asyncio
import logging
from types import SimpleNamespace

from mcp_bd_readonly.config import load_config
from mcp_bd_readonly.perfiles import (
    CORE,
    PERFILES,
    SOLO_TODAS,
    aviso_perfil,
    herramientas_activas,
)
from mcp_bd_readonly.server import build_mcp


def _cfg(tmp_path, perfil=""):
    return SimpleNamespace(
        files_dir="",
        data_dir=str(tmp_path),
        http_host="127.0.0.1",
        http_port=8443,
        allowed_hosts="",
        tunnel_enabled=False,
        tool_profile=perfil,
    )


def _nombres(tmp_path, perfil=""):
    mcp = build_mcp(_cfg(tmp_path, perfil), executor=object(), audit=None, remote=False)
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_sin_perfil_registra_todas_las_tools(tmp_path):
    # 38 del servidor remoto (incluye run_script) + setup_ssh, solo en local.
    assert len(_nombres(tmp_path, "")) == 39
    assert len(_nombres(tmp_path, "todas")) == 39


def test_perfil_contabilidad_deja_22_tools(tmp_path):
    nombres = _nombres(tmp_path, "contabilidad")
    assert nombres == PERFILES["contabilidad"]
    assert len(nombres) == 22
    assert "run_query" in nombres and "balance" in nombres
    assert "stock_actual" not in nombres
    # El entrenamiento no puede quedar inaccesible con un perfil de dominio:
    # el cliente recibiría "Unknown tool" al intentar consultar memoria.json.
    assert "consultar_memoria" in nombres
    assert "run_script" in nombres


def test_perfiles_de_dominio_mas_pequenos(tmp_path):
    assert len(_nombres(tmp_path, "operaciones")) == 12
    assert len(_nombres(tmp_path, "excel")) == 11
    for perfil in ("operaciones", "excel"):
        assert "consultar_memoria" in _nombres(tmp_path, perfil)
        assert "run_script" in _nombres(tmp_path, perfil)


def test_core_presente_en_todos_los_perfiles():
    for nombre, tools in PERFILES.items():
        assert CORE <= tools, f"el perfil {nombre} se queda sin tools core"


def test_perfiles_cubren_todas_las_tools(tmp_path):
    """Si alguien añade una tool y no la clasifica, esta prueba salta.

    Es la red de seguridad de los perfiles: sin ella, una tool nueva no
    existiría en ningún perfil y desaparecería en silencio para todos los
    clientes que no usen `todas`.
    """
    todas = _nombres(tmp_path, "todas")
    clasificadas = set().union(*PERFILES.values()) | SOLO_TODAS
    assert todas == clasificadas, (
        f"sin clasificar: {sorted(todas - clasificadas)} · "
        f"sobran en perfiles: {sorted(clasificadas - todas)}"
    )


def test_mantenimiento_solo_en_todas():
    assert "setup_ssh" in SOLO_TODAS
    assert "estado_tunel" in SOLO_TODAS
    for tools in PERFILES.values():
        assert not (tools & SOLO_TODAS)


def test_vacio_y_todas_son_equivalentes():
    assert herramientas_activas("") is None
    assert herramientas_activas("todas") is None
    assert herramientas_activas(None) is None


def test_perfil_desconocido_no_tumba_el_servicio(caplog):
    """Una errata en `MCP_TOOL_PROFILE` no puede dejar el endpoint en crash-loop:
    antes lanzaba y systemd lo reiniciaba en bucle hasta dejar mcp-back caído."""
    with caplog.at_level(logging.ERROR, logger="mcp_bd_readonly.perfiles"):
        assert herramientas_activas("contabilid") is None
    assert "MCP_TOOL_PROFILE" in caplog.text
    assert "contabilidad" in caplog.text  # dice los válidos


def test_perfil_desconocido_sirve_las_38_y_lo_dice_en_instructions(tmp_path):
    """Tampoco puede pasar desapercibido: se sirven las de siempre (nada
    desaparece en silencio) y el aviso viaja en `instructions`, que es lo que
    lee el cliente en cada `initialize`."""
    assert len(_nombres(tmp_path, "contabilid")) == 39
    mcp = build_mcp(_cfg(tmp_path, "contabilid"), executor=object(), audit=None,
                    remote=False)
    texto = mcp.instructions or ""
    assert "MCP_TOOL_PROFILE" in texto and "contabilidad" in texto


def test_perfil_valido_y_vacio_no_annaden_aviso(tmp_path):
    for perfil in ("", "todas", "contabilidad"):
        mcp = build_mcp(_cfg(tmp_path, perfil), executor=object(), audit=None,
                        remote=False)
        assert "MCP_TOOL_PROFILE" not in (mcp.instructions or "")
        assert aviso_perfil(perfil) == ""


def test_write_config_persiste_el_perfil(tmp_path, monkeypatch):
    from mcp_bd_readonly.config import Config, write_config

    cfg = Config(host="h", port=1, db="d", user="u", password="p",
                 data_dir=tmp_path, tunnel_host="", tool_profile="contabilidad")
    texto = write_config(cfg, path=tmp_path / "nuevo.env").read_text()
    assert "MCP_TOOL_PROFILE=contabilidad" in texto
    # y load_config lo vuelve a leer desde ese fichero
    monkeypatch.delenv("MCP_TOOL_PROFILE", raising=False)
    assert load_config(tmp_path / "nuevo.env").tool_profile == "contabilidad"


def test_config_deja_leer_el_perfil(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TOOL_PROFILE", "contabilidad")
    assert load_config(tmp_path / "no-existe.env").tool_profile == "contabilidad"
    monkeypatch.delenv("MCP_TOOL_PROFILE")
    assert load_config(tmp_path / "no-existe.env").tool_profile == ""
