import json
import time
import unicodedata
from pathlib import Path


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.lower().split())


# Palabras funcionales cortas. Sin filtrarlas, "de" aparece en casi cualquier
# frase en español y cualquier búsqueda devuelve la memoria entera.
_STOP_CORTO = frozenset({
    "de", "la", "el", "los", "las", "un", "una", "y", "en", "al",
    "se", "su", "es", "lo", "o", "a",
})


class Memoria:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "memoria.json"
        self._limit = 200

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries[-self._limit:], ensure_ascii=False, indent=1))
        return {"guardado": True, "usuaria": entry.get("usuaria", "zerocool"), "total": len(entries)}

    def consultar(self, texto: str, limite: int = 5) -> list:
        tokens = _norm(texto).split()
        if not tokens:
            return []
        scored = []
        for e in self._load():
            hay = _norm(f"{e.get('frase','')} {e.get('resumen','')} {e.get('query','')}")
            palabras = set(hay.split())
            hit = 0
            for t in tokens:
                if len(t) >= 3:
                    # Substring a propósito: sigue encontrando "factura" dentro
                    # de "facturas" sin tener que hacer stemming.
                    if t in hay:
                        hit += 1
                elif t not in _STOP_CORTO and t in palabras:
                    # Los tokens cortos solo como palabra entera: si no, "ot"
                    # cae dentro de "total_euros" y una búsqueda de OT devuelve
                    # memorias de IVA. Se salvan las de 1-2 letras que sí son
                    # consultas reales ("x", "ot").
                    hit += 1
            if hit:
                scored.append((hit, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limite]]


def build_memoria_tools(audit, data_dir):
    mem = Memoria(data_dir)

    def recordar_consulta(frase: str, query: str, resumen: str, usuaria: str = "zerocool") -> dict:
        """Guarda una consulta hecha (frase natural + query + resumen del resultado) por usuaria, para reusarla después."""
        audit and audit.record("recordar_consulta", "mcp", f"{usuaria}: {frase}")
        return mem.guardar({
            "frase": frase, "query": query, "resumen": resumen,
            "usuaria": usuaria, "ts": int(time.time()),
        })

    def consultar_memoria(texto: str, limite: int = 5) -> dict:
        """Busca consultas guardadas (frase/resumen/query) que coincidan con el texto."""
        audit and audit.record("consultar_memoria", "mcp", texto)
        return {"resultados": mem.consultar(texto, limite=limite)}

    return [recordar_consulta, consultar_memoria]