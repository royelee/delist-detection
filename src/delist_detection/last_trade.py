"""The last day a security traded on its exchange.

No rule requires an issuer to state it, so it is read from several places and
cross-checked: the exchange's Form 25 notice (form25.notice_last_trade), the
closing 8-K's Item 3.01 text (here), SEC MIDAS exchange volume and Nasdaq's
code-D halts. Measured volume beats wording, and wording that disagrees with it
is flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .evidence import item_text
from .trading_calendar import previous_trading_day

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
_DATE = rf"((?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}})"
_OPEN = r"(?:prior to|before) (?:the )?(?:open|opening)(?: of (?:the )?(?:trading|market))?"
_CLOSE = r"(?:at|after|following) the close(?: of (?:the )?(?:trading|market|business)(?: day| session)?)?"


def _day(s: str) -> date:
    return datetime.strptime(re.sub(r"\s+", " ", s), "%B %d, %Y").date()


def _closing_date(text: str) -> date | None:
    pattern = _DATE + r'\s*\((?:the\s*)?' + '["' + "'" + '“]?' + r'Closing Date'
    m = re.search(pattern, text, re.I)
    return _day(m.group(1)) if m else None


def eightk_last_trade(text: str) -> tuple[date | None, str]:
    if not text:
        return None, ""
    flat = re.sub(r"\s+", " ", text)
    section = re.sub(r"\s+", " ", item_text(text, "3.01", width=3000) or "") or flat
    m = re.search(rf"{_OPEN}(?: on)? {_DATE}", section, re.I)
    if m:
        return previous_trading_day(_day(m.group(1))), "8k_open"
    if re.search(rf"{_OPEN}[^.]{{0,40}}?Closing Date", section, re.I):
        cd = _closing_date(flat)
        if cd:
            return previous_trading_day(cd), "8k_open_closing"
    m = re.search(rf"{_CLOSE} on {_DATE}", section, re.I)
    if m:
        return _day(m.group(1)), "8k_close"
    if re.search(rf"{_CLOSE}[^.]{{0,40}}?Closing Date", section, re.I):
        cd = _closing_date(flat)
        if cd:
            return cd, "8k_close_closing"
    m = re.search(rf"last (?:day of trading|trading day)[^.]{{0,40}}?(?:was|will be|is) {_DATE}", section, re.I)
    if m:
        return _day(m.group(1)), "8k_last_day"
    m = re.search(rf"suspended (?:immediately )?on {_DATE}", section, re.I)
    if m:
        return _day(m.group(1)), "8k_suspended_unconfirmed"
    return None, ""


@dataclass(frozen=True)
class LastTrade:
    day: date | None
    source: str
    flags: tuple[str, ...]
    # Days of the Nasdaq halt feed this decision asked for and could not read
    # (nasdaq_halts: a failure, not "no halts"): the decision rests on them.
    halt_feed_failed: tuple[date, ...] = ()


def _confirmed(kind: str) -> bool:
    return bool(kind) and not kind.endswith("unconfirmed")


def decide_last_trade(*, notice: tuple[date | None, str], eightk: tuple[date | None, str],
                      midas: date | None, halt: date | None) -> LastTrade:
    texts = [d for d, _ in (notice, eightk) if d is not None]

    def pick(day: date, source: str, extra: tuple[str, ...] = ()) -> LastTrade:
        conflict = ("last_trade_date_conflict",) if any(d != day for d in texts) else ()
        return LastTrade(day, source, extra + conflict)

    if midas is not None:
        return pick(midas, "midas")
    if halt is not None:
        return pick(halt, "nasdaq_halt")
    (n_day, n_kind), (e_day, e_kind) = notice, eightk
    if n_day and _confirmed(n_kind):
        return pick(n_day, "ex99_notice")
    if e_day and _confirmed(e_kind):
        return pick(e_day, "8k_301")
    if n_day:
        return pick(n_day, "ex99_notice", ("last_trade_date_unconfirmed",))
    if e_day:
        return pick(e_day, "8k_301", ("last_trade_date_unconfirmed",))
    return LastTrade(None, "", ("no_last_trade_date",))
