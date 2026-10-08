"""The scorecard: how far one run's tables are from the requirement (spec:
Delist Library Reset, Part 2's gap table), as one flat dict of numbers written
to `output/scorecard.json` on every run.

- L1/L2: lifecycle coverage and quality, per input ticker and per security
  (`lifecycle.LifecycleView`).
- R1.x/R2.x: the identity and delisting-return lines of the gap table.
- G.x: the golden set (`data/golden_lifecycles.csv`), A.x: the accuracy audit
  (`data/accuracy_audit.csv`), both judged by `truth.judge`.
- D.x: the diagnosis truth set (`data/diagnosis_truth.csv`, spec 2026-10-03-diagnosis-truth-fixes),
  judged by `diagnosis_truth.judge_case` against contract/delistings.csv and contract/payout_legs.csv.

Every line reads one run snapshot (`run_snapshot.RunSnapshot`): the pipeline's stage 10h builds it from the rows it
is about to write, scripts/scorecard.py and the floor test from the written folder, so they agree by construction.

`METRICS` gives each floored number its good direction. `drops` compares a
scorecard to the floor in `data/scorecard.json` (a number that moved the bad
way), `raise_floor` moves the floor up to a better scorecard. Window lines
(`*_in_window`) are computed only when the config names the caller's training
window. Pure, apart from `write` and `load_config`.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .atomic_io import write_atomic
from .lifecycle import (CLOSED_NO_EVENT, ENDED_INCOMPLETE,
                        HIGH, LEFT_VIEW, LOW, MEDIUM, NO_INTERVAL,
                        NO_MAPPED_SIGHTING, Lifecycle, LifecycleView)
from .diagnosis_truth import (KNOWN_WRONG as D_KNOWN_WRONG, MISMATCH_FIELDS, PASS as D_PASS, RULING_PENDING,
                              DiagnosisCase, LibraryRows, field_key, judge_all as judge_diagnosis)
from .exit_kind import (CONFLICT, EXCHANGE_PRINTS, UNCONFIRMED, VALUE_RULES, ending_fields, flag_names, is_distress,
                        is_real_ending, rests_on_continued_filings)
from .run_snapshot import RunSnapshot
from .truth import KNOWN_WRONG, PASS, TruthCase, clopper_pearson_upper, judge_all, load_truth
from .truth_set import TruthSet, truth_file_of
from .verdict import ENDING, SECURITY, SEED

SCORECARD_NAME = "scorecard.json"
UP, DOWN = "up", "down"
CENSUS_GROUPS = ("distress", "continuation", "left_view", "blank_no_value", "assumed_par")

# Every floored number and the direction that is better. A number not listed
# here is reported but never floored.
METRICS: dict[str, str] = {
    "L1.coverage_tickers": UP, "L1.coverage_securities": UP,
    "L1.left_view": DOWN, "L1.ended_incomplete": DOWN, "L1.closed_no_event": DOWN, "L1.no_interval": DOWN,
    "L1.no_mapped_sighting": DOWN,
    "L2.high_share": UP, "L2.low": DOWN,
    "R1.1.mapped_share": UP,
    "R1.2.cusip_share": UP, "R1.2.ticker_only": DOWN, "R1.2.placeholder": DOWN, "R1.2.figi_without_cik": DOWN,
    "R1.3.transfer_no_successor": DOWN,
    "R1.4.review_rows": DOWN,
    "R2.1.missing_last_trade_date": DOWN, "R2.1.missing_last_trade_date_in_window": DOWN,
    "R2.2.unknown_reason": DOWN, "R2.2.continued_filings_rule": DOWN,
    "R2.3.blank_dlret_in_window": DOWN, "R2.3.blank_no_value_in_window": DOWN,
    "R2.4.assumed_par": DOWN,
    "R2.7.payout_rule_known": UP,
    "R2.5.distress_blank_dlret": DOWN, "R2.5.distress_no_last_trade_date": DOWN,
    "R2.6.distress_flagged": DOWN,
    "G.pass": UP,
    "D.mismatches": DOWN, "D.cases_matching": UP, "D.ruling_pending": DOWN,
    **{f"D.mismatches.{f}": DOWN for f in MISMATCH_FIELDS},
    "A.random.upper95": DOWN,
    "V.uncertain_seeds": DOWN, "V.uncertain_securities": DOWN, "V.uncertain_endings": DOWN,
    "V.uncertain_endings_in_window": DOWN, "V.uncertain_distress": DOWN, "V.uncertain_input_tickers_share": DOWN,
    "V.audit.confirmed_but_wrong": DOWN,
    **{f"A.census.{g}.errors": DOWN for g in CENSUS_GROUPS},
}


class ScorecardConfigError(ValueError):
    """data/scorecard.json cannot be read; the message names the file."""


@dataclass(frozen=True)
class Window:
    start: str          # ISO dates, inclusive
    end: str

    def contains(self, iso: str) -> bool:
        return bool(iso) and self.start <= iso <= self.end


@dataclass(frozen=True)
class ScorecardConfig:
    window: Window | None = None
    floor: Mapping[str, float] = field(default_factory=dict)
    golden: Sequence[TruthCase] = ()
    audit: Sequence[TruthCase] = ()
    diagnosis: Sequence[DiagnosisCase] = ()


def load_config(path: str | Path) -> ScorecardConfig:
    """data/scorecard.json: {"window": {"start", "end"} | null, "floor": {metric: number},
    "golden": file, "audit": file, "diagnosis": file} (the truth files relative to the config's folder; a missing
    truth file means no cases). The diagnosis truth set is read whole (`truth_set.TruthSet`): its legs and change
    log are named after the truth file, and a "diagnosis_legs" entry must name that legs file
    (`truth_set.truth_file_of`). Raises ScorecardConfigError or truth.TruthFileError."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ScorecardConfigError(f"{path}: not JSON ({exc})") from None
    if not isinstance(raw, dict):
        raise ScorecardConfigError(f"{path}: the top level is not an object")
    for key in ("window", "floor"):
        if raw.get(key) is not None and not isinstance(raw[key], dict):
            raise ScorecardConfigError(f"{path}: {key} must be an object")
    unknown = set(raw) - {"window", "floor", "golden", "audit", "diagnosis", "diagnosis_legs"}
    if unknown:
        raise ScorecardConfigError(f"{path}: unknown key(s) {sorted(unknown)}")
    window = None
    if raw.get("window"):
        w = raw["window"]
        try:
            start, end = date.fromisoformat(w["start"]).isoformat(), date.fromisoformat(w["end"]).isoformat()
        except (KeyError, TypeError, ValueError):
            raise ScorecardConfigError(f"{path}: window needs start and end as YYYY-MM-DD") from None
        if start > end:
            raise ScorecardConfigError(f"{path}: window starts after it ends")
        window = Window(start, end)
    floor = raw.get("floor") or {}
    bad = sorted(k for k, v in floor.items() if k not in METRICS or isinstance(v, bool) or not isinstance(v, (int, float)))
    if bad:
        raise ScorecardConfigError(f"{path}: floor entries {bad} are not floored metrics with a number")

    def cases(key: str) -> list[TruthCase]:
        name = raw.get(key)
        if not name:
            return []
        p = path.parent / name
        return load_truth(p, allow_pending=(key == "audit")) if p.exists() else []

    truth = truth_file_of(raw, path.parent, str(path))
    diagnosis = TruthSet.open(truth).cases if truth is not None and truth.exists() else []
    return ScorecardConfig(window, dict(floor), cases("golden"), cases("audit"), diagnosis)


