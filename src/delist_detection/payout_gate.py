"""Check every merger payout against the last trade before it reaches the table.

A completed deal trades at its consideration, so a payout far from the last
close is a misread (VRTV $1.00 vs $169.99, TWO $25 vs $12.18) or a stale
vendor price (CAB $0.03). Either way the number must not become a return."""
from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field

from .reconstruction import for_delisting

DEFAULT_TOL = 0.15
GATE_FAILED = "payout_gate_failed:"
LLM_GATE_FAILED = "llm_gate_failed"
GATE_SKIPPED = "terms_gate_skipped:"   # terms the gate cannot check: a non-USD cash leg, a basket, a dollar-valued leg
DROP_REASONS = ("csv_override", "no_acq_ticker", "no_acq_price", "no_last_close", "fail_sanity", "skipped")
PACKAGE = "llm_election_package"     # an election's default cash-and-stock package settled the row
ELECTION_CASH = "llm_election_cash"
BY_TICKER, BY_LINE = "ticker", "line"   # which acquirer price settled a stock leg (`GatedPayouts.priced_by`)


NULL_TICKERS = frozenset({"", "null", "none", "n/a", "n-a", "-"})


def clean_ticker(ticker: object) -> str:
    """The terms' acquirer ticker, blank for an LLM's spelled-out null ("NULL", "None", "N/A", "-": GRUB 2021's
    terms), so a stock leg with no ticker is reported as `no_acq_ticker`, never as a price missing for "NULL"."""
    t = ticker.strip() if isinstance(ticker, str) else ""
    return "" if t.lower() in NULL_TICKERS else t


def is_package(terms) -> bool:
    """Whether the LLM answer names its package (prompt v3, sub-plan 5f): its cash and stock legs are what one share
    became (ruling R4), an election's included, never its alternatives. An earlier answer's election legs were the
    alternatives, and keep sub-plan 5e's either-or reading."""
    return bool(getattr(terms, "package_basis", ""))


def skip_reason(terms) -> str:
    """Why the gate cannot check these terms against a USD close (ruling R5 and R3), "" when it can: the cash
    leg's currency when it is not USD (the library has no FX source), `basket` for two or more securities, and
    `stock_value` for shares stated as a dollar value over an averaging price the library does not have."""
    cur = getattr(terms, "cash_currency", "") or ""
    if terms.cash_per_share and cur and cur != "USD":
        return cur
    if getattr(terms, "extra_legs", ()):
        return "basket"
    if getattr(terms, "stock_value", None) and not terms.stock_ratio:
        return "stock_value"
    return ""


@dataclass(frozen=True)
class Reconciled:
    cash: float | None
    stock_ratio: float | None
    acquirer_price: float | None
    source: str
    flags: tuple[str, ...]


def _gap(value: float, last_close: float) -> float:
    return abs(value / last_close - 1.0)


def _fits(value: float | None, last_close: float, tol: float) -> bool:
    return value is not None and value > 0 and _gap(value, last_close) <= tol


