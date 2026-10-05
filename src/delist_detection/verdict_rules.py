"""The verdict-only rulings of the diagnosis-truth spec, section 2.3 (sub-plan 5i), each with its guard from reader
note A. They settle a doubt `verdict` would otherwise raise; none changes a table row, only the verdict.

- **A relabel a matched Form 25 settles** (`settles_relabel`, note A theme 1). The end-of-era resolver turned a
  continued-filings ending into a merger by its 8-K item 5.01 or 2.01 ("; the registrant kept filing after it"):
  with the security's own exchange Form 25 (25-NSE) on the row, the merger rests on the exchange's removal, and the
  registrant keeps filing only for its debt or preferred. Not the issuer's own Form 25 (a voluntary removal after a
  change in control that leaves shares outstanding is no merger; a removal under rule 12d2-2(b) is not on the row,
  so it reads as a 25-NSE). Not for any other branch: a listing-deficiency relabel (MDRX, RHD), a liquidation (EQC)
  or a bankruptcy before a sale keeps its doubt, and so does a merger with no Form 25 (FCL, SGP).
- **A successor registration confirms a continuation** (`successor_registration`, note A themes 2 and 6). The
  resolver's successor branch ("Successor registration 8-K12B <date>") or the handoff stage's continuation by an
  8-K12B/8-K12G3 ("Continuation (8-K12B <accession>)") names the filing that carries the security to its
  successor: neither the continued-filings relabel nor the no-evidence default the row carried before the handoff
  rewrote it is a doubt then (BHI, BKFS, GOOGL). Only on a continuation (a successor other than itself): a
  successor registration whose successor was never found keeps its doubt, and so does one whose registrant's own
  filings state another ratio or cash (`Reading.doubt`, stage 9g: CHTR 2016's 0.9042 is a stock merger, reason
  `continuation_not_one_for_one:ratio:0.9042`; SIRI 2024's 0.1 is a reverse split of the same class and no doubt,
  `ratio_doubt`; a missing reading vetoes nothing). A continuation linked by timing alone ("timing:cik", the Liberty
  tracking-stock reclassifications) is untouched.
- **The matched Form 25's filer is issuer evidence** (`issuer_by_form25`, note A theme 3). An issuer found in
  today's company_tickers.json is confirmed when the row's own Form 25 (not the unmatched one a handoff row
  borrows) was read from that same CIK and the observed name agreed with it on the date (no
  `member_name_mismatch`, CHK 2020; the finder raises it only against an observed name, so every seed of the
  security must carry one). A Form 25 of another CIK (SPB's 1487730 against issuer 109177, MTCH 2020) and an ending
  with no Form 25 (CBL, TDW, VRM, SIRI) keep the doubt.
- **An unpriced gate is not a failed one** (`unpriced_gate`, decision 4, note A theme 4). Assumed par after a failed
  gate stays uncertain unless every failed gate on the row failed on the price side: the stock leg's acquirer price
  was missing for a named acquirer (`no_acq_price`), or the gate compared the terms with a last close more than
  STALE_CLOSE_DAYS trading days old (`ftd_close_prior:<n>`) and missed it by no more than the gate's tolerance
  widened per day of the close's age (`STALE_TOL_BASE`, `STALE_TOL_PER_DAY`: AT's Series D misread, 481.37 against
  71, is the terms'). A close the fails rows date a few days late (`ftd_close_lagged`) is not stale enough: PNRA's
  and MRD's terms are right, MDP's and PCYC's miss a leg, and the flag cannot tell them apart. A missing acquirer
  ticker (`no_acq_ticker`), or a row that names none or a NULL-like one ("NULL", "None", "N/A": GRUB 2021's contract
  row publishes `price_ticker=NULL`, its delistings row none), is a doubt about the terms. A gate that did not check
  (`terms_gate_skipped`, 5f) is never price-side. The gate tokens are verdict.py's `GATE_FAILED`, passed in.
- **A stale seed after a confirmed ending** (`stale_seed`, note A theme 5). A caller's introduction past the
  security's clipped history (`after_delisting`) does not make the security uncertain when its last real ending is
  confirmed on its own, is not a continuation and rests on its own Form 25: the caller's snapshot kept the ticker
  after the merger (BOL, TEK 2007). The seed itself stays listed (`outside_security_history`). An
  `after_unconfirmed_delisting` seed (CDWC, DADE) keeps its doubt; so does an ending whose own row carries a doubt
  its reasons do not raise (`doubted_ending`: a `last_trade_date_conflict`, FRK 2007; a merger of one share and no
  cash, R1's continuation, MEL 2007), and a seed more than STALE_SEED_DAYS after the ending's last trade (a later
  era on a recycled ticker is no stale snapshot).
- **No ending at all** (`closed_without_ending`, the wave 1 gap). An observed security whose every ticker interval is
  closed and that has no real ending (lifecycle `closed_no_event`; every `ended_without_delisting` security is one)
  is uncertain, `closed_no_event:<its last interval's end>`: nothing says how it left (WW 2013, NCRA). A security
  the run added (an acquirer's price line) is no lifecycle claim and is left alone.

Pure: string rows as store.read_table returns them.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .lifecycle import RESOLVED_FROM_CONTINUED_FILINGS, flag_names

STALE_CLOSE_DAYS = 3                      # a last close older than this many trading days cannot test the terms
# end_of_era.resolve's merger branches (a change in control, a completed acquisition)
MERGER_RELABELS = ("Change in control (8-K item 5.01", "Completed acquisition (8-K item 2.01")
STALE_SEED_DAYS = 365                     # a seed counts as stale only this soon after the ending's last trade
STALE_TOL_BASE, STALE_TOL_PER_DAY = 0.15, 0.05   # the gate's own tolerance, widened per trading day of close age
_SUCCESSOR_FILING = re.compile(r"^(?:Successor registration |Continuation \()(?:8-K12B|8-K12G3)(?:/A)? ")
_FILING_DATE = re.compile(r"^Successor registration 8-K12(?:B|G3)(?:/A)? (\d{4}-\d{2}-\d{2})")
_COMPARED = frozenset({"", "fail_sanity"})   # a gate token's detail when it compared the terms with the last close
SKIPPED_GATE = "terms_gate_skipped"       # a gate that could not check (sub-plan 5f): never a price-side failure
_NO_TICKER = frozenset({"", "NULL", "NONE", "N/A", "NA", "-", "--", "NAN"})   # an acquirer ticker in name only


@dataclass(frozen=True)
class Reading:
    """What stage 9g (`continuation_evidence`) read for one continuation. `filing`: `"<form> <accession>"` of the
    filing whose text states the exchange one for one, for a continuation the continued-filings rule or timing
    linked; `doubt`: why the registrant's own filings contradict an 8-K12B continuation (`ratio:0.9042`, `cash`)."""
    filing: str = ""
    doubt: str = ""


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
    """A merger relabel of the continued-filings rule that the row's own exchange Form 25 (25-NSE) settles (module
    docstring): not the issuer's own Form 25 (a voluntary removal after a change in control that leaves shares
    outstanding is no merger). A removal under rule 12d2-2(b) is not on the row: it reads as a 25-NSE too."""
    return (RESOLVED_FROM_CONTINUED_FILINGS in row["reason"] and row["reason"].startswith(MERGER_RELABELS)
            and own_form25(row) and row["delist_filing_form"].startswith("25-NSE"))


