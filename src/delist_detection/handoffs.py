"""Ticker handoffs (CONTEXT.md, Handoff): one security of the run stops trading
under a ticker and another security of the run starts trading under it within
days. The pass finds every such pair (`find_handoffs`), decides what each one
is (`decide_handoff`), and acts on it (`apply_handoffs`):

- a continuation (a holding-company reorganization, a redomicile, a rename or a
  share reclassification: the holders' shares became the new security's one
  for one, and the ticker's price series continues) gets a delisting row for
  the predecessor, an `exchange_transfer` with a zero return whose
  `successor_sec_id` is the new security;
- a ticker takeover (an acquirer renamed itself after its target and took over
  its ticker: II-VI as Coherent Corp on COHR, Eldorado as Caesars on CZR)
  leaves the target's row as it is and records the taker in
  `ticker_successor_sec_id`.

The Form 25 matcher and the classifier are not changed: this pass runs after
the delisting search and the successor search, before the ticker history is
built, so a row it adds clips the predecessor's range like any other delisting.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .delistings import Delisting
from .edgar import EdgarSubmission
from .evidence import names_near
from .exit_kind import SUCCESSOR_FORMS, TIMING_CIK, TIMING_CUSIP, continuation_reason, successor_note
from .filing_search import successor_query
from .ftd import FtdIndex
from .history import TAKEOVER_DAYS, Sighting
from .last_trade import NO_DAY, at_handoff
from .review_triage import ReviewItem
from .rewrites import HANDOFF_CONTINUATION, Payouts, Rule, continuation
from .security_master import Security
from .store import DelistingKey

OVERLAP_DAYS = 10         # B's first sighting under the ticker may precede A's last by this much (CZR: 8)
CONTINUATION_DAYS = 10    # a continuation by timing: A's last and B's first sighting this close
# TAKEOVER_DAYS (history.py: a successor's ticker window too): B's first sighting at most this long after A's last
ISSUER_AGE_DAYS = 365     # B's issuer filing with EDGAR this long before the handoff: a company that existed


def _bare(ticker: str) -> str:
    return ticker.replace("-", "")


def _days(lo: str, hi: str) -> int:
    return (date.fromisoformat(hi) - date.fromisoformat(lo)).days


@dataclass(frozen=True)
class HandoffPair:
    """Security `a` stops trading under `ticker` (its last sighting under it,
    `a_last`) and security `b` starts under it (`b_first`); `b_first_any` is
    `b`'s first sighting under any ticker (earlier than `b_first` for a taker
    that traded under its own ticker first); `a_last_any` is `a`'s last
    sighting under any ticker (later than `a_last` when `a` lived on under
    another ticker: Delphi Automotive as APTV, after the spun-off Delphi
    Technologies took DLPH)."""
    ticker: str
    a: str
    b: str
    a_last: str
    b_first: str
    b_first_any: str
    a_last_any: str = ""

    @property
    def gap(self) -> int:
        """Days from A's last sighting under the ticker to B's first (negative: they overlap)."""
        return _days(self.a_last, self.b_first)


def find_handoffs(sightings: Mapping[str, Sequence[Sighting]]) -> list[HandoffPair]:
    """The candidate handoffs among the run's securities (`sightings`: sec_id ->
    its dated ticker sightings, `history.ticker_sightings`; a ticker spelled
    with or without its separator is one ticker). For each ticker, the
    securities sighted under it, in the order they began under it; each one and
    the next one to begin form a pair when the next one's first sighting under
    the ticker falls within [-OVERLAP_DAYS, TAKEOVER_DAYS] days of the first
    one's last sighting under it. Sorted by ticker, then date."""
    spans: dict[str, dict[str, list[str]]] = defaultdict(dict)       # bare ticker -> sec_id -> [first, last]
    label: dict[tuple[str, str], str] = {}
    first_any: dict[str, str] = {}
    last_any: dict[str, str] = {}
    for sid, sig in sightings.items():
        for s in sig:
            t = _bare(s.value)
            span = spans[t].setdefault(sid, [s.day, s.day])
            span[0], span[1] = min(span[0], s.day), max(span[1], s.day)
            label.setdefault((t, sid), s.value)
            first_any[sid] = min(first_any.get(sid, s.day), s.day)
            last_any[sid] = max(last_any.get(sid, s.day), s.day)
    out: list[HandoffPair] = []
    for t, by_sec in spans.items():
        ordered = sorted(by_sec.items(), key=lambda kv: (kv[1][0], kv[0]))
        for (a, (_, a_last)), (b, (b_first, _)) in zip(ordered, ordered[1:]):
            if -OVERLAP_DAYS <= _days(a_last, b_first) <= TAKEOVER_DAYS:
                out.append(HandoffPair(label[(t, a)], a, b, a_last, b_first, first_any[b], last_any[a]))
    return sorted(out, key=lambda p: (p.ticker, p.a_last, p.a, p.b))


