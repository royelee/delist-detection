"""List currently-unknown classifications with their AV company name.

Useful as input when curating MANUAL_OVERRIDES — saves you from looking
each ticker up by hand.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLS = ROOT / "output" / "delist_classifications.csv"
# Override with AV_LISTING_CSV; default assumes qlib_practice is a sibling repo.
AV = Path(os.environ.get(
    "AV_LISTING_CSV",
    str(ROOT.parent / "qlib_practice" / "fetch_data_aplha"
        / "data" / "alphavantage_listing_status"
        / "listing_status_delisted_2026-05-19.csv")))


def main() -> int:
    av_names: dict[str, dict] = {}
    with AV.open() as fh:
        for r in csv.DictReader(fh):
            t = (r.get("symbol") or "").upper()
            if t and t not in av_names:
                av_names[t] = r
    with CLS.open() as fh:
        rows = list(csv.DictReader(fh))
    unknowns = [r for r in rows if r["bucket"] == "unknown"]
    print(f"Total: {len(rows)}  Unknown: {len(unknowns)}")
    print()
    for r in sorted(unknowns, key=lambda x: x["observed_delist_date"]):
        av = av_names.get(r["ticker"].upper(), {})
        print(f"{r['ticker']:8s} {r['observed_delist_date']:>10s} "
              f"name={av.get('name','?'):40s}  exch={av.get('exchange','?'):8s} "
              f"reason={r['reason'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