def _share(n: int, d: int) -> float:
    return round(n / d, 6) if d else 0.0


def _lifecycle_lines(view: LifecycleView) -> dict[str, float]:
    by_ticker, by_security = view.by_input_ticker(), view.by_security()
    kinds_s = Counter(lc.kind for lc in by_security.values())
    kinds_t = Counter(lc.kind for lc in by_ticker.values())
    covered_t = sum(lc.covered for lc in by_ticker.values())
    covered_s = sum(lc.covered for lc in by_security.values())
    grades = Counter(lc.quality for lc in by_ticker.values() if lc.covered)
    out = {
        "L1.tickers": len(by_ticker), "L1.tickers_covered": covered_t,
        "L1.coverage_tickers": _share(covered_t, len(by_ticker)),
        "L1.securities": len(by_security), "L1.securities_covered": covered_s,
        "L1.coverage_securities": _share(covered_s, len(by_security)),
        "L1.left_view": kinds_s[LEFT_VIEW], "L1.ended_incomplete": kinds_s[ENDED_INCOMPLETE],
        "L1.closed_no_event": kinds_s[CLOSED_NO_EVENT], "L1.no_interval": kinds_s[NO_INTERVAL],
        "L1.no_mapped_sighting": kinds_t[NO_MAPPED_SIGHTING],
        "L2.high": grades[HIGH], "L2.medium": grades[MEDIUM], "L2.low": grades[LOW],
        "L2.high_share": _share(grades[HIGH], covered_t),
    }
    return out


