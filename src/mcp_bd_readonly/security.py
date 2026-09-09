import re

FORBIDDEN_FIRST = re.compile(
    r"^\s*(insert|update|delete|drop|truncate|alter|replace|create|grant|revoke|rename)\b",
    re.IGNORECASE,
)


class ReadOnlyViolation(Exception):
    pass


def is_read_only(sql: str) -> bool:
    if FORBIDDEN_FIRST.search(sql):
        return False
    return True


def enforce_read_only(sql: str) -> None:
    if not is_read_only(sql):
        raise ReadOnlyViolation(sql)
