"""The securities a run adds that no observation names -- a merger's acquirer
(`acquirers.find_acquirer`), an exchange transfer's successor
(`successors.successor_from_8k12b`) and a FIGI line's successor the line follow
found (`line_follow`) -- each with the one ticker_history row the run can give it."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import ClassVar

from ..sources.ftd import FtdRow
from .security_master import Security


@dataclass
class AddedSecurity:
    """A security the run adds that no observation names -- a merger's acquirer
    (`AddedAcquirer`) or an exchange transfer's successor (`AddedSuccessor`) --
    with the one ticker it is known by. Its one ticker_history row, built
    directly (`ranges_from_sightings` would drop a lone sighting), runs over
    `span()` and names its `source`."""
    security: Security
    ticker: str
    source: ClassVar[str] = ""

    def span(self) -> tuple[str, str]:
        """(first, last) day the run saw it."""
        raise NotImplementedError

    def history_row(self, *, listed: bool, exchange: str | None) -> dict:
        """Its ticker_history row: open-ended while it is listed today."""
        first, last = self.span()
        return {"sec_id": self.security.sec_id, "ticker": self.ticker, "exchange": exchange, "valid_from": first,
                "valid_to": None if listed else last, "source": self.source}


@dataclass
class AddedAcquirer(AddedSecurity):
    """A merger's acquirer, seen in the fails rows under its ticker around each
    merger that names it (every merger's window, not just the first), else on
    the first such merger's last trade day (`fallback_day`)."""
    fallback_day: date
    rows: list[FtdRow] = field(default_factory=list)
    source: ClassVar[str] = "ftd"

    def span(self) -> tuple[str, str]:
        dates = sorted(r.date for r in self.rows)
        first = dates[0] if dates else self.fallback_day.isoformat()
        return first, (dates[-1] if dates else first)


@dataclass
class AddedLineSuccessor(AddedSecurity):
    """A FIGI line's successor the line follow found (pipeline stage 4b; R2: the line's new CUSIP has its own
    composite): seen from the step's first row (`first`) through that CUSIP's fails rows under the line's new
    ticker (`rows`), clipped at the last trade of its own ending when the run found one (`last`, pipeline stage 9d:
    its fails rows can run past it)."""
    first: str
    rows: list[FtdRow] = field(default_factory=list)
    last: str = ""
    source: ClassVar[str] = "ftd"

    def span(self) -> tuple[str, str]:
        dates = sorted({self.first, *(r.date for r in self.rows)})
        return dates[0], max(dates[0], min(dates[-1], self.last)) if self.last else dates[-1]


@dataclass
class AddedSuccessor(AddedSecurity):
    """An exchange transfer's successor, seen on its 8-K12B's filing date (never
    before the day after the predecessor's last trade), through `last`: the last
    trade of its own ending when the run found one (pipeline stage 9d), else that
    day alone."""
    filing_date: str
    last: str = ""
    source: ClassVar[str] = "edgar_8k"

    def span(self) -> tuple[str, str]:
        return self.filing_date, max(self.filing_date, self.last or self.filing_date)
