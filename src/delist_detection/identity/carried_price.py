"""Whether a share became one share across a CUSIP change: the price carried over.

A share that became one share keeps its price about where it was (GGP 2010: 17.39 to 15.40); a bankruptcy plan's new
shares (Seadrill 2018: 0.10 to 18.50), a spin-off that takes the ticker (The Aaron's Company 2020: 62.93 to 18.41), a
merger that gives a new CUSIP under the old ticker (Uniti 2025: 4.91 to 8.09) and a reverse split (WE 2023, 1-for-40:
32) do not. One band is read by the two places that ask it: the identity stage, for a derived era that joins the line it
came from (`identity.identify`, rule J), and the handoff stage, for a continuation by timing across two issuers
(`endings.handoffs.decide_handoff`).
"""
from __future__ import annotations

from ..sources.ftd import FtdIndex

CARRIED_PRICE: tuple[float, float] = (2 / 3, 3 / 2)    # the new CUSIP's first fails price over the old one's last


def price_carried(ratio: float | None) -> bool:
    """Whether a price ratio lies in `CARRIED_PRICE`; an unknown ratio (None) counts as carried."""
    return ratio is None or CARRIED_PRICE[0] <= ratio <= CARRIED_PRICE[1]


def step_price_ratio(ftd: FtdIndex, ticker: str, old_cusip: str, new_cusip: str) -> float | None:
    """The new CUSIP's first fails price under `ticker` over the old CUSIP's last one on or before that day. None when
    either CUSIP has no row under the ticker (on that side of the day), or either price is missing or not above zero."""
    rows = ftd.by_symbol(ticker)
    new = next((r for r in rows if r.cusip == new_cusip), None)
    old = next((r for r in reversed(rows) if r.cusip == old_cusip and new is not None and r.date <= new.date), None)
    if new is None or old is None:
        return None
    a, b = old.price, new.price
    return b / a if a and b and a > 0 and b > 0 else None
