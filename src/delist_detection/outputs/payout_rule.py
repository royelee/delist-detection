"""The payout rule of one ending, as the contract writes it (operator decision 2026-10-03;
docs/superpowers/plans/2026-10-03-payout-rule.md): what one share turned into, as a rule and its terms, so the caller
computes

    dlret = payout per share / last trading close - 1

with its own prices. The rule and its terms are decided once, by `dlret.rule_of` (architecture step 10): which rule,
which terms (a --merger-terms row, the terms the payout gate kept, else what the library read before the gate dropped
them), their source and the gate's verdict, and whose price it needs. This module writes that answer as
contract/delistings.csv's eleven columns (`value_fields`): `value_rule` (one of `exit_kind.VALUE_RULES`),
`cash_per_share`, `cash_currency` (ruling R5: as the filing states it; blank for a --merger-terms row and when no
cash), `stock_ratio`, `price_sec_id`/`price_ticker`/`price_date` (whose price the rule needs, and when: the trading day
after the last trade, as price_requests dates it), `recovery_ratio`, `terms_source`, `terms_gate` and `value_formula`;
and a basket's legs as contract/payout_legs.csv's rows (`basket_legs`, ruling R3).

A stock leg stated as a dollar value (PCYC) is written in `value_formula` over the acquirer's averaging price, with no
ratio; the averaging period is named there as the filing words it (`avg_price(ABBV: ten consecutive trading days
ending on and including the second trading day prior to the final expiration date of the offer)`). A bankruptcy
plan's ratio is written with the filing's own digits. Pure, on string rows as store.read_table returns them; it loads
no client."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from .dlret import DistressTerms, MergerInputs, Rule, StockLeg, rule_of
from ..vocabulary.trading_calendar import next_trading_day


def _blank() -> dict[str, Any]:
    return {"value_rule": "unknown", "cash_per_share": None, "cash_currency": "", "stock_ratio": None,
            "price_sec_id": "", "price_ticker": "", "price_date": "", "recovery_ratio": None,
            "terms_source": "", "terms_gate": "", "value_formula": ""}


def _day_after(last_trade_date: str) -> str:
    return next_trading_day(date.fromisoformat(last_trade_date)).isoformat() if last_trade_date else ""


def _price(ticker: str, day: str) -> str:
    return f"price({ticker or '?'}, {day or '?'})"


def _leg(leg: StockLeg, day: str) -> str:
    """A stock leg's term: its ratio (a plan's as the filing words it) times the line's price, or a dollar value over
    the averaging price (PCYC: $109.00 of AbbVie)."""
    if leg.ratio:
        ratio = leg.ratio if isinstance(leg.ratio, str) else f"{leg.ratio:.6g}"
        return f"{ratio} × {_price(leg.ticker, day)}"
    window = f": {leg.window}" if leg.window else ""
    return f"{leg.value:.2f} × {_price(leg.ticker, day)} / avg_price({leg.ticker or '?'}{window})"


def _formula(rule: Rule, day: str) -> str:
    if rule.name == "basket":
        parts = ([f"{rule.cash:.2f}"] if rule.cash else []) + [
            f"{r:.6g} × {_price(t, day)}" for r, t, _ in rule.basket.legs(rule.basket_ticker)]
        return f"({' + '.join(parts)}) / last_close − 1"
    if rule.name == "cash_plus_stock":
        return f"({rule.cash:.2f} + {_leg(rule.leg, day)}) / last_close − 1"
    if rule.name == "stock":
        return f"{_leg(rule.leg, day)} / last_close − 1"
    if rule.name == "cash":
        return f"{rule.cash:.2f} / last_close − 1"
    if rule.name == "recovery":
        return f"{rule.recovery_ratio:.4f} − 1"
    if rule.name == "worthless":
        return "0 − 1"
    if rule.name == "otc_print":
        return f"otc_print({rule.print_symbol or '?'}, from {day or '?'}) / last_close − 1"
    return ""


def value_fields(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs | None = None,
                 distress: DistressTerms | None = None) -> dict[str, Any]:
    """The payout-rule columns of one ending: `row` is its delistings.csv row, `last_trade_date` the date the
    contract publishes (blank when none), `inputs` the merger's pre-gate reads and overrides, `distress` what
    stage 9e read for a drop or a bankruptcy (its OTC symbol, a plan's ratio; None: not read)."""
    rule = rule_of(row, inputs, distress)
    day = _day_after(last_trade_date)
    out = {**_blank(), "value_rule": rule.name, "terms_source": rule.terms_source, "terms_gate": rule.terms_gate,
           "value_formula": _formula(rule, day)}
    if rule.cash:
        out.update(cash_per_share=rule.cash, cash_currency=rule.currency)
    if rule.leg is not None:
        out.update(stock_ratio=rule.leg.ratio, price_sec_id=rule.leg.sec_id, price_ticker=rule.leg.ticker,
                   price_date=day)
    if rule.name == "otc_print":
        out.update(price_sec_id=rule.print_sec_id, price_ticker=rule.print_symbol, price_date=day)
    if rule.recovery_ratio is not None:
        out["recovery_ratio"] = rule.recovery_ratio
    return out


def basket_legs(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs | None) -> list[dict[str, Any]]:
    """contract/payout_legs.csv's rows of one ending (ruling R3): each security of a basket per share, with the
    security, ticker and date its price is needed on (the main leg's security is the acquirer stage 8 found, the
    others the run's holder of their ticker, `MergerInputs.leg_sec_ids`), and the leg's share class as the answer
    names it (`MergerTerms.legs`: a further leg's ticker is its own class's); none unless the ending's value rule is
    `basket`."""
    if inputs is None:
        return []
    rule = rule_of(row, inputs)
    if rule.name != "basket":
        return []
    main = inputs.price_ticker or rule.basket.ticker
    day = _day_after(last_trade_date)
    out = []
    for n, (ratio, ticker, share_class) in enumerate(rule.basket.legs(main), start=1):
        sid = (inputs.acquirer_sec_id or row["acquirer_sec_id"]) if n == 1 else inputs.leg_sec_ids.get(ticker, "")
        out.append({"sec_id": row["sec_id"], "leg": n, "ratio": ratio, "share_class": share_class,
                    "price_sec_id": sid, "price_ticker": ticker, "price_date": day})
    return out
