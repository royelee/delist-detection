"""The verdict-only rulings of the diagnosis-truth spec, section 2.3 (sub-plan 5i), each with its guard from reader
note A. They settle a doubt `verdict` would otherwise raise; none changes a table row, only the verdict.

- **A relabel a matched Form 25 settles** (`settles_relabel`, note A theme 1). The end-of-era resolver turned a
  continued-filings ending into a merger by its 8-K item 5.01 or 2.01 ("; the registrant kept filing after it"):
  with the security's own Form 25 on the row, the merger rests on the exchange's removal, and the registrant keeps
  filing only for its debt or preferred. Not for any other branch: a listing-deficiency relabel (MDRX, RHD), a
  liquidation (EQC) or a bankruptcy before a sale keeps its doubt, and so does a merger with no Form 25 (FCL, SGP).
- **A successor registration confirms a continuation** (`successor_registration`, note A themes 2 and 6). The
  resolver's successor branch ("Successor registration 8-K12B <date>") or the handoff stage's continuation by an
  8-K12B/8-K12G3 ("Continuation (8-K12B <accession>)") names the filing that carries the security to its
  successor: neither the continued-filings relabel nor the no-evidence default the row carried before the handoff
  rewrote it is a doubt then (BHI, BKFS, GOOGL). Only on a continuation (a successor other than itself): a
  successor registration whose successor was never found keeps its doubt. A continuation linked by timing alone
  ("timing:cik", the Liberty tracking-stock reclassifications) is untouched.
- **The matched Form 25's filer is issuer evidence** (`issuer_by_form25`, note A theme 3). An issuer found in
  today's company_tickers.json is confirmed when the row's own Form 25 (not the unmatched one a handoff row
  borrows) was read from that same CIK and the observed name agreed with it on the date (no
  `member_name_mismatch`, CHK 2020). A Form 25 of another CIK (SPB's 1487730 against issuer 109177, MTCH 2020) and
  an ending with no Form 25 (CBL, TDW, VRM, SIRI) keep the doubt.
- **An unpriced gate is not a failed one** (`unpriced_gate`, decision 4, note A theme 4). Assumed par after a failed
  gate stays uncertain unless every failed gate on the row failed on the price side: the stock leg's acquirer price
  was missing (`no_acq_price`, GRUB 2021), or the gate compared the terms with a last close more than
  STALE_CLOSE_DAYS trading days old (`ftd_close_prior:<n>`). A close the fails rows date a few days late
  (`ftd_close_lagged`) is not stale enough: PNRA's and MRD's terms are right, MDP's and PCYC's miss a leg, and the
  flag cannot tell them apart. A missing acquirer ticker (`no_acq_ticker`) is a doubt about the terms.
- **A stale seed after a confirmed ending** (`stale_seed`, note A theme 5). A caller's introduction past the
  security's clipped history (`after_delisting`) does not make the security uncertain when its last real ending is
  confirmed on its own, is not a continuation and rests on its own Form 25: the caller's snapshot kept the ticker
  after the merger (BOL, MEL, TEK 2007). The seed itself stays listed (`outside_security_history`). An
  `after_unconfirmed_delisting` seed (CDWC, DADE) keeps its doubt.
- **No ending at all** (`closed_without_ending`, the wave 1 gap). An observed security whose every ticker interval is
  closed and that has no real ending (lifecycle `closed_no_event`; every `ended_without_delisting` security is one)
  is uncertain, `closed_no_event:<its last interval's end>`: nothing says how it left (WW 2013, NCRA). A security
  the run added (an acquirer's price line) is no lifecycle claim and is left alone.

Pure: string rows as store.read_table returns them.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .lifecycle import RESOLVED_FROM_CONTINUED_FILINGS, flag_names

STALE_CLOSE_DAYS = 3                      # a last close older than this many trading days cannot test the terms
# end_of_era.resolve's merger branches (a change in control, a completed acquisition)
MERGER_RELABELS = ("Change in control (8-K item 5.01", "Completed acquisition (8-K item 2.01")
_SUCCESSOR_FILING = re.compile(r"^(?:Successor registration |Continuation \()(?:8-K12B|8-K12G3)(?:/A)? ")
_GATE_FAILED = frozenset({"payout_gate_failed", "llm_gate_failed", "terms_gate_failed"})
_COMPARED = frozenset({"", "fail_sanity"})   # a gate token's detail when it compared the terms with the last close


def tokens(row: Mapping[str, str]) -> list[str]:
    """The review flag tokens on a delistings.csv row, whole (`payout_gate_failed:34.88`)."""
    return [f for f in row.get("review_flags", "").split(";") if f]


def is_continuation(row: Mapping[str, str]) -> bool:
    return bool(row["successor_sec_id"]) and row["successor_sec_id"] != row["sec_id"]


def own_form25(row: Mapping[str, str]) -> bool:
    """The row cites a Form 25 the delisting finder matched to the security: one is on the row, and the row is not
    one the handoff stage built around an unmatched (ambiguous) Form 25 of its predecessor (such a row has no
    resolver tier of its own)."""
    if not (row["delist_filing_date"] and row["delist_filing_form"].startswith("25")):
        return False
    return not ("handoff_continuation" in flag_names(row) and not row["resolution_source"])


def settles_relabel(row: Mapping[str, str]) -> bool:
    """A merger relabel of the continued-filings rule that the row's own Form 25 settles (module docstring)."""
    return (RESOLVED_FROM_CONTINUED_FILINGS in row["reason"] and row["reason"].startswith(MERGER_RELABELS)
            and own_form25(row))


