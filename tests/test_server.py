from mcp_bd_readonly.tools_core import build_tools


def test_registers_four():
    tools = build_tools(executor=None, audit=None)
    names = {t.__name__ for t in tools}
    assert {"list_databases", "list_tables", "describe_table", "run_query"} <= names


class FakeExecutor:
    def __init__(self, cols, rows):
        self._cols = cols
        self._rows = rows
        self.sqls = []

    def run(self, sql, params=None, limit=100):
        self.sqls.append(sql)
        return self._cols, self._rows


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_list_databases():
    executor = FakeExecutor(
        ["Database"],
        [{"Database": "back"}, {"Database": "information_schema"}],
    )
    audit = FakeAudit()
    [list_databases, *_] = build_tools(executor, audit)
    result = list_databases()
    assert result == ["back", "information_schema"]
    assert audit.calls[0][0] == "list_databases"


def test_list_databases_key_fallback():
    executor = FakeExecutor(
        ["db"],
        [{"db": "back"}],
    )
    [list_databases, *_] = build_tools(executor, None)
    result = list_databases()
    assert result == ["back"]


def test_list_tables():
    executor = FakeExecutor(
        ["Tables_in_back"],
        [{"Tables_in_back": "users"}, {"Tables_in_back": "orders"}],
    )
    audit = FakeAudit()
    [_, list_tables, *_] = build_tools(executor, audit)
    result = list_tables("back")
    assert result == ["users", "orders"]
    assert executor.sqls[0] == "SHOW TABLES FROM `back`"
    assert audit.calls[0][2] == "SHOW TABLES FROM back"


def test_describe_table():
    executor = FakeExecutor(
        ["Field", "Type"],
        [{"Field": "id", "Type": "int(11)"}],
    )
    audit = FakeAudit()
    [_, _, describe_table, *_] = build_tools(executor, audit)
    result = describe_table("users")
    assert result == [{"Field": "id", "Type": "int(11)"}]
    assert executor.sqls[0] == "DESCRIBE `users`"
    assert audit.calls[0][2] == "DESCRIBE users"


def test_run_query():
    executor = FakeExecutor(
        ["id", "name"],
        [{"id": 1, "name": "Alice"}],
    )
    audit = FakeAudit()
    [_, _, _, run_query] = build_tools(executor, audit)
    result = run_query("SELECT id, name FROM users")
    assert result == {"columns": ["id", "name"], "rows": [[1, "Alice"]]}
    assert audit.calls[0][0] == "run_query"


def test_run_query_no_columns():
    executor = FakeExecutor([], [])
    [_, _, _, run_query] = build_tools(executor, None)
    result = run_query("SELECT 1")
    assert result == {"columns": [], "rows": []}


def test_describe_table_escapes_backticks():
    executor = FakeExecutor(["Field"], [])
    [_, _, describe_table, _] = build_tools(executor, None)
    describe_table("a`b")
    assert executor.sqls[0] == "DESCRIBE `a``b`"


def test_list_tables_quotes_schema():
    executor = FakeExecutor(["Tables_in_back"], [])
    [_, list_tables, _, _] = build_tools(executor, None)
    list_tables("my`db")
    assert executor.sqls[0] == "SHOW TABLES FROM `my``db`"
