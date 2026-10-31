"""Guard de solo-lectura: dos barreras antes de abrir conexión.

1. La PRIMERA palabra debe pertenecer a {SELECT, SHOW, DESCRIBE, DESC, EXPLAIN, WITH}.
2. Ningún verbo DML/DDL/admin puede aparecer en NINGUNA posición, y solo se
   admite un statement.

La barrera 2 es la que cierra `WITH c AS (...) DELETE FROM t`, que en MySQL 8
es válido y el allowlist de primera palabra por sí solo dejaba pasar. Antes de
buscar verbos se eliminan comentarios y literales de texto, para no vetar una
columna `credit_limit` ni un valor `'sin limit'`.
"""

import re

LEADING_COMMENTS = re.compile(r"^(?:\s*(?:--[^\n]*\n|#[^\n]*\n|/\*.*?\*/))*\s*", re.S)

# Primera palabra admitida.
STATEMENT_ALLOWED = frozenset({"select", "show", "describe", "desc", "explain", "with"})

# Verbos vetados en cualquier posición (se comparan como palabras completas).
FORBIDDEN_WORDS = (
    "insert", "update", "replace", "delete", "drop", "truncate", "alter",
    "create", "rename", "grant", "revoke", "call", "load", "handler",
    "lock", "unlock", "set", "prepare", "execute", "deallocate", "flush",
    "kill", "optimize", "repair", "analyze", "install", "uninstall",
    "shutdown", "restart", "backup", "restore", "purge", "savepoint",
    "commit", "rollback", "begin", "start", "do", "use",
    "into", "outfile", "dumpfile", "sleep", "benchmark", "get_lock",
    "load_file",
)

# Esquemas del sistema que no se exponen (information_schema sí: lo usa el snapshot).
DENIED_SCHEMAS = ("mysql", "performance_schema", "sys")

_STRING = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"", re.S)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# Comentario "ejecutable" de MySQL: `/*! código */` o `/*!50001 código */`.
# MySQL lo trata como SQL real a ejecutar (no como comentario) si la versión
# coincide — nuestro _BLOCK_COMMENT genérico sí lo trataba como comentario y
# descartaba su contenido ANTES de buscar verbos prohibidos, dejando pasar
# `SELECT 1 /*!50000 ; DELETE FROM x */` porque "delete" nunca llegaba a
# escanearse. Sin uso legítimo en lectura: se rechaza directamente.
_EXEC_COMMENT = re.compile(r"/\*!")
_LINE_COMMENT = re.compile(r"--[^\n]*|#[^\n]*")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FOR_UPDATE = re.compile(
    r"\bfor\s+(?:update|share)\b|\block\s+in\s+share\s+mode\b|\bnowait\b|\bskip\s+locked\b",
    re.I,
)


class ReadOnlyViolation(ValueError):
    """La sentencia intenta salir del modo solo-lectura."""


def _strip_literals(sql: str) -> str:
    """Quita comentarios y contenido de literales de texto.

    El orden importa: los comentarios de bloque pueden contener comillas, así
    que se eliminan antes de procesar strings.
    """
    s = _BLOCK_COMMENT.sub(" ", sql)
    s = _STRING.sub("''", s)
    s = _LINE_COMMENT.sub(" ", s)
    return s


def _statements(stripped: str) -> list[str]:
    return [p for p in stripped.split(";") if p.strip()]


def _denied_schema(stmt_lower: str) -> str | None:
    for schema in DENIED_SCHEMAS:
        # `mysql`.`user` y mysql.user, sin casar columnas como mysql_id.
        if re.search(rf"(?<![a-z0-9_])(?:`{schema}`|{schema})\s*\.", stmt_lower):
            return schema
    return None


def enforce_read_only(sql: str) -> None:
    """Lanza ReadOnlyViolation si la sentencia no es estrictamente de lectura."""
    if not isinstance(sql, str) or not sql.strip():
        raise ReadOnlyViolation("run_query: la query está vacía.")

    if _EXEC_COMMENT.search(sql):
        raise ReadOnlyViolation(
            "run_query: los comentarios ejecutables de MySQL (/*! ... */) no están "
            "permitidos: MySQL los trata como SQL real, no como comentario."
        )

    stmts = _statements(_strip_literals(sql))
    if not stmts:
        raise ReadOnlyViolation("run_query: la query no contiene ninguna sentencia ejecutable.")
    if len(stmts) > 1:
        raise ReadOnlyViolation(
            f"run_query: solo se admite un statement por llamada (se encontraron {len(stmts)}). "
            "Divide la consulta en varias llamadas."
        )

    stmt = stmts[0].strip()
    match = _WORD.match(stmt)
    first = match.group(0).lower() if match else ""
    if first not in STATEMENT_ALLOWED:
        raise ReadOnlyViolation(
            f"run_query: sentencia no permitida ({first or 'vacía'}). "
            "Solo SELECT / SHOW / DESCRIBE / DESC / EXPLAIN / WITH."
        )

    if _FOR_UPDATE.search(stmt):
        raise ReadOnlyViolation(
            "run_query: FOR UPDATE / LOCK IN SHARE MODE toman bloqueos de escritura "
            "y no están permitidos en modo solo-lectura."
        )

    words = {w.lower() for w in _WORD.findall(stmt)}
    bad = sorted(words.intersection(FORBIDDEN_WORDS))
    # SHOW CREATE TABLE/VIEW/PROCEDURE es introspección legítima y de solo lectura.
    if bad == ["create"] and first == "show":
        bad = []
    if bad:
        raise ReadOnlyViolation(
            f"run_query: la sentencia contiene {', '.join(bad)}, que no está permitido en lectura. "
            "Un WITH solo puede terminar en SELECT."
        )

    schema = _denied_schema(stmt.lower())
    if schema:
        raise ReadOnlyViolation(
            f"run_query: el esquema '{schema}' no está expuesto por este servidor."
        )