@dataclass(frozen=True)
class HandoffDecision:
    """What a pair is: `kind` "continuation" or "takeover", on what evidence
    (`evidence`: "<form> <accession>" of the successor issuer's filing, or
    "timing:cik" / "timing:cusip" for a continuation by timing and identity,
    "timing" for a takeover), and whether a filing settled it (`by_filing`)."""
    pair: HandoffPair
    kind: str
    evidence: str
    by_filing: bool


def continuation_filing(search: Callable, *, name: str, day: date,
                        successor_cik: int) -> tuple[str, str, str] | None:
    """The successor-issuer filing (8-K12B / 8-K12G3, Rule 12g-3) that
    `successor_cik` filed naming the predecessor's issuer `name` around `day`
    (EDGAR full-text search, `filing_search.successor_query`: 30 days before to 60
    after), as (form, accession, filing date); None without one. The filer may
    keep the predecessor's CIK (Aon plc's 2020 move from the UK to Ireland)."""
    for h in search(*successor_query(name, day)):
        src = h.get("_source", h)
        if successor_cik in {int(c) for c in src.get("ciks") or []}:
            return src.get("form") or "", src.get("adsh") or "", src.get("file_date") or ""
    return None


def own_continuation_filing(filings: Sequence[EdgarSubmission], day: date) -> tuple[str, str, str] | None:
    """The successor issuer's own 8-K12B/8-K12G3 (Rule 12g-3) in its filing list,
    in the window `continuation_filing`'s search uses (30 days before `day`, B's
    first sighting, to 60 after), as (form, accession, filing date); the first
    by filing date. Where the full-text search for the predecessor's name finds
    nothing, the successor's own registration is the filing that says the
    holders' shares carried over (Xerox Holdings 2019, Cigna 2018)."""
    lo, hi = day - timedelta(days=30), day + timedelta(days=60)
    hits = sorted((f.filing_date, f.form, f.accession) for f in filings
                  if f.form in SUCCESSOR_FORMS and f.filing_date
                  and lo <= date.fromisoformat(f.filing_date) <= hi)
    return (hits[0][1], hits[0][2], hits[0][0]) if hits else None


_CLASS_WORDS = re.compile(r"\b(?:CL(?:ASS)?|SER(?:IES)?)\s*-?\s*[A-Z0-9]\b|-[A-Z]$", re.I)
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")


def predecessor_names(sub: dict | None, a_last: str, observed: str | None) -> list[str]:
    """The names to search A's successor-issuer filing under, as an 8-K12B would
    print A's issuer: the EDGAR names it carried within 30 days of its last
    sighting (a reorganization often renames the old company right after:
    Ashland Inc's CIK is ASHLAND LLC today), then its current EDGAR name, then
    its observed name without class words; state tags dropped, each once."""
    names: list[str] = []
    if isinstance(sub, dict):
        names += names_near(sub, date.fromisoformat(a_last), 30)
        names.append(sub.get("name") or "")
    names.append(_CLASS_WORDS.sub(" ", observed or ""))
    out: list[str] = []
    for n in names:
        n = re.sub(r"\s+", " ", _STATE_TAG.sub("", n)).strip(" -")
        if n and n.upper() not in {o.upper() for o in out}:
            out.append(n)
    return out


