"""The scorecard: how far one run's tables are from the requirement (spec:
Delist Library Reset, Part 2's gap table), as one flat dict of numbers written
to `output/scorecard.json` on every run.

- L1/L2: lifecycle coverage and quality, per input ticker and per security
  (`lifecycle.LifecycleView`).
- R1.x/R2.x: the identity and delisting-return lines of the gap table.
- G.x: the golden set (`data/golden_lifecycles.csv`), A.x: the accuracy audit
  (`data/accuracy_audit.csv`), both judged by `truth.judge`.

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
from .lifecycle import (CLOSED_NO_EVENT, CONTINUED_FILINGS, DISTRESS, ENDED_INCOMPLETE, EXCHANGE_PRINT_SOURCES,
                        HIGH, LEFT_VIEW, LOW, MEDIUM, NO_INTERVAL,
                        NO_MAPPED_SIGHTING, LifecycleView, Tables, flag_names)
from .truth import KNOWN_WRONG, PASS, TruthCase, clopper_pearson_upper, judge_all, load_truth

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
    "R2.5.distress_blank_dlret": DOWN, "R2.5.distress_no_last_trade_date": DOWN,
    "R2.6.distress_flagged": DOWN,
    "G.pass": UP,
    "A.random.upper95": DOWN,
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


def load_config(path: str | Path) -> ScorecardConfig:
    """data/scorecard.json: {"window": {"start", "end"} | null, "floor": {metric: number},
    "golden": file, "audit": file} (the two truth files relative to the config's
    folder; a missing truth file means no cases). Raises ScorecardConfigError or
    truth.TruthFileError."""
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
    unknown = set(raw) - {"window", "floor", "golden", "audit"}
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
    return ScorecardConfig(window, dict(floor), cases("golden"), cases("audit"))


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


def _identity_lines(tables: Tables) -> dict[str, float]:
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


def _ending_lines(tables: Tables, window: Window | None) -> dict[str, float]:
    real = [r for r in tables.delistings if r["successor_sec_id"] != r["sec_id"]]
    inw = (lambda r: window.contains(r["delist_date"])) if window else None
    xfer = [r for r in real if r["bucket"] == "exchange_transfer" and not r["successor_sec_id"]]
    missing_ltd = [r for r in real if not r["last_trade_date"]]
    blank = [r for r in real if not r["dlret"]]
    distress = [r for r in real if r["bucket"] in DISTRESS]
    out: dict[str, float] = {
        "R1.3.transfer_no_successor": len(xfer),
        "R1.3.transfer_no_successor_placeholder": sum(r["sec_id"].startswith("CIK") for r in xfer),
        "R2.endings": len(real),
        "R2.1.with_last_trade_date": len(real) - len(missing_ltd),
        "R2.1.missing_last_trade_date": len(missing_ltd),
        "R2.1.exchange_print_source": sum(r["last_trade_date_source"] in EXCHANGE_PRINT_SOURCES for r in real),
        "R2.2.unknown_reason": sum(r["bucket"] == "unknown" for r in real),
        "R2.2.continued_filings_rule": sum(r["reason"].startswith(CONTINUED_FILINGS) for r in real),
        "R2.4.assumed_par": sum(r["dlret_method"] == "assumed_par" for r in real),
        "R2.5.distress": len(distress),
        "R2.5.distress_blank_dlret": sum(not r["dlret"] for r in distress),
        "R2.5.distress_no_last_trade_date": sum(not r["last_trade_date"] for r in distress),
        "R2.6.distress_flagged": sum(bool(flag_names(r)) for r in distress),
        "R2.6.distress_date_flagged": sum(bool(flag_names(r) & {"last_trade_date_conflict",
                                                                  "last_trade_date_unconfirmed"}) for r in distress),
        "R2.6.distress_ticker_map": sum("resolved_by_current_ticker_map" in flag_names(r) for r in distress),
        "R2.6.distress_normal_price": sum("distress_at_normal_price" in flag_names(r) for r in distress),
    }
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


def _truth_lines(view: LifecycleView, config: ScorecardConfig) -> dict[str, float]:
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
    return out


def build(tables: Tables, *, as_of: date, config: ScorecardConfig = ScorecardConfig()) -> dict:
    """The scorecard of one run's tables: {"as_of", "window", "metrics", "golden_failures"}."""
    view = LifecycleView(tables)
    metrics = {**_lifecycle_lines(view), **_identity_lines(tables), **_ending_lines(tables, config.window),
               **_truth_lines(view, config)}
    failures = [f"{j.case.case}: {'; '.join(j.mismatches)}" for j in judge_all(config.golden, view)
                if j.case.status == PASS and not j.ok]
    window = None if config.window is None else {"start": config.window.start, "end": config.window.end}
    return {"as_of": as_of.isoformat(), "window": window, "metrics": metrics, "golden_failures": failures}


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
