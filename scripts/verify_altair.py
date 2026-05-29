"""End-to-end sanity check: ALTR (Altair Engineering) → CRSP 231 M&A."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "edgar"

from delist_detection import EdgarClient, TickerResolver, DelistClassifier
from delist_detection.crsp_codes import CrspBucket


def main() -> int:
    edgar = EdgarClient(cache_dir=CACHE)
    resolver = TickerResolver(edgar, cache_path=ROOT / "cache" / "ticker_resolution.json")
    classifier = DelistClassifier(edgar, resolver)

    rec = classifier.classify_ticker("ALTR", observed_delist_date="2025-03-26")
    print(json.dumps(rec.to_dict(), indent=2, default=str))

    ok = (
        rec.bucket == CrspBucket.MERGER
        and rec.crsp_code in (200, 231, 233)
        and rec.confidence in ("high", "medium")
    )
    if not ok:
        print("VERIFICATION FAILED", file=sys.stderr)
        return 1
    print("\nVERIFIED: ALTR classified as", rec.bucket.value, "code", rec.crsp_code,
          "with", rec.confidence, "confidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