def _identity_lines(tables: RunSnapshot) -> dict[str, float]:
    statuses = Counter(r["status"] for r in tables.observation_map)
    n_obs = len(tables.observation_map)
    observed = [r for r in tables.securities if r.get("observed") == "true"]
    sources = Counter(r["figi_source"] for r in observed)
    no_cik = sum(1 for r in observed if r["figi_source"] != "placeholder" and not r["issuer_cik"])
    out: dict[str, float] = {
        "R1.1.sightings": n_obs, "R1.1.mapped": statuses["mapped"],
        "R1.1.mapped_share": _share(statuses["mapped"], n_obs),
        **{f"R1.1.status.{s}": n for s, n in sorted(statuses.items())},
        "R1.2.securities": len(observed), "R1.2.cusip": sources["cusip"],
        "R1.2.cusip_share": _share(sources["cusip"], len(observed)),
        "R1.2.ticker_only": sources["ticker"], "R1.2.placeholder": sources["placeholder"],
        "R1.2.figi_without_cik": no_cik,
        "R1.4.review_rows": len(tables.review),
        "R1.4.review_securities": len({r["sec_id"] for r in tables.review if r["sec_id"]}),
    }
    return out


def _ending_lines(tables: RunSnapshot, window: Window | None) -> dict[str, float]:
    real = [r for r in tables.delistings if is_real_ending(r)]
    inw = (lambda r: window.contains(r["delist_date"])) if window else None
    fields = {id(r): ending_fields(r) for r in real}
    xfer = [r for r in real if fields[id(r)].exit_kind == "exchange" and not fields[id(r)].continuation]
    missing_ltd = [r for r in real if not r["last_trade_date"]]
    blank = [r for r in real if not r["dlret"]]
    distress = [r for r in real if is_distress(r)]
    out: dict[str, float] = {
        "R1.3.transfer_no_successor": len(xfer),
        "R1.3.transfer_no_successor_placeholder": sum(r["sec_id"].startswith("CIK") for r in xfer),
        "R2.endings": len(real),
        "R2.1.with_last_trade_date": len(real) - len(missing_ltd),
        "R2.1.missing_last_trade_date": len(missing_ltd),
        "R2.1.exchange_print_source": sum(r["last_trade_date_source"] in EXCHANGE_PRINTS for r in real),
        "R2.2.unknown_reason": sum(not fields[id(r)].exit_kind for r in real),
        "R2.2.continued_filings_rule": sum(rests_on_continued_filings(r["reason"]) for r in real),
        "R2.4.assumed_par": sum(r["dlret_method"] == "assumed_par" for r in real),
        "R2.5.distress": len(distress),
        "R2.5.distress_blank_dlret": sum(not r["dlret"] for r in distress),
        "R2.5.distress_no_last_trade_date": sum(not r["last_trade_date"] for r in distress),
        "R2.6.distress_flagged": sum(bool(flag_names(r)) for r in distress),
        "R2.6.distress_date_flagged": sum(bool(flag_names(r) & {CONFLICT, UNCONFIRMED}) for r in distress),
        "R2.6.distress_ticker_map": sum("resolved_by_current_ticker_map" in flag_names(r) for r in distress),
        "R2.6.distress_normal_price": sum("distress_at_normal_price" in flag_names(r) for r in distress),
    }
    if tables.contract_delistings is not None:
        counts = Counter(r["value_rule"] for r in tables.contract_delistings)
        out.update({f"R2.7.value_rule.{rule}": counts.get(rule, 0) for rule in sorted(VALUE_RULES)})
        out["R2.7.payout_rule_known"] = len(tables.contract_delistings) - counts.get("unknown", 0)
    if inw is not None:
        blank_w = [r for r in blank if inw(r)]
        out.update({
            "R2.1.missing_last_trade_date_in_window": sum(inw(r) for r in missing_ltd),
            "R2.3.blank_dlret_in_window": len(blank_w),
            "R2.3.blank_needs_last_close_in_window": sum(r["dlret_method"] == "needs_last_trade" for r in blank_w),
            "R2.3.blank_no_value_in_window": sum(r["dlret_method"] != "needs_last_trade" for r in blank_w),
            "R2.4.assumed_par_in_window": sum(r["dlret_method"] == "assumed_par" and inw(r) for r in real),
            "R2.5.distress_in_window": sum(inw(r) for r in distress),
        })
    return out


