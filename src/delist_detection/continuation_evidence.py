"""What the registrant's own filings say of a continuation the run linked (the diagnosis-truth spec's ruling 2.3,
sub-plan 5i; reader note A themes 2 and 7), for its verdict only. Two readings, both of sub-plan 5c's R1 reader
(`exchange_terms.own_exchange`) over the registrant's 8-Ks in [day - TEXT_BEFORE_DAYS, day + TEXT_AFTER_DAYS] of the
ending's last trade and delisting dates:

- **A confirming filing** (`confirming_filing`). A continuation the continued-filings rule or the handoff stage's
  timing linked to its successor ("Continued 10-K/Q filings ...; successor by same issuer", "Continuation
  (timing:cik)") rests on that link alone: the verdict keeps `continued_filings_rule` or
  `continuation_by_timing_only`. An 8-K item 3.03 (a reclassification, a holding-company merger) or the registrant's
  own 8-K12B/8-K12G3 confirms it when the texts state the security's own exchange one for one
  (`own_exchange(...).one_for_one`: one share per share, no cash, one reading, no second leg), the reading's target
  names the registrant itself or the run's successor, and the answer is the filing whose own text holds the
  statement (never merely the first 3.03 of the window). A 3.03 can describe any charter change, so the reading is
  the guard: the Liberty tracking-stock reclassifications of 2023 (one new share plus 0.25 or 0.0428 of a Liberty
  Live share, R1's second leg) and Dell's class V election (DVMT 2018) stay timing-only; APA's, CMCSK's and HHC's
  holding company and class changes are confirmed.
- **A contradicting ratio** (`successor_doubt`). A continuation whose reason names its successor registration (an
  8-K12B/8-K12G3, `verdict_rules.successor_filing_reason`) is confirmed by that filing unless the registrant's own
  filings state a ratio that is neither one nor a plain split, or cash (`verdict_rules.ratio_doubt`): CHTR 2016's
  0.9042 is a stock merger (R1), SIRI 2024's 0.1 a reverse split of the same issuer's class (R2: a continuation),
  and a missing reading vetoes nothing.

The successor itself is the run's (stage 9 or the handoff stage): the readings settle only how the link is
evidenced, never which security it names.

Network through the run's EDGAR client (cached); a refusal (`fatal.FATAL`) propagates. A read that fails gives no
filing and no veto, so the doubt stands; the caller reports it `resolution_degraded`.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from . import exchange_terms
from .exchange_terms import TEXT_AFTER_DAYS, TEXT_BEFORE_DAYS
from .figi_resolution import share_class_from_name
from .lifecycle import CONTINUED_FILINGS
from .names import names_agree
from .verdict_rules import Reading, ratio_doubt, successor_filing_date, successor_filing_reason

SUCCESSOR_FORMS = ("8-K12B", "8-K12G3")


def needs_filing(reason: str, sec_id: str, successor: str | None) -> bool:
    """A continuation (a successor other than itself) whose link rests on the continued-filings rule or on timing
    and the same CIK (a CUSIP switch is evidence of its own)."""
    return (bool(successor) and successor != sec_id
            and (reason.startswith(CONTINUED_FILINGS) or "(timing:cik)" in reason))


def needs_doubt_check(reason: str, sec_id: str, successor: str | None) -> bool:
    """A continuation whose reason names its successor registration (module docstring)."""
    return bool(successor) and successor != sec_id and successor_filing_reason(reason)


def _confirming(f) -> bool:
    return f.form.startswith(SUCCESSOR_FORMS) or (f.form.startswith("8-K") and "3.03" in f.item_set)


def _own(edgar, cik: int, filings, days: list[date], name: str):
    letter, words = exchange_terms.class_of(share_class_from_name(name), name)
    names = exchange_terms.registrant_names(edgar.submissions(cik), min(days), name or "")
    own = exchange_terms.own_exchange(exchange_terms.read_texts(edgar, cik, filings, days), names=names,
                                      class_letter=letter, class_words=words)
    return own, names


def _target_is_known(own, registrant_names: Sequence[str], successor_names: Sequence[str]) -> bool:
    """The reading's target names the registrant itself or the run's successor (the name tie, 5c): a reclassification
    or a holding company of the same issuer, or a new issuer the successor's names agree with."""
    if own.target_own:
        return True
    known = [n for n in (*registrant_names, *successor_names) if n]
    return any(names_agree(t, k) for t in own.target_names for k in known)


def confirming_filing(edgar, cik: int, days: Sequence[date | None], name: str,
                      successor_names: Sequence[str] = ()) -> str:
    """`"<form> <accession>"` of the filing that confirms the continuation (module docstring), else ""."""
    days = [d for d in days if d]
    if not days:
        return ""
    filings = edgar.recent_filings(cik)
    windows = [(d - timedelta(days=TEXT_BEFORE_DAYS), d + timedelta(days=TEXT_AFTER_DAYS)) for d in days]

    def near(f) -> bool:
        try:
            filed = date.fromisoformat(f.filing_date[:10])
        except ValueError:
            return False
        return any(lo <= filed <= hi for lo, hi in windows)

    found = [f for f in sorted(filings, key=lambda f: (f.filing_date, f.accession)) if _confirming(f) and near(f)]
    if not found:
        return ""
    own, names = _own(edgar, cik, filings, days, name)
    if own is None or not own.one_for_one or not _target_is_known(own, names, successor_names):
        return ""
    # the filing whose own text states it: the sentence the joint reading kept, else the first confirming filing
    sentence = exchange_terms.normalize(own.sentence)
    for f in found:
        text = edgar.fetch_filing_text(cik, f.accession, f.primary_doc) or ""
        if sentence and sentence in exchange_terms.normalize(text):
            return f"{f.form} {f.accession}"
    return f"{found[0].form} {found[0].accession}"


def successor_doubt(edgar, cik: int, days: Sequence[date | None], name: str) -> str:
    """Why the registrant's own filings contradict a successor registration (`ratio:0.9042`, `cash`), else ""."""
    days = [d for d in days if d]
    if not days:
        return ""
    own, _ = _own(edgar, cik, edgar.recent_filings(cik), days, name)
    return "" if own is None else ratio_doubt(own.ratio, own.cash)


def read_continuation(edgar, cik: int, days: Sequence[date | None], name: str, reason: str, sec_id: str,
                      successor: str | None, successor_names: Sequence[str] = ()) -> Reading:
    """What stage 9g reads for one delisting: a `Reading` (empty when it is neither kind of continuation)."""
    if needs_filing(reason, sec_id, successor):
        return Reading(filing=confirming_filing(edgar, cik, days, name, successor_names))
    if needs_doubt_check(reason, sec_id, successor):
        return Reading(doubt=successor_doubt(edgar, cik, [*days, successor_filing_date(reason)], name))
    return Reading()
