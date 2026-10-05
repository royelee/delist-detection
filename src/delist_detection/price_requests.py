"""price_requests.csv (spec: "What crosses the boundary", Out then In): the
prices the library asks the caller's store for, and the caller's answers read
back.

One `last_close` per contract ending with a last trade date that is not a
continuation (the security's own close on that day), and one `received_close`
per stock leg the library read from a filing (the acquirer's close on the
ex-date, the trading day after the last trade). One `otc_print` per drop or
distress ending (`OTC_EXIT_KINDS`), dated the session after the last trade; the
caller answers with the first off-exchange print within 10 sessions. The
answers file is this file plus a `price` column (raw as-traded closes). An
answered last close replaces the library's fails-to-deliver close, an answered
received close the acquirer price, and an answered OTC print values the drop
(dlret.OTC_PRINT), so a second run with the answers changes values only. An answer is matched on `PriceKey`;
`lookup_sec_id` is informational."""
from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

from .observations import normalize_ticker
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


def stock_legs(endings: Sequence[Mapping[str, str]], llm_terms: Mapping[DelistingKey, Any],
               merger_terms: Mapping, acquirer_ids: Mapping[DelistingKey, str],
               price_tickers: Mapping[DelistingKey, str] = {}) -> dict[DelistingKey, tuple[str, str]]:
    """The acquirer (ticker, sec_id) of each ending whose LLM terms read a stock
    ratio and name its acquirer: by the acquirer security's symbol on the price
    date (`price_tickers`, sub-plan 5e), else the terms' ticker. A --merger-terms
    row for the ending wins and carries its own acquirer price, so it asks
    nothing. Read before the payout gate's verdict, so an answer that changes the
    gate does not change the requests; the acquirer sec_id is "" when the run
    found none."""
    out: dict[DelistingKey, tuple[str, str]] = {}
    for r in endings:
        key = DelistingKey(r["sec_id"], r["delist_date"])
        if for_delisting(merger_terms, key):
            continue
        t = llm_terms.get(key)
        ticker = price_tickers.get(key) or (normalize_ticker(t.acquirer_ticker) if t is not None and
                                            t.acquirer_ticker else "")
        # a stock leg stated as a dollar value (PCYC) asks the acquirer's close too (sub-plan 5f)
        if t is not None and (t.stock_ratio or getattr(t, "stock_value", None)) and ticker:
            out[key] = (ticker, acquirer_ids.get(key, ""))
    return out


def request_rows(contract_rows: Sequence[Mapping[str, Any]], endings: Mapping[str, Mapping[str, str]],
                 legs: Mapping[DelistingKey, tuple[str, str]],
                 basket: Mapping[str, Sequence[tuple[str, str]]] = {}) -> list[dict[str, str]]:
    """price_requests.csv: per contract ending (`endings`: each sec_id's last real
    delistings.csv row, contract.last_endings) with a last trade date and no
    continuation, its last close, the first OTC print of a drop or distress ending (under
    its published OTC symbol), the received close of its stock leg (`legs`: a merger's,
    or a bankruptcy plan's new line), and of each further leg of a basket (`basket`: sec_id ->
    [(ticker, sec_id)] of legs 2 and on, contract/payout_legs.csv; ruling R3). A basket leg's
    answer is accepted and not used: the library prices no basket."""
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