def reconcile(regex_value, last_close, llm_terms, acquirer_price, tol) -> Reconciled:
    if last_close is None or last_close <= 0:
        return Reconciled(regex_value, None, None, "regex" if regex_value is not None else "none",
                          ("no_last_close",))
    flags: list[str] = []
    if regex_value is not None:
        if _fits(regex_value, last_close, tol):
            return Reconciled(regex_value, None, None, "regex", ())
        flags.append(f"{GATE_FAILED}{regex_value:g}")
    if llm_terms is not None:
        cash, ratio = llm_terms.cash_per_share, llm_terms.stock_ratio
        if is_package(llm_terms):
            # A v3 answer's legs are the package to publish (ruling R4): a cash-only package is checked here, one
            # with stock in the cash+stock gate (pass 2 of gate_payouts), an election as any other deal.
            if not llm_terms.has_stock:
                skip = skip_reason(llm_terms)
                if skip:
                    return Reconciled(None, None, None, "none", tuple(flags) + (f"{GATE_SKIPPED}{skip}",))
                if _fits(cash, last_close, tol):
                    return Reconciled(cash, None, None, ELECTION_CASH if llm_terms.deal_type == "election"
                                      else "llm", tuple(flags))
                flags.append(LLM_GATE_FAILED)
            return Reconciled(None, None, None, "none", tuple(flags))
        if llm_terms.deal_type == "election":
            stock = ratio * acquirer_price if ratio is not None and acquirer_price is not None else None
            stock_fits, cash_fits = _fits(stock, last_close, tol), _fits(cash, last_close, tol)
            # A regex value within 1% of the deal's own cash leg read a real term
            # of the deal, even when the election ultimately settles by the other
            # leg -- the "failed the last close" flag would be spurious there.
            regex_matches_cash_leg = (
                regex_value is not None and cash is not None and cash != 0
                and abs(regex_value / cash - 1.0) <= 0.01
            )
            settled_flags = () if regex_matches_cash_leg else tuple(flags)
            # The legs are equal at signing, so both usually fit: take the one nearer
            # the last close; a tie goes to stock.
            if stock_fits and (not cash_fits or _gap(stock, last_close) <= _gap(cash, last_close)):
                return Reconciled(None, ratio, acquirer_price, "llm_election_stock", settled_flags)
            if cash_fits:
                return Reconciled(cash, None, None, "llm_election_cash", settled_flags)
            # Neither leg alone: the LLM read the default package (cash AND stock per share, which electing holders
            # could trade for all cash or all stock, prorated: NYX, EV, SUN). The two legs together are near the
            # close only then; an either-or election's legs together are twice it (sub-plan 5e).
            if stock is not None and cash is not None and _fits(cash + stock, last_close, tol):
                return Reconciled(cash, ratio, acquirer_price, PACKAGE, settled_flags)
        elif ratio is None and _fits(cash, last_close, tol):
            # A cash deal, including the cash + CVR deals the LLM labels "other".
            return Reconciled(cash, None, None, "llm", tuple(flags))
        if llm_terms.deal_type == "election" or ratio is None:
            # Terms this function settles that did not reconcile: the row lands at
            # par, so flag it. Other stock-ratio terms go to the cash+stock gate.
            flags.append(LLM_GATE_FAILED)
    return Reconciled(None, None, None, "none", tuple(flags))


@dataclass
class GatedPayouts:
    payouts: dict
    sources: dict
    confidences: dict
    merged_terms: dict
    flags: dict
    llm_cash: int = 0
    emitted: int = 0
    dropped: dict = field(default_factory=lambda: dict.fromkeys(DROP_REASONS, 0))
    priced_by: dict = field(default_factory=dict)    # key -> BY_TICKER | BY_LINE: the price that settled its stock leg

    @property
    def gate_failed(self) -> int:
        """Rows flagged payout_gate_failed that nothing settled: no gated payout
        and no merged terms (a row the LLM cash or full terms settled keeps its
        flag for review but is not counted)."""
        return sum(
            any(f.startswith(GATE_FAILED) for f in fl)
            and key not in self.payouts and not for_delisting(self.merged_terms, key)
            for key, fl in self.flags.items()
        )


