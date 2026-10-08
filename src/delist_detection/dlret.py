"""An ending's value, decided once (architecture step 10): its DLRET, and its value rule (what one share became, as
the contract publishes it). Every reader asks this module instead of deciding again: the table (reconstruction,
stage 10a), the contract's value cells (contract and payout_rule, stage 10g) and the firm month (handling and the
qlib_adapter splicer).

- **The DLRET** (`decide`), from one typed input record per ending (`ValueInputs`: the bucket and the exchange the
  classification gave, the last close, a merger's terms, the caller's answers). It answers an `EndingValue`: the
  method (`DlretMethod`), the value, the terminal value and its confidence, whether the value is measured or a fill
  (`METHODS`, each method's kind and confidence beside it), the table's cell (`table_dlret`) and the DLRET the
  BMP 2007 firm month compounds (`firm_month`).
- **The value rule** (`rule_of`), from the ending's delistings.csv row (the table's answer and the terms it carries)
  and the two reads the table does not carry: a merger's pre-gate reads (`MergerInputs`, stage 8) and a drop's or a
  bankruptcy's (`DistressTerms`, stage 9e). It answers a `Rule`: one of `exit_kind.VALUE_RULES` and the terms it
  publishes; payout_rule writes them as the contract's eleven columns. The contract decides from the tables, so a
  committed output's contract can be rebuilt from its tables alone.
- **The contract's value cells** (`contract_value`): the table's value under its method's kind, a measured `dlret`
  or a `dlret_fill`, and none for a continuation.

A liquidation or a drop takes one order, read by both the value and the rule (`_distress_rule`): a caller's recovery
ratio, else a bankruptcy plan's new shares (ruling R6), else the first off-exchange print (decision 11); the value
measures it when its price is answered and fills it with the Shumway mark otherwise.

A merger's DLRET captures the full consideration:

    terminal = cash_per_share + stock_ratio * acquirer_price
    DLRET    = terminal / last_trade_close - 1

**Two DLRETs per ending, by design** (open for the operator's ruling, step 10's measurement): the table fills a
merger or an expiration with no computable consideration, and an unknown ending the classifier found deregistered,
at par (`ASSUMED_PAR`) when it has a last close, and blanks an abstain and an unknown; the firm month compounds the
value before that fill (`EndingValue.firm_month`: an expiration drops, an abstain and an unknown are 0.0).

Pure; it loads no client (the LLM's answer type is named for its annotations only)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple

from .crsp_codes import CrspBucket
from .exchanges import Exchange
from .exit_kind import TERMS_GATE_SKIPPED, flag_names, is_continuation
from .identifiers import normalize_ticker

if TYPE_CHECKING:
    from .llm_merger_extractor import MergerTerms

__all__ = [
    "SHUMWAY_NYSE_AMEX", "SHUMWAY_NASDAQ", "DlretMethod", "METHODS", "MEASURED", "FILL",
    "ValueInputs", "EndingValue", "decide",
    "MergerInputs", "DistressTerms", "Rule", "StockLeg", "rule_of", "ContractValue", "contract_value",
]


SHUMWAY_NYSE_AMEX: float = -0.30
SHUMWAY_NASDAQ: float = -0.55


class DlretMethod(str, Enum):
    CASH_ONLY = "cash_only"
    CASH_PLUS_STOCK = "cash_plus_stock"
    STOCK_ONLY = "stock_only"
    ABSTAIN_NO_CONSIDERATION = "abstain_no_consideration"
    NEEDS_LAST_TRADE = "needs_last_trade"
    EXCHANGE_TRANSFER_ZERO = "exchange_transfer_zero"
    RECOVERY_RATIO = "recovery_ratio"
    OTC_PRINT = "otc_print"
    PLAN_STOCK = "plan_stock"          # ruling R6: a bankruptcy plan's new shares, at the caller's answered close
    SHUMWAY_NYSE_AMEX = "shumway_nyse_amex"
    SHUMWAY_NASDAQ = "shumway_nasdaq"
    WORTHLESS = "worthless"            # reserved; not emitted in v1
    DROPPED_EXPIRATION = "dropped_expiration"
    ASSUMED_PAR = "assumed_par"        # completed delisting, terminal assumed = last price (DLRET≈0)
    UNKNOWN = "unknown"


# Each method's kind and the confidence of the value it gives. A measured value is the rule's, from read terms and
# answered prices; a fill stands in for one (assumed par, a Shumway mark, a transfer's 0.0); a method of neither kind
# gives no value. A NaN value is always low; a cash-only value takes its cash read's own confidence when it has one.
MEASURED, FILL = "measured", "fill"
HIGH, MEDIUM, LOW = "high", "medium", "low"
METHODS: dict[DlretMethod, tuple[str, str]] = {
    DlretMethod.CASH_ONLY: (MEASURED, MEDIUM),
    DlretMethod.CASH_PLUS_STOCK: (MEASURED, MEDIUM),      # the stock leg rests on a market price
    DlretMethod.STOCK_ONLY: (MEASURED, MEDIUM),
    DlretMethod.RECOVERY_RATIO: (MEASURED, MEDIUM),
    DlretMethod.OTC_PRINT: (MEASURED, MEDIUM),
    # controller ruling (step 10): the caller's answered close of the new line times the plan's ratio, the same kind
    # of measured value as an OTC print
    DlretMethod.PLAN_STOCK: (MEASURED, MEDIUM),
    DlretMethod.WORTHLESS: (MEASURED, LOW),
    DlretMethod.EXCHANGE_TRANSFER_ZERO: (FILL, HIGH),
    DlretMethod.SHUMWAY_NYSE_AMEX: (FILL, MEDIUM),
    DlretMethod.SHUMWAY_NASDAQ: (FILL, MEDIUM),
    DlretMethod.ASSUMED_PAR: (FILL, LOW),
    DlretMethod.ABSTAIN_NO_CONSIDERATION: ("", LOW),
    DlretMethod.NEEDS_LAST_TRADE: ("", LOW),
    DlretMethod.DROPPED_EXPIRATION: ("", LOW),
    DlretMethod.UNKNOWN: ("", LOW),
}
_GRADES = {HIGH, MEDIUM, LOW}
# Blank in the table: an abstain (only one with no last close reaches it: with one it is assumed par) and an unknown,
# so a reader never mistakes an uncomputable row for a realized 0%. A transfer's 0.0 and assumed par keep theirs.
_BLANK_IN_TABLE = frozenset({DlretMethod.ABSTAIN_NO_CONSIDERATION, DlretMethod.UNKNOWN})


# -- the DLRET ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ValueInputs:
    """One ending's value inputs. `bucket` and `exchange` are its classification's; `last_trade_close` its last close;
    `payout_per_share`, `stock_ratio` and `acquirer_price` a merger's terms (the caller's --merger-terms row, else the
    terms the payout gate kept; a stock leg needs both of its halves), with `payout_confidence` its cash read's own
    confidence; `recovery_ratio` the caller's --recoveries ratio; `otc_print` the answered first off-exchange print;
    `plan_value` a bankruptcy plan's ratio times its new line's answered close (ruling R6); `deregistered` an unknown
    ending the classifier found deregistered with no merger or distress evidence (valued at par). None is blank."""
    bucket: CrspBucket
    exchange: Exchange = Exchange.OTHER
    last_trade_close: float | None = None
    payout_per_share: float | None = None
    stock_ratio: float | None = None
    acquirer_price: float | None = None
    recovery_ratio: float | None = None
    otc_print: float | None = None
    plan_value: float | None = None
    payout_confidence: str | None = None
    deregistered: bool = False


@dataclass(frozen=True)
class EndingValue:
    """One ending's DLRET: `value` (NaN when there is none) by `method`, the `terminal_value` one share became, and
    its `confidence`; `firm_month` is the DLRET the BMP firm month compounds (the value before the table's par fill)."""
    method: DlretMethod
    value: float
    terminal_value: float | None
    confidence: str
    firm_month: float

    @property
    def kind(self) -> str:
        """MEASURED, FILL, or "" (no value)."""
        return METHODS[self.method][0]

    @property
    def table_dlret(self) -> float | None:
        """delistings.csv's dlret: None (blank) for an abstain and an unknown, else the value (a NaN is blank too)."""
        return None if self.method in _BLANK_IN_TABLE else self.value


class _Resolved(NamedTuple):
    value: float
    method: DlretMethod
    terminal_value: float | None


_NAN = float("nan")


def _valid(price: float | None) -> bool:
    return price is not None and price > 0


def _shumway(exchange: Exchange) -> _Resolved:
    if exchange in (Exchange.NYSE, Exchange.AMEX):
        return _Resolved(SHUMWAY_NYSE_AMEX, DlretMethod.SHUMWAY_NYSE_AMEX, None)
    return _Resolved(SHUMWAY_NASDAQ, DlretMethod.SHUMWAY_NASDAQ, None)


def _merger(v: ValueInputs) -> _Resolved:
    # A dangling stock term would silently understate DLRET to the cash floor with falsely-high confidence; fail loud.
    if (v.stock_ratio is None) != (v.acquirer_price is None):
        raise ValueError("merger stock leg under-specified: stock_ratio and acquirer_price "
                         "must both be provided or both omitted")
    cash: float | None = None
    if v.payout_per_share is not None:
        if v.payout_per_share < 0:
            return _Resolved(_NAN, DlretMethod.UNKNOWN, None)
        cash = float(v.payout_per_share)
    stock: float | None = None
    if v.stock_ratio is not None and v.acquirer_price is not None:
        leg = float(v.stock_ratio) * float(v.acquirer_price)
        if leg < 0:
            return _Resolved(_NAN, DlretMethod.UNKNOWN, None)
        stock = leg
    legs = [x for x in (cash, stock) if x is not None]
    # A valid last close is required, before the no-consideration abstain: a bad or absent price is a NaN drop
    # whatever the legs.
    if not _valid(v.last_trade_close):
        return _Resolved(_NAN, DlretMethod.NEEDS_LAST_TRADE if legs else DlretMethod.ABSTAIN_NO_CONSIDERATION, None)
    if not legs:
        return _Resolved(0.0, DlretMethod.ABSTAIN_NO_CONSIDERATION, None)
    terminal = float(sum(legs))
    if cash is not None and stock is not None:
        method = DlretMethod.CASH_PLUS_STOCK
    elif cash is not None:
        method = DlretMethod.CASH_ONLY
    else:
        method = DlretMethod.STOCK_ONLY
    return _Resolved(terminal / v.last_trade_close - 1.0, method, terminal)


# the rules of a liquidation or a drop, in their one order (`_distress_rule`)
_RECOVERY, _PLAN, _PRINT = "recovery", "plan", "print"


def _distress_rule(bucket: CrspBucket, recovery: bool, plan: bool) -> str:
    """The rule of a liquidation or a drop: a liquidation's recovery ratio (`recovery`: the caller gave one), else a
    bankruptcy plan's new shares (`plan`: R6), else the first off-exchange print. The value asks with what it can
    measure (an answered plan value), the contract's rule with what was read (a plan's ratio)."""
    if bucket is CrspBucket.LIQUIDATION and recovery:
        return _RECOVERY
    if bucket is CrspBucket.LIQUIDATION and plan:
        return _PLAN
    return _PRINT


def _resolve(v: ValueInputs) -> _Resolved:
    """The value by the bucket's rule, before the table's par fill (the firm month's)."""
    if v.bucket is CrspBucket.EXPIRATION:
        return _Resolved(_NAN, DlretMethod.DROPPED_EXPIRATION, None)
    if v.bucket is CrspBucket.EXCHANGE_TRANSFER:
        return _Resolved(0.0, DlretMethod.EXCHANGE_TRANSFER_ZERO, None)
    if v.bucket is CrspBucket.MERGER:
        return _merger(v)
    close = v.last_trade_close
    if not _valid(close):
        return _Resolved(_NAN, DlretMethod.UNKNOWN, None)
    if v.bucket in (CrspBucket.LIQUIDATION, CrspBucket.COMPLIANCE_FAILURE):
        rule = _distress_rule(v.bucket, v.recovery_ratio is not None, _valid(v.plan_value))
        if rule == _RECOVERY:
            if v.recovery_ratio < 0:
                return _Resolved(_NAN, DlretMethod.UNKNOWN, None)
            return _Resolved(v.recovery_ratio - 1.0, DlretMethod.RECOVERY_RATIO, v.recovery_ratio * close)
        if rule == _PLAN:
            return _Resolved(v.plan_value / close - 1.0, DlretMethod.PLAN_STOCK, v.plan_value)
        if _valid(v.otc_print):
            return _Resolved(v.otc_print / close - 1.0, DlretMethod.OTC_PRINT, v.otc_print)
        return _shumway(v.exchange)
    # ACTIVE / UNKNOWN: no shock by default
    return _Resolved(0.0, DlretMethod.UNKNOWN, None)


def _at_par(v: ValueInputs, method: DlretMethod) -> bool:
    """The table's fill: no empty DLRET for an ending whose price did not collapse after it. A completed merger or a
    fund or non-equity closure with a last close but no computable consideration has a terminal value ≈ that close
    (merger arbitrage closes the gap to the deal value before the last trade; a fund redeems at NAV ≈ its last trade),
    so DLRET ≈ 0 is the maximum-likelihood estimate, not a missing value: assumed par, at low confidence, so a reader
    never mistakes it for a realized return. So is an unknown ending the classifier found deregistered with no merger
    or distress evidence. A liquidation or a drop carries a recovery, a print or a Shumway mark and never gets here."""
    if not _valid(v.last_trade_close):
        return False
    if v.bucket is CrspBucket.UNKNOWN and v.deregistered:
        return True
    return v.bucket in (CrspBucket.MERGER, CrspBucket.EXPIRATION) and method in (
        DlretMethod.ABSTAIN_NO_CONSIDERATION, DlretMethod.DROPPED_EXPIRATION)


def _confidence(method: DlretMethod, value: float, payout_confidence: str | None) -> str:
    if math.isnan(value):
        return LOW
    if method is DlretMethod.CASH_ONLY and payout_confidence in _GRADES:
        return payout_confidence
    return METHODS[method][1]


def decide(inputs: ValueInputs) -> EndingValue:
    """One ending's DLRET from its value inputs: the bucket's rule measured from the terms and the answered prices,
    else a fill (a Shumway mark, a transfer's 0.0, or the table's assumed par), its confidence, and the firm month's
    DLRET (before the par fill)."""
    base = _resolve(inputs)
    value, method, terminal = base
    if _at_par(inputs, method):
        value, method, terminal = 0.0, DlretMethod.ASSUMED_PAR, inputs.last_trade_close
    return EndingValue(method, value, terminal, _confidence(method, value, inputs.payout_confidence), base.value)


# -- the value rule ----------------------------------------------------------------------------------------------
OVERRIDE_SOURCE = "--merger-terms"
PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"       # terms_gate


@dataclass(frozen=True)
class DistressTerms:
    """What the contract publishes for one drop or bankruptcy ending beyond its delistings.csv row (stage 9e, from
    distress.py's readers): `otc_symbol` the symbol of its first off-exchange print ("" when unknown); `plan_ratio` a
    bankruptcy plan's new shares per old share as read (R6: the ending is valued by the stock rule on the new line),
    with `plan_ticker` the new line's ticker and `plan_source` where the ratio was read."""
    otc_symbol: str = ""
    plan_ratio: str = ""
    plan_ticker: str = ""
    plan_source: str = ""


@dataclass(frozen=True)
class MergerInputs:
    """What stage 8 holds about one merger ending beyond its delistings.csv row (`merger_value.MergerValues.
    contract_inputs`)."""
    override: Mapping[str, Any] | None = None     # the --merger-terms row (cash_per_share, stock_ratio, acquirer_*)
    llm: MergerTerms | None = None                # the LLM's answer, before the payout gate
    raw_value: float | None = None                # the regex payout read, before the gate
    raw_source: str = ""
    acquirer_sec_id: str = ""
    price_ticker: str = ""        # the acquirer security's symbol on the price date (sub-plan 5e), over the terms'
    raw_currency: str = ""        # the regex read's currency (ruling R5)
    leg_sec_ids: Mapping[str, str] = field(default_factory=dict)   # a basket's further legs: ticker -> sec_id


@dataclass(frozen=True)
class StockLeg:
    """The shares one share became, priced on the day after the last trade: `ratio` per share (a merger's a number, a
    bankruptcy plan's the filing's own digits) or, with no ratio, a dollar `value` over the acquirer's averaging price
    (PCYC; `window` the averaging period as the filing words it), of the line `ticker`, the security `sec_id` (blank
    for a plan's new line: not a security of the run)."""
    ratio: float | str | None
    ticker: str
    sec_id: str = ""
    value: float | None = None
    window: str = ""


@dataclass(frozen=True)
class Rule:
    """One ending's value rule (`name`, one of exit_kind.VALUE_RULES) and the terms it publishes, as read: `cash` and
    its `currency`, a stock `leg`, a `basket`'s terms (ruling R3: its legs, with `basket_ticker` its main leg's
    ticker), a liquidation's `recovery_ratio`, an OTC print's security and symbol (`print_sec_id`, `print_symbol`),
    and where the terms came from (`terms_source`) and the payout gate's verdict (`terms_gate`)."""
    name: str
    cash: float | None = None
    currency: str = ""
    leg: StockLeg | None = None
    basket: MergerTerms | None = None
    basket_ticker: str = ""
    recovery_ratio: float | None = None
    print_sec_id: str = ""
    print_symbol: str = ""
    terms_source: str = ""
    terms_gate: str = ""


def _num(cell: str) -> float | None:
    return float(cell) if cell not in ("", None) else None


def _ungated(row: Mapping[str, str]) -> str:
    """The terms_gate of terms the payout gate did not keep: `skipped` when it could not check them (a non-USD
    cash leg, a basket, a dollar-valued leg: `terms_gate_skipped`), `failed` when it checked and refused them, and
    blank when no last close existed to check them against."""
    if TERMS_GATE_SKIPPED in flag_names(row):
        return SKIPPED
    return FAILED if row["last_trade_close"] else ""


def _llm_published(row: Mapping[str, str], inputs: MergerInputs) -> MergerTerms | None:
    """The LLM terms whose own legs the ending publishes (a dollar-valued leg, a basket): the terms the gate did
    not keep, published as read (`MergerTerms.published`: an answer that states no package publishes only its
    all-cash alternative); None for a --merger-terms row, terms the gate kept, or a regex read."""
    if inputs.override or row["payout_per_share"] or row["stock_ratio"] or inputs.llm is None:
        return None
    return inputs.llm.published


def _merger_rule(row: Mapping[str, str], inputs: MergerInputs) -> Rule:
    """A merger's terms come, in order, from a --merger-terms row (no gate), from the terms its delistings.csv row
    carries (they passed the payout gate; `terms_gate` is `passed`, or blank when no last close existed to check
    them), else from what the library read before the gate dropped them (the LLM terms, else the regex payout):
    `terms_gate` is `failed`, `skipped`, or blank (`_ungated`). An LLM answer (prompt v3) is the package one share
    became (ruling R4); one of two or more securities is a basket (R3)."""
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
        currency = (llm.cash_currency if llm is not None else "") if source.startswith("llm") \
            else inputs.raw_currency
    elif terms is not None:
        cash, ratio, ticker = terms.cash_per_share, terms.stock_ratio, terms.acquirer_ticker or ""
        source, gate, currency = "llm", _ungated(row), terms.cash_currency
    elif inputs.raw_value is not None:
        cash, ratio, ticker = inputs.raw_value, None, ""
        source, gate, currency = inputs.raw_source or "regex", _ungated(row), inputs.raw_currency
    else:
        return Rule("unknown")
    # a --merger-terms row's acquirer ticker is the caller's, published as given; else the acquirer security's
    # symbol on the price date (the request's ticker), over the terms'
    ticker = (normalize_ticker(ticker) if ticker else "") if override else (
        inputs.price_ticker or (normalize_ticker(ticker) if ticker else ""))
    common = dict(cash=cash, currency=currency or "", terms_source=source, terms_gate=gate)
    if terms is not None and terms.is_basket:
        return Rule("basket", basket=terms, basket_ticker=ticker, **common)
    value = terms.stock_value if terms is not None and not ratio else None
    leg = None
    if ratio or value:
        leg = StockLeg(ratio or None, ticker, inputs.acquirer_sec_id or row["acquirer_sec_id"], value,
                       (terms.value_window or "") if value else "")
    name = ("cash_plus_stock" if cash else "stock") if leg else "cash"
    return Rule(name, leg=leg, **common)


def rule_of(row: Mapping[str, str], merger: MergerInputs | None = None,
            distress: DistressTerms | None = None) -> Rule:
    """The value rule of one ending: `row` is its delistings.csv row, `merger` the merger's pre-gate reads and the
    caller's terms, `distress` what stage 9e read for a drop or a bankruptcy (its OTC symbol, a plan's ratio; None:
    not read, and the OTC print is named by the exchange ticker). A continuation has none (decision 9)."""
    if is_continuation(row):
        return Rule("continuation")
    bucket = row["bucket"]
    if bucket == CrspBucket.MERGER.value:
        return _merger_rule(row, merger or MergerInputs())
    if bucket == CrspBucket.EXCHANGE_TRANSFER.value:
        return Rule("transfer")
    if bucket in (CrspBucket.LIQUIDATION.value, CrspBucket.COMPLIANCE_FAILURE.value):
        rule = _distress_rule(CrspBucket(bucket), bool(row["recovery_ratio"]),
                              distress is not None and bool(distress.plan_ratio))
        if rule == _RECOVERY:
            return Rule("recovery", recovery_ratio=float(row["recovery_ratio"]))
        if rule == _PLAN:
            # R6: the old line never traded off the exchange; the new line is no security of the run
            return Rule("stock", leg=StockLeg(distress.plan_ratio, distress.plan_ticker),
                        terms_source=distress.plan_source)
        if bucket == CrspBucket.LIQUIDATION.value and row["dlret_method"] == DlretMethod.WORTHLESS.value:
            return Rule("worthless")
        # decision 11: the first off-exchange print, under the security's own OTC symbol as stage 9e read it (blank
        # when it found none), else (no terms: a caller of this pure function) its exchange ticker
        return Rule("otc_print", print_sec_id=row["sec_id"],
                    print_symbol=distress.otc_symbol if distress is not None else row["ticker"])
    if bucket == CrspBucket.EXPIRATION.value:
        return Rule("expiration")
    return Rule("unknown")


# -- the contract's value cells ----------------------------------------------------------------------------------
class ContractValue(NamedTuple):
    dlret: str            # the table's measured value as delistings.csv writes it, or ""
    dlret_fill: str       # the table's fill as delistings.csv writes it, or ""
    terminal_value: str


_KIND_OF = {m.value: kind for m, (kind, _) in METHODS.items()}


def contract_value(row: Mapping[str, str]) -> ContractValue:
    """contract/delistings.csv's dlret, dlret_fill and terminal_value of one delistings.csv row: the table's value
    under its method's kind (`METHODS`: a cash or stock consideration, a recovery, an OTC print or a plan value is
    measured; a Shumway mark, assumed par and a transfer's 0.0 are fills); none for a continuation (decision 9: the
    same holders own the successor)."""
    if is_continuation(row):
        return ContractValue("", "", "")
    kind, value = _KIND_OF.get(row["dlret_method"], ""), row["dlret"]
    return ContractValue(value if kind == MEASURED else "", value if kind == FILL else "", row["terminal_value"])
