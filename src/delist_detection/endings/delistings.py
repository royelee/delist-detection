"""Find, date and classify every delisting of one security (D6, D16, D17, D20).

A delisting is a Form 25 that removed the security's class from its exchange
and left it on no exchange or on a new one. Securities with no Form 25 fall back
to the classifier's no-Form-25 paths; a security that ended with no evidence at
all is reported for review instead of being dropped.

The finder's interface (architecture step 14): `DelistingFinder.find(SecurityContext)`, where the context is data
only -- the security's trading record (`trading_record.TradingRecord`), its issuer's securities' records, whether it
is listed today, its other CIK in force and its issuer's lookup tier -- and `SecurityContexts`, the constructor that
builds each security's record once over its sightings, its own CUSIPs and the fails index. The finder works out what
it reads of the security's trading from the record itself.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cached_property

from .classifier import DelistClassifier
from ..outputs.reconstruction import DelistRecord
from ..vocabulary.crsp_codes import CrspBucket
from ..sources.edgar import EdgarSubmission
from ..filings.evidence import edgar_names
from ..vocabulary.exit_kind import effective_date, rests_on_continued_filings
from ..sources.ftd import FtdIndex
from ..filings.form25 import (
    ISSUER_FORM25_FORMS, REGIONAL_EXCHANGES, Form25, SecurityRef, class_kind, class_letters, is_involuntary,
    list_form25, match_securities, other_class, parse_form25, tied_securities,
)
from ..identity.history import Ending
from ..vocabulary.identifiers import class_letter
from .last_trade import Dating, LastTrade, anchor_day
from ..filings.listing_status import exchanges_around, issuer_exchange, withdrawal_kind
from .own_shares import OwnShares
from ..outputs.review_triage import FilingRef, ReviewItem
from .rewrites import SUCCESSOR_UNKNOWN, Rewrite, Rule, continuation, security_goes_on
from ..identity.security_master import Security
from ..outputs.store import DelistingKey
from ..vocabulary.trading_calendar import add_trading_days
from .trading_record import TradingRecord

FORM25_LOOKBACK_DAYS = 30           # how far before the security's first sighting to look for a Form 25
SAME_EVENT_DAYS = 30                # Form 25s of this security this close together are one delisting
IGNORE_AFTER_DEFINITIVE_DAYS = 30   # once truly delisted, a later Form 25 past this is suspect
SEEN_AFTER_DAYS = 5                 # sighted this long past the effective date: the security kept trading
SIBLING_ALIVE_BEFORE_DAYS = 30      # a sibling's own first sighting, minus this: still alive
SIBLING_ALIVE_AFTER_DAYS = 400      # a sibling's own last sighting, plus this: still alive
DEREG_FALLBACK_BEFORE_DAYS = 30     # a fallback revocation or Form 15 must be within
OWN_SWITCH_DAYS = 5                 # trading days between a Form 25 and the security's own CUSIP switch it removed
DEREG_FALLBACK_AFTER_DAYS = 120     # [last_seen - this, last_seen + this] to date the delisting
EIGHT_A_DAYS = 10                   # the issuer's own Form 25 and its 8-A12B this close together: an exchange move
EIGHT_A_FORMS = frozenset({"8-A12B"})      # not 8-A12B/A: a rights-plan amendment registers no class (Biomet 2006)
EARLY_REACH_DAYS = 365              # gone today: Form 25s this far before the floor are judged in the main scan
LATE_ROW_DAYS = 30                  # no sibling alive: the security's own CUSIP traded this close before the Form 25

# Buckets whose delisting ends the security's exchange life even when it is
# sighted afterwards (OTC trading, a stale snapshot): all but a transfer and
# a delisting the classifier could not place.
ENDING_BUCKETS = frozenset({CrspBucket.MERGER, CrspBucket.LIQUIDATION, CrspBucket.COMPLIANCE_FAILURE,
                            CrspBucket.EXPIRATION})

# Preferred exchange for a multi-exchange delisting group: the filing on the
# most-senior exchange supplies the delisting's `exchange` and `form25`/`form25_sub`.
EXCHANGE_PREFERENCE = ("NYSE", "NASDAQ", "NYSE AMERICAN", "CBOE BZX", "NYSE ARCA")


@dataclass
class Delisting:
    """One delisting of one security (CONTEXT.md): the Form 25 group (or the
    fallback filing) that ended its listing, dated and classified (`record`).
    Its kind and successor change after the finder built it only through
    `rewrites.py`, which records each change in `rewrites` (typed provenance).
    `own_shares`: what the registrant said each share became (`own_shares.OwnShares`), once read: the
    classifier's reading when its rules read it, else the first later stage's (`own_shares.of`)."""
    sec_id: str
    cik: int
    ticker: str
    delist_date: str
    record: DelistRecord
    last_trade: LastTrade
    form25: Form25 | None
    form25_sub: EdgarSubmission | None
    exchange: str
    rewrites: list[Rewrite] = field(default_factory=list)
    own_shares: OwnShares | None = field(default=None, compare=False, repr=False)

    @property
    def key(self) -> DelistingKey:
        """`(sec_id, delist_date)`: the delisting's key in delistings.csv and in
        every per-delisting map of the run."""
        return DelistingKey(self.sec_id, self.delist_date)

    @property
    def flags(self) -> list[str]:
        """The delisting's review flags: its record's `evidence["flags"]`, the one
        list its delistings.csv row is built from (the classifier's flags, then
        the finder's and the pipeline's)."""
        return self.record.evidence.setdefault("flags", [])

    def add_flag(self, flag: str) -> None:
        self.flags.append(flag)

    @property
    def anchor(self) -> date:
        """The day this ending is read around (`last_trade.anchor_day`): its last trade, else its Form 25's filing
        date, else the 8-K the classifier anchored on, else its delisting date."""
        filed = self.form25_sub.filing_date if self.form25_sub is not None else None
        anchor_8k = ((self.record.evidence or {}).get("anchor_8k") or {}).get("filing_date")
        return anchor_day(self.last_trade, self.delist_date, filed=filed, anchor_8k=anchor_8k)

    @property
    def ending(self) -> Ending:
        """What the security's history reads of this delisting (`history.Ending`): its key, last trade, bucket,
        successor and exchange, as they stand now."""
        return Ending(self.key, self.last_trade, self.record.bucket, self.record.successor_sec_id, self.exchange)


def _ref(record: TradingRecord) -> SecurityRef:
    """The finder's view of a security (`form25.SecurityRef`): its class, kind and name, and for a class with no
    letter the one its own CUSIPs' fails descriptions name (`TradingRecord.letter_hint`, R2)."""
    s = record.security
    return SecurityRef(s.sec_id, s.share_class, s.kind, s.name, record.letter_hint)


