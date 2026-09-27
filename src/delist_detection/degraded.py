"""Answers that rested on a failed request or a stale copy: the
`resolution_degraded` review rows and flags the pipeline writes for them. An
SEC read counts itself as degraded (`sec_stats.SEC_STATS.degraded`), which a
`DegradedWatch` notices on its thread; a Nasdaq halt-feed day that failed is
carried on the delisting's last-trade decision (`LastTrade.halt_feed_failed`)."""
from __future__ import annotations

from collections.abc import Sequence

from .delistings import Delisting
from .review_triage import ReviewItem
from .sec_stats import SEC_STATS

DEGRADED_FLAG = "resolution_degraded"


def degraded_item(sec_id: str, ticker: str, cik: int | None, what: str, then: str = "",
                  **where: str) -> ReviewItem:
    """The `resolution_degraded` review row saying `what` rested on a failed EDGAR
    request or a stale copy (`then` appended); `where` is its `delist_date` or
    `last_seen`."""
    return ReviewItem(sec_id, ticker, cik, DEGRADED_FLAG,
                      f"{what} rested on a failed EDGAR request or a stale copy{then}", **where)


class DegradedWatch:
    """Whether an EDGAR answer on this thread rested on a failed request or a stale
    copy since the watch was made (sec_stats.SEC_STATS.thread_degraded())."""

    def __init__(self) -> None:
        self._mark = SEC_STATS.thread_degraded()

    def tripped(self) -> bool:
        return SEC_STATS.thread_degraded() > self._mark

    def report(self, review: list[ReviewItem], item: ReviewItem, flag_rows: Sequence[Delisting] = ()) -> None:
        """When tripped: add `item` to `review`, and the flag to each of `flag_rows`'
        own delistings.csv row, so the flag reaches the delisting itself, not only
        review.csv."""
        if not self.tripped():
            return
        review.append(item)
        for delisting in flag_rows:
            flag_degraded(delisting)

    def report_delisting(self, review: list[ReviewItem], e: Delisting, what: str, *, own_row: bool = True) -> None:
        """`report` for one delisting's `what`: its review row, and with `own_row`
        its delistings.csv row too."""
        self.report(review, degraded_item(e.sec_id, e.ticker, e.cik, what, delist_date=e.delist_date),
                    [e] if own_row else ())


def flag_degraded(delisting: Delisting) -> None:
    """`resolution_degraded` on the delisting's own delistings.csv row, once."""
    if DEGRADED_FLAG not in delisting.flags:
        delisting.add_flag(DEGRADED_FLAG)


def report_halt_feed_failures(review: list[ReviewItem], delistings: Sequence[Delisting]) -> None:
    """Each delisting whose last-trade decision asked the Nasdaq halt feed for a
    day it could not read (`LastTrade.halt_feed_failed`): the same treatment as
    a failed SEC request -- `resolution_degraded` on its own delistings.csv row,
    and a review row naming the feed and the days."""
    for d in delistings:
        if not d.last_trade.halt_feed_failed:
            continue
        days = ", ".join(sorted({day.isoformat() for day in d.last_trade.halt_feed_failed}))
        review.append(ReviewItem(d.sec_id, d.ticker, d.cik, DEGRADED_FLAG,
                                 f"the last-trade date rested on a failed Nasdaq halt feed read ({days}); "
                                 "run again once the feed answers", delist_date=d.delist_date))
        flag_degraded(d)
