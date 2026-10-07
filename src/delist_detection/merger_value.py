"""Stage 8: what one share of each merger ending became, as one record per ending (architecture step 1).

`value_mergers` is the stage. It takes the run's merger delistings, the run's securities as acquirer lines
(`acquirer_line.LineIndex`), the last-trade closes, the caller's --merger-terms rows and the caller's price answers
(`price_requests.PriceAnswers`), and returns `MergerValues`: one `MergerValue` per merger ending, and the acquirers the
run adds as securities of their own. Inside, in order:

1. the reads: the regex payout read and the LLM's terms (the LLM is told the target security's name: its class decides
   its terms, PARA's class B), filled ahead on the worker threads when there are several;
2. the acquirer line of each stock leg (stage 8a, sub-plan 5e: `acquirer_line`), before the gate and whether or not
   its terms will pass it, and the ticker of a leg the LLM names without one (8a', `acquirer_ticker`);
3. the payout gate (`payout_gate`), a first pass that reads none of the caller's answers: the acquirer and the
   request's ticker depend on what the run reads alone, so a second run with the requests answered keeps both; then
   the acquirer security (`acquirers`) and its price ticker, the received close each stock leg asks
   (`MergerValue.request`), and a second gate pass with the answers to those requests;
4. a basket's further legs' holders (ruling R3).

A read that rests on a failed request or a stale copy is a `resolution_degraded` review item (and, for the reads of
step 1, a flag on the merger's own row); a refusal (`fatal.FATAL`) stops the run. Issuers' submissions, filing lists,
first filings and SEC's name index are read through the run's issuer record (`issuer_record.IssuerRecord`), whose
failure policy is the stage's: a failed read is unknown and never remembered.

The later stages ask `MergerValues`, never a parallel map: stage 8b the terms R1 reads (`read_terms`) and the rows it
rewrites (`drop`), stage 9b whether a merger reconciled (`reconciled`), stage 10a the delistings.csv inputs
(`table_inputs`), 10c the payouts.csv rows (`payout_rows`) and 10g the contract's inputs (`contract_inputs`) and the
stock legs' price requests (`requests`).

The four rule modules it calls are its collaborators, each with its own interface and real-case tests:
`acquirer_line` (who the acquirer is, its line and price), `acquirer_ticker` (an unnamed leg's ticker), `acquirers`
(the acquirer's FIGI from its fails rows, its CIK) and `payout_gate` (the check against the last close)."""
from __future__ import annotations

import inspect
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import requests

from . import acquirer_line
from . import acquirer_ticker
from .acquirers import acquirer_cik, find_acquirer
from .added_securities import AddedAcquirer, AddedSecurity
from .crsp_codes import CrspBucket
from .degraded import DegradedWatch, degraded_item
from .delistings import Delisting
from .fatal import FATAL
from .figi_resolution import class_letter, share_class_from_name
from .ftd import FtdIndex
from .llm_merger_extractor import MergerTerms
from .observations import normalize_ticker
from .payout_gate import BY_LINE, BY_TICKER, GATE_SKIPPED, GatedPayouts, gate_payouts
from .payout_rule import MergerInputs
from .prefetch import warm
from .price_requests import PriceAnswers
from .reconstruction import for_delisting
from .review_triage import ReviewItem
from .sec_stats import SEC_STATS
from .security_master import Security
from .store import DelistingKey
from .trading_calendar import next_trading_day


@dataclass(frozen=True)
class MergerValue:
    """One merger ending's value: what the library read, what the payout gate kept, and the acquirer.

    `raw` is the regex payout read (`read`: the regex reader answered, so payouts.csv has a row) and `llm` the LLM's
    terms (a ticker named by stage 8a' included), both before the gate. The gate's verdict: the cash it kept
    (`payout`, `source`, `confidence`), the stock leg it priced (`terms`: cash_per_share, stock_ratio,
    acquirer_price, acquirer_ticker), its `flags` and the price that settled the leg (`priced_by`). The acquirer
    security (`acquirer_sec_id`), its symbol on the price date (`price_ticker`), a basket's further legs' holders
    (`leg_sec_ids`, ticker -> sec_id), and the received close the stock leg asks (`request`: (ticker, acquirer
    sec_id), None when it asks none)."""
    key: DelistingKey
    raw: Any = None
    read: bool = False
    llm: MergerTerms | None = None
    payout: float | None = None
    source: str | None = None
    confidence: str | None = None
    terms: Mapping[str, Any] | None = None
    flags: tuple[str, ...] = ()
    priced_by: str = ""
    acquirer_sec_id: str = ""
    price_ticker: str = ""
    leg_sec_ids: Mapping[str, str] = field(default_factory=dict)
    request: tuple[str, str] | None = None