@dataclass(frozen=True)
class SecurityContext:
    """What the finder reads of one security, all data: its trading record (`trading_record.TradingRecord`: its
    sightings, own CUSIPs and the fails index, from which the finder works out the ticker on a day, the last
    sighting, trading after a day, rows near a Form 25, its CUSIP switches, the ticker's tenure and the rows' last
    trading day); the records of the securities of its issuer the search holds (`siblings`; itself among them, added
    when absent), among which a Form 25 is matched while each is alive (`spans`); whether it is listed today
    (None: unknown); the one CIK other than its issuer's that was its issuer in force over its whole span
    (`other_cik`, R5: stage 4c, `pipeline._other_issuers`), whose Form 25s are read too (the old Spectrum Brands,
    the old Match Group); and the lookup tier that found its issuer (`resolution_source`, recorded on every
    DelistRecord of its delistings). Built by `SecurityContexts` (stage 5, the real-case harnesses) or directly
    from a record (stage 9d's added successors)."""
    record: TradingRecord
    siblings: tuple[TradingRecord, ...] = ()
    listed_today: bool | None = None
    other_cik: int | None = None
    resolution_source: str = "security_master"

    @property
    def security(self) -> Security:
        return self.record.security

    @cached_property
    def _members(self) -> tuple[TradingRecord, ...]:
        """The siblings, the security's own record among them."""
        own = self.security.sec_id
        return self.siblings if any(r.security.sec_id == own for r in self.siblings) else (self.record, *self.siblings)

    @cached_property
    def refs(self) -> list[SecurityRef]:
        """The finder's view of each sibling (`_ref`), in the siblings' order."""
        return [self.own_ref if r.security.sec_id == self.security.sec_id else _ref(r) for r in self._members]

    @cached_property
    def own_ref(self) -> SecurityRef:
        return _ref(self.record)

    @cached_property
    def spans(self) -> dict[str, tuple[str, str]]:
        """sec_id -> (first sighting, last own-ticker sighting) of each sibling with sightings
        (`TradingRecord.span`). A sibling absent here is treated as alive at every filing date."""
        return {r.security.sec_id: r.span for r in self._members if r.span is not None}