def cusip_switch(ftd: FtdIndex, pair: HandoffPair, a_cusips: Sequence[str], b_cusips: Sequence[str]) -> bool:
    """Whether the pair's ticker switches CUSIP in the fails data at the
    handoff: a CUSIP of A's last fails under the ticker, and a different CUSIP
    of B's first fails under it, both within `CONTINUATION_DAYS` of B's first
    sighting (ITT 2016: 450911201 last fails 2016-05-17, 45073V108 first
    2016-05-18)."""
    rows = ftd.by_symbol(pair.ticker)
    a_rows = [r for r in rows if r.cusip in a_cusips]
    b_rows = [r for r in rows if r.cusip in b_cusips and r.cusip not in a_cusips]
    if not a_rows or not b_rows:
        return False
    return all(abs(_days(pair.b_first, d)) <= CONTINUATION_DAYS for d in (a_rows[-1].date, b_rows[0].date))


def issuer_carries_on(pair: HandoffPair, securities: Mapping[str, Security],
                      first_seen: Mapping[str, str]) -> bool:
    """Whether A's issuer starts another security of the run (not B, and not of
    B's issuer) within `CONTINUATION_DAYS` of A's last sighting: A's holders
    kept A's issuer under a new line and ticker, while B, another issuer's line,
    took the old ticker (Liberty Media's 2013 split: the old issuer went on as
    STRZA, the spun-off Liberty Media took LMCA). `first_seen`: each security's
    first sighting."""
    a, b = securities.get(pair.a), securities.get(pair.b)
    if a is None or b is None or a.issuer_cik is None or a.issuer_cik == b.issuer_cik:
        return False
    return any(s.issuer_cik == a.issuer_cik and sid not in (pair.a, pair.b) and sid in first_seen
               and abs(_days(pair.a_last, first_seen[sid])) <= CONTINUATION_DAYS
               for sid, s in securities.items())


def decide_handoff(pair: HandoffPair, *, filing: tuple[str, str, str] | None, same_issuer: bool,
                   cusip_switch: bool, issuer_carries_on: bool = False,
                   b_issuer_since: str | None = None) -> HandoffDecision | None:
    """What the pair is, the first rule that applies. A that lived on under
    another ticker (`pair.a_last_any` past `CONTINUATION_DAYS` after A's last
    sighting under this one) is no continuation at all: B took a ticker A
    left, as a spin-off does.

    1. a continuation by filing: B's issuer filed an 8-K12B/8-K12G3 naming A's
       issuer (`filing`, `continuation_filing`);
    2. a continuation by timing and identity: A's last and B's first sighting
       are at most `CONTINUATION_DAYS` apart, B was sighted under no ticker
       before `CONTINUATION_DAYS` ahead of A's last, and the two share an issuer
       CIK (`same_issuer`) or the ticker's CUSIP switches from A's to B's
       (`cusip_switch`), and A's issuer does not carry on in another line while
       B is another issuer's (`issuer_carries_on`);
    3. a takeover: B traded before (under another ticker: IIVI), or B's issuer
       is another, older company (it filed with EDGAR `ISSUER_AGE_DAYS` before A's
       last sighting, `b_issuer_since`: Eldorado, unobserved as ERI, took CZR);
    4. otherwise nothing (None)."""
    lived_on = bool(pair.a_last_any) and _days(pair.a_last, pair.a_last_any) > CONTINUATION_DAYS
    if filing is not None and not lived_on:
        form, accession, _ = filing
        return HandoffDecision(pair, "continuation", f"{form} {accession}".strip(), True)
    existed = _days(pair.b_first_any, pair.a_last) > CONTINUATION_DAYS
    if (abs(pair.gap) <= CONTINUATION_DAYS and not existed and not lived_on and not issuer_carries_on
            and (same_issuer or cusip_switch)):
        return HandoffDecision(pair, "continuation", TIMING_CIK if same_issuer else TIMING_CUSIP, False)
    older = (not same_issuer and b_issuer_since is not None
             and _days(b_issuer_since, pair.a_last) > ISSUER_AGE_DAYS)
    if existed or older:
        return HandoffDecision(pair, "takeover", "timing" if existed else "timing:issuer", False)
    return None


