"""One verdict per seed, security and ending: confirmed, or uncertain with its
reasons (spec: Delist Library Reset, Part 3 "Invariants the library's build
enforces"; decisions 1, 4 and 9).

- A security is confirmed when its identity rests on a FIGI, or, for a
  placeholder (a CIK and class with no FIGI), on a filing that ties its
  ticker to that CIK (decision 1; `ticker_evidence`); when every seed
  resolved to it falls inside its ticker history; and when no other security
  holds one of its tickers over an overlapping date range, unless an ending
  of one hands the ticker to the other. A seed past the history after a
  settled last ending (ruling E below: not one whose row carries a last-trade conflict or
  one-for-one merger terms, and within a year of its last trade) does not count, and an
  observed security closed with no ending at all is uncertain (ruling F).
- An ending (a delistings.csv row whose successor is not the security itself)
  is confirmed when its security is confirmed, its issuer CIK did not come
  from today's ticker map, and its exit kind rests on a filing: not the
  continued-filings rule, not the no-evidence default, not unknown. An
  ending the end-of-era resolver relabelled from the continued-filings rule
  stays uncertain unless its own Form 25 settles a merger or its successor
  registration a continuation; today's ticker map stays a doubt unless the
  row's own Form 25 came from that CIK (the rulings below). A
  continuation (a successor other than itself) must rest on a successor
  filing or a CUSIP switch, not on timing alone. Any other ending needs a
  last trade date from an exchange print (MIDAS, a Nasdaq halt, the
  exchange's notice, 8-K item 3.01) that is confirmed, that no other text
  source contradicts unless MIDAS or a halt measured it, and that falls no
  later than the Form 25's effective date. The value never decides the
  verdict, except assumed par after a failed payout, LLM or terms gate (decision 4)
  that did not fail on the price side alone (ruling D).
  An ending that is not its security's last (one that ended, returned and
  ended again) is uncertain, `earlier_ending:<the last one's delist_date>`: the
  contract keeps one ending per security (decision 12).
- A seed (an observation_map row) is confirmed when it has a sec_id, was
  seen under one name that day, falls inside one of its security's ticker
  intervals, and its security is confirmed.

The rulings of the diagnosis-truth spec, section 2.3 (sub-plan 5i), each with its guard from reader note A. They
settle a doubt the rules above would otherwise raise; none changes a table row, only the verdict.

- **A. A relabel a matched Form 25 settles** (note A theme 1). The end-of-era resolver turned a continued-filings
  ending into a merger by its 8-K item 5.01 or 2.01 (`exit_kind.merger_relabel`): with the security's own exchange
  Form 25 (25-NSE) on the row, the merger rests on the exchange's removal, and the registrant keeps filing only for
  its debt or preferred. Not the issuer's own Form 25 (a voluntary removal after a change in control that leaves
  shares outstanding is no merger; a removal under rule 12d2-2(b) is not on the row, so it reads as a 25-NSE). Not
  for any other branch: a listing-deficiency relabel (MDRX, RHD), a liquidation (EQC) or a bankruptcy before a sale
  keeps its doubt, and so does a merger with no Form 25 (FCL, SGP).
- **B. A successor registration confirms a continuation** (note A themes 2 and 6). The resolver's successor branch
  ("Successor registration 8-K12B <date>") or the handoff stage's continuation by an 8-K12B/8-K12G3
  ("Continuation (8-K12B <accession>)", `exit_kind.names_successor_registration`) names the filing that carries the
  security to its successor: the continued-filings relabel is no doubt then (BHI, BKFS). Only on a continuation (a
  successor other than itself): a successor registration whose successor was never found keeps its doubt, and so
  does one whose registrant's own filings state another ratio or cash (`ContinuationReading.doubt`, stage 9g: CHTR
  2016's 0.9042 is a stock merger, reason `continuation_not_one_for_one:ratio:0.9042`; SIRI 2024's 0.1 is a reverse
  split of the same class and no doubt, by the one split factor rule; a missing reading vetoes nothing). A
  continuation linked by timing alone ("timing:cik", the Liberty tracking-stock reclassifications) is untouched. (A
  continuation never carries the no-evidence default: `rewrites.continuation` drops it.)
- **C. The matched Form 25's filer is issuer evidence** (note A theme 3). An issuer found in today's
  company_tickers.json is confirmed when the row's own Form 25 (not the unmatched one a handoff row borrows) was read
  from that same CIK and the observed name agreed with it on the date (no `member_name_mismatch`, CHK 2020; the
  finder raises it only against an observed name, so every seed of the security must carry one). A Form 25 of
  another CIK (SPB's 1487730 against issuer 109177, MTCH 2020) and an ending with no Form 25 (CBL, TDW, VRM, SIRI)
  keep the doubt.
- **D. An unpriced gate is not a failed one** (decision 4, note A theme 4). Assumed par after a failed gate stays
  uncertain unless every failed gate on the row failed on the price side: the stock leg's acquirer price was missing
  for a named acquirer (`no_acq_price`), or the gate compared the terms with a last close more than
  STALE_CLOSE_DAYS trading days old (`ftd_close_prior:<n>`) and missed it by no more than the gate's tolerance
  widened per day of the close's age (`STALE_TOL_BASE`, `STALE_TOL_PER_DAY`: AT's Series D misread, 481.37 against
  71, is the terms'). A close the fails rows date a few days late (`ftd_close_lagged`) is not stale enough: PNRA's
  and MRD's terms are right, MDP's and PCYC's miss a leg, and the flag cannot tell them apart. A missing acquirer
  ticker (`no_acq_ticker`), or a row that names none or a NULL-like one ("NULL", "None", "N/A": GRUB 2021's contract
  row publishes `price_ticker=NULL`, its delistings row none), is a doubt about the terms. A gate that did not check
  (`terms_gate_skipped`, 5f) is never price-side. The gates are the row vocabulary's one set
  (`exit_kind.GATE_FLAGS`).
- **E. A stale seed after a confirmed ending** (note A theme 5). A caller's introduction past the security's
  clipped history (`after_delisting`) does not make the security uncertain when its last real ending is confirmed
  on its own, is not a continuation and rests on its own Form 25: the caller's snapshot kept the ticker after the
  merger (BOL, TEK 2007). The seed itself stays listed (`outside_security_history`). An
  `after_unconfirmed_delisting` seed (CDWC, DADE) keeps its doubt; so does an ending whose own row carries a doubt
  its reasons do not raise (a `last_trade_date_conflict`, FRK 2007; a merger of one share and no cash, R1's
  continuation, MEL 2007), and a seed more than STALE_SEED_DAYS after the ending's last trade (a later era on a
  recycled ticker is no stale snapshot).
- **F. No ending at all** (the wave 1 gap). An observed security whose every ticker interval is closed and that has
  no real ending (lifecycle `closed_no_event`; every `ended_without_delisting` security is one) is uncertain,
  `closed_no_event:<its last interval's end>`: nothing says how it left (WW 2013, NCRA). A security the run added (an
  acquirer's price line) is no lifecycle claim and is left alone.

`uncertain_rows` is uncertain.csv: every uncertain security and ending, and
every seed uncertain for a reason of its own; a seed whose only problem is
its security is counted, not listed. Each reason is `code` or `code:detail`.
Pure: a function of one run's snapshot (`run_snapshot.RunSnapshot`): its tables, read through the row vocabulary
(exit_kind: real endings, flags, the evidence a reason names, the last trade), and what stage 9g read from the
registrant's own filings for each continuation (`RunSnapshot.continuations`: run_manifest.json's
`continuation_filings`, so the verdicts recomputed from a written folder are the run's), plus each placeholder's
ticker evidence (stage 10e, `evidence`: the run records none, so an offline caller supplies it).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .exit_kind import (CONFLICT, EXCHANGE_PRINTS, GATE_FLAGS, MEASURED, PAYOUT_GATE_FAILED, TERMS_GATE_SKIPPED,
                        ContinuationReading, cites_form25, effective_of, end_day_of, ending_fields, flag_detail,
                        flag_name, flag_names, flag_tokens, is_continuation, is_real_ending, last_endings,
                        linked_by_timing, merger_relabel, names_successor_registration, of_row,
                        resolved_from_continued_filings, rests_on_continued_filings)
from .run_snapshot import RunSnapshot

SEED, SECURITY, ENDING = "seed", "security", "ending"
SECURITY_UNCERTAIN = "security_uncertain"
CONFIRMED, UNCERTAIN = "confirmed", "uncertain"
STALE_CLOSE_DAYS = 3                      # a last close older than this many trading days cannot test the terms
STALE_SEED_DAYS = 365                     # a seed counts as stale only this soon after the ending's last trade
STALE_TOL_BASE, STALE_TOL_PER_DAY = 0.15, 0.05   # the gate's own tolerance, widened per trading day of close age
_COMPARED = frozenset({"", "fail_sanity"})   # a gate token's detail when it compared the terms with the last close
_NO_TICKER = frozenset({"", "NULL", "NONE", "N/A", "NA", "-", "--", "NAN"})   # an acquirer ticker in name only


@dataclass(frozen=True)
class Verdict:
    reasons: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return not self.reasons

    @property
    def word(self) -> str:
        """The contract's verdict column."""
        return CONFIRMED if self.confirmed else UNCERTAIN


