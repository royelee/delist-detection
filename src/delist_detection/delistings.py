"""Find, date and classify every delisting of one security (D6, D16, D17, D20).

A delisting is a Form 25 that removed the security's class from its exchange
and left it on no exchange or on a new one. Securities with no Form 25 fall back
to the classifier's no-Form-25 paths; a security that ended with no evidence at
all is reported for review instead of being dropped.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .classifier import DelistClassifier, DelistRecord
from .crsp_codes import CrspBucket
from .edgar import EdgarSubmission
from .evidence import edgar_names
from .figi_resolution import class_letter
from .form25 import (
    REGIONAL_EXCHANGES, Form25, SecurityRef, class_kind, class_letters, effective_date, is_involuntary,
    list_form25, match_securities, notice_last_trade, other_class, parse_form25, tied_securities,
)
from .last_trade import LastTrade, decide_last_trade, eightk_last_trade
from .listing_status import exchanges_around, issuer_exchange, withdrawal_kind
from .midas import MIDAS_START
from .nasdaq_halts import last_trade_from_halt
from .review_triage import ReviewItem
from .security_master import Security
from .store import DelistingKey
from .trading_calendar import add_trading_days, previous_trading_day

FORM25_LOOKBACK_DAYS = 30           # how far before the security's first sighting to look for a Form 25
SAME_EVENT_DAYS = 30                # Form 25s of this security this close together are one delisting
IGNORE_AFTER_DEFINITIVE_DAYS = 30   # once truly delisted, a later Form 25 past this is suspect
SEEN_AFTER_DAYS = 5                 # sighted this long past the effective date: the security kept trading
SIBLING_ALIVE_BEFORE_DAYS = 30      # a sibling's own first sighting, minus this: still alive
SIBLING_ALIVE_AFTER_DAYS = 400      # a sibling's own last sighting, plus this: still alive
MIDAS_BEFORE_DAYS, MIDAS_AFTER_DAYS, MIDAS_STILL_TRADING_DAYS = 75, 10, 5
EIGHTK_BEFORE_DAYS, EIGHTK_AFTER_DAYS = 60, 5      # single-filing 8-K window (fallback path)
EIGHTK_GROUP_AFTER_DAYS = 15                       # group 8-K window: latest filed + this many days
DEREG_FALLBACK_BEFORE_DAYS = 30     # a fallback revocation or Form 15 must be within
OWN_SWITCH_DAYS = 5                 # trading days between a Form 25 and the security's own CUSIP switch it removed
DEREG_FALLBACK_AFTER_DAYS = 120     # [last_seen - this, last_seen + this] to date the delisting
EIGHT_A_DAYS = 10                   # the issuer's own Form 25 and its 8-A12B this close together: an exchange move
EIGHT_A_FORMS = frozenset({"8-A12B"})      # not 8-A12B/A: a rights-plan amendment registers no class (Biomet 2006)
ISSUER_FORM25_FORMS = frozenset({"25", "25/A"})      # filed by the issuer, not by the exchange (25-NSE)
EARLY_REACH_DAYS = 365              # gone today: Form 25s this far before the floor are judged in the main scan
LATE_ROW_DAYS = 30                  # no sibling alive: the security's own CUSIP traded this close before the Form 25

# Buckets whose delisting ends the security's exchange life even when it is
# sighted afterwards (OTC trading, a stale snapshot): all but a transfer and
# a delisting the classifier could not place.
ENDING_BUCKETS = frozenset({CrspBucket.MERGER, CrspBucket.LIQUIDATION, CrspBucket.COMPLIANCE_FAILURE,
                            CrspBucket.EXPIRATION})

# The review flag of an exchange transfer whose successor is not known yet; it
# comes off the delisting once a successor is found (`Delisting.set_successor`).
SUCCESSOR_UNKNOWN = "successor_unknown"

# Preferred exchange for a multi-exchange delisting group: the filing on the
# most-senior exchange supplies the delisting's `exchange` and `form25`/`form25_sub`.
EXCHANGE_PREFERENCE = ("NYSE", "NASDAQ", "NYSE AMERICAN", "CBOE BZX", "NYSE ARCA")


@dataclass
class Delisting:
    """One delisting of one security (CONTEXT.md): the Form 25 group (or the
    fallback filing) that ended its listing, dated and classified (`record`)."""
    sec_id: str
    cik: int
    ticker: str
    delist_date: str
    record: DelistRecord
    last_trade: LastTrade
    form25: Form25 | None
    form25_sub: EdgarSubmission | None
    exchange: str

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

    def set_successor(self, sec_id: str) -> None:
        """Record `sec_id` as the successor: the row no longer says `successor_unknown`."""
        self.record.successor_sec_id = sec_id
        self.record.evidence["flags"] = [f for f in self.flags if f != SUCCESSOR_UNKNOWN]


@dataclass
class SecurityContext:
    security: Security
    siblings: list[SecurityRef]
    ticker_on: Callable[[str], str | None]
    last_seen: str
    seen_after: Callable[[str], bool]
    listed_today: bool | None
    expected_name: str | None
    # sec_id -> (first sighting, last sighting), ISO. A sibling absent here is
    # treated as alive at every filing date (the caller doesn't know its span).
    sibling_spans: dict[str, tuple[str, str]] = field(default_factory=dict)
    # The resolver tier that found this security's CIK (e.g. "cik_map",
    # "manual"); recorded on every DelistRecord this security's delistings
    # produce, in place of the classify_event default "security_master".
    resolution_source: str = "security_master"
    # True when an SEC fails-to-deliver row under one of the security's own
    # tickers is dated after the given ISO day: evidence of trading that an
    # observation alone does not give (a stale snapshot can list a security
    # long after it was acquired). Unknown (the default) counts as none.
    ftd_seen_after: Callable[[str], bool] = lambda day: False
    # Every ticker the security was sighted under between two ISO days (its own
    # and, from fails rows, an OTC symbol it moved to), for the exchange-trade
    # confirmations (MIDAS, Nasdaq halts): the ticker on a Form 25's date can be
    # the OTC symbol already (SAVE -> SAVEQ), which no exchange source knows.
    tickers_between: Callable[[str, str], list[str]] = lambda lo, hi: []
    # The first fails row of each of the security's own CUSIPs after its first, ISO: a CUSIP switch on its own
    # line (a reverse split, a redomicile that kept the composite). A Form 25 filed at one while the security
    # trades on removed the old CUSIP, not the security (QGEN 2026, Acxiom/LiveRamp 2018).
    cusip_switches: tuple[str, ...] = ()
    # True when the fails rows of the security's own CUSIPs, under any symbol it trades under, show it still
    # trading after the given ISO day (`ftd.trades_after`). With `listed_today`, the one sign that a security went
    # on after a Form 25 (`DelistingFinder._continued`): an observation can be a stale snapshot (XMSR 2008, SOV
    # 2009). Unknown (the default) counts as no.
    trades_after: Callable[[str], bool] = lambda day: False
    # True when the security's own CUSIPs have a trading fails row in the LATE_ROW_DAYS up to the given ISO day:
    # a Form 25 filed long after the security's last sighting still reaches it (Monster Worldwide 2016, L).
    cusip_rows_near: Callable[[str], bool] = lambda day: False
    # The one CIK other than `security.issuer_cik` that was the issuer in force over the security's whole span
    # (`pipeline._other_issuers`), whose Form 25s are read too (R5: the old Spectrum Brands, the old Match Group).
    other_cik: int | None = None


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
    def __init__(self, edgar, classifier: DelistClassifier, *, midas=None, halts=None) -> None:
        self.edgar, self.classifier, self.midas, self.halts = edgar, classifier, midas, halts

    # -- sibling / class matching -----------------------------------------
    def _alive_at(self, ctx: SecurityContext, sec_id: str, filing_date: str) -> bool:
        span = ctx.sibling_spans.get(sec_id)
        if span is None:
            return True
        first, last = span
        lo = (date.fromisoformat(first) - timedelta(days=SIBLING_ALIVE_BEFORE_DAYS)).isoformat()
        hi = (date.fromisoformat(last) + timedelta(days=SIBLING_ALIVE_AFTER_DAYS)).isoformat()
        return lo <= filing_date <= hi

    @staticmethod
    def _at_own_switch(ctx: SecurityContext, filing_date: str) -> bool:
        """Whether one of the security's own CUSIP switches (`SecurityContext.cusip_switches`) lies within
        `OWN_SWITCH_DAYS` trading days of a Form 25's filing date."""
        day = date.fromisoformat(filing_date)
        lo = add_trading_days(day, -OWN_SWITCH_DAYS).isoformat()
        hi = add_trading_days(day, OWN_SWITCH_DAYS).isoformat()
        return any(lo <= d <= hi for d in ctx.cusip_switches)

    def _class_conflict(self, f25: Form25, ref: SecurityRef) -> bool:
        """True when the Form 25 names class letters and the matched sibling's
        class letter is not one of them: `match_securities`' single-sibling branch
        (`len(same) == 1`) accepts by elimination without checking letters, so
        this is the backstop for a class the universe doesn't actually hold."""
        f_letters = class_letters(f25.class_text)
        r_letter = class_letter(ref.share_class)
        return bool(f_letters and r_letter and r_letter not in f_letters)

    # -- last trade (single filing; used by the no-Form-25 fallback) -----
    def _eightk_window(self, cik: int, filings: list[EdgarSubmission], lo: date, hi: date,
                       anchor: date) -> tuple[date | None, str]:
        cands = [f for f in filings if f.form.startswith("8-K") and "3.01" in f.item_set
                 and f.filing_date and lo <= date.fromisoformat(f.filing_date) <= hi]
        for f in sorted(cands, key=lambda f: abs((date.fromisoformat(f.filing_date) - anchor).days)):
            got = eightk_last_trade(self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc))
            if got[0] is not None:
                return got
        return None, ""

    def _eightk(self, cik: int, filings: list[EdgarSubmission], filed: date) -> tuple[date | None, str]:
        return self._eightk_window(cik, filings, filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                   filed + timedelta(days=EIGHTK_AFTER_DAYS), filed)

    def _halt_feed_failures(self) -> tuple[date, ...]:
        """The halt feed's failed days so far on this thread (a halt client
        without `failed_days` never fails)."""
        failed_days = getattr(self.halts, "failed_days", None)
        return tuple(failed_days()) if failed_days is not None else ()

    def _confirmations(self, tickers: list[str], filed: date, lo: date, hi: date, still_trading: date,
                       guesses: list[date]) -> tuple[date | None, date | None, tuple[date, ...]]:
        """(MIDAS last day with exchange volume, Nasdaq code-D halt day, halt
        feed days that failed to read) over every ticker in `tickers`: MIDAS
        (asked when `filed` is in its coverage) takes the latest day in `[lo,
        hi]` before `still_trading` under any of them; the halt feed is asked
        only when MIDAS has nothing, around the text sources' `guesses`."""
        midas = None
        if self.midas is not None and filed >= MIDAS_START:
            days = [m for t in tickers if (m := self.midas.last_trade_day(t, lo, hi)) is not None
                    and m < still_trading]
            midas = max(days) if days else None
        halt, failed = None, ()
        if midas is None and self.halts is not None:
            before = len(self._halt_feed_failures())
            for t in tickers:
                h = self.halts.deletion_halt(t, min(guesses) - timedelta(days=2),
                                             max(guesses) + timedelta(days=2), max_days=5)
                if h:
                    halt = last_trade_from_halt(h)
                    break
            failed = self._halt_feed_failures()[before:]
        return midas, halt, failed

    @staticmethod
    def _decide(notice: tuple[date | None, str], eightk: tuple[date | None, str],
                confirmations: tuple[date | None, date | None, tuple[date, ...]]) -> LastTrade:
        """`decide_last_trade` over the text sources and the confirmations,
        carrying the halt feed days that failed to read."""
        midas, halt, failed = confirmations
        lt = decide_last_trade(notice=notice, eightk=eightk, midas=midas, halt=halt)
        return replace(lt, halt_feed_failed=failed) if failed else lt

    @staticmethod
    def _tickers(ctx: SecurityContext | None, ticker: str, lo: date, hi: date) -> list[str]:
        """`ticker` first, then every other ticker the security carried in `[lo, hi]`."""
        others = ctx.tickers_between(lo.isoformat(), hi.isoformat()) if ctx is not None else []
        return list(dict.fromkeys([ticker, *others]))

    def _last_trade(self, cik: int, filings: list[EdgarSubmission], f25: Form25 | None, ticker: str,
                    filed: date, ctx: SecurityContext | None = None) -> LastTrade:
        notice = notice_last_trade(f25) if f25 else (None, "")
        eightk = self._eightk(cik, filings, filed)
        lo, hi = filed - timedelta(days=MIDAS_BEFORE_DAYS), filed + timedelta(days=MIDAS_AFTER_DAYS)
        confirmations = self._confirmations(
            self._tickers(ctx, ticker, lo, hi), filed, lo, hi, filed + timedelta(days=MIDAS_STILL_TRADING_DAYS),
            [d for d, _ in (notice, eightk) if d] or [previous_trading_day(filed)])
        return self._decide(notice, eightk, confirmations)

    # -- last trade for a group of Form 25s of one delisting --------------
    def _last_trade_group(self, cik: int, filings: list[EdgarSubmission],
                          group: list[tuple[EdgarSubmission, Form25]], ticker: str,
                          ctx: SecurityContext | None = None) -> LastTrade:
        subs = [s for s, _ in group]
        earliest_filed = date.fromisoformat(min(s.filing_date for s in subs))
        latest_filed = date.fromisoformat(max(s.filing_date for s in subs))
        latest_eff = date.fromisoformat(max(effective_date(s.filing_date) for s in subs))

        ordered = sorted(group, key=lambda item: (item[0].form != "25-NSE", item[0].filing_date))
        notice: tuple[date | None, str] = (None, "")
        for _, f25 in ordered:
            n = notice_last_trade(f25)
            if n[0] is not None:
                notice = n
                break

        eightk = self._eightk_window(cik, filings, earliest_filed - timedelta(days=EIGHTK_BEFORE_DAYS),
                                     latest_filed + timedelta(days=EIGHTK_GROUP_AFTER_DAYS), earliest_filed)

        lo = earliest_filed - timedelta(days=MIDAS_BEFORE_DAYS)
        hi = latest_eff + timedelta(days=MIDAS_AFTER_DAYS)
        confirmations = self._confirmations(
            self._tickers(ctx, ticker, lo, hi), earliest_filed, lo, hi,
            latest_eff + timedelta(days=MIDAS_STILL_TRADING_DAYS),
            [d for d, _ in (notice, eightk) if d] or [previous_trading_day(latest_filed)])
        return self._decide(notice, eightk, confirmations)

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
        review.append(ReviewItem(sec.sec_id, ticker, cik, flag, reason,
                                 delist_date=effective_date(sub.filing_date)))

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
        SEEN_AFTER_DAYS (`SecurityContext.trades_after`). An observation alone never continues a security: a
        stale snapshot lists one long after it was acquired (XMSR 2008, SOV 2009), and the OTC tail after a
        removal under (b) is not the listing going on (R.H. Donnelley, Idearc, LSC Communications)."""
        if ctx.listed_today:
            return True
        if self._eight_a(sub, f25, filings) is not None:
            return True
        if is_involuntary(f25):
            return False
        after = date.fromisoformat(effective_date(sub.filing_date)) + timedelta(days=SEEN_AFTER_DAYS)
        return ctx.trades_after(after.isoformat())

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
    @staticmethod
    def _own_ref(ctx: SecurityContext) -> SecurityRef:
        sec = ctx.security
        return next((r for r in ctx.siblings if r.sec_id == sec.sec_id),
                    SecurityRef(sec.sec_id, sec.share_class, sec.kind, sec.name))

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
        if other_class(f25, self._own_ref(ctx), issuer_names):
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
        if by_elimination and self._names_other_letter(f25, self._own_ref(ctx)):
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

    # -- main ------------------------------------------------------------
    def find(self, ctx: SecurityContext, *, fallback: bool = True) -> tuple[list[Delisting], list[ReviewItem]]:
        """The security's delistings and review items. `fallback=False` (pipeline stage 9d, a successor the run
        added): Form 25 matches only, no fallback ending and no review item for a security without one."""
        sec = ctx.security
        if not sec.eras:
            return [], []
        cik = sec.issuer_cik
        ticker_last = sec.eras[-1].ticker
        if sec.line_tickers:            # the line went on under a ticker the line follow found: its latest one
            latest = ctx.ticker_on(ctx.last_seen)
            ticker_last = latest if latest in sec.own_tickers() else ticker_last
        if cik is None:
            if ctx.listed_today is False:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "ended_without_delisting",
                                       "no issuer CIK to search for a Form 25", last_seen=ctx.last_seen)]
            if ctx.listed_today is None:
                return [], [ReviewItem(sec.sec_id, ticker_last, None, "listing_status_unknown",
                                       "no issuer CIK and listing status unknown", last_seen=ctx.last_seen)]
            return [], []

        filings = self.edgar.recent_filings(cik)
        first_seen = min(e.first for e in sec.eras)
        floor = (date.fromisoformat(first_seen) - timedelta(days=FORM25_LOOKBACK_DAYS)).isoformat()
        # E: a security gone today also judges the Form 25s of the year before the floor, as when a stale
        # snapshot first listed it months after its merger (TXU, Station Casinos, Biomet 2007)
        early_floor = (date.fromisoformat(floor) - timedelta(days=EARLY_REACH_DAYS)).isoformat() \
            if ctx.listed_today is False else floor
        own = self._own_ref(ctx)
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
                refs = [own] + [r for r in ctx.siblings
                                if r.sec_id != sec.sec_id and self._alive_at(ctx, r.sec_id, sub.filing_date)]
                f25 = self._judge(ctx, scan, cik, sub, refs, names, quiet=True, by_elimination=len(refs) == 1)
                after = date.fromisoformat(effective_date(sub.filing_date)) + timedelta(days=SEEN_AFTER_DAYS)
                if f25 is not None and self._eight_a(sub, f25, filings) is not None:
                    pass                            # the issuer moved the class (R7), no ending
                elif f25 is not None and not ctx.trades_after(after.isoformat()):
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
            alive = [r for r in ctx.siblings if self._alive_at(ctx, r.sec_id, sub.filing_date)]
            late = False
            if not alive:
                if not ctx.cusip_rows_near(sub.filing_date):
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
                if gap > IGNORE_AFTER_DEFINITIVE_DAYS and not ctx.seen_after(earliest_sub.filing_date):
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
                fb = self._fallback(ctx, cik, filings, ticker_last, scan.older)
                if fb is not None:
                    delistings.append(fb)
                else:
                    # Also next to form25_* rows: those say a filing could not be
                    # placed; accepting one as "not about this security" must not
                    # drop the security itself from review (spec 8.10, G6).
                    why = ("no Form 25 matched it (see its form25_* rows) and no other delisting filing found"
                           if scan.had_unmatched else "no Form 25 or delisting filing found")
                    review.append(ReviewItem(sec.sec_id, ticker_last, cik, "ended_without_delisting",
                                             f"not listed today and {why}", last_seen=ctx.last_seen))
            elif ctx.listed_today is None:
                review.append(ReviewItem(sec.sec_id, ticker_last, cik, "listing_status_unknown",
                                         "listing status unknown and no delisting found",
                                         last_seen=ctx.last_seen))
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
        sec = ctx.security
        winner_sub, winner_f25 = min(group, key=self._exchange_rank)
        filing_ticker = ctx.ticker_on(winner_sub.filing_date) or sec.eras[-1].ticker
        lt = self._last_trade_group(cik, filings, group, filing_ticker, ctx)
        # spec 7.4: the delisting's ticker is the ticker on the last trade
        # date, not on the Form 25 filing date -- only fall back to the
        # filing-date ticker when the last trade date itself is unknown.
        ticker = (lt.day and ctx.ticker_on(lt.day.isoformat())) or filing_ticker
        anchor = lt.day.isoformat() if lt.day else winner_sub.filing_date
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=anchor, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=winner_sub,
                                             resolution_source=ctx.resolution_source,
                                             trading_after=continued)
        if continued and rec.bucket is CrspBucket.UNKNOWN:
            moved = next(((s, a) for s, f in sorted(group, key=lambda i: i[0].filing_date)
                          if (a := self._eight_a(s, f, filings)) is not None), None)
            if moved is not None:          # R7: the issuer moved the class (Kraft Heinz 2026, Nasdaq to NYSE)
                s, a = moved
                rec.crsp_code, rec.bucket, rec.confidence = 304, CrspBucket.EXCHANGE_TRANSFER, "high"
                rec.reason = f"Exchange transfer: the issuer's Form 25 {s.filing_date} with its 8-A12B {a.filing_date}"
                rec.evidence["flags"] = [f for f in rec.evidence.get("flags", []) if f != "no_evidence_default"]
        return self._delisting(sec, cik, ticker, eff, rec, lt, winner_f25, winner_sub, continued, extra_flags)

    def _delisting(self, sec: Security, cik: int, ticker: str, delist_date: str, rec: DelistRecord, lt: LastTrade,
               f25: Form25 | None, sub: EdgarSubmission | None, continued: bool,
               extra_flags: tuple[str, ...] = (), exchange: str = "") -> Delisting:
        rec.sec_id = sec.sec_id
        rec.delist_date = delist_date
        flags = list(lt.flags) + list(extra_flags)
        if rec.bucket is CrspBucket.EXCHANGE_TRANSFER:
            if continued:
                rec.successor_sec_id = sec.sec_id
            else:
                flags.append(SUCCESSOR_UNKNOWN)
        delisting = Delisting(sec.sec_id, cik, ticker, delist_date, rec, lt, f25, sub,
                              f25.exchange if f25 else exchange)
        for f in flags:
            if f not in delisting.flags:
                delisting.add_flag(f)
        return delisting

    # -- no-Form-25 fallback ----------------------------------------------
    def _fallback_date(self, ctx: SecurityContext, evidence: dict) -> tuple[str, tuple[str, ...]]:
        """Date a fallback delisting: the confirmed bankruptcy 8-K, then the
        anchor 8-K, then the revocation filing or a Form 15 but only if either
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
        lo = (date.fromisoformat(ctx.last_seen) - timedelta(days=DEREG_FALLBACK_BEFORE_DAYS)).isoformat()
        hi = (date.fromisoformat(ctx.last_seen) + timedelta(days=DEREG_FALLBACK_AFTER_DAYS)).isoformat()
        for key in ("revoked_filing", "dereg_filing"):
            f = evidence.get(key)
            fd = f.get("filing_date") if f else None
            if fd and lo <= fd <= hi:
                return fd, ()
        return ctx.last_seen, ("delist_date_approx",)

    def _early_group(self, ctx: SecurityContext, cik: int, picked: str,
                     early: list[EdgarSubmission]) -> list[tuple[EdgarSubmission, Form25]]:
        """The Form 25 `picked` (an accession) from `early`, the filings dated
        before the main scan's floor, with its early neighbours within
        SAME_EVENT_DAYS — each kept only when it matches this security by the
        main scan's own rules (readable, not regional, a recognized class, and
        `match_securities` against this security and the siblings alive then).
        The security itself counts as alive: its first sighting is what put
        the filing before the floor. Empty when `picked` is not early."""
        sec = ctx.security
        anchor = next((s for s in early if s.accession == picked), None)
        if anchor is None:
            return []
        own = self._own_ref(ctx)
        group: list[tuple[EdgarSubmission, Form25]] = []
        for sub in early:
            if abs((date.fromisoformat(sub.filing_date) - date.fromisoformat(anchor.filing_date)).days) > SAME_EVENT_DAYS:
                continue
            raw = self.edgar.fetch_filing_raw(cik, sub.accession)
            if not raw:
                continue
            f25 = parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date)
            if f25.exchange in REGIONAL_EXCHANGES or class_kind(f25.class_text) == "other" \
                    or other_class(f25, own, self._issuer_names(cik)):
                continue
            alive = [own] + [r for r in ctx.siblings
                             if r.sec_id != sec.sec_id and self._alive_at(ctx, r.sec_id, sub.filing_date)]
            matched, _ = match_securities(f25, alive)
            if sec.sec_id in matched and not self._class_conflict(f25, own):
                group.append((sub, f25))
        return group

    def _fallback(self, ctx: SecurityContext, cik: int, filings: list[EdgarSubmission],
                  ticker: str, early: list[EdgarSubmission] | None = None) -> Delisting | None:
        sec = ctx.security
        rec = self.classifier.classify_event(ticker=ticker, cik=cik, anchor_date=ctx.last_seen, name=sec.name,
                                             expected_name=ctx.expected_name, kind=sec.kind, form25=None,
                                             resolution_source=ctx.resolution_source)
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
            group = self._early_group(ctx, cik, evidence["delist_filing"].get("accession") or "", early or [])
            if not group:
                return None
            eff = effective_date(min(s.filing_date for s, _ in group))
            if ctx.ftd_seen_after((date.fromisoformat(eff) + timedelta(days=SEEN_AFTER_DAYS)).isoformat()):
                return None
            return self._build_delisting(ctx, cik, filings, group, eff, False, ("observed_after_delisting",))
        if rec.bucket is CrspBucket.UNKNOWN and not evidence.get("deregistered"):
            return None
        ended_by, extra_flags = self._fallback_date(ctx, evidence)
        lt = self._last_trade(cik, filings, None, ticker, date.fromisoformat(ended_by), ctx)
        if lt.day is None:
            lt = LastTrade(date.fromisoformat(ctx.last_seen), "", ("last_trade_date_unconfirmed",), lt.halt_feed_failed)
        # No Form 25 means no exchange evidence from a filing; fall back to
        # whatever exchange EDGAR's own submissions JSON records for this
        # ticker (spec D22) rather than leaving it blank -- which otherwise
        # maps to Exchange.OTHER and applies the wrong Shumway constant.
        exch = issuer_exchange(self.edgar, cik, ticker) or ""
        return self._delisting(sec, cik, ticker, ended_by, rec, lt, None, None, False, ("no_form25", *extra_flags),
                           exchange=exch)