class SecurityContexts:
    """The finder's contexts over one search's securities: each security's trading record, and as its siblings the
    records of every security of its issuer (by issuer CIK, in the records' order; a security with no CIK stands
    alone). Asked for a security and today's listing answer (`contexts(security, listed)`), it gives that security's
    `SecurityContext`, with its other CIK in force (`other_ciks`, by sec_id) and its issuer's lookup tier
    (`resolution_source(security)`; none: "security_master"). Stage 5's warm pass and its sequential pass ask the
    one object, so each security is searched over the same context on either."""

    def __init__(self, records: Iterable[TradingRecord], *, other_ciks: Mapping[str, int] = {},
                 resolution_source: Callable[[Security], str] | None = None) -> None:
        self.records: dict[str, TradingRecord] = {r.security.sec_id: r for r in records}
        of_issuer: dict[int, list[TradingRecord]] = defaultdict(list)
        for r in self.records.values():
            if r.security.issuer_cik is not None:
                of_issuer[r.security.issuer_cik].append(r)
        self._siblings = {cik: tuple(rs) for cik, rs in of_issuer.items()}
        self._other_ciks = dict(other_ciks)
        self._resolution_source = resolution_source

    @classmethod
    def observed(cls, securities: Mapping[str, Security], cusips: Mapping[str, Sequence[str]], fails: FtdIndex,
                 **kw) -> SecurityContexts:
        """The contexts over a run's securities (`TradingRecord.observed`: each over its own CUSIPs, `cusips` by
        sec_id, and the fails index); `kw`: `other_ciks`, `resolution_source`."""
        return cls((TradingRecord.observed(s, fails, cusips.get(sid, ())) for sid, s in securities.items()), **kw)

    def __call__(self, security: Security, listed_today: bool | None) -> SecurityContext:
        record = self.records[security.sec_id]
        source = self._resolution_source(security) if self._resolution_source is not None else "security_master"
        return SecurityContext(record, self._siblings.get(security.issuer_cik, (record,)), listed_today,
                               self._other_ciks.get(security.sec_id), source)


@dataclass
class _Scan:
    """The finder's working state for one security: the ticker its review rows carry, the review items and the
    keys already raised, whether some Form 25 could not be placed, the Form 25s from before the early window (the
    fallback's to judge), and those whose text could not be read."""
    ticker: str
    review: list[ReviewItem] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    had_unmatched: bool = False
    older: list[EdgarSubmission] = field(default_factory=list)
    unreadable: list[EdgarSubmission] = field(default_factory=list)


