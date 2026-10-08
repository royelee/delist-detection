"""price_requests.csv (spec: "What crosses the boundary", Out then In): the prices the library asks the caller's store
for, and the caller's answers read back. This module owns both directions of the round trip: the requests
(`request_rows`) and the answers (`PriceAnswers`), matched on one key derivation (`_input_key`), so a second run with
the answers changes values only.

Each request fills one value input, and its answer reaches the stage that reads that input only through the
request it matches:

- `last_close`, one per contract ending with a last trade date that is not a continuation: the security's own close
  on that day, the last-trade close of stage 7 (`PriceAnswers.last_closes`, in place of the fails-to-deliver close);
- `received_close` of a merger's stock leg, the acquirer's close on the ex-date (the trading day after the last
  trade): the acquirer price stage 8's payout gate reads (`PriceAnswers.received_close`, asked with the leg's own
  request ticker, `merger_value`);
- `received_close` of a bankruptcy plan's new line (ruling R6): the plan's value at stage 10a, its ratio times the
  close (`PriceAnswers.ending_values`);
- `received_close` of a basket's further leg (ruling R3): accepted and not used, the library prices no basket;
- `otc_print`, one per drop or distress ending (`OTC_EXIT_KINDS`), dated the session after the last trade, the
  caller answering with the first off-exchange print within 10 sessions: the drop's value at stage 10a
  (`PriceAnswers.ending_values`, dlret.OTC_PRINT).

The answers file is the requests file plus a `price` column (raw as-traded closes). A last close or an OTC print is
the security's own, on its last trade day: matched on the security, the day and the kind (its ticker and date are a
hint). A received close is one leg's: matched on its ticker too. An answer whose whole `PriceKey` matches no request
of the run stops it (`PriceAnswers.refuse_unrequested`); `lookup_sec_id` is informational."""
from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

from .dlret import DistressTerms
from .reconstruction import OverrideFileError, for_delisting
from .store import PRICE_REQUEST_COLUMNS, DelistingKey
from .trading_calendar import next_trading_day

LAST_CLOSE, RECEIVED_CLOSE, OTC_PRINT = "last_close", "received_close", "otc_print"
KINDS = (LAST_CLOSE, RECEIVED_CLOSE, OTC_PRINT)
OTC_EXIT_KINDS = frozenset({"dropped", "liquidation"})   # decision 11: a drop or distress ending's first off-exchange print


class PriceKey(NamedTuple):
    sec_id: str
    last_trade_date: str
    kind: str
    lookup_ticker: str
    date: str


def key_of(row: Mapping[str, Any]) -> PriceKey:
    return PriceKey(row["sec_id"], row["last_trade_date"], row["kind"], row["lookup_ticker"], row["date"])


def _input_key(sec_id: str, last_trade_date: str, kind: str, ticker: str = "") -> tuple[str, str, str, str]:
    """What a request and its answer are matched on, for the stage that reads the value: the security, its last trade
    day and the kind, and for a received close the leg's ticker (a last close and an OTC print are the security's
    own: their ticker and date are a hint)."""
    return sec_id, last_trade_date, kind, ticker if kind == RECEIVED_CLOSE else ""


class PriceAnswers:
    """The caller's answers to this run's price requests (`--price-answers`, `load_answers`), read by each stage only
    through the request it makes: a stage asks for the answer to its own value input, never for "an answer of this
    delisting". Holds only the caller's file; nothing a stage reads is written back into it."""

    def __init__(self, answers: Mapping[PriceKey, float] | None = None) -> None:
        self._answers = dict(answers or {})
        self._by_input = {_input_key(k.sec_id, k.last_trade_date, k.kind, k.lookup_ticker): price
                          for k, price in self._answers.items()}

    def __bool__(self) -> bool:
        return bool(self._answers)

    def _get(self, sec_id: str, last_trade: date | None, kind: str, ticker: str = "") -> float | None:
        if last_trade is None:
            return None
        return self._by_input.get(_input_key(sec_id, last_trade.isoformat(), kind, ticker))

    def received_close(self, sec_id: str, last_trade: date | None, ticker: str) -> float | None:
        """The answered close of the leg `ticker` asks for (a merger's stock leg, a plan's new line), on the ex-date
        of the delisting of `sec_id` whose last trade day is `last_trade`; None unanswered."""
        return self._get(sec_id, last_trade, RECEIVED_CLOSE, ticker) if ticker else None

    def last_closes(self, delistings: Sequence[Any], given: Mapping) -> dict[DelistingKey, float]:
        """Stage 7's answered last-trade closes: each delisting's (its `sec_id` and last trade day) whose last close
        was answered. A last close the caller also gives in --last-trade-closes (`given`) stops the run
        (OverrideFileError)."""
        out: dict[DelistingKey, float] = {}
        twice: list[str] = []
        for e in delistings:
            price = self._get(e.sec_id, e.last_trade.day, LAST_CLOSE)
            if price is None:
                continue
            if for_delisting(given, e.key) is not None:
                twice.append(f"{e.sec_id} {e.last_trade.day.isoformat()}")
            out[e.key] = price
        if twice:
            raise OverrideFileError("--price-answers and --last-trade-closes both give the last close of: "
                                    + "; ".join(twice))
        return out

    def ending_values(self, sec_id: str, last_trade: date | None, distress: DistressTerms | None
                      ) -> tuple[float | None, float | None]:
        """Stage 10a's answered values of one ending: `(otc_print, plan_value)`. The first off-exchange print of a
        drop or a bankruptcy, and a bankruptcy plan's value (ruling R6: its ratio times the new line's answered
        close, `distress.plan_ticker`), unless an answered OTC print values the ending already."""
        otc = self._get(sec_id, last_trade, OTC_PRINT)
        if otc is not None or distress is None or not distress.plan_ratio:
            return otc, None
        close = self.received_close(sec_id, last_trade, distress.plan_ticker)
        return None, (float(distress.plan_ratio) * close if close is not None else None)

    def refuse_unrequested(self, requests: Sequence[Mapping[str, Any]]) -> None:
        """Stop the run (OverrideFileError) when an answer's `PriceKey` matches none of `requests` (stage 10g)."""
        unrequested = sorted(set(self._answers) - {key_of(r) for r in requests})
        if unrequested:
            raise OverrideFileError("--price-answers rows that answer no request of this run: "
                                    + "; ".join(" ".join(k) for k in unrequested[:5])
                                    + (f" (and {len(unrequested) - 5} more)" if len(unrequested) > 5 else ""))