@dataclass
class MergerValues:
    """Stage 8's answer: one `MergerValue` per merger ending (`records`), the caller's --merger-terms rows
    (`caller_terms`, by sec_id or (sec_id, delist_date): they win over the library's reads, for every delisting of
    the security), the acquirers the run adds as securities of their own (`added`) and the review items."""
    records: dict[DelistingKey, MergerValue] = field(default_factory=dict)
    caller_terms: Mapping = field(default_factory=dict)
    added: dict[str, AddedSecurity] = field(default_factory=dict)
    review: list[ReviewItem] = field(default_factory=list)

    def get(self, key: DelistingKey) -> MergerValue | None:
        return self.records.get(key)

    def drop(self, key: DelistingKey) -> None:
        """Forget the merger reads of an ending that is no merger after all (stage 8b's R1 continuation: a
        continuation has no value)."""
        self.records.pop(key, None)

    def _terms(self, key: DelistingKey) -> Mapping[str, Any] | None:
        """The terms delistings.csv carries for the delisting: the caller's row, else the stock leg the gate
        priced."""
        given = for_delisting(self.caller_terms, key)
        if given is not None:
            return given
        v = self.records.get(key)
        return v.terms if v is not None else None

    def _payout(self, key: DelistingKey) -> float | None:
        v = self.records.get(key)
        return v.payout if v is not None else None

    def read_terms(self, key: DelistingKey) -> tuple[float | None, float | None] | None:
        """The (cash, stock ratio) one share became as stage 8b's R1 test reads them: the terms the payout gate
        kept, else the LLM's as read, else the regex cash; None with none, and for a merger the caller gave terms
        for. (The contract's reading, `payout_rule`, publishes only an election's all-cash alternative where this
        reads both of its legs.)"""
        if for_delisting(self.caller_terms, key):
            return None
        v = self.records.get(key)
        terms, cash = self._terms(key) or {}, self._payout(key)
        if terms or cash is not None:
            return terms.get("cash_per_share", cash), terms.get("stock_ratio")
        llm = v.llm if v is not None else None
        if llm is not None and (llm.cash_per_share or llm.stock_ratio):
            return llm.cash_per_share, llm.stock_ratio
        pr = v.raw if v is not None else None
        return (pr.value, None) if pr is not None and pr.value is not None else None

    def reconciled(self, key: DelistingKey) -> bool:
        """Whether the delisting's value reconciled with its last close (stage 9b): a payout the gate kept or terms
        (the caller's or the gate's), unless they are one share per share and no cash, which proves nothing against
        a continuation (R1, sub-plan 5f: SPB 2018, one HRG share, the old line's close under the ticker the successor
        took)."""
        terms, payout = self._terms(key), self._payout(key)
        if payout is None and not terms:
            return False
        t = terms or {}
        return not (t.get("stock_ratio") == 1.0 and not t.get("cash_per_share") and payout is None)

    def table_inputs(self) -> dict[str, Mapping]:
        """`reconstruction.build_delistings_table`'s merger inputs, keyed as it reads them: the caller's rows by
        sec_id or delisting and the gate's verdicts by delisting."""
        merger_terms = dict(self.caller_terms)
        merger_terms.update({k: v.terms for k, v in self.records.items() if v.terms is not None})
        return {
            "payouts": {k: v.payout for k, v in self.records.items() if v.payout is not None},
            "merger_terms": merger_terms,
            "payout_sources": {k: v.source for k, v in self.records.items() if v.source is not None},
            "payout_confidences": {k: v.confidence for k, v in self.records.items() if v.confidence is not None},
            "payout_flags": {k: v.flags for k, v in self.records.items() if v.flags},
        }

    def payout_rows(self, tickers: Mapping[DelistingKey, str]) -> list[dict]:
        """payouts.csv (stage 10c): each merger the regex reader answered for, its gated payout and where it came
        from (an LLM-sourced payout cites the LLM's filing: its regex accession, if any, is often blank or of another
        filing tier). `tickers`: each delisting's ticker."""
        rows = []
        for key, v in self.records.items():
            if not v.read:
                continue
            source = v.source or "none"
            if source.startswith("llm"):
                accession = v.llm.source.partition(":")[2] if v.llm is not None else None
            else:
                accession = v.raw.accession if v.raw and v.payout is not None else None
            rows.append({"sec_id": key.sec_id, "delist_date": key.delist_date, "ticker": tickers[key],
                         "payout_per_share": v.payout, "confidence": v.confidence or "none", "source": source,
                         "accession": accession})
        return rows

    def contract_inputs(self, endings: Sequence[Mapping[str, str]]) -> dict[DelistingKey, MergerInputs]:
        """The payout rule's inputs of each merger-bucket ending (`endings`: delistings.csv rows, stage 10g)."""
        out: dict[DelistingKey, MergerInputs] = {}
        for r in endings:
            if r["bucket"] != "merger":
                continue
            key = DelistingKey(r["sec_id"], r["delist_date"])
            v = self.records.get(key) or MergerValue(key)
            pr = v.raw
            out[key] = MergerInputs(for_delisting(self.caller_terms, key), v.llm, getattr(pr, "value", None),
                                    getattr(pr, "source", "") or "", v.acquirer_sec_id or r["acquirer_sec_id"],
                                    v.price_ticker, getattr(pr, "currency", "") or "", v.leg_sec_ids)
        return out

    def requests(self, endings: Sequence[Mapping[str, str]]) -> dict[DelistingKey, tuple[str, str]]:
        """The received close each ending's stock leg asks, (ticker, acquirer sec_id) (`MergerValue.request`):
        decided at stage 8, before the gate's verdict, so an answer that changes the gate does not change it."""
        out: dict[DelistingKey, tuple[str, str]] = {}
        for r in endings:
            key = DelistingKey(r["sec_id"], r["delist_date"])
            v = self.records.get(key)
            if v is not None and v.request is not None:
                out[key] = v.request
        return out