def gate_payouts(
    keys: Iterable[tuple[str, str | None]],
    payouts: Mapping,
    sources: Mapping,
    confidences: Mapping,
    llm_terms: Mapping,
    last_closes: Mapping,
    csv_terms: Mapping,
    acquirer_price: Callable[[str, tuple[str, str | None]], float | None],
    tol: float,
    line_price: Callable[[tuple[str, str | None]], tuple[str, float] | None] | None = None,
    line_first: Collection = (),
) -> GatedPayouts:
    """Route every merger payout through the last-close check. Inputs are not mutated.

    keys: (sec_id, delist_date) of every merger delisting. payouts / sources / confidences:
    the regex extraction, and llm_terms: MergerTerms, all by those keys. last_closes and
    csv_terms: the --last-trade-closes and --merger-terms maps (bare sec_id or
    (sec_id, delist_date) keys). A --merger-terms row always wins over the LLM.
    acquirer_price(ticker, key): the acquirer's price on THAT merger's own last-trade
    day — called with the merger's full key, not just its date, because many mergers
    can share a delist date and each must be priced on its own last-trade day.
    line_price(key): the (ticker, price) of the acquirer's line (`acquirer_line`, sub-plan 5e), tried when the
    terms' ticker gives no price or its price does not reconcile; `priced_by` records which one settled a stock
    leg. A ticker price that reconciles is never replaced, except for a key in `line_first` (its terms' ticker's
    rows are those of another line of the issuer: Charter before the closing for Time Warner Cable's New Charter,
    CBS class B for Viacom class A), whose line price is tried first.

    Pass 1 reconciles each key's regex value (and its cash or election LLM terms).
    Pass 2 is the cash+stock gate for the other LLM terms that carry a stock ratio:
    it emits full terms when cash + ratio x acquirer price reconciles.
    """
    out = GatedPayouts(dict(payouts), dict(sources), dict(confidences), dict(csv_terms), {})

    def drop_payout(key) -> None:
        for m in (out.payouts, out.sources, out.confidences):
            m.pop(key, None)

    def prices(ticker: str, key) -> list[tuple[str, str, float]]:
        """(how, ticker, price) to try, in order: the terms' ticker's, then the acquirer line's when it differs."""
        got = []
        if ticker:
            p = acquirer_price(ticker, key)
            if p is not None:
                got.append((BY_TICKER, ticker, p))
        line = line_price(key) if line_price is not None else None
        if line is not None and line[1] is not None:
            if key in line_first:
                got = [(BY_LINE, line[0], line[1])] + [g for g in got if abs(g[2] - line[1]) > 1e-9]
            elif all(abs(line[1] - p) > 1e-9 for _, _, p in got):
                got.append((BY_LINE, line[0], line[1]))
        return got

    for key in keys:
        has_csv = for_delisting(csv_terms, key) is not None
        terms = None if has_csv else llm_terms.get(key)
        regex, close = out.payouts.get(key), for_delisting(last_closes, key)
        ticker = clean_ticker(terms.acquirer_ticker) if terms is not None else ""
        if terms is not None and terms.deal_type == "election" and not is_package(terms):
            tried = [(how, t, reconcile(regex, close, terms, p, tol)) for how, t, p in prices(ticker, key)]
            how, used, r = next(((h, t, x) for h, t, x in tried if x.source.startswith("llm")), None) \
                or (tried[0] if tried else (BY_TICKER, ticker or None, reconcile(regex, close, terms, None, tol)))
        else:
            how, used = BY_TICKER, (ticker or None) if terms else None
            r = reconcile(regex, close, terms, acquirer_price(ticker, key) if ticker else None, tol)
        if r.flags:
            out.flags[key] = r.flags
        if r.cash is not None:
            out.payouts[key] = r.cash
        else:
            drop_payout(key)
        if r.source.startswith("llm"):   # llm | llm_election_cash | llm_election_stock | llm_election_package
            out.sources[key] = r.source
            out.confidences[key] = terms.confidence or "medium"
            if r.cash is not None and r.stock_ratio is None:
                out.llm_cash += 1
        if r.stock_ratio is not None:   # an election's stock leg or package; terms is set, so no CSV row
            d = {"stock_ratio": r.stock_ratio, "acquirer_price": r.acquirer_price, "acquirer_ticker": used}
            out.merged_terms[key] = {"cash_per_share": r.cash, **d} if r.cash is not None else d
            out.priced_by[key] = how

    def flag_terms_gate_drop(key, reason: str) -> None:
        # Every drop reason but csv_override gets a flag: a merger row the rules
        # leave at par must still surface in review.csv.
        out.flags[key] = out.flags.get(key, ()) + (f"terms_gate_failed:{reason}",)

    for key, terms in llm_terms.items():
        package = is_package(terms)
        if not terms.has_stock or (terms.deal_type == "election" and not package):
            continue   # settled in pass 1
        if for_delisting(csv_terms, key) is not None:
            out.dropped["csv_override"] += 1
            continue
        if package:
            # Sub-plan 5f. A package that holds stock is what one share became (R4): a regex cash read beside it
            # read an election's cash alternative (SUG's $44.25) or one leg, so it never stands for an election,
            # nor when no last close can check the package (FWLT, AWH).
            last_close = for_delisting(last_closes, key)
            skip = skip_reason(terms)
            regex = out.payouts.get(key)
            # a regex read equal to the package's cash leg read that leg alone (SHAW 2013's $41.00 of $41.00 and
            # 0.12883 CB&I shares): it never stands for the package, whatever the gate says of the stock leg
            one_leg = regex is not None and bool(terms.cash_per_share) and abs(regex / terms.cash_per_share - 1) <= 0.01
            if terms.deal_type == "election" or skip or one_leg or last_close is None or last_close <= 0:
                drop_payout(key)
            if skip:
                out.dropped["skipped"] += 1
                out.flags[key] = out.flags.get(key, ()) + (f"{GATE_SKIPPED}{skip}",)
                continue
            if last_close is None or last_close <= 0:
                out.dropped["no_last_close"] += 1
                flag_terms_gate_drop(key, "no_last_close")
                continue
        acq = clean_ticker(terms.acquirer_ticker)
        tried = prices(acq, key)
        if not acq and not tried:
            out.dropped["no_acq_ticker"] += 1
            flag_terms_gate_drop(key, "no_acq_ticker")
            continue
        if not tried:
            out.dropped["no_acq_price"] += 1
            flag_terms_gate_drop(key, "no_acq_price")
            continue
        last_close = for_delisting(last_closes, key)
        if last_close is None or last_close <= 0:
            # <=0 guard mirrors _resolve_merger (dlret.py): a zero/blank close
            # would both divide-by-zero here and yield a NaN DLRET downstream.
            out.dropped["no_last_close"] += 1
            flag_terms_gate_drop(key, "no_last_close")
            continue
        cash = terms.cash_per_share
        fit = next(((how, t, p) for how, t, p in tried
                    if _gap((cash or 0.0) + terms.stock_ratio * p, last_close) <= tol), None)
        if fit is None:
            out.dropped["fail_sanity"] += 1
            flag_terms_gate_drop(key, "fail_sanity")
            continue
        how, acq, acq_price = fit
        out.priced_by[key] = how
        d = {"stock_ratio": terms.stock_ratio, "acquirer_price": acq_price, "acquirer_ticker": acq}
        if cash is not None:
            d["cash_per_share"] = cash
        else:
            # The LLM read this as all-stock and the stock leg alone reconciles, so
            # any cash the regex (mis)read from the filing is wrong. Drop it:
            # otherwise build_delistings_table's `terms.get("cash_per_share", payouts[...])`
            # fallback would re-add that phantom cash (e.g. MRD 65x).
            drop_payout(key)
        out.merged_terms[key] = d
        out.emitted += 1
        if package:
            out.sources[key] = PACKAGE if terms.deal_type == "election" else "llm"
            out.confidences[key] = terms.confidence or "medium"
        # A cash leg is not expected to reconcile alone; the full terms settle the row.
        kept = tuple(f for f in out.flags.get(key, ()) if not f.startswith(GATE_FAILED))
        if kept:
            out.flags[key] = kept
        else:
            out.flags.pop(key, None)
    return out
