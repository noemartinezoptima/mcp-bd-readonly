from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger

def _quote_id(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"

def build_tools(executor: QueryExecutor, audit: AuditLogger):

    def list_databases() -> list[str]:
        """Lista las bases de datos disponibles (SHOW DATABASES)."""
        audit and audit.record("list_databases", "mcp", "SHOW DATABASES")
        cols, rows = executor.run("SHOW DATABASES", limit=None)
        return [r.get("Database") or next(iter(r.values())) for r in rows]

    def list_tables(schema: str = "back") -> list[str]:
        """Lista las tablas de un esquema (default 'back')."""
        audit and audit.record("list_tables", "mcp", f"SHOW TABLES FROM {schema}")
        cols, rows = executor.run(f"SHOW TABLES FROM {_quote_id(schema)}", limit=None)
        key = cols[0]
        return [r[key] for r in rows]

    def describe_table(table: str) -> list[dict]:
        """Columnas y tipos de una tabla (DESCRIBE)."""
        audit and audit.record("describe_table", "mcp", f"DESCRIBE {table}")
        _, rows = executor.run(f"DESCRIBE {_quote_id(table)}", limit=None)
        return rows

    def run_query(query: str, limit: int = 100) -> dict:
        """SQL solo-lectura; devuelve {columns, rows} (JSON). limit clamp filas (default 100; 0=sólo conteo, None=todo)."""
        audit and audit.record("run_query", "mcp", query)
        from mcp_bd_readonly.dbutils import shape_rows
        return shape_rows(executor.run(query, limit=limit))

    return [list_databases, list_tables, describe_table, run_query]