@dataclass(frozen=True)
class _Uncertain:
    """uncertain.csv's rows as look-ups."""
    seeds: int
    securities: frozenset[str]
    endings: frozenset[tuple[str, str]]          # (sec_id, delist_date)

    @classmethod
    def of(cls, rows: Sequence[Mapping[str, str]]) -> _Uncertain:
        return cls(sum(r["kind"] == SEED for r in rows),
                   frozenset(r["sec_id"] for r in rows if r["kind"] == SECURITY),
                   frozenset((r["sec_id"], r["date"]) for r in rows if r["kind"] == ENDING))

    def touches(self, lc: Lifecycle) -> bool:
        """A lifecycle whose chain holds an uncertain security, or whose final
        ending is uncertain."""
        if set(lc.chain) & self.securities:
            return True
        return lc.final is not None and (lc.final["sec_id"], lc.final["delist_date"]) in self.endings


def _verdict_lines(tables: RunSnapshot, view: LifecycleView, window: Window | None,
                   unc: _Uncertain | None) -> dict[str, float]:
    """The V lines, from uncertain.csv; none when the run wrote no uncertain.csv."""
    if unc is None:
        return {}
    distress = {(r["sec_id"], r["delist_date"]) for r in tables.delistings if is_distress(r)}
    by_ticker = view.by_input_ticker()
    tickers = sum(lc.kind == NO_MAPPED_SIGHTING or unc.touches(lc) for lc in by_ticker.values())
    out: dict[str, float] = {
        "V.uncertain_seeds": unc.seeds, "V.uncertain_securities": len(unc.securities),
        "V.uncertain_endings": len(unc.endings), "V.uncertain_distress": len(unc.endings & distress),
        "V.uncertain_input_tickers": tickers, "V.uncertain_input_tickers_share": _share(tickers, len(by_ticker)),
    }
    if window is not None:
        out["V.uncertain_endings_in_window"] = sum(window.contains(day) for _, day in unc.endings)
    return out


def _audited_uncertain(case: TruthCase, view: LifecycleView, unc: _Uncertain) -> bool:
    sec = view.security_on(case.ticker, case.on)
    return sec is None or unc.touches(view.lifecycle(sec))