def successor_filing_reason(reason: str) -> bool:
    """A reason that names a successor registration, an 8-K12B or 8-K12G3 (the resolver's or the handoff's)."""
    return bool(_SUCCESSOR_FILING.match(reason))


def successor_filing_date(reason: str) -> date | None:
    """The filing date a resolver's successor-registration reason names, else None."""
    m = _FILING_DATE.match(reason)
    return date.fromisoformat(m.group(1)) if m else None


def reverse_split(ratio: float) -> bool:
    """A share becomes 1/N of a share (SIRI 2024's 0.1) or N shares: the same holding in fewer or more shares, not a
    new security's exchange ratio (CHTR 2016's 0.9042)."""
    if ratio <= 0 or ratio == 1.0:
        return False
    x = 1 / ratio if ratio < 1 else ratio
    return round(x) >= 2 and abs(x - round(x)) < 1e-6


def ratio_doubt(ratio: float, cash: bool) -> str:
    """Why a registrant's own reading contradicts a continuation: cash in the exchange, or a ratio that is neither
    one nor a plain split (`reverse_split`); "" when it does not."""
    if cash:
        return "cash"
    return "" if ratio == 1.0 or reverse_split(ratio) else f"ratio:{ratio:g}"


def successor_registration(row: Mapping[str, str], reading: Reading = Reading()) -> bool:
    """A continuation whose reason names its successor registration, an 8-K12B or 8-K12G3, and whose registrant's
    own filings do not state another ratio or cash (`reading.doubt`; module docstring)."""
    return is_continuation(row) and successor_filing_reason(row["reason"]) and not reading.doubt


