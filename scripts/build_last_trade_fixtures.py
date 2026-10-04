"""Build tests/fixtures/last_trade/ from the local caches, once (sub-plan 5d): the real cases whose last trade date
tests/test_last_trade_cases.py replays offline through the run's own code (tests/last_trade_cases.py): the finder's
8-K and notice readers, its MIDAS and halt reads bounded by the ticker's tenure, the closing day, and the fails
close of the last trade day.

  PYTHONPATH=src python scripts/build_last_trade_fixtures.py          # -> tests/fixtures/last_trade/

It is scripts/build_issuer_role_fixtures.py (5c) over this sub-plan's cases: the same files (cases.json,
edgar.json.gz, figi.json, ftd_rows.csv.gz, midas.json, halts.json), built the same offline way from the committed
output/ and the caches (every SEC request refused; a missing answer is left out, never fetched). SUPPORT holds the
securities whose CUSIPs bound a case's ticker (the successor that took it) or name another security's close.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_issuer_role_fixtures as b5c  # noqa: E402  (refuses every SEC request on import)

CASES = {
    # rule 1: the 3.01 section read sentence by sentence
    "BBG000BH2T94": "GLBL 2011: suspended after the close of trading on NASDAQ on December 1 (rule 1)",
    "BBG000BQ3F39": "NOVL 2011: at the close of business on April 27 ... ceased trading, past a cross-reference (rule 1)",
    "BBG000C0BGS7": "SEPR 2009: ceased effective as of the close of trading on October 20 (rule 1)",
    "BBG000FRVFM1": "PPDI 2011: suspended after the closing of trading on December 5 (rule 1)",
    "BBG000KBQZ88": "CTRX 2015: ceases trading as of the close of trading on the Closing Date (rule 1)",
    "BBG000CB2ZY4": "KG 2011: continue to be listed through February 28 (rule 1)",
    "CIK351346-COMMON": "BMET 2007: withdrawn from listing as of the close of business on September 25 (rule 1)",
    "BBG00ZHCT050": "DSEY 2023: halted following the closing of trading on the Closing Date (rule 1)",
    "BBG01HMFL081": "LLYVA 2025: delisted following the Effective Time, 4:05 p.m. (rule 1)",
    "BBG01HMFLTN1": "LLYVK 2025: delisted following the Effective Time, 4:05 p.m. (rule 1)",
    "BBG00VNLZL95": "TMUSR 2020: Subscription Rights Expiring 7/27/2020, the notice empty (rule 1)",
    # rule 2: source order and R8
    "BBG003PGJHP5": "TMHC 2026: the 8-K's following the closing of trading beats the notice's bare date (rule 2)",
    "BBG002BHBHM1": "MNK 2020: suspended on October 12, no timing word: the 9th (R8, rule 2)",
    "BBG000FXYZF9": "WM 2008: the 8-K puts the feed's 09:30:06 halt at the NYSE market open on September 26: the 25th (R8, rule 2)",
    "BBG000BCTL84": "PMI 2011: halted on October 21, the last day it traded (rule 2)",
    # rule 3: the ticker's tenure
    "BBG000BF5RY1": "CCE 2016: MIDAS's May 31 under CCE is CCEP's (rule 3)",
    "BBG000BMDV41": "JCI 2016: MIDAS's September 6 under JCI is Johnson Controls plc's (rule 3)",
    "BBG001KWG293": "GRUB 2021: MIDAS's June 15 under GRUB is Just Eat Takeaway's ADS (rule 3, ruling)",
    "BBG000BF1R66": "CB 2016: MIDAS's January 15 under CB is Chubb Ltd's (rule 3, outside the truth set)",
    "BBG000BHW628": "WCN 2016: MIDAS's June 1 under WCN is the new Waste Connections' (rule 3, outside)",
    "BBG000D1QCF1": "FTI 2017: MIDAS's January 17 under FTI is TechnipFMC's (rule 3, outside)",
    "BBG000BWPN99": "WEN 2008: the close by symbol is Wendy's/Arby's new CUSIP's (rule 3, the fails close)",
    # rule 4: the closing day
    "BBG000BB5HV5": "ADCT 2010: effected the short-form merger on December 9 (rule 4)",
    "BBG000BHD665": "CDWC 2007: the Closing Date October 12 (rule 4)",
    "BBG000BK7SL0": "GENZ 2011: completed its acquisition on April 8 (rule 4)",
    "BBG000BPQD31": "MYL 2020: the closing of the transactions on November 16 (rule 4)",
    "BBG000C1R174": "HLTH 2009: no completion text; the Form 25 day (rule 4)",
    "CIK1319048-COMMON": "CHAP 2007: no 8-K cached; the Form 25 day (rule 4)",
    "CIK709519-COMMON": "SUNW 2010: suspended on completion, January 26 (rule 4)",
    "BBG000CGQ485": "IMCL 2008: effective at 8:28 A.M. on November 24: the 21st (rule 4)",
    "BBG000FHN2M1": "CKFR 2007: completed the evening of December 3 (rule 4)",
    "BBG000CNZC55": "ODP 2020: the effective time 8:00 p.m. on June 30 (rule 4)",
    "BBG000BC2C10": "APA 2021: implemented the reorganization on March 1 (rule 4)",
    "BBG000BM1RP0": "FCL 2009: no Form 25; merged on July 31 (rule 4, the fallback)",
    "BBG000BSVZM9": "SGP 2009: no Form 25; the Closing Date November 3 (rule 4, the fallback)",
    "BBG002B67HB2": "UNIT 2025: no Form 25; completed on August 1 (rule 4, the fallback)",
    "BBG000BX67G5": "MLNM 2008: the Form 25 day, May 14 (rule 4; the press release is an exhibit)",
    "CIK867773-COMMON": "SPWRA 2011: the Form 25 day, November 16 (rule 4)",
    "BBG000BJ3QD0": "DADE 2007: the Form 25 day (rule 4; the truth's November 5 is residual)",
    "BBG000BJXXX0": "IFIN 2007: the Form 25 day (rule 4; the truth's June 29 is residual)",
    "BBG000BKKXG0": "PHLY 2008: the code-D halt at 08:50 on the Form 25 day, December 1: November 28 (rule 2, ruling)",
    # guards
    "BBG000BGYDX9": "DBD 2023: MIDAS's May 26 stands; the same CUSIP went to DBDQQ (guard, ruling)",
    "BBG00GBV88T6": "BTU 2016: no own row under BTU in the window, so no tenure bound (guard)",
    "BBG00Z6DX554": "CHK 2020: no own row under CHK in the window, so no tenure bound (guard)",
    "BBG005DKMJ67": "LTRPA 2023: MIDAS's October 27 stands (guard)",
    "BBG000BV18Z1": "TDW 2017: a bankruptcy fallback keeps its last sighting (guard)",
    "BBG000C070N2": "XMSR 2008: the Nasdaq halt's July 28 (guard)",
    "BBG005CPNTQ2": "KHC 2026: a continuing move to the NYSE, its last Nasdaq day read (rule 1; no ending)",
    "BBG000BT0093": "SIRI 2024: no text day, so MIDAS is not bounded by New Sirius's start (guard)",
    "BBG000C1TTV4": "HET 2008: the feed's 09:30:05 halt against the 8-K's close of business on January 28 (guard)",
    "BBG000C0NY96": "TCF 2019: the new TCF's first fails row carries Chemical's close; no MIDAS bound (guard)",
    "BBG000F2XXP2": "SBGI 2023: Sinclair Inc's first fails row lags its first day; no MIDAS bound (guard)",
    "BBG000PTXBV3": "HTS 2016: the 8-K's following the close of trading on July 12 beats the notice's bare date (rule 2, ruling)",
}

# The securities whose CUSIPs bound a case's ticker or hold another security's close under its symbol
SUPPORT = {
    "BBG000BVWLJ6": "TYC/JCI (Johnson Controls plc)", "BBG000D52545": "WEN (Wendy's/Arby's)",
    "BBG000BR14K5": "CB (Chubb Ltd)", "BBG00DL8NMV2": "FTI (TechnipFMC)",
    "BBG01YY256K1": "LLYVA (Liberty Live Holdings)", "BBG01YYX1Z14": "LLYVK (Liberty Live Holdings)",
    "BBG00Y4RQNH4": "VTRS", "BBG00R24W7X2": "ODP (The ODP Corp)", "BBG00YTS96G2": "APA (APA Corp)",
}


def main(argv: list[str] | None = None) -> int:
    b5c.CASES, b5c.SUPPORT = CASES, SUPPORT
    argv = list(argv or [])
    if "--out" not in argv:
        argv += ["--out", str(ROOT / "tests" / "fixtures" / "last_trade")]
    return b5c.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
