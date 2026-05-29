"""Regenerate golden payout fixtures from live SEC EDGAR. Not run in CI.

Run manually:  python scripts/regen_payout_fixtures.py
"""
from pathlib import Path

from delist_detection import EdgarClient

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"

CASES = [
    # (out_name, cik, accession, primary_doc)
    ("altr_8k_201.txt", 1701732, "0001193125-25-066329", "d869190d8k.htm"),
    ("atvi_8k_201.txt", 718877, "0001104659-23-108985", "tm2328253d1_8k.htm"),
]


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    for name, cik, acc, doc in CASES:
        text = edgar.fetch_filing_text(cik, acc, doc)
        assert text, f"empty fetch for {name}"
        (FIX / name).write_text(text)
        print(f"wrote {name} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
