"""Build tests/fixtures/distress/ from the local caches, once (sub-plan 5g): the real cases whose bankruptcy and
liquidation endings (stage 5) and whose drop reason, bankruptcy plan exchange and OTC symbol (pipeline stage 9e)
tests/test_distress_cases.py replays offline through the run's own code (tests/distress_cases.py).

  PYTHONPATH=src python scripts/build_distress_fixtures.py [--repo PATH]   # -> tests/fixtures/distress/

It is scripts/build_form25_fixtures.py run over this sub-plan's cases (the same files: cases.json, ftd_rows.csv.gz,
edgar.json.gz, midas.json, halts.json; every fails row of a case's CUSIPs, every cached Form 25 raw and every cached
8-K text with item 1.03 or 3.01 of its issuer). `--repo` names a checkout holding the committed output/ and the
caches (cache/); the caches are only read: every SEC request is refused, and the EDGAR client neither writes a cache
entry nor removes a temp file."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_form25_fixtures as b5  # noqa: E402  (refuses every SEC request on import)
import delist_detection.sources.edgar as edgar_mod  # noqa: E402

edgar_mod.write_atomic = lambda *a, **k: None          # the caches are read, never written...
edgar_mod.clean_orphan_temps = lambda *a, **k: None    # ...nor cleaned: another run may be writing them

# The cases: securities of the committed run, each with what it pins
CASES = {
    # the 5g truth cases
    "BBG000B9YSK6": "CBL 2020: a bankruptcy 8-K whose item heading reads 'ITEM 1 .0 3'; OTC as CBLAQ",
    "BBG000BBG3P1": "TMA 2008: the NYSE's notice cites the $1 price only (552, was 580); OTC as THMR",
    "BBG000BG09F5": "GPOR 2020: OTC as GPORQ (the Nasdaq symbol later reused)",
    "BBG000BG14P4": "WOLF 2025: a plan exchange, the ratio from the plan 8-K's counts (R6)",
    "BBG000BKQ3V3": "SDRL 2018: a plan exchange the Form 25 notice states, no 8-K items (R6)",
    "BBG000BLY636": "IMB 2008: OTC as IDMC",
    "BBG000BRF6B5": "RHD 2009: market capitalization beside the price (guidelines); OTC as RHDC",
    "BBG000BRWGG9": "RAD 2023: OTC as RADCQ",
    "BBG000DY8ZS4": "WFT 2019: no Form 25, a price-only 3.01 (552); OTC as WFTIF before WFTIQ",
    "BBG000PSSG77": "IAR 2008: a price-only notice (552); OTC as IDAR",
    "BBG005DKMJ67": "LTRPA 2023: Nasdaq's bid-price rule 5450(a)(1) (552); trades on under LTRPA",
    "BBG009NGKQ45": "VRM 2024: OTC as VRMMQ",
    "BBG00D1WHZD9": "HTZ 2020: OTC as HTZGQ",
    "BBG00GBV88T6": "BTU 2016: the fails rows lack its post-split CUSIP; the 3.01 names BTUUQ",
    "BBG00HY28P97": "GTX 2020: OTC as GTXMQ, which its ticker history also carries",
    "BBG000BJ3CN0": "CWTR 2014: OTC as CWTRQ",
    "BBG000BP62Y3": "MNI 2020: OTC as MNIQQ",
    "BBG000BGZ9V9": "ASNA 2020: OTC as ASNAQ",
    "BBG000FH5YM1": "FTR 2020: OTC as FTRCQ",
    "CIK38079-COMMON": "FST 2014: a back-door listing beside the price (guidelines); OTC as FSTO",
    "CIK886835-COMMON": "SPNV 2020: market capitalization (guidelines); the 3.01 names SPNX",
    "BBG000BBMT95": "DF 2019: OTC as DFODQ",
    "BBG000BLG1L7": "EQC 2025: a voluntary delisting during the liquidation (end-of-era liquidation)",
    "BBG000BMLYZ2": "KWK 2015: an abnormally low price only (552); OTC as KWKA",
    "BBG0057K5Y79": "EPE 2019: an abnormally low price only (552); OTC as EPEG",
    # what must not change, or changes as the rules say
    "BBG000BF2JS9": "CNB 2009: fails settling under CNB, no OTC symbol read (blank)",
    "BBG000BV18Z1": "TDW 2017: a prepackaged plan without a Form 25: no plan rule",
    "BBG009R0CVG1": "LKSD 2019: market capitalization (guidelines); OTC under LKSD itself",
    "BBG000BLDXH5": "MDRX 2024: a late 10-K (guidelines); OTC under MDRX itself",
    "BBG000PX3XC0": "WLL 2020: a plan exchange that states no ratio (no stock rule)",
    "BBG000BC2C10": "APA 2021: a holding company's 12d2-2(a)(3) notice, no bankruptcy (unchanged)",
    "BBG000BT0CM2": "SIVB 2023: fails settling under SIVB, no OTC symbol read (blank)",
    "BBG00ZSDS6T8": "TSP 2024: the issuer's own Form 25 (no price reason read)",
    "BBG000CPZ0F5": "PDLI 2020: the issuer's own Form 25; OTC under PDLI itself",
    "BBG000BCTL84": "PMI 2011: halted, suspended 38 days later; fails relabelled OTC prints, then PPMIQ",
    "BBG00Z6DX554": "CHK 2020: no fails under its CUSIP; the 3.01 names CHKAQ",
}

# WOLF's new CUSIP, which shares its ticker: its rows must not price the old line's last close
EXTRA_CUSIPS = ("97785W106",)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "distress")
    p.add_argument("--repo", type=Path, default=ROOT)
    args = p.parse_args(argv)
    b5.CASES, b5.EXTRA_CIKS, b5.EXTRA_CUSIPS = CASES, (), EXTRA_CUSIPS
    return b5.main(["--out", str(args.out), "--repo", str(args.repo)])


if __name__ == "__main__":
    sys.exit(main())