FORM25_NEAR_DAYS = 30            # an ambiguous Form 25 of A this soon after the handoff dates the new row
CONTINUATION_FLAG = HANDOFF_CONTINUATION
UNMATCHED_FORM25 = "form25_unmatched"     # the finder's item for a Form 25 of ambiguous class (its `filing` typed)
# A's review rows a continuation explains: it did end, by the handoff.
_RESOLVED_FLAGS = ("ended_without_delisting",)


@dataclass
class HandoffOutcome:
    """`apply_handoffs`' answer: the delisting rows it adds, the review items
    (the input's, less those a continuation resolves, plus its own), the pairs
    whose `ticker_shared` rows a continuation resolves (`drop_resolved_shared`),
    and the counts for run_manifest.json."""
    added: list[Delisting]
    review: list[ReviewItem]
    resolved_pairs: set[tuple[str, str, str]]
    counts: dict[str, int]


def _day_of(d: Delisting) -> date:
    return d.anchor


def _near(delistings: Sequence[Delisting], pair: HandoffPair, sec_id: str, days: int) -> Delisting | None:
    """`sec_id`'s delisting nearest the handoff: its last trade (else its
    delisting date) within `days` before A's last sighting and `days` after the
    later of A's last and B's first sighting."""
    lo = date.fromisoformat(pair.a_last) - timedelta(days=days)
    hi = date.fromisoformat(max(pair.a_last, pair.b_first)) + timedelta(days=days)
    near = [d for d in delistings if d.sec_id == sec_id and lo <= _day_of(d) <= hi]
    a = date.fromisoformat(pair.a_last)
    return min(near, key=lambda d: (abs((_day_of(d) - a).days), d.delist_date), default=None)


def _unmatched_form25(review: Sequence[ReviewItem], pair: HandoffPair) -> ReviewItem | None:
    """A's `form25_unmatched` ambiguous-class item for the handoff: effective on
    or after A's last sighting (a delisting takes effect after the last trade:
    the Braves split-off's Form 25, a week before FWONA's last sighting, is
    another event), and no more than `FORM25_NEAR_DAYS` after the later of A's
    last and B's first sighting (fails rows can be sparse: old LabCorp's last is
    five weeks before its Form 25, the holding company's first one week);
    nearest A's last sighting first."""
    a = date.fromisoformat(pair.a_last)
    hi = date.fromisoformat(max(pair.a_last, pair.b_first)) + timedelta(days=FORM25_NEAR_DAYS)
    items = [r for r in review if r.sec_id == pair.a and r.flag == UNMATCHED_FORM25 and r.delist_date
             and r.filing is not None and a <= date.fromisoformat(r.delist_date) <= hi]
    return min(items, key=lambda r: (r.delist_date, r.reason), default=None)


def _continuation_reason(decision: HandoffDecision) -> str:
    p = decision.pair
    return continuation_reason(decision.evidence, f"{p.a} last traded as {p.ticker} on {p.a_last} and {p.b} took the "
                                                  f"ticker from {p.b_first}; holders' shares became {p.b}'s")


def _continue(d: Delisting, decision: HandoffDecision, payouts: Payouts | None) -> None:
    """Rewrite A's row `d` to the continuation's values (`rewrites.continuation`, `Rule.HANDOFF`: a 304 whose
    successor is B, its no-evidence default, payout reads and payout flags dropped)."""
    p = decision.pair
    continuation(d, p.b, Rule.HANDOFF, reason=_continuation_reason(decision),
                 confidence="high" if decision.by_filing else "medium", flag=CONTINUATION_FLAG, how="handoff",
                 evidence=decision.evidence, successor_from=p.b_first, payouts=payouts)


def _continuation_row(decision: HandoffDecision, sec: Security, form25: ReviewItem | None) -> Delisting | None:
    """The delisting row a continuation writes for A, which has none near it: built with no kind, then made the
    continuation by the one rewrite every handoff continuation takes (`_continue`). Its Form 25 is the ambiguous
    one's typed filing (`ReviewItem.filing`)."""
    p = decision.pair
    if sec.issuer_cik is None:
        return None
    evidence: dict = {"name": sec.name}
    if form25 is not None:
        delist_date = form25.delist_date
        evidence["delist_filing"] = {"form": form25.filing.form, "filing_date": form25.filing.filing_date,
                                     "accession": form25.filing.accession}
    else:
        delist_date = (date.fromisoformat(p.a_last) + timedelta(days=1)).isoformat()
    last = at_handoff(None, p.a_last, p.b_first)
    rec = DelistRecord(p.ticker, sec.issuer_cik, last.day.isoformat(), None, CrspBucket.UNKNOWN, "", "", evidence,
                       sec_id=sec.sec_id, delist_date=delist_date)
    d = Delisting(sec.sec_id, sec.issuer_cik, p.ticker, delist_date, rec, last, None, None, "")
    _continue(d, decision, None)
    return d


