"""Bucle de feedback de bajo nivel para `resolve_domain_term` (ver glosario.py).

Hasta ahora, los gaps del glosario (sinónimo sin canónico, canónico que
apunta a la tabla equivocada) solo se detectaban probando frases a mano en
una sesión de auditoría en vivo. Este módulo da a cualquier agente conectado
una forma de DEJAR CONSTANCIA del gap en el momento en que lo nota durante
uso real, en vez de que se pierda al cerrar la sesión.

Deliberadamente NO escribe `glosario.py`: solo acumula señal en un JSON local
(mismo patrón que `memoria.py`). Sigue haciendo falta una sesión humana que
lea `glosario_pendientes()`, decida el fix, lo teste y lo mergee -- igual que
todos los PRs de la sesión del 1/2-nov-2026, pero con la parte de "encontrar
el gap" continua en vez de depender de una ronda de pruebas manual.
"""

import json
import time
from collections import Counter
from pathlib import Path

from mcp_bd_readonly.secure_log import write_text_private


class GlosarioFeedback:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "glosario_feedback.json"
        self._limit = 500

    def _load(self) -> list:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def guardar(self, entry: dict) -> dict:
        entries = self._load()
        entries.append(entry)
        # 0600: la frase puede incluir detalles de negocio reales.
        write_text_private(self.path, json.dumps(entries[-self._limit:], ensure_ascii=False, indent=1))
        return {"guardado": True, "total": len(entries)}

    def pendientes(self, limite: int) -> dict:
        entries = self._load()
        # Agrupado por (canonico_obtenido, canonico_esperado): el mismo gap
        # reportado varias veces (como pasó con "gastado" y "presupuestado"
        # en la sesión del 1/2-nov-2026) debe aparecer una vez con su
        # frecuencia, no N veces duplicado en la lista.
        contador = Counter((e.get("canonico_obtenido") or "", e.get("canonico_esperado") or "") for e in entries)
        ejemplos: dict[tuple[str, str], list[str]] = {}
        for e in entries:
            clave = (e.get("canonico_obtenido") or "", e.get("canonico_esperado") or "")
            ejemplos.setdefault(clave, [])
            if len(ejemplos[clave]) < 3:
                ejemplos[clave].append(e.get("frase", ""))

        agrupado = [
            {
                "canonico_obtenido": obtenido or None,
                "canonico_esperado": esperado or None,
                "veces_reportado": n,
                "frases_ejemplo": ejemplos[(obtenido, esperado)],
                "motivo_mas_reciente": next(
                    (e.get("motivo") for e in reversed(entries)
                     if (e.get("canonico_obtenido") or "", e.get("canonico_esperado") or "") == (obtenido, esperado)),
                    None,
                ),
            }
            for (obtenido, esperado), n in contador.most_common(limite)
        ]
        return {"total_reportes": len(entries), "gaps_agrupados": agrupado}


def build_glosario_feedback_tools(audit, data_dir):
    store = GlosarioFeedback(data_dir)

    def reportar_fallo_glosario(
        frase: str,
        canonico_esperado: str,
        motivo: str,
        canonico_obtenido: str = "",
    ) -> dict:
        """Registra que resolve_domain_term dio una respuesta vacía o equivocada para
        `frase`, para que una sesión futura lo revise y corrija glosario.py. NO cambia
        nada en caliente: solo deja constancia (igual que recordar_consulta, pero para
        gaps del glosario en vez de queries exitosas). Llamar justo cuando se note el
        fallo en uso real, con `canonico_esperado` = el canónico que debería haber
        salido (o el nombre de tabla real si no existe ninguno todavía) y `motivo` en
        una frase corta. `canonico_obtenido` es opcional: vacío si resolve_domain_term
        no devolvió ninguna coincidencia."""
        audit and audit.record("reportar_fallo_glosario", "mcp", f"{frase} -> esperado={canonico_esperado}")
        return store.guardar({
            "frase": frase,
            "canonico_obtenido": canonico_obtenido or None,
            "canonico_esperado": canonico_esperado,
            "motivo": motivo,
            "ts": int(time.time()),
        })

    def glosario_pendientes(limite: int = 10) -> dict:
        """Resume los fallos de resolve_domain_term reportados con reportar_fallo_glosario,
        agrupados por (lo que salió, lo que se esperaba) y ordenados por frecuencia.
        Útil al empezar una sesión de mantenimiento del glosario: evita inventar frases
        de prueba desde cero, ya hay gaps reales detectados en producción esperando PR."""
        audit and audit.record("glosario_pendientes", "mcp", f"limite={limite}")
        return store.pendientes(limite)

    return [reportar_fallo_glosario, glosario_pendientes]
