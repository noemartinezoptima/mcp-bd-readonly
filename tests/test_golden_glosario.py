"""Golden set: preguntas reales en español -> tool canónica recomendada.

Es la evaluación del entrenamiento: si alguien toca el glosario y una de estas
frases deja de resolver (o resuelve a otra cosa), esta prueba salta. Las
expectativas se fijaron ejecutando resolver() contra el glosario real, no a ojo.
"""

import pytest

from mcp_bd_readonly.glosario import resolver

GOLDEN = [
    # (frase natural tal como la escribiría alguien, recomendado esperado)
    ("cuantas OT abiertas tengo en septiembre", "ots"),
    ("OT abiertas de este mes", "ots"),
    ("cuanto IVA hay que liquidar este trimestre", "resumen_iva"),
    ("iva a liquidar", "resumen_iva"),
    ("remesas pendientes de cobrar", "efectos_pago"),
    ("efectos de pago de un cliente", "efectos_pago"),
    ("facturas de venta del año", "facturas_venta"),
    ("cuadre de la factura", "facturas_venta"),
    ("gastos por tipo", "facturas_compra"),
    ("margen neto", "margen"),
    ("balance de situacion", "balance"),
    ("aging de efectos", "efectos_pago"),
    ("stock actual por ubicacion", "stock"),
    ("top clientes por facturacion", "facturas_venta"),
    ("establecimiento y responsable", "establecimiento"),
]


@pytest.mark.parametrize("frase,esperado", GOLDEN, ids=[f for f, _ in GOLDEN])
def test_golden_recomienda_lo_correcto(frase, esperado):
    r = resolver(frase)
    assert r.get("recomendado") == esperado, (
        f"{frase!r} recomienda {r.get('recomendado')!r}, se esperaba {esperado!r}"
    )


@pytest.mark.parametrize("frase", [f for f, _ in GOLDEN], ids=[f for f, _ in GOLDEN])
def test_golden_siempre_trae_trampas(frase):
    """Toda frase del golden debe devolver al menos una coincidencia con tabla,
    herramienta y trampas: resolver sin contenido no sirve al agente."""
    r = resolver(frase)
    coincidencias = r.get("coincidencias") or []
    assert coincidencias, f"{frase!r} no devuelve coincidencias"
    info = coincidencias[0].get("info") or {}
    assert info.get("tabla"), f"{frase!r} sin tabla"
    assert info.get("trampas"), f"{frase!r} sin trampas"
