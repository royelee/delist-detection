"""The own-share reading (CONTEXT.md): what the registrant said each of a security's shares became at one ending,
read once per ending (sub-plan 5c's ruling R1, spec 5c rules 1 and 6; architecture step 7b).

`exchange_terms` reads the statements out of texts, and stays pure. This module chooses, once, what an ending's
statement is read in and against, and holds the judgments its callers used to make one by one:

- **the texts**: the registrant's 8-Ks (8-K12B and 8-K12G3 included) filed in [day - TEXT_BEFORE_DAYS, day +
  TEXT_AFTER_DAYS] of the ending's anchor day, in filing order, then the EX-99.25 notice of its matched Form 25;
- **the names**: the registrant's EDGAR names in force in the NAMES_BEFORE_DAYS up to two days before the day (else
  its current name), then the security's own name;
- **the class**: the security's share class (its FIGI's, `Security.share_class`) and the words its name sets the
  class apart by ("SPECIAL").

What a reading (`OwnShares`) answers: the statement and its ratio, any cash, the target (`statement`); the same of the
registrant's own 8-Ks alone, the exchange's notice left out (`registrant_statement`, the verdict's reading: stage 9g);
one for one or a split (`exchange_terms.OwnExchange.one_for_one`, `split`, `stake_changed`); whom the target names
(`names_target`, the one name tie; `target_issuer`, the registrant or a new issuer, `new_issuer` and
NEW_ISSUER_DAYS); the registrant's other roles (`survived`, rule 1); and whether it rested on a failed or stale read
(`degraded`).

One reading per ending. The delisting finder makes it (`Reader.ending`, at the ending's anchor: its last trade, worked
out or not, else its Form 25's filing date; the last sighting for an ending with no Form 25) and hands it to the
classifier, whose rules 1, 6 and R1 read it. The delisting carries it when its statement was read (`stated`,
`Delisting.own_shares`): the ratio the classification decided on is the one stage 9g and the verdict read (CHTR 2016).
A later stage that asks first makes it at the delisting's anchor (`of`); stages 8b, 9 and 9g read the carried
reading, never the texts again. Nothing is read until a caller asks. Reads go through the run's issuer record (the
filing list, the names) and EDGAR client (the texts); `fatal.FATAL` propagates, and a reading that rested on a failed
or stale read says so (`degraded`), so a later stage that takes it reports it as its own."""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .edgar import EdgarSubmission
from .evidence import names_between, parse_day
from .exchange_terms import CLASS_MODIFIERS, OwnExchange, acquires, distributes, own_exchange
from .figi_resolution import class_letter
from .form25 import parse_form25
from .names import names_agree
from .observations import normalize_ticker

if TYPE_CHECKING:
    from .delistings import Delisting
    from .form25 import Form25
    from .issuer_record import IssuerRecord

TEXT_BEFORE_DAYS, TEXT_AFTER_DAYS = 3, 10       # the registrant's 8-Ks filed this close to the ending's anchor day
NAMES_BEFORE_DAYS = 365                          # the registrant's EDGAR names in force this long before the day
NEW_ISSUER_DAYS = 1095    # R1 (operator, 2026-10-04): an issuer that first filed with EDGAR at most this long before
#                           the event is a new one (new holding companies measured 0-548 days: DowDuPont 548, Linde
#                           517, Viatris 388; existing acquirers 4,125-8,442)
SAME_ISSUER, NEW_ISSUER = "same_issuer", "new_issuer"


def registrant_names(sub: dict | None, before: date, security_name: str = "") -> list[str]:
    """The registrant's names before the event: the EDGAR names it carried in the NAMES_BEFORE_DAYS up to two days
    before `before` (the earliest day the reading looks at: a registrant renamed at the closing, Schering-Plough as
    "Merck", Foundation Coal as "Alpha Natural Resources", is read by its old name), else its current one, then the
    security's own name."""
    names = names_between(sub, before - timedelta(days=NAMES_BEFORE_DAYS), before - timedelta(days=2)) \
        if isinstance(sub, dict) else []
    if not names and isinstance(sub, dict) and sub.get("name"):
        names = [sub["name"]]
    return [*names, security_name] if security_name else names


