#!/usr/bin/env python3
"""Siembra `data/memoria.json` con consultas verificadas, para que
`consultar_memoria` deje de buscar en el vacío.

Por qué un sembrador y no el histórico de `data/audit.jsonl`: la auditoría solo
guarda `{ts, tool, who, sql, note}` — es decir, **SQL sin lenguaje natural** —
y `Memoria.consultar` puntúa coincidiendo contra la `frase`. Sembrar desde ahí
daría frases idénticas al SQL y cero aciertos. Estas entradas están escritas a
mano y CADA query se ejecutó contra la BD real antes de entrar aquí.

Idempotente: no duplica por `frase`. Uso:

    python3 scripts/seed_memoria.py                 # siembra lo que falte
    python3 scripts/seed_memoria.py --dry-run       # qué haría
    python3 scripts/seed_memoria.py --data-dir DIR  # otro destino
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcp_bd_readonly.memoria import Memoria  # noqa: E402

USUARIA = "zerocool"

# Solo consultas ejecutadas con éxito contra la BD real (verificado 30-oct-2026).
SEEDS: list[dict] = [
    {
        "frase": "cuantas OT abiertas hay en un mes concreto",
        "query": (
            "SELECT COUNT(*) AS recibidas, SUM(fecha_cierre IS NULL) AS abiertas "
            "FROM ots WHERE fecha_recibida >= '2026-09-01' "
            "AND fecha_recibida < '2026-10-01'"
        ),
        "resumen": (
            "Abierta = fecha_cierre IS NULL; el mes va por fecha_recibida. "
            "Sep-2026: 21.176 recibidas, 1.068 sin cerrar (cifras del 30-oct-2026). "
            "OJO: la tabla de estados es `estados`, NO `estados_ot` (que está vacía)."
        ),
    },
    {
        "frase": "desglose de OT abiertas por estado",
        "query": (
            "SELECT e.nombre AS estado, COUNT(*) AS n FROM ots o "
            "JOIN estados e ON e.id = o.estado_id "
            "WHERE o.fecha_recibida >= '2026-09-01' AND o.fecha_recibida < '2026-10-01' "
            "AND o.fecha_cierre IS NULL GROUP BY e.nombre ORDER BY n DESC"
        ),
        "resumen": (
            "JOIN a `estados` (no a estados_ot). Algunas OT tienen estado terminal "
            "con fecha_cierre NULL: separa 'sin cerrar' de 'en curso' y di cuántas excluyes."
        ),
    },
    {
        "frase": "base imponible y iva de un trimestre sin la tool",
        "query": (
            "SELECT SUM(total_euros) AS total, SUM(iva_euros) AS iva "
            "FROM facturas_venta WHERE fecha_factura >= '2026-07-01' "
            "AND fecha_factura < '2026-10-01' AND deleted_at IS NULL"
        ),
        "resumen": (
            "Verificado: Q3-2026 = 11.344.061,26 EUR de base y 1.228.467,41 EUR de IVA. "
            "facturas_venta NO tiene base_euros: usa total_euros - iva_euros. "
            "Prefiere la tool resumen_iva(trimestre, anio) si solo quieres el agregado."
        ),
    },
    {
        "frase": "efectos de pago pendientes de un cliente",
        "query": (
            "SELECT e.id, e.fecha_vencimiento, e.total_euros, e.fecha_pagado "
            "FROM efectos_pago e WHERE e.modelo_id = 12 "
            "AND e.relacion_id IN (SELECT id FROM facturas_venta WHERE cliente_id = 1) "
            "AND e.deleted_at IS NULL ORDER BY e.fecha_vencimiento"
        ),
        "resumen": (
            "efectos_pago es polimorfico: modelo_id 12=FacturaVenta, 11=FacturaCompra; "
            "relacion_id apunta al id de esa tabla y NO es foreign key. "
            "No tiene cliente_id. La fecha de pago es fecha_pagado (no fecha_pago) "
            "y NO existe cobros_remesas (error 1146)."
        ),
    },
    {
        "frase": "cuanto IVA hay que liquidar este trimestre",
        "query": "resumen_iva(trimestre=<1-4>, anio=<anio>)",
        "resumen": (
            "Es un agregado, no hay tabla de impuestos: llama la tool resumen_iva. "
            "Solo existe iva_euros; no hay impuestos adicionales separados."
        ),
    },
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Siembra memoria con consultas verificadas.")
    ap.add_argument("--data-dir", default="data", help="directorio con memoria.json (default: data)")
    ap.add_argument("--dry-run", action="store_true", help="muestra qué haría sin escribir")
    args = ap.parse_args(argv)

    mem = Memoria(Path(args.data_dir))
    existentes = {e.get("frase") for e in mem._load()}
    nuevos = [s for s in SEEDS if s["frase"] not in existentes]

    print(f"memoria: {len(existentes)} entradas existentes · {len(nuevos)} nuevas de {len(SEEDS)}")
    if not nuevos:
        print("nada que hacer")
        return 0
    for s in nuevos:
        print(f"  + {s['frase']}")
        if args.dry_run:
            continue
        mem.guardar({**s, "usuaria": USUARIA, "ts": int(time.time())})

    if not args.dry_run:
        print(f"escrito en {mem.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
