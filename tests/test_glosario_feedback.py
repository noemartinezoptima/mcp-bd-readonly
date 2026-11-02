import stat

from mcp_bd_readonly.glosario_feedback import GlosarioFeedback, build_glosario_feedback_tools


def _tools(data_dir):
    return {fn.__name__: fn for fn in build_glosario_feedback_tools(audit=None, data_dir=data_dir)}


def test_reportar_y_ver_en_pendientes(tmp_path):
    tools = _tools(tmp_path)
    out = tools["reportar_fallo_glosario"](
        frase="cuánto hemos gastado este mes",
        canonico_esperado="facturas_compra",
        motivo="no devolvia ninguna coincidencia",
        canonico_obtenido="",
    )
    assert out["guardado"] is True

    pendientes = tools["glosario_pendientes"]()
    assert pendientes["total_reportes"] == 1
    gap = pendientes["gaps_agrupados"][0]
    assert gap["canonico_esperado"] == "facturas_compra"
    assert gap["canonico_obtenido"] is None
    assert gap["veces_reportado"] == 1
    assert "cuánto hemos gastado este mes" in gap["frases_ejemplo"]


def test_pendientes_agrupa_reportes_repetidos():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        tools = _tools(Path(d))
        for frase in ["cuánto hemos gastado este mes", "qué gastamos el mes pasado"]:
            tools["reportar_fallo_glosario"](
                frase=frase,
                canonico_esperado="facturas_compra",
                motivo="participio no matcheaba",
            )
        # Un gap distinto, reportado una sola vez.
        tools["reportar_fallo_glosario"](
            frase="qué iban tiene este cliente",
            canonico_esperado="forma_pago",
            canonico_obtenido="efectos_pago",
            motivo="confundia config de pago con cobros",
        )

        pendientes = tools["glosario_pendientes"]()
        assert pendientes["total_reportes"] == 3
        por_esperado = {g["canonico_esperado"]: g for g in pendientes["gaps_agrupados"]}
        assert por_esperado["facturas_compra"]["veces_reportado"] == 2
        assert len(por_esperado["facturas_compra"]["frases_ejemplo"]) == 2
        assert por_esperado["forma_pago"]["veces_reportado"] == 1
        assert por_esperado["forma_pago"]["canonico_obtenido"] == "efectos_pago"


def test_pendientes_respeta_el_limite(tmp_path):
    tools = _tools(tmp_path)
    for i in range(5):
        tools["reportar_fallo_glosario"](
            frase=f"frase {i}",
            canonico_esperado=f"canonico_{i}",
            motivo="gap distinto cada vez",
        )
    pendientes = tools["glosario_pendientes"](limite=2)
    assert len(pendientes["gaps_agrupados"]) == 2
    assert pendientes["total_reportes"] == 5


def test_sin_reportes_pendientes_vacio(tmp_path):
    tools = _tools(tmp_path)
    pendientes = tools["glosario_pendientes"]()
    assert pendientes == {"total_reportes": 0, "gaps_agrupados": []}


def test_persiste_entre_instancias(tmp_path):
    store = GlosarioFeedback(tmp_path)
    store.guardar({"frase": "x", "canonico_obtenido": None, "canonico_esperado": "y", "motivo": "z"})
    store2 = GlosarioFeedback(tmp_path)
    assert store2.pendientes(10)["total_reportes"] == 1


def test_json_queda_con_permisos_privados(tmp_path):
    store = GlosarioFeedback(tmp_path)
    store.guardar({"frase": "x", "canonico_obtenido": None, "canonico_esperado": "y", "motivo": "z"})
    modo = stat.S_IMODE((tmp_path / "glosario_feedback.json").stat().st_mode)
    assert modo == 0o600