def is_introduction(row: Mapping[str, str]) -> bool:
    """An observation_map row that is its era's first sighting: the spec's
    seed (one row per introduction). An era key reads `TICKER@DATE[#n]`."""
    return row["as_of"] == row["era"].split("@", 1)[-1].split("#", 1)[0]


def _covered(intervals: list[Mapping[str, str]], day: str) -> bool:
    return any(r["valid_from"] <= day and (not r["valid_to"] or day <= r["valid_to"]) for r in intervals)


# -- the rulings (module docstring, A to F) -----------------------------------------------------------------------
def _own_form25(row: Mapping[str, str]) -> bool:
    """The row cites a Form 25 the delisting finder matched to the security: one is on the row, and the row is not
    one the handoff stage built around an unmatched (ambiguous) Form 25 of its predecessor (such a row has no
    resolver tier of its own)."""
    if not cites_form25(row):
        return False
    return not ("handoff_continuation" in flag_names(row) and not row["resolution_source"])


def _settles_relabel(row: Mapping[str, str]) -> bool:
    """A: a merger relabel of the continued-filings rule that the row's own exchange Form 25 (25-NSE) settles: not
    the issuer's own Form 25 (a voluntary removal after a change in control that leaves shares outstanding is no
    merger). A removal under rule 12d2-2(b) is not on the row: it reads as a 25-NSE too."""
    return merger_relabel(row["reason"]) and _own_form25(row) and row["delist_filing_form"].startswith("25-NSE")


