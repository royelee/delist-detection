"""Pure file-IO loader over the Tiingo raw price CSVs.

Provides `RawTiingoPrices`, a thin helper that reads per-ticker CSV files and
returns the nominal close price for a given date.  Results are cached in-memory
per ticker so repeated lookups within a process don't re-read the file.

Root resolution order:
1. Explicit ``root`` argument.
2. ``RAW_TIINGO_DIR`` environment variable.
3. Default path relative to the repo: ``../qlib_practice/fetch_data_aplha/
   data/tiingo_2026_05_22/raw_tiingo_csv`` (resolved from the package file's
   location up to the repository root).

CSV format (per-ticker file ``{ticker.lower()}.csv``):
    date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,
    adjVolume,divCash,splitFactor

The nominal ``close`` column (not ``adjClose``) is used for all lookups.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Default path: resolve relative to this file's location.
# Path(__file__) → src/delist_detection/raw_tiingo.py
#   parents[0] → src/delist_detection/
#   parents[1] → src/
#   parents[2] → <repo root>  (delist_detection/)
#   parents[2].parent → <repo root's parent>
_DEFAULT_ROOT = (
    Path(__file__).resolve().parents[2].parent
    / "qlib_practice"
    / "fetch_data_aplha"
    / "data"
    / "tiingo_2026_05_22"
    / "raw_tiingo_csv"
)


class RawTiingoPrices:
    """Look up nominal close prices from raw Tiingo per-ticker CSV files.

    Parameters
    ----------
    root:
        Directory containing the per-ticker CSV files (e.g. ``aet.csv``).
        When *None*, resolution falls back to the ``RAW_TIINGO_DIR``
        environment variable, then to the hardcoded default qlib_practice path.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        if root is not None:
            self._root = Path(root)
        else:
            env = os.environ.get("RAW_TIINGO_DIR")
            self._root = Path(env) if env else _DEFAULT_ROOT
        # Per-ticker cache: ticker_lower -> pd.Series(date_str -> close_float)
        # indexed by the date string, sorted ascending.
        self._cache: dict[str, pd.Series | None] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close_on(self, ticker: str, date: str) -> float | None:
        """Return the nominal close price for *ticker* on *date*.

        If *date* is not a trading day present in the file, returns the close
        of the nearest prior trading day (i.e. the last row with
        ``row.date <= date``).

        Returns *None* if:
        - *ticker* is blank / None.
        - The ticker's CSV file does not exist.
        - There is no row on or before *date*.
        """
        if not ticker or not ticker.strip():
            return None

        series = self._load(ticker)
        if series is None:
            return None

        # Select rows up to and including date.
        candidates = series[series.index <= date]
        if candidates.empty:
            return None

        return float(candidates.iloc[-1])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, ticker: str) -> pd.Series | None:
        """Load (or retrieve from cache) the close series for *ticker*.

        Returns a ``pd.Series`` indexed by date strings (``YYYY-MM-DD``,
        ascending), or *None* if the file does not exist.
        """
        key = ticker.lower().strip()
        if key in self._cache:
            return self._cache[key]

        path = self._root / f"{key}.csv"
        try:
            df = pd.read_csv(path, usecols=["date", "close"], dtype={"date": str, "close": float})
        except FileNotFoundError:
            self._cache[key] = None
            return None

        # Sort by date string (ISO format sorts lexicographically = chronologically).
        df = df.sort_values("date").reset_index(drop=True)
        series = df.set_index("date")["close"]
        self._cache[key] = series
        return series
