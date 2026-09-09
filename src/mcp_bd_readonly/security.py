import re

FORBIDDEN_FIRST = re.compile(
    r"^\s*(insert|update|delete|drop|truncate|alter|replace|create|grant|revoke|rename)\b",
    re.IGNORECASE,
)

LEADING_COMMENTS = re.compile(r"^\s*(?:(?:--[^\n]*|#[^\n]*|/\*.*?\*/)\s*)*", re.DOTALL)


class ReadOnlyViolation(Exception):
    pass


def _split_statements(sql: str) -> list[str]:
    return [s for s in sql.split(";") if s.strip()]


def _strip_leading_comments(stmt: str) -> str:
    return LEADING_COMMENTS.sub("", stmt, count=1)


def is_read_only(sql: str) -> bool:
    for s in _split_statements(sql):
        stripped = _strip_leading_comments(s)
        if FORBIDDEN_FIRST.search(stripped):
            return False
    return True


def enforce_read_only(sql: str) -> None:
    if not is_read_only(sql):
        raise ReadOnlyViolation(sql)
