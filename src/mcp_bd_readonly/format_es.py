from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28


def _dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


def exact_sum(values) -> Decimal:
    total = sum((_dec(v) for v in values), Decimal("0"))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt_money(v) -> str:
    d = _dec(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    grouped = f"{d:,.2f}"
    return grouped.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def fmt_date(d) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d/%m/%Y")