def _successor_registration(row: Mapping[str, str], reading: ContinuationReading) -> bool:
    """B: a continuation whose reason names its successor registration, an 8-K12B or 8-K12G3, and whose registrant's
    own filings do not state another ratio or cash (`reading.doubt`)."""
    return is_continuation(row) and names_successor_registration(row["reason"]) and not reading.doubt


def _issuer_by_form25(row: Mapping[str, str], issuer_cik: str, named: bool = False) -> bool:
    """C: the row's own Form 25 was read from the security's issuer CIK and the observed name agreed. `named`: every
    seed of the security carries an observed name (`member_name_mismatch` is raised only against one)."""
    return (named and _own_form25(row) and bool(issuer_cik) and row["cik"] == issuer_cik
            and "member_name_mismatch" not in flag_names(row))


def _close_age(row: Mapping[str, str]) -> int:
    """The last close's age in trading days (`ftd_close_prior:<n>`), 0 for a close of the day after the last trade."""
    for t in flag_tokens(row):
        if flag_name(t) == "ftd_close_prior" and flag_detail(t).isdecimal():
            return int(flag_detail(t))
    return 0


def _number(text: str) -> float | None:
    try:
        v = float(text)
    except ValueError:
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _near_stale_close(row: Mapping[str, str], name: str, detail: str, age: int) -> bool:
    """D: a gate that compared the terms with a stale close, within the tolerance the close's age widens: the payout
    it names (or the row's terminal value) against the close. A failure past it is the terms' (AT's Series D misread,
    481.37 against about 71)."""
    if name == TERMS_GATE_SKIPPED or not (name == PAYOUT_GATE_FAILED or detail in _COMPARED):
        return False
    value = _number(detail) if name == PAYOUT_GATE_FAILED else None
    value = value if value is not None else _number(row.get("terminal_value", ""))
    close = _number(row.get("last_trade_close", ""))
    if value is None or close is None or close <= 0:
        return False
    return abs(value / close - 1) <= STALE_TOL_BASE + STALE_TOL_PER_DAY * age


