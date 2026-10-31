"""Tool de balance (hoja de situación) a partir de la contabilidad PGC.

Calcula el saldo por cuenta (debe − haber) desde accounting_entry_lines, y
clasifica cada cuenta por su pgc_group (subgrupo PGC) en activo/pasivo/
patrimonio/ingreso/gasto. Devuelve un balance que cuadra: activo − (pasivo +
patrimonio) == resultado.

NOTA: clasificación PGC simplificada por subgrupo (balance_nature está vacío en
la BD). El grupo 3 (existencias) está vacío en esta contabilidad.
"""

from decimal import Decimal

from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger

_PASIVO = ("40", "41", "42", "46", "49", "52", "55", "50", "51", "53", "17", "18", "19")
_ACTIVO_CTE = ("43", "44", "45", "47", "48", "57", "56")
_PATRIMONIO = ("10", "11", "12", "13", "14", "15", "16")


def _dec(v):
    return Decimal(str(v)) if v is not None else Decimal("0")


def _categoria(g) -> str:
    g = g or ""
    if g in _PATRIMONIO:
        return "patrimonio"
    if g[:1] == "2":
        return "activo_no_corriente"
    if g[:1] == "3":
        return "existencias"
    if g in _PASIVO:
        return "pasivo"
    if g in _ACTIVO_CTE:
        return "activo_corriente"
    if g[:1] == "6":
        return "gasto"
    if g[:1] == "7":
        return "ingreso"
    return "otro"


def balance(ex):
    """Balance de situación: activo / pasivo / patrimonio / resultado."""
    _, rows = ex.run(
        "SELECT a.pgc_group, SUM(l.debit_amount) debe, SUM(l.credit_amount) haber "
        "FROM accounting_entry_lines l "
        "JOIN accounting_accounts a ON a.id = l.accounting_account_id "
        "GROUP BY a.pgc_group",
        limit=None,
    )
    tot = {}
    for r in rows:
        d = _dec(r["debe"]) - _dec(r["haber"])  # saldo debe-haber
        c = _categoria(r["pgc_group"])
        tot[c] = tot.get(c, Decimal("0")) + d

    no_corriente = tot.get("activo_no_corriente", Decimal("0"))
    corriente = tot.get("activo_corriente", Decimal("0"))
    existencias = tot.get("existencias", Decimal("0"))
    pasivo = -tot.get("pasivo", Decimal("0"))
    patrimonio = -tot.get("patrimonio", Decimal("0"))
    ingresos = -tot.get("ingreso", Decimal("0"))
    gastos = tot.get("gasto", Decimal("0"))

    activo_total = no_corriente + existencias + corriente
    pasivo_patrimonio = pasivo + patrimonio
    resultado = ingresos - gastos

    return {
        "activo": {
            "no_corriente": no_corriente,
            "existencias": existencias,
            "corriente": corriente,
            "total": activo_total,
        },
        "pasivo": {"total": pasivo},
        "patrimonio": {"total": patrimonio},
        "pasivo_patrimonio_total": pasivo_patrimonio,
        "ingresos": ingresos,
        "gastos": gastos,
        "resultado": resultado,
        "cuadra": activo_total - pasivo_patrimonio,
    }


def build_balance_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("balance", "Balance de situación (activo/pasivo/patrimonio/resultado) desde contabilidad PGC. Cuadra: activo − (pasivo+patrimonio) = resultado.")
    def tool_balance():
        audit and audit.record("balance", "mcp", "balance")
        return balance(executor)

    return [tool_balance]