def apply_handoffs(decisions: Sequence[HandoffDecision], delistings: Sequence[Delisting],
                   securities: Mapping[str, Security], review: Sequence[ReviewItem], *,
                   reconciled: Collection[DelistingKey] = (), payouts: Payouts | None = None) -> HandoffOutcome:
    """Act on each decided pair (A hands the ticker to B).

    A continuation:
    - with no delisting of A near the handoff (`_near`, `CONTINUATION_DAYS`),
      writes one: dated by A's ambiguous-class Form 25 that took effect after
      A's last sighting and within `FORM25_NEAR_DAYS` of the handoff
      (`_unmatched_form25`; its effective date, as every Form 25 row), else the
      day after that sighting; last trade on A's last
      sighting, but before B's first (`last_trade.at_handoff`); an `exchange_transfer` (code 304, so a zero return) whose
      successor is B; confidence high on a filing, medium on timing; flagged
      `handoff_continuation`, the evidence in its reason;
    - with one, sets its successor to B, rewriting an `unknown` or a merger
      row to the continuation's values -- except a merger on timing evidence
      between two issuers (`timing:cusip`), or whose payout was reconciled
      (`reconciled`, by delisting key) on timing evidence alone, or that spec 5c's rule 6 made (sub-plan 5f: its
      own-share statement gives another ratio, `end_of_era` `successor_merger`), which stands,
      with a `handoff_conflict` item; a rewritten merger keeps its
      old bucket in a `handoff_rebucketed` item. A row that ended A in
      another way (a liquidation, a compliance failure, an expiration), or that
      already names another successor or itself, stands too, with a
      `handoff_conflict` item.
    Every continuation goes through `rewrites.continuation` (`Rule.HANDOFF`): a rewritten merger's value is dropped
    from `payouts` (stage 8's merger values; required when a merger is rewritten).
    A kept row's last trade is the last trade module's (`last_trade.at_handoff`): with no day it takes A's last
    sighting before B's first, so A's range ends before B's begins, and a worked-out closing day never reaches B's
    first sighting. A continuation that wrote or kept a row resolves A's `ended_without_delisting`
    item, the ambiguous-class Form 25 items of A and B it rests on, and the
    pair's `ticker_shared` rows (`resolved_pairs`).

    A takeover sets `ticker_successor_sec_id` to B on A's delisting nearest the
    handoff (within `TAKEOVER_DAYS`), else writes a
    `handoff_takeover_no_delisting` item."""
    added: list[Delisting] = []
    own: list[ReviewItem] = []
    drop: set[int] = set()
    resolved: set[tuple[str, str, str]] = set()
    counts = {"handoffs": len(decisions), "continuations_by_filing": 0, "continuations_by_timing": 0,
              "takeovers": 0, "conflicts": 0, "rows_added": 0}
    rows = list(delistings)
    for decision in decisions:
        p = decision.pair
        if decision.kind == "takeover":
            counts["takeovers"] += 1
            d = _near(rows, p, p.a, TAKEOVER_DAYS)
            if d is not None:
                d.record.ticker_successor_sec_id = p.b
            else:
                sec = securities.get(p.a)
                own.append(ReviewItem(p.a, p.ticker, sec.issuer_cik if sec else None, "handoff_takeover_no_delisting",
                                      f"{p.b} took over {p.ticker} from {p.b_first} ({p.a} last seen under it "
                                      f"{p.a_last}), but {p.a} has no delisting to record it on",
                                      last_seen=p.a_last))
            continue
        counts["continuations_by_filing" if decision.by_filing else "continuations_by_timing"] += 1
        d = _near(rows, p, p.a, CONTINUATION_DAYS)
        form25 = _unmatched_form25(review, p)
        if d is None:
            d = _continuation_row(decision, securities[p.a], form25)
            if d is None:
                continue
            added.append(d)
            rows.append(d)
            counts["rows_added"] += 1
        else:
            bucket = d.record.bucket
            conflict = None
            if d.record.successor_sec_id not in (None, "", p.b):
                conflict = f"its row already names {d.record.successor_sec_id} as its successor"
            elif bucket is CrspBucket.MERGER and decision.evidence == TIMING_CUSIP:
                # Another issuer's new line taking the target's ticker is also an
                # acquirer's holding company (Wendy's into Wendy's/Arby's at 4.25
                # shares, IGT into IGT PLC for cash and stock): only a filing says
                # the holders' shares carried over one for one.
                conflict = "its merger row says holders were paid, and only timing across two issuers says otherwise"
            elif bucket is CrspBucket.MERGER and not decision.by_filing and d.key in reconciled:
                conflict = "its merger row has a reconciled payout and only timing says otherwise"
            elif bucket is CrspBucket.MERGER and (d.record.evidence or {}).get("end_of_era") == "successor_merger":
                # spec 5c rule 6 (sub-plan 5f): the registrant's own filings say each share became another number of
                # the successor's shares (CHTR 2016, 0.9042 New Charter): a merger, whatever files the successor's
                # registration
                conflict = "its own-share statement gives another ratio than one for one (rule 6)"
            elif bucket not in (CrspBucket.MERGER, CrspBucket.EXCHANGE_TRANSFER, CrspBucket.UNKNOWN):
                conflict = f"its row is a {bucket.value}"
            if conflict is not None:
                counts["conflicts"] += 1
                own.append(ReviewItem(p.a, d.ticker, d.cik, "handoff_conflict",
                                      f"{p.b} continues {p.a} under {p.ticker} ({decision.evidence}), but "
                                      f"{conflict}; the row stands", delist_date=d.delist_date))
                continue
            if bucket is not CrspBucket.EXCHANGE_TRANSFER:
                if bucket is CrspBucket.MERGER:
                    own.append(ReviewItem(p.a, d.ticker, d.cik, "handoff_rebucketed",
                                          f"was {bucket.value} (CRSP {d.record.crsp_code}: {d.record.reason}); "
                                          f"{p.b} continues it under {p.ticker} ({decision.evidence})",
                                          delist_date=d.delist_date))
                _continue(d, decision, payouts)
            elif d.record.successor_sec_id != p.b:           # else the successor search already linked B
                continuation(d, p.b, Rule.HANDOFF,
                             reason=d.record.reason + successor_note("handoff", decision.evidence),
                             flag=CONTINUATION_FLAG, how="handoff", evidence=decision.evidence,
                             successor_from=p.b_first)
            if d.last_trade.day is None:            # A's range ends where B's begins (PNFP 2026)
                d.record.evidence["flags"] = [f for f in d.flags if f != NO_DAY]
            d.last_trade = at_handoff(d.last_trade, p.a_last, p.b_first)
        resolved.add((_bare(p.ticker), p.a, p.b))
        accession = form25.filing.accession if form25 is not None else None
        for i, r in enumerate(review):
            if r.sec_id == p.a and r.flag in _RESOLVED_FLAGS:
                drop.add(i)
            elif (accession and r.flag == UNMATCHED_FORM25 and r.sec_id in (p.a, p.b)
                  and r.filing is not None and r.filing.accession == accession):
                drop.add(i)
    kept = [r for i, r in enumerate(review) if i not in drop]
    return HandoffOutcome(added, kept + own, resolved, counts)


def drop_resolved_shared(items: Sequence[ReviewItem], resolved: Collection[tuple[str, str, str]]) -> list[ReviewItem]:
    """`items` less the `ticker_shared` rows (`history.ticker_range_review`) that
    name both securities of a continuation the pass resolved."""
    def solved(r: ReviewItem) -> bool:
        return r.flag == "ticker_shared" and any(
            _bare(r.ticker) == t and f"({a})" in r.reason and f"({b})" in r.reason for t, a, b in resolved)
    return [r for r in items if not solved(r)]
