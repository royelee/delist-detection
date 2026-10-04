"""The payout rule of one ending (operator decision 2026-10-03; docs/superpowers/plans/2026-10-03-payout-rule.md):
what one share turned into, as a rule and its terms, so the caller computes

    dlret = payout per share / last trading close - 1

with its own prices. contract/delistings.csv carries the ten columns of `value_fields`: `value_rule` (one of
`VALUE_RULES`), `cash_per_share`, `cash_currency` (always blank: no source records one), `stock_ratio`,
`price_sec_id`/`price_ticker`/`price_date` (whose price the rule needs, and when: the trading day after the last
trade, as price_requests dates it), `recovery_ratio`, `terms_source`, `terms_gate` and `value_formula`.

A merger's terms come, in order, from a --merger-terms row (no gate), from the terms its delistings.csv row carries
(they passed the payout gate; `terms_gate` is `passed`, or blank when no last close existed to check them), else
from what the library read before the gate dropped them (the LLM terms, else the regex payout): `terms_gate` is
`failed`. An election the gate dropped publishes both legs as read (THI's "election" is cash and stock; the failed
gate tells the caller to re-check). Pure, on string rows
as store.read_table returns them."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .exit_kind import ending_fields
from .observations import normalize_ticker
from .reconstruction import for_delisting
from .store import DelistingKey
from .trading_calendar import next_trading_day

VALUE_RULES = frozenset({"cash", "stock", "cash_plus_stock", "otc_print", "recovery", "worthless", "transfer",
                         "continuation", "expiration", "unknown"})
OVERRIDE_SOURCE = "--merger-terms"
PASSED, FAILED = "passed", "failed"


@dataclass(frozen=True)
class MergerInputs:
    """What the pipeline holds about one merger ending beyond its delistings.csv row."""
    override: Mapping[str, Any] | None = None     # the --merger-terms row (cash_per_share, stock_ratio, acquirer_*)
    llm: Any = None                               # llm_merger_extractor.MergerTerms, before the payout gate
    raw_value: float | None = None                # the regex payout read, before the gate
    raw_source: str = ""
    acquirer_sec_id: str = ""
    price_ticker: str = ""        # the acquirer security's symbol on the price date (sub-plan 5e), over the terms'


def merger_inputs(endings: Sequence[Mapping[str, str]], llm_terms: Mapping, raw: Mapping, merger_terms: Mapping,
                  acquirer_ids: Mapping, price_tickers: Mapping = {}) -> dict[DelistingKey, MergerInputs]:
    """The inputs of each merger-bucket ending (`endings`: delistings.csv rows)."""
    out: dict[DelistingKey, MergerInputs] = {}
    for r in endings:
        if r["bucket"] != "merger":
            continue
        key = DelistingKey(r["sec_id"], r["delist_date"])
        pr = raw.get(key)
        out[key] = MergerInputs(for_delisting(merger_terms, key), llm_terms.get(key),
                                getattr(pr, "value", None), getattr(pr, "source", "") or "",
                                acquirer_ids.get(key, "") or r["acquirer_sec_id"], price_tickers.get(key, ""))
    return out


def _num(cell: str) -> float | None:
    return float(cell) if cell not in ("", None) else None


def _blank() -> dict[str, Any]:
    return {"value_rule": "unknown", "cash_per_share": None, "cash_currency": "", "stock_ratio": None,
            "price_sec_id": "", "price_ticker": "", "price_date": "", "recovery_ratio": None,
            "terms_source": "", "terms_gate": "", "value_formula": ""}


def _day_after(last_trade_date: str) -> str:
    return next_trading_day(date.fromisoformat(last_trade_date)).isoformat() if last_trade_date else ""


def _merger(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs) -> dict[str, Any]:
    out = _blank()
    llm, override = inputs.llm, inputs.override
    if override:
        cash, ratio = override.get("cash_per_share"), override.get("stock_ratio")
        ticker = override.get("acquirer_ticker") or (llm.acquirer_ticker if llm else "") or row["acquirer_ticker"]
        source, gate = OVERRIDE_SOURCE, ""
    elif row["payout_per_share"] or row["stock_ratio"]:
        cash, ratio = _num(row["payout_per_share"]), _num(row["stock_ratio"])
        ticker = row["acquirer_ticker"] or (llm.acquirer_ticker if llm else "")
        source = row["payout_source"] or "llm"
        gate = PASSED if row["last_trade_close"] else ""
    elif llm is not None and (llm.cash_per_share or llm.stock_ratio):
        cash, ratio, ticker = llm.cash_per_share, llm.stock_ratio, llm.acquirer_ticker or ""
        source, gate = "llm", FAILED
    elif inputs.raw_value is not None:
        cash, ratio, ticker = inputs.raw_value, None, ""
        source, gate = inputs.raw_source or "regex", FAILED
    else:
        return out
    ticker = inputs.price_ticker or (normalize_ticker(ticker) if ticker else "")
    price_date = _day_after(last_trade_date)
    leg = ""
    if ratio:
        leg = f"{ratio:.6g} × price({ticker or '?'}, {price_date or '?'})"
    if cash and ratio:
        rule, payout = "cash_plus_stock", f"({cash:.2f} + {leg})"
    elif ratio:
        rule, payout = "stock", leg
    else:
        rule, payout = "cash", f"{cash:.2f}"
    out.update(value_rule=rule, cash_per_share=cash or None, stock_ratio=ratio or None, terms_source=source,
               terms_gate=gate, value_formula=f"{payout} / last_close − 1")
    if ratio:
        out.update(price_sec_id=inputs.acquirer_sec_id or row["acquirer_sec_id"], price_ticker=ticker,
                   price_date=price_date)
    return out


def _otc(row: Mapping[str, str], last_trade_date: str) -> dict[str, Any]:
    out, day = _blank(), _day_after(last_trade_date)
    out.update(value_rule="otc_print", price_sec_id=row["sec_id"], price_ticker=row["ticker"], price_date=day,
               value_formula=f"otc_print({row['ticker']}, from {day or '?'}) / last_close − 1")
    return out


def value_fields(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs | None = None) -> dict[str, Any]:
    """The payout-rule columns of one ending: `row` is its delistings.csv row, `last_trade_date` the date the
    contract publishes (blank when none), `inputs` the merger's pre-gate reads and overrides."""
    f = ending_fields(row)
    if f.continuation:
        return {**_blank(), "value_rule": "continuation"}
    bucket = row["bucket"]
    if bucket == "merger":
        return _merger(row, last_trade_date, inputs or MergerInputs())
    out = _blank()
    if bucket == "exchange_transfer":
        out["value_rule"] = "transfer"
    elif bucket == "liquidation" and row["recovery_ratio"]:
        ratio = float(row["recovery_ratio"])
        out.update(value_rule="recovery", recovery_ratio=ratio, value_formula=f"{ratio:.4f} − 1")
    elif bucket == "liquidation" and row["dlret_method"] == "worthless":
        out.update(value_rule="worthless", value_formula="0 − 1")
    elif bucket in ("liquidation", "compliance_failure") or f.exit_kind == "dropped":
        out = _otc(row, last_trade_date)
    elif bucket == "expiration":
        out["value_rule"] = "expiration"
    return out