def class_of(share_class: str | None, name: str | None) -> tuple[str, tuple[str, ...]]:
    """The class letter a security's statements must name ("" for a plain common) and the words that set its class
    apart in its name ("COMCAST SPECIAL CORP CLASS A": ("SPECIAL",))."""
    up = (name or "").upper()
    return class_letter(share_class) or "", tuple(w for w in CLASS_MODIFIERS if w in up)


def names_target(statement: OwnExchange, names: Iterable[str], tickers: Iterable[str] = ()) -> bool:
    """The name tie (R1): the statement's target names the candidate. One of its tickers (two letters or more) is a
    word of a target name ("BHGE's Class A common stock"), or a target name agrees with one of its names
    (`names.names_agree`: "DowDuPont" and DowDuPont Inc.; "Holdco", expanded, and Howard Hughes Holdings Inc.)."""
    words = {w.upper() for t in statement.target_names for w in re.findall(r"[A-Za-z0-9]+", t)}
    if {normalize_ticker(t).replace("-", "") for t in tickers if len(t) >= 2} & words:
        return True
    names = [n for n in names if n]
    return any(names_agree(t, n) for t in statement.target_names for n in names)


def new_issuer(first_filed: date | None, day: date) -> bool:
    """R1's new issuer: its first EDGAR filing is known and at most NEW_ISSUER_DAYS before `day` (an existing company
    is never a continuation: LVNTA into GCI Liberty, WCN into Progressive Waste)."""
    return first_filed is not None and (day - first_filed).days <= NEW_ISSUER_DAYS


def other_role(texts: Sequence[str], names: Sequence[str]) -> str:
    """The sentence in which the registrant acquired another party or issued its shares to it
    (`exchange_terms.acquires`: RRI Energy and Mirant, SXC and Catalyst, Forest Oil and Sabine) or distributed another
    company's shares to its holders, who kept theirs (`distributes`: News Corp 2013), else "" (rule 1)."""
    return acquires(texts, names=names) or distributes(texts, names=names)


def _windows(days: Iterable[date]) -> list[tuple[date, date]]:
    return [(d - timedelta(days=TEXT_BEFORE_DAYS), d + timedelta(days=TEXT_AFTER_DAYS)) for d in days if d]


def _eightks(filings: Iterable[EdgarSubmission], days: Iterable[date]) -> list[EdgarSubmission]:
    """The 8-Ks (8-K12B and 8-K12G3 included) filed in a window of any of `days`, in filing order."""
    windows = _windows(days)
    out = []
    for f in sorted(filings, key=lambda f: (f.filing_date, f.accession)):
        day = parse_day(f.filing_date)
        if day is not None and f.form.startswith("8-K") and any(lo <= day <= hi for lo, hi in windows):
            out.append(f)
    return out


class Reader:
    """Reads own-share readings over the run's EDGAR client (the texts) and issuer record (the filing list and the
    names). Holds nothing of its own: a warm pass's copy reads through the warm classifier's shadow record."""

    def __init__(self, edgar: Any, issuers: IssuerRecord) -> None:
        self.edgar, self.issuers = edgar, issuers

    def ending(self, cik: int, *, share_class: str | None, name: str | None, day: date,
               form25: Form25 | EdgarSubmission | None = None) -> OwnShares:
        """One ending's reading (nothing read yet): the registrant `cik`, the security's `share_class` and `name`, the
        ending's anchor `day` and its matched Form 25 (`form25`, for its notice: parsed, or the filing, whose
        complete text is read and parsed when the notice is asked)."""
        return OwnShares(self, int(cik), share_class=share_class, name=name or "", day=day, form25=form25)

    def read_text(self, cik: int, f: EdgarSubmission) -> str:
        """One filing's text through the EDGAR client ("" when unreadable)."""
        return self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc) or ""

    def read_form25(self, cik: int, sub: EdgarSubmission) -> Form25 | None:
        """The Form 25 `sub` parsed from its complete text; None when it cannot be read."""
        fetch = getattr(self.edgar, "fetch_filing_raw", None)
        raw = fetch(cik, sub.accession) if fetch is not None else ""
        return parse_form25(raw, accession=sub.accession, form=sub.form, filing_date=sub.filing_date) if raw else None