def _quiet(*_: object) -> None:
    pass


@dataclass
class _Stage:
    """What every step of the stage shares: the run's clients (edgar, resolver, issuers, figi, ftd_client,
    payout_extractor, llm_extractor), the run's securities as acquirer lines, the first day the run loaded fails rows
    from, the prefetch worker count and the log."""
    clients: Any
    index: acquirer_line.LineIndex
    ftd_lo: date | None
    workers: int
    log: Callable

    @property
    def ftd(self) -> FtdIndex:
        return self.index.ftd

    @property
    def securities(self) -> Mapping[str, Security]:
        return self.index.securities

    @property
    def cusips(self) -> Mapping[str, Sequence[str]]:
        return self.index.cusips


def value_mergers(delistings: Sequence[Delisting], index: acquirer_line.LineIndex, *, clients: Any,
                  closes: Mapping[DelistingKey, float], caller_terms: Mapping, answers: PriceAnswers, tol: float,
                  ftd_lo: date | None = None, workers: int = 1, log: Callable = _quiet) -> MergerValues:
    """Stage 8 (see the module docstring): every merger-bucket delisting of `delistings`, valued. `index` holds the
    run's securities, their ticker sightings, CUSIPs and the fails index (extended here with the acquirers' rows);
    `clients` the run's edgar, resolver, issuers (the issuer record), figi, ftd_client, payout_extractor and
    llm_extractor."""
    st = _Stage(clients, index, ftd_lo, workers, log)
    mergers = [e for e in delistings if e.record.bucket is CrspBucket.MERGER]
    raw, llm_terms, review = _read_terms(st, mergers, closes, {sid: s.name or "" for sid, s in st.securities.items()})
    trade_day = {e.key: e.last_trade.day for e in delistings}
    lines, line_review = _acquirer_lines(st, mergers, llm_terms, caller_terms)
    llm_terms, name_review = _name_acquirer_tickers(st, mergers, llm_terms, lines, caller_terms)
    found = _TickerSecurity(st)
    wins = _line_wins(st, mergers, lines, llm_terms, caller_terms, trade_day, found)
    # the first pass reads none of the caller's received closes: the acquirer and the request's ticker depend on
    # what the run reads alone, so a second run with the requests answered keeps both (`--price-answers`)
    gated, lagged = _gate(st, mergers, trade_day, raw, llm_terms, closes, caller_terms, tol, lines, wins)
    acquirer_ids, added, acquirer_review = _add_acquirers(st, mergers, trade_day, gated, lines, wins, found)
    price_tickers = _price_tickers(acquirer_ids, lines, index.fresh() if lines else None)
    asked = {e.key: request for e in mergers
             if (request := _request(e, llm_terms, caller_terms, acquirer_ids, price_tickers)) is not None}
    answered = _answered_paths(mergers, answers, llm_terms, caller_terms, lines, gated, asked)
    if answered:
        gated, lagged = _gate(st, mergers, trade_day, raw, llm_terms, closes, caller_terms, tol, lines, wins, answered)
    for e in mergers:
        if e.key in lagged:
            e.add_flag("acquirer_close_lagged")
    legs = _leg_holders(st, mergers, llm_terms, price_tickers)
    records = {e.key: _record(e.key, raw, llm_terms, gated, caller_terms, acquirer_ids, price_tickers, legs, asked)
               for e in mergers}
    return MergerValues(records, caller_terms, added, review + line_review + name_review + acquirer_review)


def _record(key: DelistingKey, raw: Mapping, llm_terms: Mapping, gated: GatedPayouts, caller_terms: Mapping,
            acquirer_ids: Mapping, price_tickers: Mapping, legs: Mapping, asked: Mapping) -> MergerValue:
    """One merger's record from the stage's steps (the gate's merged terms of a merger the caller gave terms for are
    the caller's row, which `MergerValues` holds itself)."""
    return MergerValue(
        key, raw=raw.get(key), read=key in raw, llm=llm_terms.get(key), payout=gated.payouts.get(key),
        source=gated.sources.get(key), confidence=gated.confidences.get(key),
        terms=None if for_delisting(caller_terms, key) is not None else gated.merged_terms.get(key),
        flags=tuple(gated.flags.get(key, ())), priced_by=gated.priced_by.get(key, ""),
        acquirer_sec_id=acquirer_ids.get(key, ""), price_ticker=price_tickers.get(key, ""),
        leg_sec_ids=legs.get(key, {}), request=asked.get(key))


# --- 1. the reads ----------------------------------------------------------------------------------------------