def issuer_by_form25(row: Mapping[str, str], issuer_cik: str, named: bool = False) -> bool:
    """The row's own Form 25 was read from the security's issuer CIK and the observed name agreed (module
    docstring). `named`: every seed of the security carries an observed name (`member_name_mismatch` is raised only
    against one)."""
    return (named and own_form25(row) and bool(issuer_cik) and row["cik"] == issuer_cik
            and "member_name_mismatch" not in flag_names(row))


def _close_age(row: Mapping[str, str]) -> int:
    """The last close's age in trading days (`ftd_close_prior:<n>`), 0 for a close of the day after the last trade."""
    for t in tokens(row):
        name, _, detail = t.partition(":")
        if name == "ftd_close_prior" and detail.isdecimal():
            return int(detail)
    return 0


def _number(text: str) -> float | None:
    try:
        v = float(text)
    except ValueError:
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _near_stale_close(row: Mapping[str, str], name: str, detail: str, age: int) -> bool:
    """A gate that compared the terms with a stale close, within the tolerance the close's age widens (module
    docstring): the payout it names (or the row's terminal value) against the close. A failure past it is the
    terms' (AT's Series D misread, 481.37 against about 71)."""
    if name == SKIPPED_GATE or not (name == "payout_gate_failed" or detail in _COMPARED):
        return False
    value = _number(detail) if name == "payout_gate_failed" else None
    value = value if value is not None else _number(row.get("terminal_value", ""))
    close = _number(row.get("last_trade_close", ""))
    if value is None or close is None or close <= 0:
        return False
    return abs(value / close - 1) <= STALE_TOL_BASE + STALE_TOL_PER_DAY * age


def named_acquirer(row: Mapping[str, str]) -> bool:
    """The row names its acquirer: a ticker that is not blank or a NULL-like word (GRUB 2021's "NULL" is a missing
    ticker in disguise)."""
    return row.get("acquirer_ticker", "").strip().upper() not in _NO_TICKER


def unpriced_gate(row: Mapping[str, str], gates: Collection[str]) -> bool:
    """Every failed gate on the row (`gates`: the token names that count as a gate that did not pass, verdict.py's
    one set) failed on the price side (module docstring); False when none failed, and False whenever any such token
    is not price-side, a skipped gate (`SKIPPED_GATE`) included."""
    failed = [t.partition(":") for t in tokens(row) if t.partition(":")[0] in gates]
    if not failed:
        return False
    age = _close_age(row)
    stale = age > STALE_CLOSE_DAYS
    named = named_acquirer(row)
    return all((detail == "no_acq_price" and name != SKIPPED_GATE and named)
               or (stale and _near_stale_close(row, name, detail, age))
               for name, _, detail in failed)


def doubted_ending(row: Mapping[str, str]) -> bool:
    """A doubt the row itself carries that its own reasons do not raise: a text and a measured last-trade day that
    disagree (FRK 2007: the halt day against the NYSE notice's), or a merger whose terms are one share and no cash
    (MEL 2007: R1's continuation, published as a merger)."""
    if "last_trade_date_conflict" in flag_names(row):
        return True
    ratio, cash = _number(row.get("stock_ratio", "")), _number(row.get("payout_per_share", "")) or 0.0
    return row.get("bucket") == "merger" and ratio is not None and abs(ratio - 1.0) < 1e-6 and cash == 0.0


def _within_days(as_of: str, ending: Mapping[str, str]) -> bool:
    anchor = ending.get("last_trade_date") or ending["delist_date"]
    try:
        return 0 <= (date.fromisoformat(as_of) - date.fromisoformat(anchor)).days <= STALE_SEED_DAYS
    except ValueError:
        return False


def stale_seed(status: str, last_ending: Mapping[str, str] | None, settled: bool, as_of: str = "") -> bool:
    """An after-delisting introduction that does not count against its security (module docstring). `settled`: the
    last ending's own reasons, the security's set aside, are none; `as_of`: the seed's date, within
    STALE_SEED_DAYS of the ending's last trade (a later era on a recycled ticker is no stale snapshot)."""
    return (status == "after_delisting" and last_ending is not None and settled and as_of != ""
            and not is_continuation(last_ending) and own_form25(last_ending) and not doubted_ending(last_ending)
            and _within_days(as_of, last_ending))


def closed_without_ending(security: Mapping[str, str], intervals: Sequence[Mapping[str, str]],
                          endings: Sequence[Mapping[str, str]]) -> str:
    """`closed_no_event:<last interval end>` for an observed security whose intervals are all closed and that has no
    real ending (module docstring), else ""."""
    if security.get("observed") != "true" or not intervals or any(not r["valid_to"] for r in intervals):
        return ""
    if any(r["successor_sec_id"] != r["sec_id"] for r in endings):
        return ""
    return f"closed_no_event:{max(r['valid_to'] for r in intervals)}"
