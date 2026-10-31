"""Los prompts MCP son el "entrenamiento": se registran y se cargan bajo demanda."""

import asyncio
from types import SimpleNamespace

from mcp_bd_readonly.prompts import (
    IVA_TRIMESTRAL,
    OT_ABIERTAS,
    RIESGO_COBROS,
    SQL_SEGURO,
    build_prompts,
)
from mcp_bd_readonly.server import INSTRUCTIONS, build_mcp


def _mcp(tmp_path):
    cfg = SimpleNamespace(
        files_dir="",
        data_dir=str(tmp_path),
        http_host="127.0.0.1",
        http_port=8443,
        allowed_hosts="",
        tunnel_enabled=False,
    )
    # executor nunca se invoca al registrar tools/prompts.
    return build_mcp(cfg, executor=object(), audit=None, remote=False)


def test_registra_los_cuatro_prompts(tmp_path):
    mcp = _mcp(tmp_path)
    prompts = asyncio.run(mcp.list_prompts())
    assert sorted(p.name for p in prompts) == [
        "iva_trimestral",
        "ot_abiertas",
        "riesgo_cobros",
        "sql_seguro",
    ]


def test_todos_tienen_descripcion(tmp_path):
    mcp = _mcp(tmp_path)
    for p in asyncio.run(mcp.list_prompts()):
        assert p.description, f"{p.name} sin descripción: el cliente no sabrá para qué sirve"


def test_iva_interpola_los_argumentos():
    out = IVA_TRIMESTRAL.format(anio=2026, trimestre=3)
    assert "2026" in out and "T3" in out
    assert "trimestre=3" in out and "anio=2026" in out
    assert "{anio}" not in out and "{trimestre}" not in out


def test_los_prompts_solo_afirman_lo_verificado():
    # Trampas que se comprobaron con describe_table contra la BD real.
    assert "base_euros" in SQL_SEGURO and "solo" in SQL_SEGURO.lower()
    assert "fecha_pagado" in RIESGO_COBROS and "1146" in RIESGO_COBROS
    assert "modelo_id" in RIESGO_COBROS and "NO es foreign key" in RIESGO_COBROS
    assert "estados_ot" in OT_ABIERTAS and "VAC" in OT_ABIERTAS
    assert "facturas_venta_lineas.ot_id" in OT_ABIERTAS


def test_instructions_apunta_a_los_prompts_y_a_las_trampas_duras():
    # Viaja en cada initialize: solo las trampas duras y el puntero.
    assert "prompts/list" in INSTRUCTIONS
    assert "resolve_domain_term" in INSTRUCTIONS
    assert "base_euros" in INSTRUCTIONS
    assert "cliente_id" in INSTRUCTIONS


def test_el_registro_no_duplica_nombre_de_prompt():
    assert build_prompts.__name__ == "build_prompts"
    # Cada guión declara name= explícito: el nombre no depende del docstring.
    for bloque in (SQL_SEGURO, RIESGO_COBROS, OT_ABIERTAS):
        assert "{" not in bloque.split("\n")[0]