def _read_terms(st: _Stage, mergers: list[Delisting], closes: Mapping[DelistingKey, float],
                names: Mapping[str, str]) -> tuple[dict[DelistingKey, Any], dict[DelistingKey, MergerTerms],
                                                   list[ReviewItem]]:
    """The regex payout read and the LLM merger terms of each merger (the LLM is told the target security's name,
    `names` by sec_id), and the review items: a failed extraction's `error`, and a read that rested on a degraded
    answer (a failed EDGAR read or LLM call; it also flags the merger's own row)."""
    clients, raw, llm_terms = st.clients, {}, {}
    review: list[ReviewItem] = []
    named = clients.llm_extractor is not None and \
        "security_name" in inspect.signature(clients.llm_extractor.extract).parameters
    if st.workers > 1 and clients.payout_extractor is not None:
        # The regex payout reader's EDGAR reads, warmed.
        extractor = clients.payout_extractor
        warm(mergers, lambda e: extractor.extract(e.record, last_close=closes.get(e.key)),
             workers=st.workers, name="payouts")
    if st.workers > 1 and named:
        # The LLM calls the sequential pass makes, filled ahead on the worker threads (sub-plan 5f: a new prompt
        # version asks every merger again). Each call fills the cache entry the sequential pass then reads: the
        # same candidates in the same order, and a failed call is never cached, so the tables do not depend on the
        # worker count. A warm thread pays for a call the sequential pass skips only when an EDGAR text read
        # fails on one thread and not the other.
        llm = clients.llm_extractor
        warm(mergers, lambda e: llm.extract(e.record, security_name=names.get(e.sec_id, "")),
             workers=st.workers, name="llm terms")
    for e in mergers:
        key = e.key
        watch = DegradedWatch()
        try:
            if clients.payout_extractor is not None:
                raw[key] = clients.payout_extractor.extract(e.record, last_close=closes.get(key))
            if clients.llm_extractor is not None:
                t = clients.llm_extractor.extract(e.record, security_name=names.get(e.sec_id, "")) if named \
                    else clients.llm_extractor.extract(e.record)
                if t is not None:
                    llm_terms[key] = t
        except FATAL:
            raise
        except Exception as exc:  # an overnight run must survive one bad extraction
            st.log(f"{e.sec_id} {e.delist_date}: payout extraction ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(e.sec_id, e.ticker, e.cik, "error", f"{type(exc).__name__}: {exc}",
                                     delist_date=e.delist_date))
        watch.report_delisting(review, e, "payout extraction")
    return raw, llm_terms, review


# --- 2. the acquirer line and an unnamed leg's ticker --------------------------------------------------------------

@dataclass(frozen=True)
class _AcquirerLine:
    """Stage 8a's acquirer line of one merger's stock leg (`acquirer_line`, sub-plan 5e): the security of the run
    that held the terms' ticker on the last trade day (`holder`), the issuer's line the leg is priced on (`line`),
    its price (`(price, row_date, lagged)`) and its symbol on the price date."""
    holder: str | None
    line: str | None
    price: tuple[float, str, bool] | None
    ticker: str
    last: date
    price_day: date


def _leg_evidence(e: Delisting, llm_terms: Mapping[DelistingKey, MergerTerms],
                  caller_terms: Mapping) -> tuple[str, str, str] | None:
    """(ticker, acquirer name, quote) of a merger's stock leg: its --merger-terms row's, else the LLM's
    (`MergerTerms.stock_leg`: a dollar-valued leg too, PCYC); None when it has none."""
    given = for_delisting(caller_terms, e.key)
    if given is not None:
        return (normalize_ticker(given.get("acquirer_ticker") or ""), "", "") if given.get("stock_ratio") else None
    t = llm_terms.get(e.key)
    if t is None or not t.stock_leg:
        return None
    return t.ticker, t.acquirer_name or "", t.quote or ""