def _named_acquirer(row: Mapping[str, str]) -> bool:
    """The row names its acquirer: a ticker that is not blank or a NULL-like word (GRUB 2021's "NULL" is a missing
    ticker in disguise)."""
    return row.get("acquirer_ticker", "").strip().upper() not in _NO_TICKER


def _unpriced_gate(row: Mapping[str, str]) -> bool:
    """D: every failed gate on the row (`exit_kind.GATE_FLAGS`) failed on the price side; False when none failed,
    and False whenever any such token is not price-side, a skipped gate (`TERMS_GATE_SKIPPED`) included."""
    failed = [(flag_name(t), flag_detail(t)) for t in flag_tokens(row) if flag_name(t) in GATE_FLAGS]
    if not failed:
        return False
    age = _close_age(row)
    stale = age > STALE_CLOSE_DAYS
    named = _named_acquirer(row)
    return all((detail == "no_acq_price" and name != TERMS_GATE_SKIPPED and named)
               or (stale and _near_stale_close(row, name, detail, age))
               for name, detail in failed)


def _doubted_ending(row: Mapping[str, str]) -> bool:
    """E's guard: a doubt the row itself carries that its own reasons do not raise: a text and a measured last-trade
    day that disagree (FRK 2007: the halt day against the NYSE notice's), or a merger whose terms are one share and
    no cash (MEL 2007: R1's continuation, published as a merger)."""
    if CONFLICT in flag_names(row):
        return True
    ratio, cash = _number(row.get("stock_ratio", "")), _number(row.get("payout_per_share", "")) or 0.0
    return row.get("bucket") == "merger" and ratio is not None and abs(ratio - 1.0) < 1e-6 and cash == 0.0


def _within_days(as_of: str, ending: Mapping[str, str]) -> bool:
    """`as_of` falls within STALE_SEED_DAYS after the ending's end day (`exit_kind.end_day_of`: its last trade date,
    else its delist date)."""
    try:
        return 0 <= (date.fromisoformat(as_of) - end_day_of(ending)).days <= STALE_SEED_DAYS
    except ValueError:
        return False


def _stale_seed(status: str, last_ending: Mapping[str, str] | None, settled: bool, as_of: str = "") -> bool:
    """E: an after-delisting introduction that does not count against its security. `settled`: the last ending's
    own reasons, the security's set aside, are none; `as_of`: the seed's date, within STALE_SEED_DAYS of the
    ending's last trade (a later era on a recycled ticker is no stale snapshot)."""
    return (status == "after_delisting" and last_ending is not None and settled and as_of != ""
            and not is_continuation(last_ending) and _own_form25(last_ending) and not _doubted_ending(last_ending)
            and _within_days(as_of, last_ending))