def request_rows(contract_rows: Sequence[Mapping[str, Any]], endings: Mapping[str, Mapping[str, str]],
                 legs: Mapping[DelistingKey, tuple[str, str]], *,
                 plans: Mapping[DelistingKey, DistressTerms] | None = None,
                 leg_rows: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, str]]:
    """price_requests.csv: per contract ending (`endings`: each sec_id's last real delistings.csv row,
    exit_kind.last_endings) with a last trade date and no continuation, its last close, the first OTC print of a drop
    or distress ending (under its published OTC symbol), the received close of its stock leg (`legs`: a merger's, as
    stage 8 asked it, else a bankruptcy plan's new line from stage 9e's `plans`), and of each further leg of a basket
    (`leg_rows`: contract/payout_legs.csv's rows, legs 2 and on; ruling R3). A basket leg's answer is accepted and not
    used: the library prices no basket."""
    legs = dict(legs)
    legs.update({k: (t.plan_ticker, "") for k, t in (plans or {}).items() if t.plan_ratio and k not in legs})
    basket: dict[str, list[tuple[str, str]]] = {}
    for r in leg_rows:
        if r["leg"] > 1:
            basket.setdefault(r["sec_id"], []).append((r["price_ticker"], r["price_sec_id"]))
    out: list[dict[str, str]] = []
    for c in contract_rows:
        ltd = c["last_trade_date"]
        if not ltd or c["continuation"] is True:
            continue
        r = endings[c["sec_id"]]
        out.append({"sec_id": c["sec_id"], "last_trade_date": ltd, "kind": LAST_CLOSE,
                    "lookup_sec_id": c["sec_id"], "lookup_ticker": r["ticker"], "date": ltd})
        if c["exit_kind"] in OTC_EXIT_KINDS and c.get("value_rule") != "stock":
            # under the OTC symbol the contract publishes (sub-plan 5g), else the exchange ticker as a hint; a
            # bankruptcy plan's new shares (ruling R6) are no OTC print: their stock leg asks a received close
            out.append({"sec_id": c["sec_id"], "last_trade_date": ltd, "kind": OTC_PRINT,
                        "lookup_sec_id": c["sec_id"], "lookup_ticker": c.get("price_ticker") or r["ticker"],
                        "date": next_trading_day(date.fromisoformat(ltd)).isoformat()})
        leg = legs.get(DelistingKey(r["sec_id"], r["delist_date"]))
        asked: set[str] = set()
        for ticker, sid in ([leg] if leg is not None else []) + [b for b in basket.get(c["sec_id"], ()) if b[0]]:
            if ticker in asked:
                continue         # two legs never share a request key: one answer would price both
            asked.add(ticker)
            out.append({"sec_id": c["sec_id"], "last_trade_date": ltd, "kind": RECEIVED_CLOSE,
                        "lookup_sec_id": sid, "lookup_ticker": ticker,
                        "date": next_trading_day(date.fromisoformat(ltd)).isoformat()})
    return out


def load_answers(path: str | Path) -> dict[PriceKey, float]:
    """The answers file (--price-answers): price_requests.csv's columns plus
    `price`. A blank price is unanswered and skipped. A missing column, a kind
    not in KINDS, or a price that is not a positive number raises
    OverrideFileError naming the file and line."""
    p = Path(path)
    out: dict[PriceKey, float] = {}
    first_line: dict[PriceKey, int] = {}
    with p.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in (*PRICE_REQUEST_COLUMNS, "price") if c not in (reader.fieldnames or [])]
        if missing:
            raise OverrideFileError(f"{p}: missing column(s) {', '.join(missing)}")
        for line, row in enumerate(reader, start=2):
            where = f"{p}:{line}"
            if row["kind"] not in KINDS:
                raise OverrideFileError(f"{where}: kind {row['kind']!r} is not one of {', '.join(KINDS)}")
            cell = (row["price"] or "").strip()
            if not cell:
                continue
            try:
                price = float(cell)
            except ValueError:
                raise OverrideFileError(f"{where}: price {cell!r} is not a number") from None
            if not math.isfinite(price) or price <= 0:
                raise OverrideFileError(f"{where}: price {cell!r} is not positive")
            key = key_of(row)
            if key in out and out[key] != price:
                raise OverrideFileError(
                    f"{where}: a second price for the same request (first on line {first_line[key]})")
            out[key] = price
            first_line.setdefault(key, line)
    return out
