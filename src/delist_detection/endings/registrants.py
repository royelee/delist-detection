"""The issuer in force after a holding-company reorganization (FB-004, part b): a security whose ending goes on as the
security itself, and whose old registrant a new one replaced.

Disney's 2019 reorganization (CIK 1001039 to 1744489) and WestRock's of 2018 (1636023 to 1732845) ended the old
registrant's listing with a merger-looking Form 25 and an 8-K12B of the new one, while the security's own CUSIP kept
trading under its own ticker. The old CIK is "TWDC Enterprises 18 Corp." today and lists nothing; the later Form 25
(WRK's, 2024-07-08), the listing and the issuer in the contract are the new registrant's.

A `Registrant` is one such successor: the CIK whose 8-K12B/8-K12G3 names the old registrant around the ending, and the
day it filed. `SuccessorRegistrants.of(record, delistings)` finds them, one per ending that goes on
(`goes_on`: the security is its own successor, or the ending is a merger or an exchange transfer with a confirmed last
trade after which the security's own CUSIPs keep trading under its own tickers, `history.keeps_trading`: the test
that stops the history clipping at it). A successor registration alone changes nothing: the issuer in force changes
only for a security whose line goes on. The stage reads the answers (stage 5: the registrant's Form 25s, its listing
today; stage 10c3: the contract's issuer timeline, `issuer_in_force.with_registrants`)."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..identity.history import CONTINUATION_BUCKETS, keeps_trading
from ..identity.issuer_record import IssuerRecord
from ..identity.line_follow import READ_FAILED, name_on, successor_filer
from ..sources.capabilities import FullTextSearch
from .rewrites import is_real_ending
from .trading_record import TradingRecord

if TYPE_CHECKING:
    from .delistings import Delisting      # the finder's context holds Registrants: the type only, no cycle

MAX_REGISTRANTS = 3        # a security's reorganizations followed in a row (each registrant's own Form 25s may go on)


@dataclass(frozen=True)
class Registrant:
    """A successor registrant: its CIK and the ISO day its successor registration was filed (the day it is the
    issuer in force from)."""
    cik: int
    since: str


def goes_on(d: "Delisting", record: TradingRecord) -> bool:
    """Whether ending `d` does not end its security: the security is its own successor, or it is a merger or an
    exchange transfer with a confirmed last trade after which its own CUSIPs keep trading under its own tickers (the
    history's clip rule, `history.keeps_trading`)."""
    if not is_real_ending(d):
        return True
    if d.record.bucket not in CONTINUATION_BUCKETS or not d.last_trade.confirmed or d.last_trade.day is None:
        return False
    return keeps_trading(record.rows, record.own_tickers, d.last_trade.day.isoformat())


class SuccessorRegistrants:
    """Finds the successor registrants of a security's endings that go on, through EDGAR's full-text search for a
    successor registration naming the old registrant (`line_follow.successor_filer`: the search stage 4b's
    other-registrant check sends too, so one cache entry answers both). `search` None (the adapter states the
    capability absent): none found. The old registrant's name on the ending's day is read through the issuer record."""

    def __init__(self, issuers: IssuerRecord, search: FullTextSearch | None, edgar) -> None:
        self.issuers, self.search, self.edgar = issuers, search, edgar

    def of(self, record: TradingRecord, delistings: Iterable["Delisting"]) -> list[Registrant]:
        """The security's successor registrants, in order, one for each ending of `delistings` that goes on and
        whose old registrant a search finds another registrant replacing; at most `MAX_REGISTRANTS`. A read that
        failed finds none (the search counted itself degraded on this thread, so the caller's watch reports it)."""
        if self.search is None:
            return []
        out: list[Registrant] = []
        for d in sorted(delistings, key=lambda d: d.anchor):
            if len(out) >= MAX_REGISTRANTS or not goes_on(d, record):
                continue
            day = d.anchor
            name = name_on(self.issuers.profile(d.cik), day, record.security.name)
            got = successor_filer(self.search, self.edgar, name=name, day=day, cik=d.cik,
                                  own_tickers=record.own_tickers)
            if got is None or got == READ_FAILED:
                continue
            cik, filed = got
            if cik != d.cik and all(cik != r.cik for r in out):
                out.append(Registrant(cik, filed))
        return out