def _closed_without_ending(security: Mapping[str, str], intervals: Sequence[Mapping[str, str]],
                           endings: Sequence[Mapping[str, str]]) -> str:
    """F: `closed_no_event:<last interval end>` for an observed security whose intervals are all closed and that has
    no real ending, else ""."""
    if security.get("observed") != "true" or not intervals or any(not r["valid_to"] for r in intervals):
        return ""
    if any(is_real_ending(r) for r in endings):
        return ""
    return f"closed_no_event:{max(r['valid_to'] for r in intervals)}"


# -- the verdicts ---------------------------------------------------------------------------------------------------
def _security_verdicts(tables: RunSnapshot, evidence: Mapping[str, str],
                       settled: Mapping[str, tuple[Mapping[str, str], bool]] | None = None) -> dict[str, Verdict]:
    """`settled`: each security's last real ending and whether that ending's own reasons are none (`decide`), for
    ruling E (`_stale_seed`)."""
    settled = settled or {}
    intervals: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.ticker_history:
        intervals[r["sec_id"]].append(r)
    endings: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.delistings:
        endings[r["sec_id"]].append(r)
    linked = {frozenset((r["sec_id"], other)) for r in tables.delistings
              for other in (r["successor_sec_id"], r["ticker_successor_sec_id"]) if other and other != r["sec_id"]}
    overlaps: dict[str, dict[str, str]] = defaultdict(dict)          # sec_id -> {other sec_id: ticker}
    by_ticker: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.ticker_history:
        by_ticker[r["ticker"]].append(r)
    for ticker, rows in by_ticker.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["sec_id"] == b["sec_id"] or frozenset((a["sec_id"], b["sec_id"])) in linked:
                    continue
                if a["valid_from"] <= (b["valid_to"] or "9999-12-31") and b["valid_from"] <= (a["valid_to"] or "9999-12-31"):
                    overlaps[a["sec_id"]][b["sec_id"]] = ticker
                    overlaps[b["sec_id"]][a["sec_id"]] = ticker
    outside: dict[str, list[str]] = defaultdict(list)       # introductions outside the security's history
    for r in tables.observation_map:
        if r["sec_id"] and is_introduction(r) and not _covered(intervals[r["sec_id"]], r["as_of"]) \
                and not _stale_seed(r["status"], *settled.get(r["sec_id"], (None, False)), r["as_of"]):
            outside[r["sec_id"]].append(r["as_of"])
    out: dict[str, Verdict] = {}
    for s in tables.securities:
        sid, reasons = s["sec_id"], []
        if s["figi_source"] == "placeholder" and not evidence.get(sid):
            reasons.append(f"placeholder_without_ticker_filing:CIK {s['issuer_cik']}")
        if outside[sid]:
            reasons.append(f"seeds_outside_history:{len(outside[sid])} from {min(outside[sid])}")
        reasons += [f"ticker_overlap:{ticker}" for ticker in sorted(set(overlaps[sid].values()))]
        if closed := _closed_without_ending(s, intervals[sid], endings[sid]):
            reasons.append(closed)
        out[sid] = Verdict(tuple(reasons), tuple(sorted(overlaps[sid])))
    return out


