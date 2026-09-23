"""Caller observations: "ticker T was seen trading on date D", with the name,
CUSIP and any identity pins the caller knows.

Observations are the library's only view of the caller's universe. A ticker's
observations are split into eras: runs that belong to one security. A new era
starts after a long gap, when the name stops agreeing, or when a pin changes,
because a recycled ticker (MON = Monsanto, later Monument Circle) must never be
merged into one security.
"""
from __future__ import annotations

import csv
import re
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .names import names_agree

ERA_GAP_DAYS = 400
DATE_IN_NAME = r"(\d{4}-\d{2}-\d{2}|\d{8})"
OBS_COLUMNS = ("ticker", "as_of", "name", "cusip", "cik", "sec_id")


def normalize_ticker(raw: str) -> str:
    return re.sub(r"[./\s]+", "-", (raw or "").strip().upper()).strip("-")


@dataclass(frozen=True)
class Observation:
    ticker: str
    as_of: str
    name: str | None = None
    cusip: str | None = None
    cik: int | None = None
    sec_id: str | None = None


class ObservationError(ValueError):
    pass


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _iso(s: str) -> str | None:
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def load_observations(path: str | Path) -> list[Observation]:
    out: dict[Observation, None] = {}
    bad: list[str] = []
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        for need in ("ticker", "as_of"):
            if need not in cols:
                raise ObservationError(f"{path}: missing required column {need!r}; found {reader.fieldnames}")
        for lineno, row in enumerate(reader, start=2):
            get = lambda k: row.get(cols[k]) if k in cols else None
            ticker = normalize_ticker(get("ticker") or "")
            as_of = _iso(get("as_of") or "")
            cik_raw = _clean(get("cik"))
            if not ticker or as_of is None or (cik_raw is not None and not cik_raw.isdigit()):
                bad.append(f"line {lineno}")
                continue
            cusip = _clean(get("cusip"))
            out[Observation(
                ticker=ticker, as_of=as_of, name=_clean(get("name")),
                cusip=cusip.upper() if cusip else None,
                cik=int(cik_raw) if cik_raw else None, sec_id=_clean(get("sec_id")),
            )] = None
    if bad:
        raise ObservationError(f"{path}: bad observation rows: {', '.join(bad[:20])}")
    return list(out)


def write_observations(obs: Iterable[Observation], path: str | Path) -> int:
    rows = sorted(set(obs), key=lambda o: (o.ticker, o.as_of, o.name or "", o.cusip or ""))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OBS_COLUMNS)
        for o in rows:
            w.writerow([o.ticker, o.as_of, o.name or "", o.cusip or "", "" if o.cik is None else o.cik,
                        o.sec_id or ""])
    return len(rows)


@dataclass
class TickerEra:
    ticker: str
    first: str
    last: str
    observations: list[Observation] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys(o.name for o in self.observations if o.name))

    @property
    def name(self) -> str | None:
        named = [o.name for o in self.observations if o.name]
        return named[-1] if named else None

    @property
    def cusips(self) -> list[str]:
        return list(dict.fromkeys(o.cusip for o in reversed(self.observations) if o.cusip))

    @property
    def cik_pin(self) -> int | None:
        return next((o.cik for o in reversed(self.observations) if o.cik is not None), None)

    @property
    def sec_id_pin(self) -> str | None:
        return next((o.sec_id for o in reversed(self.observations) if o.sec_id), None)

    @property
    def key(self) -> str:
        return f"{self.ticker}@{self.first}"


def _gap_days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def split_eras(obs: list[Observation]) -> list[TickerEra]:
    eras: list[TickerEra] = []
    for o in sorted(obs, key=lambda o: o.as_of):
        cur = eras[-1] if eras else None
        if cur is not None:
            last_name = cur.name
            pin_changed = ((o.cik is not None and cur.cik_pin is not None and o.cik != cur.cik_pin)
                           or (o.sec_id and cur.sec_id_pin and o.sec_id != cur.sec_id_pin))
            name_changed = bool(o.name and last_name and not names_agree(o.name, last_name)
                                and o.name.upper() != last_name.upper())
            # A long gap alone starts a new era only when neither side's name
            # confirms continuity; a matching name outranks a bare gap (MONSANTO
            # CO traded 2016-06-30 to 2017-12-29, an 18-month span, one era).
            name_confirmed = bool(o.name and last_name and not name_changed)
            gap_exceeded = _gap_days(cur.last, o.as_of) > ERA_GAP_DAYS
            new_era = pin_changed or name_changed or (gap_exceeded and not name_confirmed)
            if not new_era:
                cur.observations.append(o)
                cur.last = o.as_of
                continue
        eras.append(TickerEra(o.ticker, o.as_of, o.as_of, [o]))
    return eras


