"""The issuer CIK in force on each sighting of a security (spec: security_history's
`issuer_id`, "the CIK in force on the interval"; golden MRK-2008).

A sighting keeps its era's CIK when that CIK's EDGAR name on the sighting's date
(`evidence.name_at`) agrees with the observed name (`names.names_agree`). When it
does not, the one other CIK that SEC's name index lists under exactly the
observed name, and whose EDGAR name on that date agrees, is the issuer in force:
Merck's 2008 sightings resolved to CIK 310158, which was Schering-Plough until
November 2009, while old Merck & Co (CIK 64978) carried the name then. No such
CIK, or two, keeps the era's.

`issuer_changes` turns the sightings into each security's issuer timeline. A
change is dated on the first day the new CIK carried an agreeing name
(`agreeing_since`), kept after the last sighting under the old CIK and no later
than the first sighting under the new one. EDGAR is reached only through the
injected `submissions` and `exact_names` callables."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..filings.evidence import name_at, parse_day
from ..vocabulary.names import names_agree

Submissions = Callable[[int], "dict | None"]      # a CIK's submissions JSON, None when it cannot be read
ExactNames = Callable[[str], Sequence[int]]       # the CIKs the name index lists under exactly this name


@dataclass(frozen=True)
class Sighting:
    sec_id: str
    day: str          # ISO date
    name: str         # the observed name
    cik: str          # the era's CIK, "" when unknown


def in_force(s: Sighting, submissions: Submissions, exact_names: ExactNames) -> str:
    """The issuer CIK in force on the sighting's date (see the module docstring)."""
    if not s.cik or not s.name:
        return s.cik
    on = date.fromisoformat(s.day)
    sub = submissions(int(s.cik))
    if not isinstance(sub, dict) or names_agree(name_at(sub, on), s.name):
        return s.cik
    agreeing = []
    for cik in sorted(set(exact_names(s.name)) - {int(s.cik)}):
        other = submissions(cik)
        if isinstance(other, dict) and names_agree(name_at(other, on), s.name):
            agreeing.append(cik)
    return str(agreeing[0]) if len(agreeing) == 1 else s.cik


def _spans(sub: dict) -> list[tuple[date | None, date | None, str]]:
    """Each EDGAR name with the days it was in force, earliest first; the current
    name runs from the day after the last former name ended."""
    former = []
    for fn in sub.get("formerNames") or []:
        if isinstance(fn, dict):
            lo, hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
            if lo and hi:
                former.append((lo, hi, fn.get("name") or ""))
    former.sort()
    start = former[-1][1] + timedelta(days=1) if former else None
    return [*former, (start, None, sub.get("name") or "")]


def agreeing_since(sub: dict, name: str, on: date) -> date | None:
    """The first day of the unbroken run of EDGAR names, ending with the one in
    force on `on`, that agree with `name`; None when the name in force on `on`
    does not agree, or the run reaches back past every dated name."""
    spans = _spans(sub)
    i = next((k for k, (lo, hi, _) in enumerate(spans)
              if (lo is None or lo <= on) and (hi is None or on <= hi)), None)
    if i is None or not names_agree(spans[i][2], name):
        return None
    while i > 0 and names_agree(spans[i - 1][2], name):
        i -= 1
    return spans[i][0]


def issuer_changes(sightings: Iterable[Sighting], submissions: Submissions,
                   exact_names: ExactNames) -> dict[str, list[tuple[str, str]]]:
    """sec_id -> [(from ISO date, CIK)], earliest first: the CIK in force on the
    security's first sighting with one, then each change. A sighting with no CIK
    changes nothing. Sightings are ordered by (day, CIK, name); a change is recorded
    only on a sighting dated after the previous one, so a same-day sighting under
    another CIK changes nothing and the dates strictly increase."""
    by_sec: dict[str, list[Sighting]] = defaultdict(list)
    for s in sightings:
        by_sec[s.sec_id].append(s)
    out: dict[str, list[tuple[str, str]]] = {}
    for sid, rows in by_sec.items():
        rows.sort(key=lambda s: (s.day, s.cik, s.name))
        timeline: list[tuple[str, str]] = []
        last_day = ""
        for s in rows:
            cik = in_force(s, submissions, exact_names)
            if not cik:
                continue
            if not timeline:
                timeline.append((s.day, cik))
            elif s.day > last_day and cik != timeline[-1][1]:
                sub = submissions(int(cik))
                since = agreeing_since(sub, s.name, date.fromisoformat(s.day)) if isinstance(sub, dict) else None
                after = (date.fromisoformat(last_day) + timedelta(days=1)).isoformat()
                timeline.append((min(max(since.isoformat() if since else s.day, after), s.day), cik))
            last_day = s.day
        if timeline:
            out[sid] = timeline
    return out