def successor_registration(row: Mapping[str, str]) -> bool:
    """A continuation whose reason names its successor registration, an 8-K12B or 8-K12G3 (module docstring)."""
    return is_continuation(row) and bool(_SUCCESSOR_FILING.match(row["reason"]))


def issuer_by_form25(row: Mapping[str, str], issuer_cik: str) -> bool:
    """The row's own Form 25 was read from the security's issuer CIK and the observed name agreed (module
    docstring)."""
    return (own_form25(row) and bool(issuer_cik) and row["cik"] == issuer_cik
            and "member_name_mismatch" not in flag_names(row))


def _close_age(row: Mapping[str, str]) -> int:
    """The last close's age in trading days (`ftd_close_prior:<n>`), 0 for a close of the day after the last trade."""
    for t in tokens(row):
        name, _, detail = t.partition(":")
        if name == "ftd_close_prior" and detail.isdigit():
            return int(detail)
    return 0


def unpriced_gate(row: Mapping[str, str]) -> bool:
    """Every failed gate on the row failed on the price side (module docstring); False when none failed."""
    failed = [t.partition(":") for t in tokens(row) if t.partition(":")[0] in _GATE_FAILED]
    if not failed:
        return False
    stale = _close_age(row) > STALE_CLOSE_DAYS
    return all(detail == "no_acq_price" or (stale and (name == "payout_gate_failed" or detail in _COMPARED))
               for name, _, detail in failed)


def stale_seed(status: str, last_ending: Mapping[str, str] | None, settled: bool) -> bool:
    """An after-delisting introduction that does not count against its security (module docstring). `settled`: the
    last ending's own reasons, the security's set aside, are none."""
    return (status == "after_delisting" and last_ending is not None and settled
            and not is_continuation(last_ending) and own_form25(last_ending))


def closed_without_ending(security: Mapping[str, str], intervals: Sequence[Mapping[str, str]],
                          endings: Sequence[Mapping[str, str]]) -> str:
    """`closed_no_event:<last interval end>` for an observed security whose intervals are all closed and that has no
    real ending (module docstring), else ""."""
    if security.get("observed") != "true" or not intervals or any(not r["valid_to"] for r in intervals):
        return ""
    if any(r["successor_sec_id"] != r["sec_id"] for r in endings):
        return ""
    return f"closed_no_event:{max(r['valid_to'] for r in intervals)}"