class DelistingFinder:
    """Finds, matches, groups and classifies a security's delistings; the last trade module dates each one
    (`last_trade.Dating`, over the run's EDGAR client and the `midas` and `halts` adapters it is given)."""

    def __init__(self, edgar, classifier: DelistClassifier, *, midas=None, halts=None) -> None:
        self.edgar, self.classifier = edgar, classifier
        self.dating = Dating(edgar, midas=midas, halts=halts)

    # -- sibling / class matching -----------------------------------------
    def _alive_at(self, ctx: SecurityContext, sec_id: str, filing_date: str) -> bool:
        span = ctx.spans.get(sec_id)
        if span is None:
            return True
        first, last = span
        lo = (date.fromisoformat(first) - timedelta(days=SIBLING_ALIVE_BEFORE_DAYS)).isoformat()
        hi = (date.fromisoformat(last) + timedelta(days=SIBLING_ALIVE_AFTER_DAYS)).isoformat()
        return lo <= filing_date <= hi

    @staticmethod
    def _at_own_switch(ctx: SecurityContext, filing_date: str) -> bool:
        """Whether one of the security's own CUSIP switches (`TradingRecord.cusip_switches`: a reverse split, a
        redomicile that kept the composite) lies within `OWN_SWITCH_DAYS` trading days of a Form 25's filing date: a
        Form 25 filed there while the security trades on removed the old CUSIP, not the security (QGEN 2026,
        Acxiom/LiveRamp 2018)."""
        day = date.fromisoformat(filing_date)
        lo = add_trading_days(day, -OWN_SWITCH_DAYS).isoformat()
        hi = add_trading_days(day, OWN_SWITCH_DAYS).isoformat()
        return any(lo <= d <= hi for d in ctx.record.cusip_switches)

    def _class_conflict(self, f25: Form25, ref: SecurityRef) -> bool:
        """True when the Form 25 names class letters and the matched sibling's
        class letter is not one of them: `match_securities`' single-sibling branch
        (`len(same) == 1`) accepts by elimination without checking letters, so
        this is the backstop for a class the universe doesn't actually hold."""
        f_letters = class_letters(f25.class_text)
        r_letter = class_letter(ref.share_class)
        return bool(f_letters and r_letter and r_letter not in f_letters)

    # -- grouping -----------------------------------------------------------
    def _group(self, candidates: list[tuple[EdgarSubmission, Form25]]
              ) -> list[list[tuple[EdgarSubmission, Form25]]]:
        """Chain matched Form 25s into one group per delisting: each filing joins
        the open group when it's within SAME_EVENT_DAYS of the group's EARLIEST
        filing (not its latest member), across exchanges — so filings on days
        0, 28 and 55 make two delistings (day 55 is 55 days from day 0), not one."""
        groups: list[list[tuple[EdgarSubmission, Form25]]] = []
        for item in sorted(candidates, key=lambda i: i[0].filing_date):
            gap = (date.fromisoformat(item[0].filing_date) - date.fromisoformat(groups[-1][0][0].filing_date)).days if groups else None
            if gap is not None and gap <= SAME_EVENT_DAYS:
                groups[-1].append(item)
            else:
                groups.append([item])
        return groups

    def _exchange_rank(self, item: tuple[EdgarSubmission, Form25]) -> tuple[int, str]:
        sub, f25 = item
        try:
            return EXCHANGE_PREFERENCE.index(f25.exchange), sub.filing_date
        except ValueError:
            return len(EXCHANGE_PREFERENCE), sub.filing_date

    # -- review bookkeeping --------------------------------------------------
    def _review(self, review: list[ReviewItem], seen: set[tuple[str, str]], sec: Security, ticker: str,
               cik: int | None, flag: str, reason: str, sub: EdgarSubmission) -> None:
        key = (flag, sub.accession)
        if key in seen:
            return
        seen.add(key)
        review.append(ReviewItem(sec.sec_id, ticker, cik, flag, reason, delist_date=effective_date(sub.filing_date),
                                 filing=FilingRef(sub.form, sub.accession, sub.filing_date)))

    # -- whether the security went on after a Form 25 ------------------------
    @staticmethod
    def _eight_a(sub: EdgarSubmission, f25: Form25, filings: list[EdgarSubmission]) -> EdgarSubmission | None:
        """The issuer's 8-A12B filed within EIGHT_A_DAYS of its own Form 25 (form 25 or 25/A, not an exchange's
        25-NSE, and not a removal under rule 12d2-2(b)), nearest first: the class registered on the exchange it
        moved to as it left the old one (R7: Kraft Heinz 2026, Monster Worldwide 2008, MSG 2015). None for any
        other Form 25: an exchange's 25-NSE beside an 8-A12B for a replacement class is a real ending (DISCK
        2022, CWENA 2026)."""
        if sub.form not in ISSUER_FORM25_FORMS or is_involuntary(f25):
            return None
        day = date.fromisoformat(sub.filing_date)
        near = [(abs((date.fromisoformat(f.filing_date) - day).days), f.filing_date, f) for f in filings
                if f.form in EIGHT_A_FORMS and f.filing_date
                and abs((date.fromisoformat(f.filing_date) - day).days) <= EIGHT_A_DAYS]
        return min(near, key=lambda x: (x[0], x[1]))[2] if near else None

    def _continued(self, ctx: SecurityContext, sub: EdgarSubmission, f25: Form25,
                   filings: list[EdgarSubmission]) -> bool:
        """Whether the security went on trading after this Form 25: it is listed today; or the issuer moved the
        class to another exchange (`_eight_a`, R7); or the Form 25 is not an exchange's removal under rule
        12d2-2(b) (`form25.is_involuntary`) and the security's own CUSIPs trade on after its effective date plus
        SEEN_AFTER_DAYS (`TradingRecord.trades_after`). An observation alone never continues a security: a
        stale snapshot lists one long after it was acquired (XMSR 2008, SOV 2009), and the OTC tail after a
        removal under (b) is not the listing going on (R.H. Donnelley, Idearc, LSC Communications)."""
        if ctx.listed_today:
            return True
        if self._eight_a(sub, f25, filings) is not None:
            return True
        if is_involuntary(f25):
            return False
        after = date.fromisoformat(effective_date(sub.filing_date)) + timedelta(days=SEEN_AFTER_DAYS)
        return ctx.record.trades_after(after.isoformat())

    def _not_this_removal(self, ctx: SecurityContext, filer: int, filings: list[EdgarSubmission],
                          sub: EdgarSubmission, f25: Form25) -> bool:
        """A Form 25 the security traded through that removed something else: the old CUSIP at the security's own
        CUSIP switch (U6), a secondary listing while the main one went on (Apache/Chicago 2020), or another class
        when the next 10-K cover still names the exchange."""
        if self._at_own_switch(ctx, sub.filing_date):
            return True             # the old CUSIP left the exchange as the security went on under its new one
        before, after = exchanges_around(self.edgar, filer, filings, date.fromisoformat(sub.filing_date))
        if withdrawal_kind(f25.exchange, before, after) == "secondary":
            return True
        return after is not None and f25.exchange in after   # another class left, not this one

    # -- one Form 25 against the security --------------------------------------
    def _issuer_names(self, cik: int) -> tuple[str, ...]:
        """The issuer's EDGAR names (current and former), for R3's group words. A failed submissions read gives (): R3 then
        refuses less, since no issuer words are removed from a Form 25's group words."""
        sub = self.edgar.submissions(cik)
        return edgar_names(sub) if isinstance(sub, dict) else ()

    def _judge(self, ctx: SecurityContext, scan: _Scan, filer: int, sub: EdgarSubmission,
               refs: list[SecurityRef], issuer_names: tuple[str, ...], *, quiet: bool = False,
               by_elimination: bool = False) -> Form25 | None:
        """The Form 25 `sub` of CIK `filer`, parsed, when it removed this security: readable, not a regional
        exchange's, of a recognized class, not about another class (`form25.other_class`, R3, against the filer's
        EDGAR names `issuer_names`), matched to this security among `refs` (`match_securities`) with no
        class-letter conflict. Else None; a filing that could not be placed gets its review row unless `quiet`
        (the early window's filings). `by_elimination`: `refs` is the security alone, so a Form 25 that names a
        class letter must name the security's own (`_names_other_letter`)."""
        sec, ticker = ctx.security, scan.ticker
        raw = self.edgar.fetch_filing_raw(filer, sub.accession)
        if not raw:
            scan.unreadable.append(sub)
            if not quiet:
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unreadable",
                             f"no filing text for {sub.form} {sub.accession}", sub)
            return None
        f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
        if f25.exchange in REGIONAL_EXCHANGES:
            return None
        if class_kind(f25.class_text) == "other":
            if not quiet:
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unclassified",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}) has no recognized class", sub)
            return None
        if other_class(f25, ctx.own_ref, issuer_names):
            return None
        matched, why = match_securities(f25, refs)
        if not matched:
            if why == "ambiguous class" and not quiet:
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unmatched",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}): {why}", sub)
            return None
        if sec.sec_id not in matched:
            if sec.sec_id in tied_securities(f25, refs) and not quiet:
                # another class of this Form 25 matched; this one shares its
                # letter with a sibling no name word tells apart, or has none
                scan.had_unmatched = True
                self._review(scan.review, scan.seen, sec, ticker, filer, "form25_unmatched",
                             f"{sub.form} {sub.accession} ({f25.class_text!r}): ambiguous class", sub)
            return None
        ref = next((r for r in refs if r.sec_id == sec.sec_id), None)
        if ref is not None and self._class_conflict(f25, ref):
            return None
        if by_elimination and self._names_other_letter(f25, ctx.own_ref):
            return None
        return f25

    @staticmethod
    def _names_other_letter(f25: Form25, own: SecurityRef) -> bool:
        """Whether a Form 25 reached through the security alone (late reach, early reach, the other CIK's) names a
        class letter and none is the security's own (its share class's, else its fails descriptions' hint): a
        letterless security takes only a Form 25 that names no letter."""
        letters = class_letters(f25.class_text)
        mine = {class_letter(own.share_class) or own.letter_hint} - {None}
        return bool(letters and not letters & mine)

    def _judge_early(self, ctx: SecurityContext, scan: _Scan, cik: int, sub: EdgarSubmission,
                     issuer_names: tuple[str, ...]) -> Form25 | None:
        """A Form 25 filed before the main scan's floor, judged by the main scan's own rules (`_judge`), quietly,
        against the security and the siblings alive on its filing date: the security itself counts as alive (its
        first sighting is what put the filing before the floor), and when it stands alone a Form 25 that names a
        class letter must name its own (`by_elimination`). The early window's filings and the fallback's early group
        (`_early_group`) are judged by this one judgement."""
        own = ctx.own_ref
        refs = [own] + [r for r in ctx.refs
                        if r.sec_id != own.sec_id and self._alive_at(ctx, r.sec_id, sub.filing_date)]
        return self._judge(ctx, scan, cik, sub, refs, issuer_names, quiet=True, by_elimination=len(refs) == 1)

    # -- main ------------------------------------------------------------
    def find(self, ctx: SecurityContext, *, fallback: bool = True) -> tuple[list[Delisting], list[ReviewItem]]:
        """The security's delistings and review items. `fallback=False` (pipeline stage 9d, a successor the run
        added): Form 25 matches only, no fallback ending and no review item for a security without one."""
        sec, rec = ctx.security, ctx.record
        if not rec.known_from:          # no day the run knows it by (no era): nothing to search around
            return [], []
        cik = sec.issuer_cik
        ticker_last = rec.ticker
        if sec.line_tickers:            # the line went on under a ticker the line follow found: its latest one
            latest = rec.ticker_on(rec.last_seen)
            ticker_last = latest if latest in rec.own_tickers else ticker_last
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=rec.last_seen)]
            if ctx.listed_today is None:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "listing_status_unknown",
                                       "no issuer CIK and listing status unknown", last_seen=rec.last_seen)]
            return [], []

        filings = self.edgar.recent_filings(cik)
        floor = (date.fromisoformat(rec.known_from) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        # E: a security gone today also judges the Form 25s of the year before the floor, as when a stale
        # snapshot first listed it months after its merger (TXU, Station Casinos, Biomet 2007)
        early_floor = (date.fromisoformat(floor) - timedelta(days=EARLY_REACH_DAYS)).isoformat() \
            if ctx.listed_today is False else floor
        own = ctx.own_ref
        scan = _Scan(ticker_last)
        names = self._issuer_names(cik)
        early: list[tuple[EdgarSubmission, Form25]] = []
        early_unreadable: list[str] = []        # filing dates of early-window Form 25s that could not be read
        candidates: list[tuple[EdgarSubmission, Form25]] = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                if sub.filing_date < early_floor:
                    scan.older.append(sub)      # before the early window: only the fallback may take one
                    continue
                f25 = self._judge_early(ctx, scan, cik, sub, names)
                after = date.fromisoformat(effective_date(sub.filing_date)) + timedelta(days=SEEN_AFTER_DAYS)
                if f25 is not None and self._eight_a(sub, f25, filings) is not None:
                    pass                            # the issuer moved the class (R7), no ending
                elif f25 is not None and not rec.trades_after(after.isoformat()):
                    early.append((sub, f25))
                elif f25 is None and sub in scan.unreadable:
                    scan.older.append(sub)          # never read: the fallback may still take it
                    early_unreadable.append(sub.filing_date)
                continue
            # Filings that plainly aren't about any security of this issuer
            # (none of the observed securities were even alive on this date)
            # get no review item at all, so these checks come before the
            # readability/classification ones below. L: the security itself
            # still counts when its own CUSIP traded within LATE_ROW_DAYS before
            # the filing (a line that went on under a ticker it was never seen
            # under: Monster Worldwide's NYSE MWW, 2016).
            alive = [r for r in ctx.refs if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            late = False
            if not alive:
                if not rec.traded_within(sub.filing_date, LATE_ROW_DAYS):
                    continue
                alive = [own]
                late = True
            # late reach only for a Form 25 that names no class letter, or the security's own (its share
            # class's, else its fails descriptions' hint); another lettered one stays for the normal paths
            f25 = self._judge(ctx, scan, cik, sub, alive, names, by_elimination=late)
            if f25 is None:
                continue
            if self._continued(ctx, sub, f25, filings) and self._not_this_removal(ctx, cik, filings, sub, f25):
                continue
            candidates.append((sub, f25))
        groups = [(cik, filings, g) for g in self._group(candidates)]
        if ctx.other_cik is not None and ctx.other_cik != cik:
            groups += self._other_issuer_groups(ctx, scan, floor, own)
        groups.sort(key=lambda x: min(s.filing_date for s, _ in x[2]))

        delistings: list[Delisting] = []
        last_definitive: Delisting | None = None
        for filer, filer_filings, group in groups:
            earliest_sub, _ = min(group, key=lambda item: item[0].filing_date)
            if last_definitive is not None:
                gap = (date.fromisoformat(earliest_sub.filing_date) - date.fromisoformat(last_definitive.delist_date)).days
                if gap > IGNORE_AFTER_DEFINITIVE_DAYS and not rec.seen_after(earliest_sub.filing_date):
                    continue        # a security truly gone can't have a later Form 25 of its own
            eff = effective_date(earliest_sub.filing_date)
            continued = any(self._continued(ctx, s, f, filer_filings) for s, f in group)     # R7: any member's move
            delisting = self._build_delisting(ctx, filer, filer_filings, group, eff, continued)
            delistings.append(delisting)
            # Only an exchange transfer (or a delisting not classified) that the
            # security traded through continues it. A merger, liquidation,
            # compliance failure or expiration ends the security's exchange life.
            if not continued or delisting.record.bucket in ENDING_BUCKETS:
                last_definitive = delisting

        # E: with no definitive delisting from the floor on, the latest early
        # group is the delisting (an older group must not pre-empt it: TXU's
        # Form 25s of January 2007); the observations after it are flagged.
        if last_definitive is None and early:
            group = self._group(early)[-1]
            if not any(d > max(s.filing_date for s, _ in group) for d in early_unreadable):
                # (an unreadable Form 25 after the latest readable group might be the real ending: the fallback decides)
                eff = effective_date(min(s.filing_date for s, _ in group))
                last_definitive = self._build_delisting(ctx, cik, filings, group, eff, False,
                                                        ("observed_after_delisting",))
                delistings.insert(0, last_definitive)

        # spec 8.10: run the fallback / ended_without_delisting logic whenever
        # no delisting found is a genuine end (every one is `continued`, e.g. an
        # exchange transfer the security kept trading through) -- not only
        # when `delistings` is empty. Otherwise a security whose only delistings
        # are continued ones gets neither a real delisting nor a review row.
        review = scan.review
        if not fallback:
            return delistings, review
        if last_definitive is None:
            if ctx.listed_today is False:
                fb = self._fallback(ctx, cik, filings, ticker_last, scan.older, names)
                if fb is not None:
                    delistings.append(fb)
                else:
                    # Also next to form25_* rows: those say a filing could not be
                    # placed; accepting one as "not about this security" must not
                    # drop the security itself from review (spec 8.10, G6).
                    why = ("no Form 25 matched it (see its form25_* rows) and no other delisting filing found"
                           if scan.had_unmatched else "no Form 25 or delisting filing found")
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                             f"not listed today and {why}", last_seen=rec.last_seen))
            elif ctx.listed_today is None:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "listing_status_unknown",
                                         "listing status unknown and no delisting found",
                                         last_seen=rec.last_seen))
        return delistings, review

    def _other_issuer_groups(self, ctx: SecurityContext, scan: _Scan, floor: str, own: SecurityRef
                             ) -> list[tuple[int, list[EdgarSubmission], list[tuple[EdgarSubmission, Form25]]]]:
        """R5: the Form 25s, from the floor on, of the one other CIK in force over the security's whole span
        (`SecurityContext.other_cik`), matched against this security alone, grouped; each group carries its
        filer CIK and filing list, which date and classify it (old Spectrum Brands 2018, old Match Group 2020)."""
        other = ctx.other_cik
        filings = self.edgar.recent_filings(other)
        names = self._issuer_names(other)
        found = []
        for sub in list_form25(filings):
            if sub.filing_date < floor:
                continue
            f25 = self._judge(ctx, scan, other, sub, [own], names, by_elimination=True)
            if f25 is None:
                continue
            if self._continued(ctx, sub, f25, filings) and self._not_this_removal(ctx, other, filings, sub, f25):
                continue
            found.append((sub, f25))
        return [(other, filings, g) for g in self._group(found)]

    def _build_delisting(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                     group: list[tuple[EdgarSubmission, Form25]], eff: str, continued: bool,
                     extra_flags: tuple[str, ...] = ()) -> Delisting:
        sec, rec = ctx.security, ctx.record
        winner_sub, winner_f25 = min(group, key=self._exchange_rank)
        filing_ticker = rec.ticker_on(winner_sub.filing_date) or rec.ticker
        lt = self.dating.of_group(cik, filings, group, (winner_sub, winner_f25), ticker=filing_ticker,
                                  trading=rec, continued=continued)
        # spec 7.4: the delisting's ticker is the ticker on the last trade
        # date, not on the Form 25 filing date -- only fall back to the
        # filing-date ticker when the last trade date itself is unknown. A worked-out closing day (rule 4) is not
        # one: the classification keeps the filing day as its anchor.
        day = None if lt.worked_out else lt.day
        ticker = (day and rec.ticker_on(day.isoformat())) or filing_ticker
        anchor = day.isoformat() if day else winner_sub.filing_date
        # the ending's own-share reading, at its anchor (a worked-out last trade included: `Delisting.anchor`)
        own = self.classifier.reader.ending(cik, share_class=sec.share_class, name=sec.name,
                                            day=anchor_day(lt, eff, filed=winner_sub.filing_date), form25=winner_f25)
        record = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=anchor, name=sec.name,
                                                expected_name=rec.expected_name, kind=sec.kind, form25=winner_sub,
                                                resolution_source=ctx.resolution_source,
                                                trading_after=continued, own_shares=own)
        moved = None
        if continued and record.bucket is CrspBucket.UNKNOWN:
            moved = next(((s, a) for s, f in sorted(group, key=lambda i: i[0].filing_date)
                          if (a := self._eight_a(s, f, filings)) is not None), None)
        delisting = self._delisting(sec, cik, ticker, eff, record, lt, winner_f25, winner_sub, continued,
                                    extra_flags)
        delisting.own_shares = own if own.stated else None
        if moved is not None:              # R7: the issuer moved the class (Kraft Heinz 2026, Nasdaq to NYSE)
            s, a = moved
            continuation(delisting, sec.sec_id, Rule.ISSUER_MOVE,
                         reason=f"Exchange transfer: the issuer's Form 25 {s.filing_date} with its 8-A12B {a.filing_date}",
                         confidence="high", evidence=f"{s.form} {s.accession}; {a.form} {a.accession}")
        return delisting

    def _delisting(self, sec: Security, cik: int, ticker: str, delist_date: str, rec: DelistRecord, lt: LastTrade,
               f25: Form25 | None, sub: EdgarSubmission | None, continued: bool,
               extra_flags: tuple[str, ...] = (), exchange: str = "") -> Delisting:
        rec.sec_id = sec.sec_id
        rec.delist_date = delist_date
        flags = list(lt.flags) + list(extra_flags)
        transfer = rec.bucket is CrspBucket.EXCHANGE_TRANSFER
        if transfer and not continued:
            flags.append(SUCCESSOR_UNKNOWN)        # stage 9 looks for its successor (`rewrites.awaits_successor`)
        delisting = Delisting(sec.sec_id, cik, ticker, delist_date, rec, lt, f25, sub,
                              f25.exchange if f25 else exchange)
        for f in flags:
            if f not in delisting.flags:
                delisting.add_flag(f)
        if transfer and continued:                # a transfer the security traded through: it goes on as itself
            security_goes_on(delisting, Rule.CONTINUED)
        return delisting

    # -- no-Form-25 fallback ----------------------------------------------
    @staticmethod
    def _fallback_date(last_seen: str, evidence: dict) -> tuple[str, tuple[str, ...]]:
        """Date a fallback delisting of a security last sighted on `last_seen`: the confirmed bankruptcy 8-K, then
        the anchor 8-K, then the revocation filing or a Form 15 but only if either
        falls within [last_seen - 30d, last_seen + 120d]; otherwise last_seen
        itself, flagged `delist_date_approx`.

        A revocation is not trusted outright: SEC revokes a delinquent filer's
        registration years after trading actually stopped, and this date feeds
        the return calculation, so a distant revocation is no better than
        having no filing at all — last_seen plus the approx flag is closer to
        the truth than a multi-year-late revocation date.
        """
        for key in ("bankruptcy_8k", "anchor_8k"):
            f = evidence.get(key)
            if f and f.get("filing_date"):
                return f["filing_date"], ()
        lo = (date.fromisoformat(last_seen) - timedelta(days=DEREG_FALLBACK_BEFORE_DAYS)).isoformat()
        hi = (date.fromisoformat(last_seen) + timedelta(days=DEREG_FALLBACK_AFTER_DAYS)).isoformat()
        for key in ("revoked_filing", "dereg_filing"):
            f = evidence.get(key)
            fd = f.get("filing_date") if f else None
            if fd and lo <= fd <= hi:
                return fd, ()
        return last_seen, ("delist_date_approx",)

    def _early_group(self, ctx: SecurityContext, cik: int, picked: str, early: list[EdgarSubmission],
                     issuer_names: tuple[str, ...]) -> list[tuple[EdgarSubmission, Form25]]:
        """The Form 25 `picked` (an accession) from `early`, the filings dated
        before the main scan's floor, with its early neighbours within
        SAME_EVENT_DAYS -- each kept only when the early window's judgement
        (`_judge_early`) matches it to this security. Empty when `picked` is not early."""
        anchor = next((s for s in early if s.accession == picked), None)
        if anchor is None:
            return []
        scratch = _Scan(ctx.record.ticker)        # quiet: no review item, and the main scan's state stays as it is
        group: list[tuple[EdgarSubmission, Form25]] = []
        for sub in early:
            if abs((date.fromisoformat(sub.filing_date) - date.fromisoformat(anchor.filing_date)).days) > SAME_EVENT_DAYS:
                continue
            f25 = self._judge_early(ctx, scratch, cik, sub, issuer_names)
            if f25 is not None:
                group.append((sub, f25))
        return group

    def _fallback(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission], ticker: str,
                  early: list[EdgarSubmission], issuer_names: tuple[str, ...]) -> Delisting | None:
        sec, last_seen = ctx.security, ctx.record.last_seen
        own = self.classifier.reader.ending(cik, share_class=sec.share_class, name=sec.name,
                                            day=date.fromisoformat(last_seen)) if last_seen else None
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=last_seen, name=sec.name,
                                             expected_name=ctx.record.expected_name, kind=sec.kind, form25=None,
                                             resolution_source=ctx.resolution_source, own_shares=own)
        evidence = rec.evidence or {}
        if evidence.get("delist_filing"):
            # The classifier picked a Form 25 on its own, ignoring class. The
            # main loop already decided about every Form 25 from the floor on,
            # so such a filing was rejected (ambiguous, another sibling's,
            # regional/secondary, another class) — never revive it. A filing
            # from before the floor was never judged: the security's first
            # sighting came after it, as when a stale index snapshot kept
            # listing a security acquired months earlier. The classifier's own
            # frozen-tail rule chose it for a security gone today, so it is
            # the delisting when it matches this security by class and no
            # fails-to-deliver row under the security's own tickers shows it
            # trading after it; the observations after it are flagged
            # `observed_after_delisting`.
            group = self._early_group(ctx, cik, evidence["delist_filing"].get("accession") or "", early,
                                      issuer_names)
            if not group:
                return None
            eff = effective_date(min(s.filing_date for s, _ in group))
            if ctx.record.seen_in_fails_after((date.fromisoformat(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat()):
                return None
            return self._build_delisting(ctx, cik, filings, group, eff, False, ("observed_after_delisting",))
        if rec.bucket is CrspBucket.UNKNOWN and not evidence.get("deregistered"):
            return None
        ended_by, extra_flags = self._fallback_date(last_seen, evidence)
        if not ctx.record.has_cusips and "delist_date_approx" in extra_flags \
                and rests_on_continued_filings(rec.reason or ""):
            # 5h: the continued-filings guess dated by the last sighting alone, for a security with no CUSIP whose
            # fails rows could show it stop: nothing says it ended there (WW 2013, a later name a snapshot
            # carried back; the line traded on to its 2025 bankruptcy). No ending; ended_without_delisting.
            return None
        lt = self.dating.of_fallback(cik, filings, ticker=ticker, ended_by=date.fromisoformat(ended_by),
                                     last_seen=date.fromisoformat(last_seen), trading=ctx.record,
                                     merger=rec.bucket is CrspBucket.MERGER)
        # No Form 25 means no exchange evidence from a filing; fall back to
        # whatever exchange EDGAR's own submissions JSON records for this
        # ticker (spec D22) rather than leaving it blank -- which otherwise
        # maps to Exchange.OTHER and applies the wrong Shumway constant.
        exch = issuer_exchange(self.edgar, cik, ticker) or ""
        delisting = self._delisting(sec, cik, ticker, ended_by, rec, lt, None, None, False,
                                    ("no_form25", *extra_flags), exchange=exch)
        delisting.own_shares = own if own is not None and own.stated else None
        return delisting