def _acquirer_lines(st: _Stage, mergers: list[Delisting], llm_terms: Mapping[DelistingKey, MergerTerms],
                    caller_terms: Mapping) -> tuple[dict[DelistingKey, _AcquirerLine], list[ReviewItem]]:
    """8a. The acquirer line of every merger's stock leg, before the payout gate and whether or not its terms will
    pass it (sub-plan 5e rules 1-4): the issuer (`acquirer_line`: the holder of the terms' ticker on the last trade
    day, else the resolver's issuer of it whose EDGAR names agree with the acquirer name, else the one issuer of the
    run that carried that name), its line on the price date, that line's symbol then and its price. A merger
    before the fails rows the run loaded (`ftd_lo`) has its candidate lines' rows read for it (a private index:
    the run's own is not extended, so no later stage sees rows it did not load). A lookup that rested on a
    degraded answer is a review item."""
    out: dict[DelistingKey, _AcquirerLine] = {}
    review: list[ReviewItem] = []
    legs = {e.key: (e, leg) for e in mergers if e.last_trade.day is not None
            and (leg := _leg_evidence(e, llm_terms, caller_terms)) is not None}
    if not legs:
        return out, review
    index, securities, ftd_lo = st.index, st.securities, st.ftd_lo
    resolver, reads = st.clients.resolver, st.clients.issuers
    issuers: dict[DelistingKey, tuple[str | None, int | None]] = {}
    for key, (e, (ticker, name, _)) in sorted(legs.items()):
        last = e.last_trade.day
        day = next_trading_day(last)
        watch = reads.watch()
        holder = index.holder(ticker, last, day, exclude=e.sec_id) if ticker else None
        cik = securities[holder].issuer_cik if holder else None
        if cik is not None and not acquirer_line.issuer_fits(reads.submissions, reads.first_filed, int(cik), name,
                                                             last):
            holder, cik = None, None
        try:
            if cik is None and ticker and resolver is not None:
                cik = acquirer_line.issuer_by_ticker(resolver, reads.submissions, ticker, name, last,
                                                     target_cik=e.cik)
            if cik is None:
                # no ticker, or one that names no issuer on the last trade day (sub-plan 5f: prompt v3 gives
                # today's ticker of a renamed acquirer, FDC 2019's FI for Fiserv's FISV): the run's issuer of the name
                cik = acquirer_line.issuer_by_name(index.issuers(), reads.submissions, name, last, day,
                                                   target_cik=e.cik)
        except FATAL:
            raise
        except requests.RequestException:
            cik = None
        if watch.tripped():
            review.append(degraded_item(e.sec_id, e.ticker, e.cik, "the acquirer issuer lookup",
                                        delist_date=e.delist_date))
        issuers[key] = (holder, int(cik) if cik else None)

    view = index
    early = [legs[k][0] for k, (_, c) in issuers.items() if c and ftd_lo and legs[k][0].last_trade.day < ftd_lo
             + timedelta(days=acquirer_line.EARLY_DAYS)]
    if early:
        # the candidate lines' rows around these mergers, read into an index of their own
        cusips = {c for e in early for sid in index.lines(issuers[e.key][1], exclude=e.sec_id)
                  for c in st.cusips.get(sid, [])}
        lo = min(e.last_trade.day for e in early) - timedelta(days=acquirer_line.EARLY_DAYS)
        hi = max(e.last_trade.day for e in early) + timedelta(days=acquirer_line.EARLY_DAYS)
        own = FtdIndex.load(st.clients.ftd_client, lo, hi, cusips=cusips) if cusips else FtdIndex()
        for r in (r for c in cusips for r in st.ftd.by_cusip(c)):
            own.add(r)
        view = index.fresh(own)

    for key, (holder, cik) in sorted(issuers.items()):
        e, (_, _, quote) = legs[key]
        last = e.last_trade.day
        day = next_trading_day(last)
        idx = view if ftd_lo and last < ftd_lo + timedelta(days=acquirer_line.EARLY_DAYS) else index
        own_sec = securities.get(e.sec_id)
        letter = acquirer_line.named_class(quote, class_letter(own_sec.share_class) if own_sec else None)
        line = acquirer_line.choose_line(idx, cik, holder=holder, letter=letter, last=last, price_day=day,
                                         exclude=e.sec_id) if cik else None
        if holder is None and line is None:
            continue
        shown = line or holder
        out[key] = _AcquirerLine(holder, line, idx.price(line, last, day) if line else None,
                                 idx.symbol_on(shown, day, last=last) or "", last, day)
    st.log(f"acquirer lines: {sum(1 for v in out.values() if v.line)} of {len(legs)} stock legs "
           f"({sum(1 for v in out.values() if v.price)} priced)")
    return out, review


def _name_acquirer_tickers(st: _Stage, mergers: list[Delisting], llm_terms: Mapping[DelistingKey, MergerTerms],
                           lines: Mapping[DelistingKey, _AcquirerLine], caller_terms: Mapping
                           ) -> tuple[dict[DelistingKey, MergerTerms], list[ReviewItem]]:
    """8a'. The ticker of a stock leg whose acquirer the LLM names without one (SHAW 2013's "CB&I", HBI 2025's
    "Gildan", CLP 2013's "MAA": prompt v3's honest null) and that stage 8a found no line of (`lines`): the filing's
    own defined terms expand the name, SEC's name index names its issuer, and the issuer's EDGAR tickers, else the
    symbol the fails rows name it under, are the ticker (`acquirer_ticker`). The terms keep every other field. A read
    that rested on a failed request is a review item and the leg keeps no ticker; it is never remembered."""
    out = dict(llm_terms)
    review: list[ReviewItem] = []
    todo = [e for e in mergers if e.key not in lines and e.last_trade.day is not None
            and for_delisting(caller_terms, e.key) is None and (t := llm_terms.get(e.key)) is not None
            and t.stock_leg and not t.acquirer_ticker and t.acquirer_name]
    if not todo:
        return out, review
    ftd_client, reads = st.clients.ftd_client, st.clients.issuers
    index = reads.name_index()
    if index is None:
        return out, review

    for e in todo:
        t, last = llm_terms[e.key], e.last_trade.day
        watch = reads.watch()
        try:
            accession = (t.source or "").split(":", 1)[-1]
            filing = next((f for f in reads.filings(e.cik) if f.accession == accession), None)
            text = reads.text(e.cik, filing) if filing is not None else ""

            def rows():
                day = next_trading_day(last)
                try:
                    for url in ftd_client.urls_for(day, day + timedelta(days=15)):
                        yield from (r for r in ftd_client.rows(url)
                                    if day.isoformat() <= r.date <= (day + timedelta(days=15)).isoformat())
                except FATAL:
                    raise
                except requests.RequestException:
                    SEC_STATS.degraded("ftd_scan")

            ticker = acquirer_ticker.acquirer_ticker(t.acquirer_name, text, index=index, subs=reads.submissions,
                                                     first_filed=reads.first_filed, rows=rows, last=last,
                                                     target_cik=e.cik)
        except FATAL:
            raise
        except requests.RequestException:
            ticker = ""
        if watch.tripped():
            review.append(degraded_item(e.sec_id, e.ticker, e.cik, "the acquirer name lookup",
                                        delist_date=e.delist_date))
        elif ticker:
            out[e.key] = replace(t, acquirer_ticker=ticker)
    st.log(f"acquirer names: {sum(1 for k in out if out[k] is not llm_terms[k])} of {len(todo)} unnamed stock legs "
           f"given a ticker")
    return out, review


