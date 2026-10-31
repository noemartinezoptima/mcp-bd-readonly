"""Tool `run_script`: encadenar varias tools en un solo turno con código corto.

Inspirado en "Code Mode" (Cloudflare): el modelo escribe código en vez de
encadenar tool-calls una a una, así los resultados intermedios no pagan una
ida-y-vuelta completa por el LLM. Diferencia deliberada con su diseño: ellos
aíslan el código en un isolate V8 sin API de red porque su sandbox es
multi-tenant (cualquiera puede mandar código). Aquí el único cliente es un
agente ya autenticado con una API key que YA puede leer toda la BD `back` vía
`run_query` — `run_script` no abre ningún acceso nuevo, solo encadena
llamadas a tools que ya están permitidas. Por eso el aislamiento es ligero
(builtins restringidos + timeout), no un sandbox de proceso/contenedor: no
hay una amenaza adversaria nueva que justifique ese coste.

Los builtins restringidos evitan ERRORES de un script mal escrito (abrir un
fichero, importar algo, colgarse), no un ataque deliberado.
"""

from __future__ import annotations

import contextlib
import io
import threading

TIMEOUT_S = 10
MAX_STDOUT = 4000

SAFE_BUILTINS = {
    "print": print,
    "len": len,
    "range": range,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "enumerate": enumerate,
    "zip": zip,
    "round": round,
    "abs": abs,
    "any": any,
    "all": all,
    "True": True,
    "False": False,
    "None": None,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "StopIteration": StopIteration,
}

# Tools excluidas aunque estén registradas: operaciones admin/escritura de
# sistema, no "fuga de datos" (eso ya lo decide el perfil activo, ver
# server.py). setup_ssh toca ~/.ssh/config; refresh_schema exige confirm=True
# explícito en una llamada directa, no tiene sentido colado dentro de un script.
DENEGADAS_EN_SCRIPT = frozenset({"setup_ssh", "refresh_schema", "run_script"})


def ejecutar(codigo: str, tools: dict) -> tuple[str, str | None]:
    """Corre `codigo` con `tools` como únicas funciones disponibles.

    Devuelve (stdout_truncado, error_o_None). Nunca lanza: cualquier excepción
    del script, o el timeout, se reporta como texto para que el modelo lo lea
    y corrija, igual que un error de cualquier otra tool.
    """
    buf = io.StringIO()
    namespace = {"__builtins__": SAFE_BUILTINS, **tools}
    resultado: dict[str, str] = {}

    def _target() -> None:
        try:
            with contextlib.redirect_stdout(buf):
                exec(codigo, namespace)  # noqa: S102 - builtins restringidos, ver docstring del módulo
        except BaseException as exc:  # noqa: BLE001 - se reporta al modelo, nunca se relanza
            resultado["error"] = f"{type(exc).__name__}: {exc}"

    hilo = threading.Thread(target=_target, daemon=True)
    hilo.start()
    hilo.join(TIMEOUT_S)

    if hilo.is_alive():
        # No se puede matar un hilo de Python de forma limpia; se abandona
        # como daemon (muere con el proceso) y se reporta el timeout. El GIL
        # limita el daño real: no compite más que cualquier otra query lenta.
        error = f"timeout: el script no terminó en {TIMEOUT_S}s"
    else:
        error = resultado.get("error")

    stdout = buf.getvalue()
    if len(stdout) > MAX_STDOUT:
        total = len(stdout)
        stdout = stdout[:MAX_STDOUT] + f"\n... truncado ({total} caracteres en total)"

    return stdout, error


def build_run_script_tools(audit, tools: dict):
    disponibles = sorted(n for n in tools if n not in DENEGADAS_EN_SCRIPT)
    tools_script = {n: f for n, f in tools.items() if n not in DENEGADAS_EN_SCRIPT}

    def run_script(codigo: str) -> dict:
        """Ejecuta Python corto para encadenar varias tools sin ida-y-vuelta por cada
        una (ej. resolver un establecimiento y luego sus OT en una sola llamada).
        Las tools ya registradas en esta sesión están disponibles como funciones
        directas (mismo nombre, misma firma, valor ya resuelto — no hace falta
        await). Usa print() para devolver algo: el valor de retorno de una
        expresión suelta NO se imprime solo. Builtins reducidos (sin import, open,
        eval, exec). Timeout 10s, stdout truncado a 4000 caracteres."""
        audit and audit.record("run_script", "mcp", codigo)
        stdout, error = ejecutar(codigo, tools_script)
        return {"stdout": stdout, "error": error, "tools_disponibles": disponibles}

    return [run_script]