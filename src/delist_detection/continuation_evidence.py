"""The filing that confirms a continuation the run linked without one (the diagnosis-truth spec's ruling 2.3, sub-plan
5i; reader note A themes 2 and 7): an 8-K item 3.03 (a reclassification, a holding-company merger) or the
registrant's own 8-K12B/8-K12G3, stating that each share of the security's class became one share with no cash.

A continuation the continued-filings rule or the handoff stage's timing linked to its successor ("Continued 10-K/Q
filings ...; successor by same issuer", "Continuation (timing:cik)") rests on that link alone: the verdict keeps
`continued_filings_rule` or `continuation_by_timing_only`. `confirming_filing` reads the registrant's 8-Ks filed in
[day - TEXT_BEFORE_DAYS, day + TEXT_AFTER_DAYS] of the ending's last trade and delisting dates (sub-plan 5c's
`exchange_terms.read_texts`) and answers the first of them that is an 8-K12B/8-K12G3 or carries item 3.03, when the
texts state the security's own exchange one for one (`exchange_terms.own_exchange(...).one_for_one`, R1: one share
per share, no cash, one reading, no second leg). A 3.03 can describe any charter change, so the R1 reading is the
guard: the Liberty tracking-stock reclassifications of 2023 (one new share plus 0.25 or 0.0428 of a Liberty Live
share, R1's second leg) and Dell's class V election (DVMT 2018) stay timing-only; APA's, CMCSK's and HHC's holding
company and class changes are confirmed. The successor itself is the run's (stage 9 or the handoff stage): this
reading settles only how the link is evidenced, never which security it names.

Network through the run's EDGAR client (cached); a refusal (`fatal.FATAL`) propagates. A read that fails gives no
filing, so the doubt stands; the caller reports it `resolution_degraded`.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from . import exchange_terms
from .exchange_terms import TEXT_AFTER_DAYS, TEXT_BEFORE_DAYS
from .figi_resolution import share_class_from_name
from .lifecycle import CONTINUED_FILINGS

SUCCESSOR_FORMS = ("8-K12B", "8-K12G3")


def needs_filing(reason: str, sec_id: str, successor: str | None) -> bool:
    """A continuation (a successor other than itself) whose link rests on the continued-filings rule or on timing
    and the same CIK (a CUSIP switch is evidence of its own)."""
    return (bool(successor) and successor != sec_id
            and (reason.startswith(CONTINUED_FILINGS) or "(timing:cik)" in reason))


def _confirming(f) -> bool:
    return f.form.startswith(SUCCESSOR_FORMS) or (f.form.startswith("8-K") and "3.03" in f.item_set)


def confirming_filing(edgar, cik: int, days: Sequence[date | None], name: str) -> str:
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
    letter, words = exchange_terms.class_of(share_class_from_name(name), name)
    names = exchange_terms.registrant_names(edgar.submissions(cik), min(days), name or "")
    own = exchange_terms.own_exchange(exchange_terms.read_texts(edgar, cik, filings, days), names=names,
                                      class_letter=letter, class_words=words)
    return f"{found[0].form} {found[0].accession}" if own is not None and own.one_for_one else ""