# --- 3. the gate, the acquirer security and the requests ----------------------------------------------------------

def _gate(st: _Stage, mergers: list[Delisting], trade_day: Mapping[DelistingKey, date | None],
          raw: Mapping[DelistingKey, Any], llm_terms: Mapping[DelistingKey, MergerTerms],
          closes: Mapping[DelistingKey, float], caller_terms: Mapping, tol: float,
          lines: Mapping[DelistingKey, _AcquirerLine], line_first: Collection[DelistingKey],
          answers: Mapping[DelistingKey, tuple[str, float]] = {}) -> tuple[GatedPayouts, set[DelistingKey]]:
    """Every merger payout through the last-close check (`payout_gate`), the acquirer's price read from its FTD rows
    around that merger's own last trade day (`trade_day`), else from its acquirer line (`lines`, stage 8a; first for
    `line_first`, whose terms' ticker is another line's). `answers` are the caller's received closes, each as `(path,
    price)`: the price of the path (BY_TICKER or BY_LINE) the answered request belongs to, so an answer settles the
    gate only through the request it answers (`_answered_paths` works the path out from a first pass that reads no
    answer). Also the mergers whose terms took a lagged acquirer close (the caller flags them from its last pass)."""
    ftd = st.ftd
    acq_symbols = {t.ticker for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in caller_terms.values() if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(st.clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                       symbols=acq_symbols)

    lagged_acquirer: set[DelistingKey] = set()

    def answered(path: str, key: DelistingKey) -> float | None:
        """The caller's received close for this merger, when its request is the one of this price path."""
        got = answers.get(key)
        return got[1] if got is not None and got[0] == path else None

    def line_price(key: DelistingKey) -> tuple[str, float] | None:
        line = lines.get(key)
        if line is None or not line.ticker:
            return None
        given = answered(BY_LINE, key)
        if given is not None:
            return line.ticker, given
        return (line.ticker, line.price[0]) if line.price else None

    def acquirer_price(ticker: str, key: DelistingKey) -> float | None:
        given = answered(BY_TICKER, key)
        if given is not None:
            return given
        # Priced on THAT merger's own last-trade day: many mergers can share a
        # delist_date, so a plain date->day map would misprice one with another's.
        day = trade_day.get(key)
        got = ftd.close_after(day, symbol=ticker) if day and ticker else None
        if got is None:
            return None
        if got[2]:
            lagged_acquirer.add(key)
        return got[0]

    regex = {k: pr for k, pr in raw.items() if pr is not None and pr.value is not None}
    # ruling R5: a cash read the filing states in another currency than USD ("C$") cannot be checked against a USD
    # close; the gate skips it with a flag (the contract publishes it with its currency)
    foreign = {k: pr.currency for k, pr in regex.items() if getattr(pr, "currency", "") not in ("", "USD")}
    regex = {k: pr for k, pr in regex.items() if k not in foreign}
    gated = gate_payouts(
        [e.key for e in mergers],
        {k: pr.value for k, pr in regex.items()}, {k: pr.source for k, pr in regex.items()},
        {k: pr.confidence for k, pr in regex.items()}, llm_terms, closes, caller_terms,
        acquirer_price, tol, line_price=line_price, line_first=line_first,
    )
    for k, cur in foreign.items():
        if k not in gated.payouts and not for_delisting(gated.merged_terms, k):
            gated.flags[k] = gated.flags.get(k, ()) + (f"{GATE_SKIPPED}{cur}",)
    lagged: set[DelistingKey] = set()
    for e in mergers:
        # A lagged FTD close (no row on the next trading day) may carry an OTC or
        # stale price: flag the delisting when that price made it into its terms.
        terms = for_delisting(gated.merged_terms, e.key)
        line = lines.get(e.key)
        if gated.priced_by.get(e.key) == BY_LINE:
            late = bool(line and line.price and line.price[2] and answered(BY_LINE, e.key) is None)
        else:
            late = e.key in lagged_acquirer
        if late and terms and terms.get("acquirer_price") is not None:
            lagged.add(e.key)
    return gated, lagged


class _TickerSecurity:
    """The security of the fails rows under a stock leg's terms' ticker (`acquirers.find_acquirer`), asked once
    for each (ticker, last trade day, target)."""

    def __init__(self, st: _Stage) -> None:
        self.st = st
        self._memo: dict[tuple, Any] = {}

    def __call__(self, e: Delisting, ticker: str, day: date | None):
        if not ticker or day is None:
            return None
        k = (ticker, day, e.sec_id)
        if k not in self._memo:
            self._memo[k] = find_acquirer(self.st.clients.figi, self.st.ftd, ticker, day,
                                          set(self.st.cusips.get(e.sec_id, [])))
        return self._memo[k]


def _stock_ticker(e: Delisting, llm_terms: Mapping[DelistingKey, MergerTerms], caller_terms: Mapping) -> str:
    """The terms' acquirer ticker of a stock leg, as the gate's merged terms carry it: its --merger-terms row's, else
    the LLM's when it reads a number of shares (a leg the line alone priced carries the line's, which no ticker
    lookup reads)."""
    given = for_delisting(caller_terms, e.key)
    if given is not None:
        return normalize_ticker(given.get("acquirer_ticker") or "")
    t = llm_terms.get(e.key)
    return t.ticker if t is not None and t.stock_ratio else ""


def _line_wins(st: _Stage, mergers: list[Delisting], lines: Mapping[DelistingKey, _AcquirerLine],
               llm_terms: Mapping[DelistingKey, MergerTerms], caller_terms: Mapping,
               trade_day: Mapping[DelistingKey, date | None], found: _TickerSecurity) -> set[DelistingKey]:
    """The stock legs whose terms' ticker belongs to another line of the acquirer's issuer than the one stage 8a
    chose (sub-plan 5e fix): the ticker's rows are the pre-closing line's (Charter's for New Charter, TWC 2016), the
    class's other line (CBS class B for Viacom class A, VIA 2019) or a placeholder's (Lions Gate's for its class B on
    a new CUSIP, STRZA 2016), and the acquirer's line of that issuer is published and priced instead. Not for a
    ticker whose security is another issuer's (IPHI's new Marvell, an acquirer the run adds) or the line itself, nor
    for a --merger-terms row, whose ticker is the caller's."""
    out: set[DelistingKey] = set()
    for e in mergers:
        line = lines.get(e.key)
        if (line is None or not line.line or not line.holder or line.line == line.holder
                or for_delisting(caller_terms, e.key) is not None):
            continue                       # no other line of the issuer holds the ticker: nothing to settle
        got = found(e, _stock_ticker(e, llm_terms, caller_terms), trade_day.get(e.key))
        if got is None:
            out.add(e.key)
        elif got[0].composite not in (line.line, e.sec_id):
            other = st.securities.get(got[0].composite)
            mine = st.securities.get(line.line)
            if other is not None and mine is not None and other.issuer_cik and other.issuer_cik == mine.issuer_cik:
                out.add(e.key)
    return out


def _add_acquirers(st: _Stage, mergers: list[Delisting], trade_day: Mapping[DelistingKey, date | None],
                   gated: GatedPayouts, lines: Mapping[DelistingKey, _AcquirerLine],
                   line_first: Collection[DelistingKey], found: _TickerSecurity
                   ) -> tuple[dict[DelistingKey, str], dict[str, AddedSecurity], list[ReviewItem]]:
    """Each merger's acquirer security: for terms the payout gate settled on the terms' own ticker, the security
    of the fails rows under it (`acquirers.find_acquirer`), else that ticker's holder; for terms the acquirer line's
    price settled, that line, and for a `line_first` leg (`_line_wins`: the ticker's rows are another line of the
    issuer's) the line whichever price settled it; for every other stock leg, failed or never gated (sub-plan 5e),
    its acquirer line, else the ticker's holder (`lines`, stage 8a). The acquirers the run adds as securities of
    their own (`AddedAcquirer`, their issuer CIK from `acquirers.acquirer_cik`) come from the first kind only, as
    before; and a review item for each acquirer-CIK lookup that rested on a degraded answer."""
    acquirer_ids: dict[DelistingKey, str] = {}
    added: dict[str, AddedSecurity] = {}
    review: list[ReviewItem] = []
    securities = st.securities
    for e in mergers:
        key = e.key
        terms = for_delisting(gated.merged_terms, e.key)
        line = lines.get(key)
        by_line = gated.priced_by.get(key) == BY_LINE or key in line_first
        if terms and not by_line:
            acq = normalize_ticker(terms.get("acquirer_ticker") or "")
            day = trade_day.get(key)
            got = found(e, acq, day)
            if got is not None and got[0].composite != e.sec_id:
                cand, rows = got
                acquirer_ids[key] = cand.composite
                if cand.composite not in securities:
                    if cand.composite not in added:
                        watch = DegradedWatch()
                        acq_cik = acquirer_cik(st.clients.resolver, st.clients.edgar, acq, day, e)
                        watch.report_delisting(review, e, f"the acquirer {acq} CIK lookup", own_row=False)
                        added[cand.composite] = AddedAcquirer(
                            Security(cand.composite, acq_cik, share_class_from_name(cand.name), cand.name,
                                     cand.security_type, False, "cusip"), acq, day)
                    # Union every merger's FTD window for this acquirer: several mergers
                    # can name the same acquirer, and its ticker_history row must span
                    # all of them, not just the first one processed.
                    added[cand.composite].rows += rows
                continue
            if got is not None:
                continue
        if line is None:
            continue
        sid = line.line if by_line else (line.holder or line.line) if terms else (line.line or line.holder)
        if sid and sid != e.sec_id:
            acquirer_ids[key] = sid
    return acquirer_ids, added, review


def _price_tickers(acquirer_ids: Mapping[DelistingKey, str], lines: Mapping[DelistingKey, _AcquirerLine],
                   index: acquirer_line.LineIndex | None) -> dict[DelistingKey, str]:
    """Each stock leg's price ticker (sub-plan 5e rule 4): its acquirer security's symbol on the price date, from
    that security's own fails rows; none for an acquirer the run added (the terms' ticker stands)."""
    out: dict[DelistingKey, str] = {}
    for key, sid in acquirer_ids.items():
        line = lines.get(key)
        if line is None or index is None or sid not in index.securities:
            continue
        symbol = line.ticker if sid == (line.line or line.holder) else index.symbol_on(sid, line.price_day,
                                                                                        last=line.last)
        if symbol:
            out[key] = symbol
    return out


def _request(e: Delisting, llm_terms: Mapping[DelistingKey, MergerTerms], caller_terms: Mapping,
             acquirer_ids: Mapping[DelistingKey, str], price_tickers: Mapping[DelistingKey, str]
             ) -> tuple[str, str] | None:
    """The received close a merger's stock leg asks (`price_requests`): (ticker, acquirer sec_id) of an LLM stock leg
    (`MergerTerms.stock_leg`) that names its acquirer, by the acquirer security's symbol on the price date (sub-plan
    5e), else the terms' ticker; the acquirer sec_id is "" when the run found none. A --merger-terms row carries its
    own acquirer price, so it asks nothing."""
    if for_delisting(caller_terms, e.key):
        return None
    t = llm_terms.get(e.key)
    ticker = price_tickers.get(e.key) or (t.ticker if t is not None else "")
    if t is None or not t.stock_leg or not ticker:
        return None
    return ticker, acquirer_ids.get(e.key, "")


def _answered_paths(mergers: list[Delisting], answers: PriceAnswers, llm_terms: Mapping[DelistingKey, MergerTerms],
                    caller_terms: Mapping, lines: Mapping[DelistingKey, _AcquirerLine], first: GatedPayouts,
                    asked: Mapping[DelistingKey, tuple[str, str]]) -> dict[DelistingKey, tuple[str, float]]:
    """The caller's received closes that answer a request this run makes (`asked`, the stock legs' requests), each
    with the price path its request belongs to: the path the first pass (no answers) settled the gate on, else the
    acquirer line's when the request is for the line's symbol and not the terms' ticker, else the ticker's."""
    out: dict[DelistingKey, tuple[str, float]] = {}
    for e in mergers:
        request = asked.get(e.key)
        price = answers.received_close(e.sec_id, e.last_trade.day, request[0]) if request is not None else None
        if price is None:
            continue
        ticker, line = request[0], lines.get(e.key)
        path = first.priced_by.get(e.key) or (
            BY_LINE if line is not None and line.ticker == ticker and ticker != _stock_ticker(e, llm_terms,
                                                                                            caller_terms)
            else BY_TICKER)
        out[e.key] = (path, price)
    return out


# --- 4. a basket's further legs ------------------------------------------------------------------------------------

def _leg_holders(st: _Stage, mergers: list[Delisting], llm_terms: Mapping[DelistingKey, MergerTerms],
                 price_tickers: Mapping[DelistingKey, str]) -> dict[DelistingKey, dict[str, str]]:
    """Each basket's further legs (ruling R3, sub-plan 5f): the run's security that held the leg's ticker on the
    price date (`acquirer_line.LineIndex.holder`, never the target itself), the leg's own class's ticker as
    `MergerTerms.legs` gives it (CAA 2018's Lennar class B is LEN-B, not the class A's LEN); a leg no security of
    the run held has none (LGFB's LION and STRZ)."""
    out: dict[DelistingKey, dict[str, str]] = {}
    baskets = [e for e in mergers if e.last_trade.day is not None and (t := llm_terms.get(e.key)) is not None
               and t.is_basket]
    if not baskets:
        return out
    index = st.index.fresh()
    for e in baskets:
        last = e.last_trade.day
        held = {}
        t = llm_terms[e.key]
        main = price_tickers.get(e.key) or t.ticker
        for _, ticker, _ in t.legs(main)[1:]:
            sid = index.holder(ticker, last, next_trading_day(last), exclude=e.sec_id) if ticker else None
            if sid:
                held[ticker] = sid
        out[e.key] = held
    return out
