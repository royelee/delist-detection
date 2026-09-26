"""Check every merger payout against the last trade before it reaches the table.

A completed deal trades at its consideration, so a payout far from the last
close is a misread (VRTV $1.00 vs $169.99, TWO $25 vs $12.18) or a stale
vendor price (CAB $0.03). Either way the number must not become a return."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from .reconstruction import _lookup

DEFAULT_TOL = 0.15
GATE_FAILED = "payout_gate_failed:"
LLM_GATE_FAILED = "llm_gate_failed"
DROP_REASONS = ("csv_override", "no_acq_ticker", "no_acq_price", "no_last_close", "fail_sanity")


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

    @property
    def gate_failed(self) -> int:
        """Rows flagged payout_gate_failed that nothing settled: no gated payout
        and no merged terms (a row the LLM cash or full terms settled keeps its
        flag for review but is not counted)."""
        return sum(
            any(f.startswith(GATE_FAILED) for f in fl)
            and key not in self.payouts and not _lookup(self.merged_terms, *key)
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
) -> GatedPayouts:
    """Route every merger payout through the last-close check. Inputs are not mutated.

    keys: (sec_id, delist_date) of every merger delisting. payouts / sources / confidences:
    the regex extraction, and llm_terms: MergerTerms, all by those keys. last_closes and
    csv_terms: the --last-trade-closes and --merger-terms maps (bare sec_id or
    (sec_id, delist_date) keys). A --merger-terms row always wins over the LLM.
    acquirer_price(ticker, key): the acquirer's price on THAT merger's own last-trade
    day — called with the merger's full key, not just its date, because many mergers
    can share a delist date and each must be priced on its own last-trade day.

    Pass 1 reconciles each key's regex value (and its cash or election LLM terms).
    Pass 2 is the cash+stock gate for the other LLM terms that carry a stock ratio:
    it emits full terms when cash + ratio x acquirer price reconciles.
    """
    out = GatedPayouts(dict(payouts), dict(sources), dict(confidences), dict(csv_terms), {})

    def drop_payout(key) -> None:
        for m in (out.payouts, out.sources, out.confidences):
            m.pop(key, None)

    for key in keys:
        sec_id, delist_date = key
        has_csv = _lookup(csv_terms, sec_id, delist_date) is not None
        terms = None if has_csv else llm_terms.get(key)
        r = reconcile(
            out.payouts.get(key),
            _lookup(last_closes, sec_id, delist_date),
            terms,
            acquirer_price(terms.acquirer_ticker, key) if terms and terms.acquirer_ticker else None,
            tol,
        )
        if r.flags:
            out.flags[key] = r.flags
        if r.cash is not None:
            out.payouts[key] = r.cash
        else:
            drop_payout(key)
        if r.source.startswith("llm"):   # llm | llm_election_cash | llm_election_stock
            out.sources[key] = r.source
            out.confidences[key] = terms.confidence or "medium"
            if r.cash is not None:
                out.llm_cash += 1
        if r.stock_ratio is not None:   # an election's stock leg; terms is set, so no CSV row
            out.merged_terms[key] = {"stock_ratio": r.stock_ratio, "acquirer_price": r.acquirer_price,
                                     "acquirer_ticker": terms.acquirer_ticker}

    def flag_terms_gate_drop(key, reason: str) -> None:
        # Every drop reason but csv_override gets a flag: a merger row the rules
        # leave at par must still surface in review.csv.
        out.flags[key] = out.flags.get(key, ()) + (f"terms_gate_failed:{reason}",)

    for key, terms in llm_terms.items():
        if terms.stock_ratio is None or terms.deal_type == "election":
            continue   # settled in pass 1
        sec_id, delist_date = key
        if _lookup(csv_terms, sec_id, delist_date) is not None:
            out.dropped["csv_override"] += 1
            continue
        acq = (terms.acquirer_ticker or "").strip()
        if not acq:
            out.dropped["no_acq_ticker"] += 1
            flag_terms_gate_drop(key, "no_acq_ticker")
            continue
        acq_price = acquirer_price(acq, key)
        if acq_price is None:
            out.dropped["no_acq_price"] += 1
            flag_terms_gate_drop(key, "no_acq_price")
            continue
        last_close = _lookup(last_closes, sec_id, delist_date)
        if last_close is None or last_close <= 0:
            # <=0 guard mirrors _resolve_merger (dlret.py): a zero/blank close
            # would both divide-by-zero here and yield a NaN DLRET downstream.
            out.dropped["no_last_close"] += 1
            flag_terms_gate_drop(key, "no_last_close")
            continue
        cash = terms.cash_per_share
        terminal = (cash or 0.0) + terms.stock_ratio * acq_price
        if _gap(terminal, last_close) > tol:
            out.dropped["fail_sanity"] += 1
            flag_terms_gate_drop(key, "fail_sanity")
            continue
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
        # A cash leg is not expected to reconcile alone; the full terms settle the row.
        kept = tuple(f for f in out.flags.get(key, ()) if not f.startswith(GATE_FAILED))
        if kept:
            out.flags[key] = kept
        else:
            out.flags.pop(key, None)
    return out