def _own_reasons(row: Mapping[str, str], issuer_cik: str = "", reading: ContinuationReading = ContinuationReading(),
                 named: bool = False) -> list[str]:
    """An ending's reasons, its security's set aside. `issuer_cik`: its security's issuer (securities.csv); `named`:
    every seed of the security carries an observed name; `reading`: what stage 9g read for a continuation (the
    filing that confirms it, `continuation_evidence.confirming_filing`, or the registrant's own ratio that
    contradicts its successor registration)."""
    flags = flag_names(row)
    confirmed = bool(reading.filing) and is_continuation(row)
    reasons = []
    if is_continuation(row) and reading.doubt:
        reasons.append(f"continuation_not_one_for_one:{reading.doubt}")
    if "resolved_by_current_ticker_map" in flags and not _issuer_by_form25(row, issuer_cik, named):
        reasons.append("issuer_from_todays_ticker_map")
    if rests_on_continued_filings(row["reason"]) and not confirmed:
        reasons.append("continued_filings_rule")
    if resolved_from_continued_filings(row["reason"]) and not _settles_relabel(row) \
            and not _successor_registration(row, reading):
        reasons.append("resolved_from_continued_filings")
    if "no_evidence_default" in flags:          # no continuation carries it (`rewrites.continuation` drops it)
        reasons.append("no_evidence_default")
    if not ending_fields(row).exit_kind:
        reasons.append("unknown_exit_kind")
    if row["dlret_method"] == "assumed_par" and flags & GATE_FLAGS and not _unpriced_gate(row):
        reasons.append("assumed_par_after_failed_gate")
    if is_continuation(row):
        if linked_by_timing(row["reason"]) and not confirmed:
            reasons.append("continuation_by_timing_only")
        return reasons
    # the row's last trade read back (`exit_kind.of_row`): each part of `LastTrade.publishable` that fails is a
    # reason of its own
    lt = of_row(row)
    if lt.day is None:
        reasons.append("no_last_trade_date")
        return reasons
    if lt.source not in EXCHANGE_PRINTS:
        reasons.append(f"last_trade_not_exchange_print:{lt.source or 'none'}")
    if not lt.confirmed:
        reasons.append("last_trade_date_unconfirmed")
    if CONFLICT in flags and lt.source not in MEASURED:
        reasons.append("last_trade_date_text_conflict")
    effective = effective_of(row)
    if effective is not None and lt.day > effective:
        reasons.append(f"last_trade_after_form25_effective:{effective.isoformat()}")
    return reasons


def _seed_reasons(row: Mapping[str, str], covered: bool, names_on_day: int,
                  security: Verdict | None) -> list[str]:
    if not row["sec_id"]:
        return ["not_placed"]
    reasons = []
    if names_on_day > 1:
        reasons.append("seen_under_two_names")
    if not covered:
        reasons.append("outside_security_history")
    if security is None or not security.confirmed:
        reasons.append(SECURITY_UNCERTAIN)
    return reasons


@dataclass(frozen=True)
class Verdicts:
    tables: RunSnapshot
    securities: Mapping[str, Verdict]
    endings: Mapping[tuple[str, str], Verdict]          # (sec_id, delist_date)
    seeds: Mapping[tuple[str, str, str, str, str, str], Verdict]   # observation_map's key

    def counts(self) -> dict[str, int]:
        """Uncertain verdicts per kind, the listed and the unlisted alike."""
        return {kind: sum(not v.confirmed for v in verdicts.values())
                for kind, verdicts in ((SEED, self.seeds), (SECURITY, self.securities), (ENDING, self.endings))}

    def uncertain_rows(self) -> list[dict[str, str]]:
        """uncertain.csv's rows (UNCERTAIN_COLUMNS), one per uncertain security
        and ending and per seed with a reason of its own; seeds that share a
        (ticker, date, sec_id) are one row."""
        latest: dict[str, str] = {}
        first: dict[str, str] = {}
        for r in sorted(self.tables.ticker_history, key=lambda r: r["valid_from"]):
            latest[r["sec_id"]] = r["ticker"]
            first.setdefault(r["sec_id"], r["valid_from"])
        rows: dict[tuple[str, str, str, str], dict[str, str]] = {}

        def add(kind: str, ticker: str, sec_id: str, day: str, v: Verdict) -> None:
            key = (kind, sec_id, day, ticker)
            row = rows.setdefault(key, {"kind": kind, "ticker": ticker, "sec_id": sec_id, "date": day,
                                        "reason": "", "candidates": ""})
            reasons = [x for x in row["reason"].split(";") if x]
            cands = [x for x in row["candidates"].split(";") if x]
            reasons += [x for x in v.reasons if x not in reasons]
            cands += [x for x in v.candidates if x not in cands]
            row["reason"], row["candidates"] = ";".join(reasons), ";".join(cands)

        for sid, v in self.securities.items():
            if not v.confirmed:
                add(SECURITY, latest.get(sid, ""), sid, first.get(sid, ""), v)
        rows_by_key = {(r["sec_id"], r["delist_date"]): r for r in self.tables.delistings}
        for key, v in self.endings.items():
            if not v.confirmed:
                add(ENDING, rows_by_key[key]["ticker"] or latest.get(key[0], ""), key[0], key[1], v)
        seed_sec = {seed_key(r): r["sec_id"] for r in self.tables.observation_map}
        for key, v in self.seeds.items():
            own = tuple(x for x in v.reasons if x != SECURITY_UNCERTAIN)
            if own:
                add(SEED, key[0], seed_sec[key], key[1], Verdict(own, v.candidates))
        return [rows[k] for k in sorted(rows)]