class OwnShares:
    """One ending's own-share reading (module docstring). The registrant's 8-Ks around `day` are listed on the first
    ask (`filings`), their texts read when a statement is asked, and every answer kept for the ending."""

    def __init__(self, reader: Reader, cik: int, *, share_class: str | None, name: str, day: date,
                 form25: Form25 | EdgarSubmission | None) -> None:
        self.reader, self.cik, self.share_class, self.name, self.day = reader, cik, share_class, name, day
        self._form25 = form25
        self.degraded = False          # whether a read it rested on failed or was answered from a stale copy
        self.stated = False            # whether its statement was read (what the finder carries)
        self._filings: list[EdgarSubmission] | None = None
        self._profile: tuple[dict | None] | None = None
        self._texts: dict[str, str] = {}
        self._statements: dict[bool, OwnExchange | None] = {}

    def __repr__(self) -> str:
        return f"OwnShares(cik={self.cik}, day={self.day}, stated={self.stated})"

    # --- the reads --------------------------------------------------------------------------------------------------

    def _watched(self, fn, *args):
        watch = self.reader.issuers.watch()
        out = fn(*args)
        if watch.tripped():
            self.degraded = True
        return out

    def _all_filings(self) -> list[EdgarSubmission]:
        if self._filings is None:
            self._filings = list(self._watched(self.reader.issuers.filings, self.cik))
        return self._filings

    def _sub(self) -> dict | None:
        if self._profile is None:
            self._profile = (self._watched(self.reader.issuers.profile, self.cik),)
        return self._profile[0]

    def text_of(self, f: EdgarSubmission) -> str:
        """One 8-K's text ("" when unreadable), read once for the reading."""
        if f.accession not in self._texts:
            self._texts[f.accession] = self._watched(self.reader.read_text, self.cik, f)
        return self._texts[f.accession]

    @property
    def filings(self) -> list[EdgarSubmission]:
        """The registrant's 8-Ks filed around the day, in filing order (no text read)."""
        return _eightks(self._all_filings(), [self.day])

    @property
    def form25(self) -> Form25 | None:
        """The matched Form 25, parsed (read once when given as its filing)."""
        if isinstance(self._form25, EdgarSubmission):
            self._form25 = self._watched(self.reader.read_form25, self.cik, self._form25)
        return self._form25

    @property
    def notice(self) -> str:
        """The matched Form 25's EX-99.25 notice ("" without one)."""
        return (getattr(self.form25, "notice_text", "") or "") if self.form25 is not None else ""

    @property
    def texts(self) -> list[str]:
        """The texts the statement is read in: the 8-Ks around the day, in filing order, then the notice."""
        out = [self.text_of(f) for f in self.filings]
        return out + [self.notice] if self.notice else out

    @property
    def edgar_names(self) -> list[str]:
        """The registrant's EDGAR names before the day (`registrant_names` without the security's name)."""
        return registrant_names(self._sub(), self.day)

    @property
    def names(self) -> list[str]:
        """The names the statement's subject is read against: the EDGAR names, then the security's own name."""
        return registrant_names(self._sub(), self.day, self.name)

    # --- what it answers --------------------------------------------------------------------------------------------

    def _statement(self, with_notice: bool) -> OwnExchange | None:
        if with_notice not in self._statements:
            texts = self.texts if with_notice else [self.text_of(f) for f in self.filings]
            letter, words = class_of(self.share_class, self.name)
            self._statements[with_notice] = own_exchange(texts, names=self.names, class_letter=letter,
                                                         class_words=words)
            self.stated = True
        return self._statements[with_notice]

    @property
    def statement(self) -> OwnExchange | None:
        """What the security's own shares became, in the 8-Ks and the notice (`exchange_terms.own_exchange`); None
        when no text states it."""
        return self._statement(True)

    @property
    def registrant_statement(self) -> OwnExchange | None:
        """The same, in the registrant's own 8-Ks alone: the exchange's notice is not the registrant's filing (stage
        9g's confirming filing and contradicting ratio: Actavis 2013's notice states Warner Chilcott's 0.160)."""
        return self._statement(False)

    @property
    def one_for_one(self) -> bool:
        """The statement is R1's: one share per share, no cash, one reading, no second leg."""
        return self.statement is not None and self.statement.one_for_one

    def names_target(self, names: Iterable[str], tickers: Iterable[str] = ()) -> bool:
        """The name tie (`names_target`) over the statement; False without one."""
        return self.statement is not None and names_target(self.statement, names, tickers)

    def consideration(self, cash: float | None) -> float | None:
        """`cash` as consideration: None when it is one of the special dividends the texts name (operator ruling
        2026-10-04: a special dividend is never consideration, KRFT 2015's $16.50)."""
        own = self.statement
        if cash and own is not None and any(abs(cash - d) < 0.005 for d in own.special_dividends):
            return None
        return cash

    def target_issuer(self) -> str:
        """Whom the statement's target names (stage 5's R1): SAME_ISSUER for the registrant (a pronoun or no other
        party: a reclassification, Clearway 2026; or a name it carried before the day, ONEOK's 2026 holding company,
        "Legacy ONEOK" into "ONEOK"), NEW_ISSUER for a registrant of another CIK in EDGAR's ticker file whose first
        filing is at most NEW_ISSUER_DAYS before the day (never an existing acquirer: LVNTA into GCI Liberty), else
        ""."""
        own = self.statement
        if own is None:
            return ""
        if own.target_own:
            return SAME_ISSUER
        if not own.target_names:
            return ""
        if names_target(own, self.edgar_names):
            return SAME_ISSUER
        company_tickers = getattr(self.reader.edgar, "company_tickers", None)
        for entry in (company_tickers().values() if company_tickers is not None else ()):
            other = entry.get("cik_str")
            if other is None or int(other) == self.cik or not names_target(own, [entry.get("title", "")]):
                continue
            if new_issuer(self._watched(self.reader.issuers.first_filed, int(other)), self.day):
                return NEW_ISSUER
        return ""

    def survived(self, deal_days: Iterable[date]) -> str:
        """Rule 1 (5c): the sentence that says the registrant survived the transaction its 8-K items call a merger --
        no statement about any class of its own shares, and another role (`other_role`: it acquired another party,
        or distributed another company's shares) -- else "". Read in the 8-Ks around the day and around the deal's
        8-Ks (`deal_days`: the 5.01 and 2.01 filings the end-of-era signals name) and the notice, by the names in
        force before the earliest of those days. Never rename or separation words alone (BNI, CAL, TXU, LGFA were
        targets renamed after closing)."""
        days = [self.day, *deal_days]
        texts = [self.text_of(f) for f in _eightks(self._all_filings(), days)]
        if self.notice:
            texts.append(self.notice)
        names = registrant_names(self._sub(), min(days), self.name)
        if own_exchange(texts, names=names, class_letter=None) is not None:
            return ""
        return other_role(texts, names)


def of(d: Delisting, reader: Reader, security: Any) -> OwnShares:
    """The delisting's own-share reading (`Delisting.own_shares`): the one it carries, else one made at its anchor
    (`Delisting.anchor`) with its matched Form 25, kept on it."""
    if d.own_shares is None:
        d.own_shares = reader.ending(d.cik, share_class=security.share_class, name=security.name, day=d.anchor,
                                     form25=d.form25)
    return d.own_shares
