"""The issuer CIK in force on each sighting of a security (spec: security_history's
`issuer_id`, "the CIK in force on the interval"; golden MRK-2008).

A sighting keeps its era's CIK when that CIK's EDGAR name on the sighting's date
(`evidence.name_at`) agrees with the observed name (`names.names_agree`). When it
does not, the one other CIK that SEC's name index lists under exactly the
observed name, and whose EDGAR name on that date agrees, is the issuer in force:
Merck's 2008 sightings resolved to CIK 310158, which was Schering-Plough until
November 2009, while old Merck & Co (CIK 64978) carried the name then. No such
CIK, or two, keeps the era's. The other CIK must have been filing a registrant's
own reports around the sighting (`REGISTRANT_FORMS`, `FILING_DAYS`, FB-015): a
company whose reports stop in 1998 is not the issuer of a stock sighted in 2020,
whatever its name (LUMN: CIK 1008114, another "LUMEN TECHNOLOGIES INC", while
EDGAR dated CenturyLink's rename four months after the ticker changed), nor is
one EDGAR holds only holders' Schedule 13Gs of (MAN: CIK 62072).

`issuer_changes` turns the sightings into each security's issuer timeline. A
change is dated on the first day the new CIK carried an agreeing name
(`agreeing_since`), kept after the last sighting under the old CIK and no later
than the first sighting under the new one. A sighting with no name (the first
day of a line the library derived, `derived_lines`) keeps its CIK and changes
the issuer on its own day. `listed_issuer` ends the timeline of a history open
on the run date with the company SEC lists its ticker under. EDGAR is reached
only through the injected `submissions`, `exact_names` and `filed` callables."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..filings.evidence import name_at, parse_day
from ..vocabulary.names import names_agree

Submissions = Callable[[int], "dict | None"]      # a CIK's submissions JSON, None when it cannot be read
ExactNames = Callable[[str], Sequence[int]]       # the CIKs the name index lists under exactly this name
# the days of a CIK's latest filings whose form starts with a prefix; None when its filing list is not known
Filed = Callable[[int, str], "Sequence[date] | None"]

FILING_DAYS = 400     # another company is the issuer in force only if it reported no longer than this before the sighting
# the reports a registrant of listed stock files itself (prefixes: 10-K405, 10-QSB, 8-K12B and N-CSRS count); a
# Schedule 13G its holders file, or a transfer agent's forms, are not its own
REGISTRANT_FORMS = ("10-K", "10-Q", "8-K", "20-F", "40-F", "6-K", "N-CSR")


def filed_in(submissions: Submissions) -> Filed:
    """The `Filed` read of a `submissions` that keeps the JSON's filings block (the tests' fixtures; the run's
    issuer record drops it from a profile and reads the days through `IssuerRecord.recent_days`)."""
    def filed(cik: int, form: str) -> list[date] | None:
        sub = submissions(cik)
        if not isinstance(sub, dict) or "filings" not in sub:
            return None
        recent = (sub.get("filings") or {}).get("recent") or {}
        return [d for f, fd in zip(recent.get("form") or [], recent.get("filingDate") or [])
                if str(f).startswith(form) and (d := parse_day(fd)) is not None]
    return filed


def _filing_around(filed: Filed, cik: int, on: date) -> bool:
    """Whether the company was still filing its own reports around `on`: the latest of its `REGISTRANT_FORMS` is no
    more than `FILING_DAYS` before it. A company with none was not (MAN: CIK 76356, a "MANPOWER INC /DE/" EDGAR
    holds no filing of, and CIK 62072, whose only filings are holders' Schedule 13Gs to 2016); one whose filing
    list is not known is not judged."""
    days: list[date] = []
    for form in REGISTRANT_FORMS:
        found = filed(cik, form)
        if found is None:
            return True
        days += found
    return bool(days) and max(days) >= on - timedelta(days=FILING_DAYS)


@dataclass(frozen=True)
class Sighting:
    sec_id: str
    day: str          # ISO date
    name: str         # the observed name
    cik: str          # the era's CIK, "" when unknown


def in_force(s: Sighting, submissions: Submissions, exact_names: ExactNames, filed: Filed | None = None) -> str:
    """The issuer CIK in force on the sighting's date (see the module docstring). `filed`: each CIK's filing days
    (default: read from `submissions`' own filings block, `filed_in`)."""
    if not s.cik or not s.name:
        return s.cik
    filed = filed or filed_in(submissions)
    on = date.fromisoformat(s.day)
    sub = submissions(int(s.cik))
    if not isinstance(sub, dict) or names_agree(name_at(sub, on), s.name):
        return s.cik
    agreeing = []
    for cik in sorted(set(exact_names(s.name)) - {int(s.cik)}):
        other = submissions(cik)
        if isinstance(other, dict) and names_agree(name_at(other, on), s.name) and _filing_around(filed, cik, on):
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


def with_registrants(timeline: Sequence[tuple[str, str]],
                     registrants: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """A security's issuer timeline (`issuer_changes`) with its successor registrants (FB-004: the new registrants a
    holding-company reorganization of an ending that went on put in the old one's place, each as (the ISO day its
    successor registration was filed, CIK), earliest first): each is the issuer in force from that day, unless it
    already is, dated after the timeline's last change so the days still strictly increase. A security with an empty
    timeline stays without one (no sighting carried a CIK)."""
    out = list(timeline)
    for day, cik in registrants:
        if not out or out[-1][1] == cik:
            continue
        after = (date.fromisoformat(out[-1][0]) + timedelta(days=1)).isoformat()
        out.append((max(day, after), cik))
    return out


def _deregistered(filed: Filed, cik: int, lo: str, hi: str) -> str | None:
    """The first day in [`lo`, `hi`] the issuer's own latest filings hold a Form 25 (25, 25-NSE, 25/A) or a Form 15:
    the day its registered stock's listing or registration ended. None without one."""
    days = [d.isoformat() for form in ("25", "15") for d in filed(cik, form) or ()]
    return min((d for d in days if lo <= d <= hi), default=None)


def listed_issuer(timeline: Sequence[tuple[str, str]], listed: int | None, name: str, on: date, last_sighting: str,
                  submissions: Submissions, filed: Filed | None = None) -> list[tuple[str, str]]:
    """FB-015: the issuer timeline of a security whose history is open on the run date `on`, ended with the company
    SEC lists its ticker under (`listed`). On a seed list a security has one sighting, and a registrant that took
    over later is in no era when the old one kept filing (MRK: old Merck, CIK 64978, files as a subsidiary since
    November 2009, so the line follow took the new CUSIP as its own). `listed` is in force at the end when it is
    not the timeline's last CIK, its EDGAR name on `on` agrees with the security's `name`, and something dates the
    change: the first day it carried the agreeing name (`agreeing_since`), and the old issuer's first Form 25 or 15
    from then on (`_deregistered`), the later of the two. The change is after the security's last sighting
    (`last_sighting`, an ISO day) and after the timeline's last change. Otherwise the timeline is returned as it
    is."""
    out = list(timeline)
    if not out or listed is None or str(listed) == out[-1][1] or not name:
        return out
    sub = submissions(int(listed))
    if not isinstance(sub, dict) or not names_agree(name_at(sub, on), name):
        return out
    filed = filed or filed_in(submissions)
    after = (date.fromisoformat(max(last_sighting, out[-1][0])) + timedelta(days=1)).isoformat()
    since = agreeing_since(sub, name, on)
    took = max(since.isoformat(), after) if since else after
    gone = _deregistered(filed, int(out[-1][1]), took, on.isoformat())
    if since is None and gone is None:
        return out
    return [*out, (min(max(took, gone or took), on.isoformat()), str(listed))]


def issuer_changes(sightings: Iterable[Sighting], submissions: Submissions, exact_names: ExactNames,
                   filed: Filed | None = None) -> dict[str, list[tuple[str, str]]]:
    """sec_id -> [(from ISO date, CIK)], earliest first: the CIK in force on the
    security's first sighting with one, then each change. A sighting with no CIK
    changes nothing. Sightings are ordered by (day, CIK, name); a change is recorded
    only on a sighting dated after the previous one, so a same-day sighting under
    another CIK changes nothing and the dates strictly increase. `filed`: each CIK's
    filing days (default: read from `submissions`' own filings block, `filed_in`)."""
    filed = filed or filed_in(submissions)
    by_sec: dict[str, list[Sighting]] = defaultdict(list)
    for s in sightings:
        by_sec[s.sec_id].append(s)
    out: dict[str, list[tuple[str, str]]] = {}
    for sid, rows in by_sec.items():
        rows.sort(key=lambda s: (s.day, s.cik, s.name))
        timeline: list[tuple[str, str]] = []
        last_day = ""
        for s in rows:
            cik = in_force(s, submissions, exact_names, filed)
            if not cik:
                continue
            if not timeline:
                timeline.append((s.day, cik))
            elif s.day > last_day and cik != timeline[-1][1]:
                sub = submissions(int(cik))
                since = agreeing_since(sub, s.name, date.fromisoformat(s.day)) if isinstance(sub, dict) else None
                after = (date.fromisoformat(last_day) + timedelta(days=1)).isoformat()
                day = max(since.isoformat() if since else s.day, after)
                if since:
                    # a holding company carries the agreeing name from its formation, long before it is the
                    # registrant of the listed stock (ICE 2013): not before the old registrant's listing ended
                    day = max(day, _deregistered(filed, int(timeline[-1][1]), after, s.day) or day)
                timeline.append((min(day, s.day), cik))
            last_day = s.day
        if timeline:
            out[sid] = timeline
    return out