def seed_key(r: Mapping[str, str]) -> tuple[str, str, str, str, str, str]:
    return (r["ticker"], r["as_of"], r["name"], r["cusip"], r["pin_cik"], r["pin_sec_id"])


def decide(tables: RunSnapshot, evidence: Mapping[str, str]) -> Verdicts:
    """Every verdict of one run (`tables`, its snapshot). `evidence` maps a placeholder's sec_id
    to what ties its ticker to its CIK (`ticker_evidence.evidence_for`); a
    placeholder missing from it, or mapped to "", has none. The snapshot's
    `continuations` give what stage 9g read for each continuation, by (sec_id, delist_date)
    (`exit_kind.ContinuationReading`: the filing that confirms it, or the doubt its
    registrant's own filings raise); a key missing from them has none."""
    continuations = tables.continuations
    issuers = {s["sec_id"]: s["issuer_cik"] for s in tables.securities}
    seeds_of: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.observation_map:
        if r["sec_id"]:
            seeds_of[r["sec_id"]].append(r)
    named = {sid: all(r["name"].strip() for r in rows) for sid, rows in seeds_of.items()}
    real = [r for r in tables.delistings if is_real_ending(r)]
    last = last_endings(tables.delistings)
    # each ending's own reasons first: a security's stale seeds count only while its last ending is unsettled
    own = {(r["sec_id"], r["delist_date"]): _own_reasons(r, issuers.get(r["sec_id"], ""),
                                                          continuations.get((r["sec_id"], r["delist_date"]),
                                                                            ContinuationReading()),
                                                          named.get(r["sec_id"], False))
           for r in real}
    settled = {sid: (r, not own[(sid, r["delist_date"])]) for sid, r in last.items()}
    securities = _security_verdicts(tables, evidence, settled)
    endings = {}
    for r in real:
        security = securities.get(r["sec_id"])
        reasons = ([SECURITY_UNCERTAIN] if security is None or not security.confirmed else []) \
            + own[(r["sec_id"], r["delist_date"])]
        last_day = last[r["sec_id"]]["delist_date"]
        if r["delist_date"] != last_day:
            reasons.append(f"earlier_ending:{last_day}")
        endings[(r["sec_id"], r["delist_date"])] = Verdict(tuple(reasons))
    intervals: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.ticker_history:
        intervals[r["sec_id"]].append(r)
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    secs_on_day: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in tables.observation_map:
        names[(r["ticker"], r["as_of"])].add(r["name"])
        if r["sec_id"]:
            secs_on_day[(r["ticker"], r["as_of"])].add(r["sec_id"])
    seeds = {}
    for r in tables.observation_map:
        day = (r["ticker"], r["as_of"])
        reasons = _seed_reasons(r, _covered(intervals[r["sec_id"]], r["as_of"]) if r["sec_id"] else False,
                                len(names[day]), securities.get(r["sec_id"]))
        others = tuple(sorted(secs_on_day[day] - {r["sec_id"]})) if len(names[day]) > 1 else ()
        seeds[seed_key(r)] = Verdict(tuple(reasons), others)
    return Verdicts(tables, securities, endings, seeds)
