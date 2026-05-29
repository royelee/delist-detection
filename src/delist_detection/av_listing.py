"""Alpha Vantage delisted listing-status loader.

The qlib_practice pipeline already fetches AV's LISTING_STATUS, which gives
us `(ticker, name, exchange, delistingDate)` for every delisted US-listed
security. We use the **name** as both a resolver fallback (EDGAR company-
name search) and as a validation signal (name-token match against the
candidate CIK's `formerNames`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AvListingRow:
    ticker: str
    name: str
    exchange: str
    asset_type: str
    ipo_date: str
    delist_date: str


class AvListingLoader:
    def __init__(
        self,
        csv_path: str | Path,
        active_csv_path: str | Path | None = None,
    ) -> None:
        self.csv_path = Path(csv_path)
        self.active_csv_path = Path(active_csv_path) if active_csv_path else None
        self._by_ticker: dict[str, AvListingRow] | None = None
        self._active_by_ticker: dict[str, AvListingRow] | None = None

    def _load(self) -> dict[str, AvListingRow]:
        if self._by_ticker is not None:
            return self._by_ticker
        out: dict[str, AvListingRow] = {}
        with self.csv_path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                t = (row.get("symbol") or "").upper().strip()
                if not t or t in out:
                    continue
                out[t] = AvListingRow(
                    ticker=t,
                    name=(row.get("name") or "").strip(),
                    exchange=(row.get("exchange") or "").strip(),
                    asset_type=(row.get("assetType") or "").strip(),
                    ipo_date=(row.get("ipoDate") or "").strip(),
                    delist_date=(row.get("delistingDate") or "").strip(),
                )
        self._by_ticker = out
        return out

    def _load_active(self) -> dict[str, AvListingRow]:
        if self._active_by_ticker is not None:
            return self._active_by_ticker
        if not self.active_csv_path or not self.active_csv_path.exists():
            self._active_by_ticker = {}
            return self._active_by_ticker
        out: dict[str, AvListingRow] = {}
        with self.active_csv_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                t = (row.get("symbol") or "").upper().strip()
                if not t or t in out:
                    continue
                out[t] = AvListingRow(
                    ticker=t,
                    name=(row.get("name") or "").strip(),
                    exchange=(row.get("exchange") or "").strip(),
                    asset_type=(row.get("assetType") or "").strip(),
                    ipo_date=(row.get("ipoDate") or "").strip(),
                    delist_date="",
                )
        self._active_by_ticker = out
        return out

    def get(self, ticker: str) -> AvListingRow | None:
        t = ticker.upper()
        row = self._load().get(t)
        if row is not None:
            return row
        return self._load_active().get(t)

    def name(self, ticker: str, observed_date: str | None = None,
             max_days_off: int = 365) -> str | None:
        """Return the AV company name, but only when it plausibly matches.

        AV stores one row per ticker — the *first* time that ticker was used.
        Tickers are recycled, so a Tiingo `observed_date` decades later may
        actually refer to a different issuer. If the AV `delistingDate` is
        more than `max_days_off` from `observed_date`, the AV name is for
        the prior issuer and we should NOT use it as a resolver hint.
        """
        row = self.get(ticker)
        if not row:
            return None
        if observed_date and row.delist_date:
            try:
                from datetime import datetime
                ad = datetime.strptime(row.delist_date, "%Y-%m-%d").date()
                od = datetime.strptime(observed_date, "%Y-%m-%d").date()
                if abs((ad - od).days) > max_days_off:
                    return None
            except ValueError:
                pass
        return row.name

    def asset_type(self, ticker: str, observed_date: str | None = None,
                   max_days_off: int = 365) -> str | None:
        row = self.get(ticker)
        if not row:
            return None
        if observed_date and row.delist_date:
            try:
                from datetime import datetime
                ad = datetime.strptime(row.delist_date, "%Y-%m-%d").date()
                od = datetime.strptime(observed_date, "%Y-%m-%d").date()
                if abs((ad - od).days) > max_days_off:
                    return None
            except ValueError:
                pass
        return row.asset_type

    def exchange(self, ticker: str, observed_date: str | None = None,
                 max_days_off: int = 365) -> str | None:
        row = self.get(ticker)
        if not row:
            return None
        if observed_date and row.delist_date:
            try:
                from datetime import datetime
                ad = datetime.strptime(row.delist_date, "%Y-%m-%d").date()
                od = datetime.strptime(observed_date, "%Y-%m-%d").date()
                if abs((ad - od).days) > max_days_off:
                    return None
            except ValueError:
                pass
        return row.exchange
