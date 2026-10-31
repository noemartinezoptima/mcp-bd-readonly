from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger
from mcp_bd_readonly.glosario import resolver as _resolver_dominio

def _quote_id(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"

def build_tools(executor: QueryExecutor, audit: AuditLogger):

    def list_databases() -> list[str]:
        """Lista las bases de datos disponibles (SHOW DATABASES)."""
        audit and audit.record("list_databases", "mcp", "SHOW DATABASES")
        cols, rows = executor.run("SHOW DATABASES", limit=None)
        return [r.get("Database") or next(iter(r.values())) for r in rows]

    def list_tables(esquema: str = "back") -> list[str]:
        """Lista las tablas de un esquema (default 'back')."""
        audit and audit.record("list_tables", "mcp", f"SHOW TABLES FROM {esquema}")
        cols, rows = executor.run(f"SHOW TABLES FROM {_quote_id(esquema)}", limit=None)
        key = cols[0]
        return [r[key] for r in rows]

    def describe_table(table: str) -> dict:
        """Columnas y tipos de una tabla (DESCRIBE). Devuelve {columns, rows}, lo
        mismo que run_query: una sola pieza de JSON en vez de un bloque de
        contenido por columna, que para una tabla de 32 campos costaba ~4 veces
        más en tokens y repetía Field/Type/Null/Key/Default/Extra en cada uno."""
        audit and audit.record("describe_table", "mcp", f"DESCRIBE {table}")
        from mcp_bd_readonly.dbutils import shape_rows
        return shape_rows(executor.run(f"DESCRIBE {_quote_id(table)}", limit=None))

    def run_query(query: str, limit: int | None = 100) -> dict:
        """SQL solo-lectura; devuelve {columns, rows, truncated} (JSON). limit = nº máximo de
        filas (default 100); None = todas, con tope duro de 50.000 filas (por encima devuelve
        error: agrega o filtra). limit 0 o negativo NO es válido: para contar usa COUNT(*).
        truncated=true cuando llegan exactamente `limit` filas: puede haber más, así que no
        uses len(rows) como total."""
        audit and audit.record("run_query", "mcp", query)
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise ValueError(
                    "run_query: limit debe ser None (todas las filas) o un entero >= 1. "
                    f"Recibido {limit!r}. Para contar usa una query con COUNT(*)."
                )
        from mcp_bd_readonly.dbutils import shape_rows
        cols, rows = executor.run(query, limit=limit)
        out = shape_rows((cols, rows))
        # Sobredice a propósito: si llegan exactamente `limit` filas no hay forma
        # de saber sin otra consulta si hay más, y dar por buena una cifra
        # recortada es un error material en contabilidad. Mejor un falso positivo
        # (se re-consulta con COUNT) que un falso negativo (se informa mal).
        out["truncated"] = limit is not None and len(rows) >= limit
        return out

    return [list_databases, list_tables, describe_table, run_query]


def build_glosario_tools(audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("resolve_domain_term", "Mapea una frase de negocio en español a términos canónicos del catálogo Optima (tabla + herramienta MCP + trampas). Llamar para desambiguar antes de elegir query.")
    def tool_resolve_domain_term(texto: str) -> dict:
        audit and audit.record("resolve_domain_term", "mcp", f"resolve_domain_term({texto})")
        return _resolver_dominio(texto)

    return [tool_resolve_domain_term]
