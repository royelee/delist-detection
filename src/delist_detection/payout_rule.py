"""The payout rule of one ending (operator decision 2026-10-03; docs/superpowers/plans/2026-10-03-payout-rule.md):
what one share turned into, as a rule and its terms, so the caller computes

    dlret = payout per share / last trading close - 1

with its own prices. contract/delistings.csv carries the eleven columns of `value_fields`: `value_rule` (one of
`VALUE_RULES`), `cash_per_share`, `cash_currency` (ruling R5: as the filing states it, from the read that supplied
the cash: the LLM's answer or the regex hit's "$"; blank for a --merger-terms row and when no cash), `stock_ratio`,
`price_sec_id`/`price_ticker`/`price_date` (whose price the rule needs, and when: the trading day after the last
trade, as price_requests dates it), `recovery_ratio`, `terms_source`, `terms_gate` and `value_formula`.

A merger's terms come, in order, from a --merger-terms row (no gate), from the terms its delistings.csv row carries
(they passed the payout gate; `terms_gate` is `passed`, or blank when no last close existed to check them), else
from what the library read before the gate dropped them (the LLM terms, else the regex payout): `terms_gate` is
`failed`, `skipped` when the gate could not check them (`terms_gate_skipped`: a non-USD cash leg, a basket, a
dollar-valued stock leg), or blank when no last close existed. An LLM answer (prompt v3, sub-plan 5f) is the
package one share became (ruling R4). A package of two or more securities is the rule `basket` (ruling R3): the
main row keeps the cash and `basket_legs` gives contract/payout_legs.csv's rows. A stock leg stated as a dollar
value (PCYC) is carried in `value_formula` over the acquirer's averaging price, with no ratio; the averaging period
is named there as the filing words it (`avg_price(ABBV: ten consecutive trading days ending on and including the
second trading day prior to the final expiration date of the offer)`: `MergerTerms.value_window`). A drop or a
bankruptcy is priced at its first off-exchange print under its own OTC symbol, and a bankruptcy plan that gave the
old holders new shares is the stock rule on the new line (ruling R6), from what stage 9e read
(`distress.DistressTerms`, sub-plan 5g). Pure, on string rows as store.read_table returns them."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass, replace
from datetime import date
from types import SimpleNamespace
from typing import Any

from .distress import DistressTerms
from .exit_kind import ending_fields
from .observations import normalize_ticker
from .payout_gate import is_package
from .reconstruction import for_delisting
from .store import DelistingKey
from .trading_calendar import next_trading_day

VALUE_RULES = frozenset({"cash", "stock", "cash_plus_stock", "basket", "otc_print", "recovery", "worthless",
                         "transfer", "continuation", "expiration", "unknown"})
OVERRIDE_SOURCE = "--merger-terms"
PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"
SKIPPED_FLAG = "terms_gate_skipped"


@dataclass(frozen=True)
class MergerInputs:
    """What the pipeline holds about one merger ending beyond its delistings.csv row."""
    override: Mapping[str, Any] | None = None     # the --merger-terms row (cash_per_share, stock_ratio, acquirer_*)
    llm: Any = None                               # llm_merger_extractor.MergerTerms, before the payout gate
    raw_value: float | None = None                # the regex payout read, before the gate
    raw_source: str = ""
    acquirer_sec_id: str = ""
    price_ticker: str = ""        # the acquirer security's symbol on the price date (sub-plan 5e), over the terms'
    raw_currency: str = ""        # the regex read's currency (ruling R5)
    leg_sec_ids: Mapping[str, str] = field(default_factory=dict)   # a basket's further legs: ticker -> sec_id


def merger_inputs(endings: Sequence[Mapping[str, str]], llm_terms: Mapping, raw: Mapping, merger_terms: Mapping,
                  acquirer_ids: Mapping, price_tickers: Mapping = {},
                  leg_sec_ids: Mapping = {}) -> dict[DelistingKey, MergerInputs]:
    """The inputs of each merger-bucket ending (`endings`: delistings.csv rows)."""
    out: dict[DelistingKey, MergerInputs] = {}
    for r in endings:
        if r["bucket"] != "merger":
            continue
        key = DelistingKey(r["sec_id"], r["delist_date"])
        pr = raw.get(key)
        out[key] = MergerInputs(for_delisting(merger_terms, key), llm_terms.get(key),
                                getattr(pr, "value", None), getattr(pr, "source", "") or "",
                                acquirer_ids.get(key, "") or r["acquirer_sec_id"], price_tickers.get(key, ""),
                                getattr(pr, "currency", "") or "", leg_sec_ids.get(key, {}))
    return out


def _num(cell: str) -> float | None:
    return float(cell) if cell not in ("", None) else None


def _blank() -> dict[str, Any]:
    return {"value_rule": "unknown", "cash_per_share": None, "cash_currency": "", "stock_ratio": None,
            "price_sec_id": "", "price_ticker": "", "price_date": "", "recovery_ratio": None,
            "terms_source": "", "terms_gate": "", "value_formula": ""}


def _day_after(last_trade_date: str) -> str:
    return next_trading_day(date.fromisoformat(last_trade_date)).isoformat() if last_trade_date else ""


def _ungated(row: Mapping[str, str]) -> str:
    """The terms_gate of terms the payout gate did not keep: `skipped` when it could not check them (a non-USD
    cash leg, a basket, a dollar-valued leg: `terms_gate_skipped`), `failed` when it checked and refused them, and
    blank when no last close existed to check them against."""
    if any(f.startswith(SKIPPED_FLAG) for f in (row.get("review_flags") or "").split(";")):
        return SKIPPED
    return FAILED if row["last_trade_close"] else ""


def _llm_published(row: Mapping[str, str], inputs: MergerInputs):
    """The LLM terms whose own legs the ending publishes (a dollar-valued leg, a basket): the terms the gate did
    not keep, published as read; None for a --merger-terms row, terms the gate kept, or a regex read. An answer that
    states no package (prompt v3 basis `none`, or an earlier prompt's) holds an election's alternatives, never the
    package: only its all-cash alternative is published, else nothing (TRH 2012: the stock alternative is no
    package)."""
    llm = inputs.llm
    if inputs.override or row["payout_per_share"] or row["stock_ratio"]:
        return None
    if llm is not None and llm.deal_type == "election" and not is_package(llm):
        cash_only = dict(stock_ratio=None, stock_value=None, extra_legs=())
        llm = (replace(llm, **cash_only) if is_dataclass(llm) else SimpleNamespace(**{**vars(llm), **cash_only})) \
            if llm.cash_per_share else None
    return llm if llm is not None and (llm.cash_per_share or getattr(llm, "has_stock", llm.stock_ratio)) else None


def _merger(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs) -> dict[str, Any]:
    out = _blank()
    llm, override = inputs.llm, inputs.override
    terms = _llm_published(row, inputs)
    if override:
        cash, ratio = override.get("cash_per_share"), override.get("stock_ratio")
        ticker = override.get("acquirer_ticker") or (llm.acquirer_ticker if llm else "") or row["acquirer_ticker"]
        source, gate, currency = OVERRIDE_SOURCE, "", ""
    elif row["payout_per_share"] or row["stock_ratio"]:
        cash, ratio = _num(row["payout_per_share"]), _num(row["stock_ratio"])
        ticker = row["acquirer_ticker"] or (llm.acquirer_ticker if llm else "")
        source = row["payout_source"] or "llm"
        gate = PASSED if row["last_trade_close"] else ""
        currency = (getattr(llm, "cash_currency", "") if llm is not None else "") if source.startswith("llm") \
            else inputs.raw_currency
    elif terms is not None:
        cash, ratio, ticker = terms.cash_per_share, terms.stock_ratio, terms.acquirer_ticker or ""
        source, gate, currency = "llm", _ungated(row), getattr(terms, "cash_currency", "")
    elif inputs.raw_value is not None:
        cash, ratio, ticker = inputs.raw_value, None, ""
        source, gate, currency = inputs.raw_source or "regex", _ungated(row), inputs.raw_currency
    else:
        return out
    # a --merger-terms row's acquirer ticker is the caller's, published as given; else the acquirer security's
    # symbol on the price date (the request's ticker), over the terms'
    ticker = (normalize_ticker(ticker) if ticker else "") if override else (
        inputs.price_ticker or (normalize_ticker(ticker) if ticker else ""))
    price_date = _day_after(last_trade_date)
    common = dict(cash_per_share=cash or None, cash_currency=(currency or "") if cash else "", terms_source=source,
                  terms_gate=gate)
    if terms is not None and getattr(terms, "is_basket", False):
        # ruling R3: two or more securities per share; the main row keeps the cash, payout_legs.csv the legs
        parts = ([f"{cash:.2f}"] if cash else []) + [
            f"{r:.6g} × price({t or '?'}, {price_date or '?'})" for r, t, _ in leg_terms(terms, ticker)]
        out.update(value_rule="basket", value_formula=f"({' + '.join(parts)}) / last_close − 1", **common)
        return out
    value = getattr(terms, "stock_value", None) if terms is not None and not ratio else None
    leg = ""
    if ratio:
        leg = f"{ratio:.6g} × price({ticker or '?'}, {price_date or '?'})"
    elif value:
        # a stock leg stated as a dollar value over the acquirer's averaging price (PCYC: $109.00 of AbbVie)
        window = getattr(terms, "value_window", "") or ""
        leg = (f"{value:.2f} × price({ticker or '?'}, {price_date or '?'}) / "
               f"avg_price({ticker or '?'}{': ' + window if window else ''})")
    if cash and leg:
        rule, payout = "cash_plus_stock", f"({cash:.2f} + {leg})"
    elif leg:
        rule, payout = "stock", leg
    else:
        rule, payout = "cash", f"{cash:.2f}"
    out.update(value_rule=rule, stock_ratio=ratio or None, value_formula=f"{payout} / last_close − 1", **common)
    if leg:
        out.update(price_sec_id=inputs.acquirer_sec_id or row["acquirer_sec_id"], price_ticker=ticker,
                   price_date=price_date)
    return out


_LETTER = re.compile(r"(?i)\s*(?:(?:class|series)\s+)?([A-Z0-9])(?:\s+(?:common|ordinary)\b.*)?\s*")


def class_letter(text: str) -> str:
    """The letter of a share class the answer names ("B", "Class B", "Series C common"), "" for any other text
    ("preferred unit", "common")."""
    m = _LETTER.fullmatch(text or "")
    return m.group(1).upper() if m else ""


def leg_terms(terms, main_ticker: str) -> list[tuple[float, str, str]]:
    """(ratio, ticker, share class) of each leg of a basket, the main one first (its ticker as the main row would
    publish it). A further leg's ticker is the one its own class trades under: a leg that repeats an earlier leg's
    ticker with another class letter takes the class ticker (CAA 2018's Lennar class B under the class A's LEN is
    LEN-B, as the fails rows spell it), a repeat with no class letter and a preferred class (BPYU 2021's "BPY
    preferred unit", not the common units' BPY) have none, so no price is asked of the wrong security."""
    out = [(terms.stock_ratio, main_ticker, terms.acquirer_share_class or "")]
    letters: dict[str, set[str]] = {main_ticker: {class_letter(terms.acquirer_share_class or "")}} if main_ticker else {}
    for leg in terms.extra_legs:
        ticker = normalize_ticker(leg.ticker) if leg.ticker else ""
        letter = class_letter(leg.share_class)
        if ticker and "PREFER" in (leg.share_class or "").upper():
            ticker = ""
        elif ticker in letters:
            base = re.sub(r"-[A-Z]$", "", ticker)
            ticker = f"{base}-{letter}" if letter and letter not in letters[ticker] else ""
        if ticker:
            letters.setdefault(ticker, set()).add(letter)
        out.append((leg.ratio, ticker, leg.share_class or ""))
    return out


def basket_legs(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs | None) -> list[dict[str, Any]]:
    """contract/payout_legs.csv's rows of one ending (ruling R3): each security of a basket per share, with the
    security, ticker and date its price is needed on (the main leg's security is the acquirer stage 8 found, the
    others the run's holder of their ticker, `MergerInputs.leg_sec_ids`), and the leg's share class as the answer
    names it (`leg_terms`: a further leg's ticker is its own class's); none unless the ending's value rule is
    `basket`."""
    if inputs is None or row["bucket"] != "merger" or ending_fields(row).continuation:
        return []
    terms = _llm_published(row, inputs)
    if terms is None or not getattr(terms, "is_basket", False):
        return []
    main = inputs.price_ticker or (normalize_ticker(terms.acquirer_ticker) if terms.acquirer_ticker else "")
    day = _day_after(last_trade_date)
    out = []
    for n, (ratio, ticker, share_class) in enumerate(leg_terms(terms, main), start=1):
        sid = (inputs.acquirer_sec_id or row["acquirer_sec_id"]) if n == 1 else inputs.leg_sec_ids.get(ticker, "")
        out.append({"sec_id": row["sec_id"], "leg": n, "ratio": ratio, "share_class": share_class,
                    "price_sec_id": sid, "price_ticker": ticker, "price_date": day})
    return out


def _otc(row: Mapping[str, str], last_trade_date: str, distress: DistressTerms | None) -> dict[str, Any]:
    """Decision 11: the first off-exchange print, under the security's own OTC symbol as stage 9e read it
    (`distress.otc_symbol`, blank when it found none), else (no terms: a caller of this pure function) its exchange
    ticker."""
    out, day = _blank(), _day_after(last_trade_date)
    symbol = distress.otc_symbol if distress is not None else row["ticker"]
    out.update(value_rule="otc_print", price_sec_id=row["sec_id"], price_ticker=symbol, price_date=day,
               value_formula=f"otc_print({symbol or '?'}, from {day or '?'}) / last_close − 1")
    return out


def _plan(last_trade_date: str, distress: DistressTerms) -> dict[str, Any]:
    """Ruling R6: a bankruptcy plan that gave the old holders new shares, the old line never trading off the
    exchange, is the stock rule on the new line (not a security of the run: no price_sec_id), at the ratio as read
    (a string: the filing's own digits)."""
    out, day = _blank(), _day_after(last_trade_date)
    out.update(value_rule="stock", stock_ratio=distress.plan_ratio, price_ticker=distress.plan_ticker,
               price_date=day, terms_source=distress.plan_source,
               value_formula=f"{distress.plan_ratio} × price({distress.plan_ticker or '?'}, {day or '?'}) "
                             f"/ last_close − 1")
    return out


def value_fields(row: Mapping[str, str], last_trade_date: str, inputs: MergerInputs | None = None,
                 distress: DistressTerms | None = None) -> dict[str, Any]:
    """The payout-rule columns of one ending: `row` is its delistings.csv row, `last_trade_date` the date the
    contract publishes (blank when none), `inputs` the merger's pre-gate reads and overrides, `distress` what
    stage 9e read for a drop or a bankruptcy (its OTC symbol, a plan's ratio; None: not read)."""
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
    elif bucket == "liquidation" and distress is not None and distress.plan_ratio:
        out = _plan(last_trade_date, distress)
    elif bucket == "liquidation" and row["dlret_method"] == "worthless":
        out.update(value_rule="worthless", value_formula="0 − 1")
    elif bucket in ("liquidation", "compliance_failure") or f.exit_kind == "dropped":
        out = _otc(row, last_trade_date, distress)
    elif bucket == "expiration":
        out["value_rule"] = "expiration"
    return out
