"""What the registrant's own filings say of a continuation the run linked (the diagnosis-truth spec's ruling 2.3,
sub-plan 5i; reader note A themes 2 and 7), for its verdict only. Two readings, both of the ending's own-share reading
(`own_shares.OwnShares.registrant_statement`: the registrant's 8-Ks around the ending's anchor day, the exchange's
Form 25 notice left out), which the delisting carries when an earlier rule read it:

- **A confirming filing** (`confirming_filing`). A continuation the continued-filings rule or the handoff stage's
  timing linked to its successor ("Continued 10-K/Q filings ...; successor by same issuer", "Continuation
  (timing:cik)") rests on that link alone: the verdict keeps `continued_filings_rule` or
  `continuation_by_timing_only`. An 8-K item 3.03 (a reclassification, a holding-company merger) or the registrant's
  own 8-K12B/8-K12G3 among those 8-Ks confirms it when the statement is one for one (`one_for_one`: one share per
  share, no cash, one reading, no second leg), its target names the registrant itself or the run's successor (the
  name tie, `own_shares.names_target`), and the answer is the filing whose own text holds the statement (never
  merely the first 3.03 of the window). A 3.03 can describe any charter change, so the statement is the guard: the
  Liberty tracking-stock reclassifications of 2023 (one new share plus 0.25 or 0.0428 of a Liberty Live share, R1's
  second leg) and Dell's class V election (DVMT 2018) stay timing-only; APA's, CMCSK's and HHC's holding company and
  class changes are confirmed.
- **A contradicting ratio** (`successor_doubt`). A continuation whose reason names its successor registration (an
  8-K12B/8-K12G3, `exit_kind.names_successor_registration`) is confirmed by that filing unless the statement gives a
  ratio that is neither one nor a split factor, or cash (`ratio_doubt`): CHTR 2016's 0.9042 is a stock merger (R1,
  decided by the classifier's rule 6 on the same reading), SIRI 2024's 0.1 a reverse split of the same issuer's class
  (R2: a continuation), and a missing statement vetoes nothing.

The successor itself is the run's (stage 9 or the handoff stage): the readings settle only how the link is
evidenced, never which security it names. Which continuations are read is decided on the row's reason
(`needs_filing`, `needs_doubt_check`), through the row vocabulary's readers (exit_kind), as the verdict reads the
same row. The answer is `exit_kind.ContinuationReading`, the verdict's input beside the tables.

The reading reads through the run's clients; a refusal (`fatal.FATAL`) propagates. A reading that rested on a failed
read gives no filing and no veto, so the doubt stands; the caller reports it `resolution_degraded`.
"""
from __future__ import annotations

from collections.abc import Sequence

from .exchange_terms import normalize, split_factor
from .exit_kind import (SUCCESSOR_FORMS, ContinuationReading, linked_by_timing, names_successor_registration,
                        rests_on_continued_filings)
from .own_shares import OwnShares, names_target


def needs_filing(reason: str, sec_id: str, successor: str | None) -> bool:
    """A continuation (a successor other than itself) whose link rests on the continued-filings rule or on timing
    and the same CIK (a CUSIP switch is evidence of its own)."""
    return (bool(successor) and successor != sec_id
            and (rests_on_continued_filings(reason) or linked_by_timing(reason)))


def needs_doubt_check(reason: str, sec_id: str, successor: str | None) -> bool:
    """A continuation whose reason names its successor registration (module docstring)."""
    return bool(successor) and successor != sec_id and names_successor_registration(reason)


def _confirming(f) -> bool:
    return f.form.startswith(SUCCESSOR_FORMS) or (f.form.startswith("8-K") and "3.03" in f.item_set)


def confirming_filing(own: OwnShares, successor_names: Sequence[str] = ()) -> str:
    """`"<form> <accession>"` of the filing that confirms the continuation (module docstring), else "". No text is
    read when no 3.03 8-K or successor registration was filed around the day."""
    found = [f for f in own.filings if _confirming(f)]
    if not found:
        return ""
    st = own.registrant_statement
    if st is None or not st.one_for_one or not (st.target_own or names_target(st, [*own.names, *successor_names])):
        return ""
    # the filing whose own text states it: the sentence the joint reading kept, else the first confirming filing
    sentence = normalize(st.sentence)
    for f in found:
        if sentence and sentence in normalize(own.text_of(f)):
            return f"{f.form} {f.accession}"
    return f"{found[0].form} {found[0].accession}"


def ratio_doubt(ratio: float, cash: bool) -> str:
    """Why a registrant's own reading contradicts a continuation: cash in the exchange, or a ratio that is neither
    one nor a split factor (`exchange_terms.split_factor`: SIRI 2024's 0.1 holds the same stake in fewer shares,
    CHTR 2016's 0.9042 is a new security's exchange ratio); "" when it does not. The verdict publishes it as
    `continuation_not_one_for_one:<doubt>`."""
    if cash:
        return "cash"
    return "" if split_factor(ratio) else f"ratio:{ratio:g}"


def successor_doubt(own: OwnShares) -> str:
    """Why the registrant's own filings contradict a successor registration (`ratio:0.9042`, `cash`), else ""."""
    st = own.registrant_statement
    return "" if st is None else ratio_doubt(st.ratio, st.cash)


def read_continuation(own: OwnShares, reason: str, sec_id: str, successor: str | None,
                      successor_names: Sequence[str] = ()) -> ContinuationReading:
    """What stage 9g reads for one delisting, from its own-share reading `own`: a `ContinuationReading` (empty when
    it is neither kind of continuation)."""
    if needs_filing(reason, sec_id, successor):
        return ContinuationReading(filing=confirming_filing(own, successor_names))
    if needs_doubt_check(reason, sec_id, successor):
        return ContinuationReading(doubt=successor_doubt(own))
    return ContinuationReading()
