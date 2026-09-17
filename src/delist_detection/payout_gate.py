"""Check every merger payout against the last trade before it reaches the table.

A completed deal trades at its consideration, so a payout far from the last
close is a misread (VRTV $1.00 vs $169.99, TWO $25 vs $12.18) or a stale
vendor price (CAB $0.03). Either way the number must not become a return."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reconciled:
    cash: float | None
    stock_ratio: float | None
    acquirer_price: float | None
    source: str
    flags: tuple[str, ...]


def _fits(value: float | None, last_close: float, tol: float) -> bool:
    return value is not None and value > 0 and abs(value / last_close - 1.0) <= tol


def reconcile(regex_value, last_close, llm_terms, acquirer_price, tol) -> Reconciled:
    if last_close is None or last_close <= 0:
        return Reconciled(regex_value, None, None, "regex" if regex_value is not None else "none",
                          ("no_last_close",))
    flags: list[str] = []
    if regex_value is not None:
        if _fits(regex_value, last_close, tol):
            return Reconciled(regex_value, None, None, "regex", ())
        flags.append(f"payout_gate_failed:{regex_value:g}")
    if llm_terms is not None:
        cash, ratio = llm_terms.cash_per_share, llm_terms.stock_ratio
        stock = ratio * acquirer_price if ratio is not None and acquirer_price is not None else None
        if llm_terms.deal_type == "election":
            if _fits(stock, last_close, tol):
                return Reconciled(None, ratio, acquirer_price, "llm_election_stock", tuple(flags))
            if _fits(cash, last_close, tol):
                return Reconciled(cash, None, None, "llm_election_cash", tuple(flags))
        elif llm_terms.deal_type == "cash" and _fits(cash, last_close, tol):
            return Reconciled(cash, None, None, "llm", tuple(flags))
    return Reconciled(None, None, None, "none", tuple(flags))
