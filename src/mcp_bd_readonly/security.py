import re

FORBIDDEN_FIRST = re.compile(
    r"^\s*(insert|update|delete|drop|truncate|alter|replace|create|grant|revoke|rename)\b",
    re.IGNORECASE,
)


class ReadOnlyViolation(Exception):
    pass


def _split_statements(sql: str) -> list[str]:
    return [s for s in sql.split(";") if s.strip()]


def is_read_only(sql: str) -> bool:
    if any(FORBIDDEN_FIRST.search(s) for s in _split_statements(sql)):
        return False
    return True


def enforce_read_only(sql: str) -> None:
    if not is_read_only(sql):
        raise ReadOnlyViolation(sql)