def _truth_lines(view: LifecycleView, config: ScorecardConfig, unc: _Uncertain | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    golden = judge_all(config.golden, view)
    if golden:
        out["G.cases"] = len(golden)
        out["G.pass"] = sum(j.ok for j in golden if j.case.status == PASS)
        out["G.pass_failing"] = sum(not j.ok for j in golden if j.case.status == PASS)
        out["G.known_wrong"] = sum(j.case.status == KNOWN_WRONG for j in golden)
        out["G.known_wrong_now_right"] = sum(j.ok for j in golden if j.case.status == KNOWN_WRONG)
    if config.audit:
        out["A.pending"] = sum(c.pending for c in config.audit)
    audit = judge_all([c for c in config.audit if not c.pending], view)
    if audit:
        rnd = [j for j in audit if j.case.group == "random"]
        errs = sum(not j.ok for j in rnd)
        out["A.random.n"], out["A.random.errors"] = len(rnd), errs
        out["A.random.upper95"] = round(clopper_pearson_upper(errs, len(rnd)), 6)
        for g in CENSUS_GROUPS:
            rows = [j for j in audit if j.case.group == f"census:{g}"]
            out[f"A.census.{g}.n"] = len(rows)
            out[f"A.census.{g}.errors"] = sum(not j.ok for j in rows)
        if unc is not None:
            out["V.audit.confirmed_but_wrong"] = sum(not j.ok and not _audited_uncertain(j.case, view, unc)
                                                     for j in audit)
    return out


def _diagnosis_lines(tables: RunSnapshot, config: ScorecardConfig) -> tuple[dict[str, float], list[str]]:
    """The D lines and the failing `pass` cases; none without a truth set or a contract with payout columns."""
    if not config.diagnosis or tables.contract_delistings is None:
        return {}, []
    judged = judge_diagnosis(config.diagnosis, LibraryRows.of(tables))
    counts = Counter(field_key(m.field) for j in judged for m in j.mismatches)
    out: dict[str, float] = {
        "D.cases": len(config.diagnosis),
        "D.ruling_pending": sum(c.status == RULING_PENDING for c in config.diagnosis),
        "D.known_wrong": sum(j.case.status == D_KNOWN_WRONG for j in judged),
        "D.known_wrong_now_right": sum(j.ok for j in judged if j.case.status == D_KNOWN_WRONG),
        "D.cases_matching": sum(j.ok for j in judged),
        "D.mismatches": sum(counts.values()),
        **{f"D.mismatches.{f}": counts.get(f, 0) for f in MISMATCH_FIELDS},
    }
    failures = [f"{j.case.case_id}: {'; '.join(map(str, j.mismatches))}" for j in judged
                if j.case.status == D_PASS and not j.ok]
    return out, failures


def build(tables: RunSnapshot, *, config: ScorecardConfig = ScorecardConfig()) -> dict:
    """The scorecard of one run (`tables`, its snapshot): {"as_of" (the run's date), "window", "metrics",
    "golden_failures", "diagnosis_failures"}."""
    view = LifecycleView(tables)
    unc = None if tables.uncertain is None else _Uncertain.of(tables.uncertain)
    diag, diag_failures = _diagnosis_lines(tables, config)
    metrics = {**_lifecycle_lines(view), **_identity_lines(tables), **_ending_lines(tables, config.window),
               **_verdict_lines(tables, view, config.window, unc), **_truth_lines(view, config, unc), **diag}
    failures = [f"{j.case.case}: {'; '.join(j.mismatches)}" for j in judge_all(config.golden, view)
                if j.case.status == PASS and not j.ok]
    window = None if config.window is None else {"start": config.window.start, "end": config.window.end}
    return {"as_of": tables.as_of.isoformat(), "window": window, "metrics": metrics, "golden_failures": failures,
            "diagnosis_failures": diag_failures}


def drops(card: Mapping, floor: Mapping[str, float]) -> list[str]:
    """Every floored metric that moved the bad way, as `name: floor -> now`
    (a floored metric the scorecard no longer has counts as a drop)."""
    out = []
    for name, bound in sorted(floor.items()):
        now = card["metrics"].get(name)
        if now is None or (METRICS[name] == UP and now < bound) or (METRICS[name] == DOWN and now > bound):
            out.append(f"{name}: {bound} -> {now}")
    return out


def raise_floor(card: Mapping, floor: Mapping[str, float]) -> dict[str, float]:
    """The floor moved to every better number in `card`; a floored metric
    never moves the bad way. Metrics new to the floor enter at their value."""
    out = dict(floor)
    for name, direction in METRICS.items():
        now = card["metrics"].get(name)
        if now is None:
            continue
        if name not in out:
            out[name] = now
        else:
            out[name] = max(out[name], now) if direction == UP else min(out[name], now)
    return dict(sorted(out.items()))


def write(out_dir: str | Path, card: Mapping) -> Path:
    path = Path(out_dir) / SCORECARD_NAME
    write_atomic(path, json.dumps(card, indent=2, sort_keys=True) + "\n")
    return path