class ObservationIndex:
    def __init__(self, observations: Iterable[Observation]) -> None:
        by: dict[str, list[Observation]] = defaultdict(list)
        for o in observations:
            by[o.ticker].append(o)
        self._by = {t: sorted(v, key=lambda o: o.as_of) for t, v in by.items()}
        self._eras = {t: split_eras(v) for t, v in self._by.items()}

    def eras(self) -> list[TickerEra]:
        return [e for t in sorted(self._eras) for e in self._eras[t]]

    def era_for(self, ticker: str, day: str) -> TickerEra | None:
        eras = self._eras.get(normalize_ticker(ticker), [])
        best, best_gap = None, None
        for e in eras:
            if e.first <= day <= e.last:
                return e
            gap = min(abs(_gap_days(day, e.first)), abs(_gap_days(day, e.last)))
            if gap <= ERA_GAP_DAYS and (best_gap is None or gap < best_gap):
                best, best_gap = e, gap
        return best

    def name_on(self, ticker: str, observed_date: str | None = None) -> str | None:
        named = [o for o in self._by.get(normalize_ticker(ticker), []) if o.name]
        if not named:
            return None
        if observed_date is None:
            return named[-1].name
        i = bisect_right([o.as_of for o in named], observed_date)
        return named[i - 1].name if i else named[0].name

    def cik_pin_on(self, ticker: str, observed_date: str | None = None) -> int | None:
        if observed_date is None:
            eras = self._eras.get(normalize_ticker(ticker), [])
            return eras[-1].cik_pin if eras else None
        era = self.era_for(ticker, observed_date)
        return era.cik_pin if era else None


def observations_from_instruments(path: str | Path) -> list[Observation]:
    """A `(ticker, start, end)` file (tab- or comma-separated, optional header)
    becomes two observations per row, on its start and end dates."""
    out: list[Observation] = []
    for line in Path(path).read_text().splitlines():
        parts = [p.strip() for p in re.split(r"[\t,]", line)]
        if len(parts) < 3:
            continue
        ticker, start, end = normalize_ticker(parts[0]), _iso(parts[1]), _iso(parts[2])
        if not ticker or start is None or end is None:
            continue                              # header or malformed line
        out += [Observation(ticker, start), Observation(ticker, end)]
    return out


def observations_from_snapshots(folder: str | Path, *, where: dict[str, str] | None = None,
                                 date_regex: str = DATE_IN_NAME) -> list[Observation]:
    """Every `*.csv` in `folder` whose file name contains a date is a snapshot:
    each row with a ticker becomes an observation on that date. `where` keeps only
    rows whose column equals the value (e.g. {"asset_class": "Equity"})."""
    out: dict[Observation, None] = {}
    for p in sorted(Path(folder).glob("*.csv")):
        m = re.search(date_regex, p.name)
        as_of = _iso(m.group(1)) if m else None
        if as_of is None:
            continue
        with p.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
            rows = list(reader)
        tcol = cols.get("ticker") or cols.get("symbol")
        if tcol is None:
            continue
        # A filter applies only where the file has that column filled in: the
        # Wikipedia snapshots carry an empty asset_class column.
        active = {cols[k.lower()]: v for k, v in (where or {}).items()
                  if k.lower() in cols and any((r.get(cols[k.lower()]) or "").strip() for r in rows)}
        for row in rows:
            if any((row.get(c) or "").strip() != v for c, v in active.items()):
                continue
            ticker = normalize_ticker(row.get(tcol) or "")
            if not ticker:
                continue
            cusip = _clean(row.get(cols["cusip"])) if "cusip" in cols else None
            out[Observation(ticker, as_of, _clean(row.get(cols["name"])) if "name" in cols else None,
                             cusip.upper() if cusip else None)] = None
    return sorted(out, key=lambda o: (o.ticker, o.as_of))
