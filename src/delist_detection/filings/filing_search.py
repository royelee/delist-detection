"""The EDGAR full-text searches several stages send, built in one place (pure: the EDGAR client sends them).

A warm pass and the sequential pass must send the same query to read the same cache entry, and stage 4b's
other-registrant check, stage 9's 8-K12B successor and the handoff stage's continuation filing ask the same
question of EDGAR: which registrant's successor registration (8-K12B, 8-K12G3) names this issuer around this day.
This module imports nothing of the package, so the line follow (stage 4b) asks it without loading stage 9."""
from __future__ import annotations

from datetime import date, timedelta

SUCCESSOR_FORMS = "8-K12B,8-K12G3"      # the successor registrations, as the full-text search takes its forms
SEARCH_BEFORE_DAYS, SEARCH_AFTER_DAYS = 30, 60      # the successor search's window around the day


def successor_query(name: str, day: date) -> tuple[str, str, date, date]:
    """The full-text search for a successor registration naming `name` around `day`: `(query, forms, lo, hi)`,
    from `SEARCH_BEFORE_DAYS` before the day to `SEARCH_AFTER_DAYS` after it."""
    return (f'"{name}"', SUCCESSOR_FORMS, day - timedelta(days=SEARCH_BEFORE_DAYS),
            day + timedelta(days=SEARCH_AFTER_DAYS))
