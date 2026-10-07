"""One verdict per seed, security and ending: confirmed, or uncertain with its
reasons (spec: Delist Library Reset, Part 3 "Invariants the library's build
enforces"; decisions 1, 4 and 9).

- A security is confirmed when its identity rests on a FIGI, or, for a
  placeholder (a CIK and class with no FIGI), on a filing that ties its
  ticker to that CIK (decision 1; `ticker_evidence`); when every seed
  resolved to it falls inside its ticker history; and when no other security
  holds one of its tickers over an overlapping date range, unless an ending
  of one hands the ticker to the other. A seed past the history after a
  settled last ending (`verdict_rules.stale_seed`: not one whose row carries a last-trade conflict or
  one-for-one merger terms, and within a year of its last trade) does not count, and an
  observed security closed with no ending at all is uncertain
  (`verdict_rules.closed_without_ending`).
- An ending (a delistings.csv row whose successor is not the security itself)
  is confirmed when its security is confirmed, its issuer CIK did not come
  from today's ticker map, and its exit kind rests on a filing: not the
  continued-filings rule, not the no-evidence default, not unknown. An
  ending the end-of-era resolver relabelled from the continued-filings rule
  stays uncertain unless its own Form 25 settles a merger or its successor
  registration a continuation; today's ticker map stays a doubt unless the
  row's own Form 25 came from that CIK (the rulings of the diagnosis-truth
  spec's 2.3, `verdict_rules`). A
  continuation (a successor other than itself) must rest on a successor
  filing or a CUSIP switch, not on timing alone. Any other ending needs a
  last trade date from an exchange print (MIDAS, a Nasdaq halt, the
  exchange's notice, 8-K item 3.01) that is confirmed, that no other text
  source contradicts unless MIDAS or a halt measured it, and that falls no
  later than the Form 25's effective date. The value never decides the
  verdict, except assumed par after a failed payout, LLM or terms gate (decision 4)
  that did not fail on the price side alone (`verdict_rules.unpriced_gate`).
  An ending that is not its security's last (one that ended, returned and
  ended again) is uncertain, `earlier_ending:<the last one's delist_date>`: the
  contract keeps one ending per security (decision 12).
- A seed (an observation_map row) is confirmed when it has a sec_id, was
  seen under one name that day, falls inside one of its security's ticker
  intervals, and its security is confirmed.

`uncertain_rows` is uncertain.csv: every uncertain security and ending, and
every seed uncertain for a reason of its own; a seed whose only problem is
its security is counted, not listed. Each reason is `code` or `code:detail`.
Pure: reads the tables as store.read_table returns them, plus what pipeline stage 9g read from the registrant's own
filings for each continuation (`continuations`, recorded in run_manifest.json's `continuation_filings`): the one
input that is not a table, so an offline recompute from committed outputs alone gives APA, CMCSK and HHC no
confirmation and CHTR no ratio doubt.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from .end_of_era import CONTINUED_FILINGS, RESOLVED_FROM_CONTINUED_FILINGS
from .exit_kind import ending_fields, is_continuation, is_real_ending
from .lifecycle import EXCHANGE_PRINT_SOURCES, Tables, flag_names
from .verdict_rules import (Reading, closed_without_ending, issuer_by_form25, settles_relabel, stale_seed,
                            successor_registration, unpriced_gate)

SEED, SECURITY, ENDING = "seed", "security", "ending"
FORM25_EFFECTIVE_DAYS = 10               # a Form 25 takes effect 10 days after it is filed
MEASURED_SOURCES = frozenset({"midas", "nasdaq_halt"})
# decision 4's gates that did not pass, or (5f) could not check: the one set (`verdict_rules.unpriced_gate` takes it
# as an argument)
GATE_FAILED = frozenset({"payout_gate_failed", "llm_gate_failed", "terms_gate_failed", "terms_gate_skipped"})
SECURITY_UNCERTAIN = "security_uncertain"
CONFIRMED, UNCERTAIN = "confirmed", "uncertain"


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


def form25_effective(row: Mapping[str, str]) -> date | None:
    """The day a row's Form 25 takes effect (FORM25_EFFECTIVE_DAYS after it was
    filed), or None when the row cites no Form 25."""
    if row["delist_filing_date"] and row["delist_filing_form"].startswith("25"):
        return date.fromisoformat(row["delist_filing_date"]) + timedelta(days=FORM25_EFFECTIVE_DAYS)
    return None


def published_last_trade_date(row: Mapping[str, str]) -> str:
    """contract/delistings.csv's last_trade_date (decision 12): the row's date when
    an exchange print gave it and it is no later than the Form 25's effective
    date, else blank."""
    ltd = row["last_trade_date"]
    if not ltd or row["last_trade_date_source"] not in EXCHANGE_PRINT_SOURCES:
        return ""
    effective = form25_effective(row)
    return "" if effective is not None and date.fromisoformat(ltd) > effective else ltd


def _security_verdicts(tables: Tables, evidence: Mapping[str, str],
                       settled: Mapping[str, tuple[Mapping[str, str], bool]] | None = None) -> dict[str, Verdict]:
    """`settled`: each security's last real ending and whether that ending's own reasons are none (`decide`), for
    `verdict_rules.stale_seed`."""
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
                and not stale_seed(r["status"], *settled.get(r["sec_id"], (None, False)), r["as_of"]):
            outside[r["sec_id"]].append(r["as_of"])
    out: dict[str, Verdict] = {}
    for s in tables.securities:
        sid, reasons = s["sec_id"], []
        if s["figi_source"] == "placeholder" and not evidence.get(sid):
            reasons.append(f"placeholder_without_ticker_filing:CIK {s['issuer_cik']}")
        if outside[sid]:
            reasons.append(f"seeds_outside_history:{len(outside[sid])} from {min(outside[sid])}")
        reasons += [f"ticker_overlap:{ticker}" for ticker in sorted(set(overlaps[sid].values()))]
        if closed := closed_without_ending(s, intervals[sid], endings[sid]):
            reasons.append(closed)
        out[sid] = Verdict(tuple(reasons), tuple(sorted(overlaps[sid])))
    return out


def _own_reasons(row: Mapping[str, str], issuer_cik: str = "", reading: Reading = Reading(),
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
    if "resolved_by_current_ticker_map" in flags and not issuer_by_form25(row, issuer_cik, named):
        reasons.append("issuer_from_todays_ticker_map")
    if row["reason"].startswith(CONTINUED_FILINGS) and not confirmed:
        reasons.append("continued_filings_rule")
    if RESOLVED_FROM_CONTINUED_FILINGS in row["reason"] and not settles_relabel(row) \
            and not successor_registration(row, reading):
        reasons.append("resolved_from_continued_filings")
    if "no_evidence_default" in flags:          # no continuation carries it (`rewrites.continuation` drops it)
        reasons.append("no_evidence_default")
    if not ending_fields(row).exit_kind:
        reasons.append("unknown_exit_kind")
    if row["dlret_method"] == "assumed_par" and flags & GATE_FAILED and not unpriced_gate(row, GATE_FAILED):
        reasons.append("assumed_par_after_failed_gate")
    if is_continuation(row):
        if "(timing:cik)" in row["reason"] and not confirmed:
            reasons.append("continuation_by_timing_only")
        return reasons
    ltd, source = row["last_trade_date"], row["last_trade_date_source"]
    if not ltd:
        reasons.append("no_last_trade_date")
        return reasons
    if source not in EXCHANGE_PRINT_SOURCES:
        reasons.append(f"last_trade_not_exchange_print:{source or 'none'}")
    if "last_trade_date_unconfirmed" in flags:
        reasons.append("last_trade_date_unconfirmed")
    if "last_trade_date_conflict" in flags and source not in MEASURED_SOURCES:
        reasons.append("last_trade_date_text_conflict")
    effective = form25_effective(row)
    if effective is not None and date.fromisoformat(ltd) > effective:
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
    tables: Tables
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


def decide(tables: Tables, evidence: Mapping[str, str],
           continuations: Mapping[tuple[str, str], Reading | str] | None = None) -> Verdicts:
    """Every verdict of one run's tables. `evidence` maps a placeholder's sec_id
    to what ties its ticker to its CIK (`ticker_evidence.evidence_for`); a
    placeholder missing from it, or mapped to "", has none. `continuations`
    maps a continuation's (sec_id, delist_date) to what stage 9g read for it
    (`verdict_rules.Reading`: the filing that confirms it, or the doubt its
    registrant's own filings raise; a bare string is the confirming filing); a
    key missing from it has none."""
    continuations = {k: v if isinstance(v, Reading) else Reading(filing=v) for k, v in (continuations or {}).items()}
    issuers = {s["sec_id"]: s["issuer_cik"] for s in tables.securities}
    seeds_of: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for r in tables.observation_map:
        if r["sec_id"]:
            seeds_of[r["sec_id"]].append(r)
    named = {sid: all(r["name"].strip() for r in rows) for sid, rows in seeds_of.items()}
    real = [r for r in tables.delistings if is_real_ending(r)]
    last_of: dict[str, str] = {}
    for r in real:
        last_of[r["sec_id"]] = max(last_of.get(r["sec_id"], ""), r["delist_date"])
    # each ending's own reasons first: a security's stale seeds count only while its last ending is unsettled
    own = {(r["sec_id"], r["delist_date"]): _own_reasons(r, issuers.get(r["sec_id"], ""),
                                                          continuations.get((r["sec_id"], r["delist_date"]), Reading()),
                                                          named.get(r["sec_id"], False))
           for r in real}
    settled = {r["sec_id"]: (r, not own[(r["sec_id"], r["delist_date"])]) for r in real
               if r["delist_date"] == last_of[r["sec_id"]]}
    securities = _security_verdicts(tables, evidence, settled)
    endings = {}
    for r in real:
        security = securities.get(r["sec_id"])
        reasons = ([SECURITY_UNCERTAIN] if security is None or not security.confirmed else []) \
            + own[(r["sec_id"], r["delist_date"])]
        if r["delist_date"] != last_of[r["sec_id"]]:
            reasons.append(f"earlier_ending:{last_of[r['sec_id']]}")
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
