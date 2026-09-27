"""Apply BMP 2007 firm-month corrections to a monthly panel keyed by sec_id.

    PYTHONPATH=src python scripts/compute_corrected_returns.py \
        --panel data/monthly_panel.parquet --delistings output/delistings.csv \
        --out output/corrected_monthly_panel.parquet

--panel: parquet/csv with (date, instrument) where instrument is the sec_id, and
         columns close, monthly_return; dates are month-ends.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from delist_detection.qlib_adapter import apply_bmp_corrections

ROOT = Path(__file__).resolve().parents[1]


def _read_panel(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, parse_dates=["date"])
    if not isinstance(df.index, pd.MultiIndex):
        df = df.set_index(["date", "instrument"]).sort_index()
    return df


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--panel", required=True, type=Path)
    p.add_argument("--delistings", default=str(ROOT / "output" / "delistings.csv"))
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    out = apply_bmp_corrections(_read_panel(args.panel), args.delistings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out) if args.out.suffix == ".parquet" else out.to_csv(args.out)
    print(f"Wrote {args.out}: {len(out)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
