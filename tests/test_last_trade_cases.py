"""Sub-plan 5d's real cases: what the run gives each security of tests/fixtures/last_trade/ (built once, offline,
from the local caches by scripts/build_last_trade_fixtures.py), through the run's own stage-5 finder and stage-7
fails close (tests/last_trade_cases.py). An outcome is the case's delistings, each (delist_date, bucket, last trade
day, its source, whether it is unconfirmed, the fails close of that day). A case the sub-plan moves (MOVES) has its
rule's outcome once the rule is in RULES_DONE, else its outcome before 5d; a guard (STAY) keeps its outcome
throughout. The rules (docs/superpowers/plans/research/2026-10-04-5d-last-trade.md): rule1, the 3.01 section read
sentence by sentence (and a rights class's expiry); rule2, the source order (ruling R8, an 8-K timing over a notice's
bare date, a halt at the open, the halt feed asked on the Form 25 day); rule3, the ticker's tenure bounding a read by
ticker; rule4, the closing day when nothing states the last trade."""
from __future__ import annotations

import pytest

from tests import last_trade_cases as lc

RULES_DONE: set[str] = {"rule1", "rule2", "rule3", "rule4"}

# sec_id -> (the rule that moves it, its outcome before 5d, its outcome after)
MOVES = {
    'BBG000BB5HV5': ('rule4', [('2010-12-19', 'merger', '', '', False, None)],
        [('2010-12-19', 'merger', '2010-12-09', 'closing_day', True, 12.76)]),   # ADCT 2010: effected the short-form merger on December 9 (rule 4)
    'BBG000BC2C10': ('rule4', [('2021-03-14', 'exchange_transfer', '', '', False, None)],
        [('2021-03-14', 'exchange_transfer', '2021-03-01', 'closing_day', True, 19.52)]),   # APA 2021: implemented the reorganization on March 1 (rule 4)
    'BBG000B9YSK6': ('rule1', [('2020-11-02', 'liquidation', '', '', True, 0.05)],
        [('2020-11-02', 'liquidation', '2020-10-30', '8k_301', False, 0.15)]),   # CBL 2020: "On November 2 ... had been suspended from trading": the 30th (R8, date first)
    'BBG000BBG3P1': ('rule1', [('2009-01-25', 'compliance_failure', '2008-12-01', 'ex99_notice', True, 0.38)],
        [('2009-01-25', 'compliance_failure', '2008-12-04', '8k_301', False, 0.24)]),   # TMA 2008: "prior to market opening on Friday, December 5" (weekday); the (b) notice's 12-01 is the press day
    'BBG000PSSG77': ('rule1', [('2009-01-01', 'compliance_failure', '2008-11-19', 'ex99_notice', True, 0.14)],
        [('2009-01-01', 'compliance_failure', '2008-11-20', '8k_301', False, 0.02)]),   # IDARQ 2008: "prior to the market opening on Friday, November 21" (weekday)
    'BBG009NGKQ45': ('rule1', [('2024-11-13', 'liquidation', '2024-12-02', '', True, 5.99)],
        [('2024-11-13', 'liquidation', '2024-11-29', '8k_301', False, 5.0)]),   # VRM 2024: no Form 25; the 3.01 8-K came 13 days after the bankruptcy 8-K (the fallback's window)
    'BBG000BCTL84': ('rule2', [('2012-01-08', 'liquidation', '2011-11-23', 'ex99_notice', True, 0.31)],
        [('2012-01-08', 'liquidation', '2011-10-21', '8k_301', False, 0.31)]),   # PMI 2011: halted on October 21, the last day it traded (rule 2)
    'BBG000BF1R66': ('rule3', [('2016-01-24', 'merger', '2016-01-15', 'midas', False, 127.26)],
        [('2016-01-24', 'merger', '2016-01-14', 'midas', False, 127.26)]),   # CB 2016: MIDAS's January 15 under CB is Chubb Ltd's (rule 3, outside the truth set)
    'BBG000BF5RY1': ('rule3', [('2016-06-10', 'merger', '2016-05-31', 'midas', False, 51.55)],
        [('2016-06-10', 'merger', '2016-05-27', 'midas', False, 51.55)]),   # CCE 2016: MIDAS's May 31 under CCE is CCEP's (rule 3)
    'BBG000BH2T94': ('rule1', [('2011-12-11', 'merger', '', '', False, None)],
        [('2011-12-11', 'merger', '2011-12-01', '8k_301', False, 8.01)]),   # GLBL 2011: suspended after the close of trading on NASDAQ on December 1 (rule 1)
    'BBG000BHD665': ('rule4', [('2007-10-22', 'merger', '', '', False, None)],
        [('2007-10-22', 'merger', '2007-10-12', 'closing_day', True, 87.72)]),   # CDWC 2007: the Closing Date October 12 (rule 4)
    'BBG000BHW628': ('rule3', [('2016-06-11', 'merger', '2016-06-01', 'midas', False, 67.18)],
        [('2016-06-11', 'merger', '2016-05-31', 'midas', False, 65.47)]),   # WCN 2016: MIDAS's June 1 under WCN is the new Waste Connections' (rule 3, outside)
    'BBG000BJ3QD0': ('rule4', [('2007-11-16', 'merger', '', '', False, None)],
        [('2007-11-16', 'merger', '2007-11-06', 'closing_day', True, 76.98)]),   # DADE 2007: the Form 25 day (rule 4; the truth's November 5 is residual)
    'BBG000BJXXX0': ('rule4', [('2007-07-12', 'merger', '', '', False, None)],
        [('2007-07-12', 'merger', '2007-07-02', 'closing_day', True, None)]),   # IFIN 2007: the Form 25 day (rule 4; the truth's June 29 is residual)
    'BBG000BK7SL0': ('rule4', [('2011-04-18', 'merger', '', '', False, None)],
        [('2011-04-18', 'merger', '2011-04-08', 'closing_day', True, 76.15)]),   # GENZ 2011: completed its acquisition on April 8 (rule 4)
    'BBG000BKKXG0': ('rule2', [('2008-12-11', 'merger', '', '', False, None)],
        [('2008-12-11', 'merger', '2008-11-28', 'nasdaq_halt', False, 61.45)]),   # PHLY 2008: the code-D halt at 08:50 on the Form 25 day, December 1: November 28 (rule 2, ruling)
    'BBG000BM1RP0': ('rule4', [('2009-08-14', 'merger', '2009-08-14', '', True, 35.93)],
        [('2009-08-14', 'merger', '2009-07-31', 'closing_day', True, 35.83)]),   # FCL 2009: no Form 25; merged on July 31 (rule 4, the fallback)
    'BBG000BMDV41': ('rule3', [('2016-09-16', 'merger', '2016-09-06', 'midas', False, 48.9)],
        [('2016-09-16', 'merger', '2016-09-02', 'midas', False, 45.04)]),   # JCI 2016: MIDAS's September 6 under JCI is Johnson Controls plc's (rule 3)
    'BBG000BPQD31': ('rule4', [('2020-11-26', 'merger', '', '', False, None)],
        [('2020-11-26', 'merger', '2020-11-16', 'closing_day', True, 15.86)]),   # MYL 2020: the closing of the transactions on November 16 (rule 4)
    'BBG000BQ3F39': ('rule1', [('2011-05-07', 'merger', '', '', False, None)],
        [('2011-05-07', 'merger', '2011-04-27', '8k_301', False, 6.1)]),   # NOVL 2011: at the close of business on April 27 ... ceased trading, past a cross-reference (rule 1)
    'BBG000BSVZM9': ('rule4', [('2009-11-04', 'merger', '2009-11-04', '', True, 28.15)],
        [('2009-11-04', 'merger', '2009-11-03', 'closing_day', True, 28.15)]),   # SGP 2009: no Form 25; the Closing Date November 3 (rule 4, the fallback)
    'BBG000BWPN99': ('rule3', [('2008-10-11', 'merger', '2008-09-29', 'ex99_notice', False, 5.26)],
        [('2008-10-11', 'merger', '2008-09-29', 'ex99_notice', False, 22.15)]),   # WEN 2008: the close by symbol is Wendy's/Arby's new CUSIP's (rule 3, the fails close)
    'BBG000BX67G5': ('rule4', [('2008-05-24', 'merger', '', '', False, None)],
        [('2008-05-24', 'merger', '2008-05-14', 'closing_day', True, 24.97)]),   # MLNM 2008: the Form 25 day, May 14 (rule 4; the press release is an exhibit)
    'BBG000C0BGS7': ('rule1', [('2009-10-30', 'merger', '', '', False, None)],
        [('2009-10-30', 'merger', '2009-10-20', '8k_301', False, 22.99)]),   # SEPR 2009: ceased effective as of the close of trading on October 20 (rule 1)
    'BBG000C1R174': ('rule4', [('2009-11-02', 'merger', '', '', False, None)],
        [('2009-11-02', 'merger', '2009-10-23', 'closing_day', True, 15.23)]),   # HLTH 2009: no completion text; the Form 25 day (rule 4)
    'BBG000CB2ZY4': ('rule1', [('2011-02-28', 'merger', '', '', False, None)],
        [('2011-02-28', 'merger', '2011-02-28', '8k_301', False, 14.24)]),   # KG 2011: continue to be listed through February 28 (rule 1)
    'BBG000CGQ485': ('rule4', [('2008-12-04', 'merger', '', '', False, None)],
        [('2008-12-04', 'merger', '2008-11-21', 'closing_day', True, 69.95)]),   # IMCL 2008: effective at 8:28 A.M. on November 24: the 21st (rule 4)
    'BBG000CNZC55': ('rule4', [('2014-10-06', 'exchange_transfer', '', '', False, None), ('2020-07-11', 'exchange_transfer', '', '', False, None)],
        [('2014-10-06', 'exchange_transfer', '2014-09-25', '8k_301', False, 5.31), ('2020-07-11', 'exchange_transfer', '2020-06-30', 'closing_day', True, 2.35)]),   # ODP 2020: the effective time 8:00 p.m. on June 30 (rule 4)
    'BBG000D1QCF1': ('rule3', [('2017-01-27', 'merger', '2017-01-17', 'midas', False, 35.85)],
        [('2017-01-27', 'merger', '2017-01-13', 'midas', False, 35.85)]),   # FTI 2017: MIDAS's January 17 under FTI is TechnipFMC's (rule 3, outside)
    'BBG000FHN2M1': ('rule4', [('2007-12-14', 'merger', '', '', False, None)],
        [('2007-12-14', 'merger', '2007-12-03', 'closing_day', True, 47.51)]),   # CKFR 2007: completed the evening of December 3 (rule 4)
    'BBG000FRVFM1': ('rule1', [('2011-12-15', 'merger', '', '', False, None)],
        [('2011-12-15', 'merger', '2011-12-05', '8k_301', False, 33.19)]),   # PPDI 2011: suspended after the closing of trading on December 5 (rule 1)
    'BBG000FXYZF9': ('rule2', [('2008-11-10', 'liquidation', '2008-09-29', 'ex99_notice', True, 0.16)],
        [('2008-11-10', 'liquidation', '2008-09-25', '8k_301', False, 1.69)]),   # WM 2008: the 8-K puts the feed's 09:30:06 halt at the NYSE market open on September 26: the 25th (R8, rule 2)
    'BBG000KBQZ88': ('rule1', [('2015-08-02', 'merger', '', '', False, None)],
        [('2015-08-02', 'merger', '2015-07-23', '8k_301', False, 61.47)]),   # CTRX 2015: ceases trading as of the close of trading on the Closing Date (rule 1)
    'BBG000PTXBV3': ('rule2', [('2016-07-22', 'merger', '2016-07-11', 'ex99_notice', False, 16.29)],
        [('2016-07-22', 'merger', '2016-07-12', '8k_301', False, 16.29)]),   # HTS 2016: the 8-K's following the close of trading on July 12 beats the notice's bare date (rule 2, ruling)
    'BBG001KWG293': ('rule3', [('2021-06-25', 'merger', '2021-06-15', 'midas', False, 59.89)],
        [('2021-06-25', 'merger', '2021-06-14', 'midas', False, 59.89)]),   # GRUB 2021: MIDAS's June 15 under GRUB is Just Eat Takeaway's ADS (rule 3, ruling)
    'BBG002B67HB2': ('rule4', [('2025-08-01', 'merger', '2025-08-04', '', True, 4.91)],
        [('2025-08-01', 'merger', '2025-08-01', 'closing_day', True, 4.91)]),   # UNIT 2025: no Form 25; completed on August 1 (rule 4, the fallback)
    'BBG002BHBHM1': ('rule2', [('2020-10-23', 'liquidation', '2020-10-12', 'ex99_notice', True, 0.75)],
        [('2020-10-23', 'liquidation', '2020-10-09', '8k_301', False, 0.75)]),   # MNK 2020: suspended on October 12, no timing word: the 9th (R8, rule 2)
    'BBG003PGJHP5': ('rule2', [('2026-08-03', 'merger', '2026-07-23', 'ex99_notice', False, 72.45)],
        [('2026-08-03', 'merger', '2026-07-24', '8k_301', False, 72.45)]),   # TMHC 2026: the 8-K's following the closing of trading beats the notice's bare date (rule 2)
    'BBG005CPNTQ2': ('rule1', [('2026-09-18', 'exchange_transfer', '', '', False, None)],
        [('2026-09-18', 'exchange_transfer', '2026-09-11', '8k_301', False, 25.7)]),   # KHC 2026: a continuing move to the NYSE, its last Nasdaq day read (rule 1; no ending)
    'BBG00VNLZL95': ('rule1', [('2020-08-06', 'expiration', '', '', False, None)],
        [('2020-08-06', 'expiration', '2020-07-27', 'ex99_notice', False, 0.14)]),   # TMUSR 2020: Subscription Rights Expiring 7/27/2020, the notice empty (rule 1)
    'BBG00ZHCT050': ('rule1', [('2023-07-15', 'merger', '', '', False, None)],
        [('2023-07-15', 'merger', '2023-07-05', '8k_301', False, 8.39)]),   # DSEY 2023: halted following the closing of trading on the Closing Date (rule 1)
    'BBG01HMFL081': ('rule1', [('2025-12-25', 'merger', '', '', False, None)],
        [('2025-12-25', 'merger', '2025-12-15', '8k_301', False, 82.97)]),   # LLYVA 2025: delisted following the Effective Time, 4:05 p.m. (rule 1)
    'BBG01HMFLTN1': ('rule1', [('2025-12-25', 'merger', '', '', False, None)],
        [('2025-12-25', 'merger', '2025-12-15', '8k_301', False, 85.12)]),   # LLYVK 2025: delisted following the Effective Time, 4:05 p.m. (rule 1)
    'CIK1319048-COMMON': ('rule4', [('2007-09-24', 'merger', '', '', False, None)],
        [('2007-09-24', 'merger', '2007-09-14', 'closing_day', True, 85.91)]),   # CHAP 2007: no 8-K cached; the Form 25 day (rule 4)
    'CIK351346-COMMON': ('rule1', [('2007-10-05', 'merger', '', '', False, None)],
        [('2007-10-05', 'merger', '2007-09-25', '8k_301', False, 45.99)]),   # BMET 2007: withdrawn from listing as of the close of business on September 25 (rule 1)
    'CIK709519-COMMON': ('rule4', [('2010-02-05', 'merger', '', '', False, None)],
        [('2010-02-05', 'merger', '2010-01-26', 'closing_day', True, None)]),   # SUNW 2010: suspended on completion, January 26 (rule 4)
    'CIK867773-COMMON': ('rule4', [('2011-11-26', 'exchange_transfer', '', '', False, None)],
        [('2011-11-26', 'exchange_transfer', '2011-11-16', 'closing_day', True, 7.22)]),   # SPWRA 2011: the Form 25 day, November 16 (rule 4)
    'BBG009XV39D8': ('rule4', [('2018-04-14', 'merger', '', '', False, None)],
        [('2018-04-14', 'merger', '2018-04-04', 'closing_day', True, 236.99)]),   # AVGO 2018: the scheme effective after the close on April 4; the fails rows trade to it (rule 4, the fails rows)
    'CIK1334814-CLASS-A': ('rule4', [('2015-02-27', 'merger', '', '', False, None)],
        [('2015-02-27', 'merger', '2015-02-17', 'closing_day', True, 109.14)]),   # Z 2015: the 8-K12B halts trading at the close on February 17; the fails rows trade to it (rule 4, the fails rows)
    'BBG000BFMBQ6': ('rule4', [('2018-12-31', 'merger', '', '', False, None)],
        [('2018-12-31', 'merger', '2018-12-20', 'closing_day', True, 179.8)]),   # CI 2018: the closing day December 20 stands (rule 4, guard)
    'BBG000BYWTX7': ('rule4', [('2021-04-20', 'merger', '', '', False, None)],
        [('2021-04-20', 'merger', '2021-04-20', 'closing_day', True, 45.84)]),   # MRVL 2021: the closing day April 20 stands (rule 4, guard)
    'BBG000DFMXT3': ('rule4', [('2022-05-26', 'merger', '', '', False, None)],
        [('2022-05-26', 'merger', '2022-05-16', 'closing_day', True, 166.3)]),   # AZPN 2022: the closing day May 16 stands (rule 4, guard)
    'BBG006G57XG0': ('rule4', [('2025-08-19', 'merger', '', '', False, None)],
        [('2025-08-19', 'merger', '2025-08-18', 'closing_day', True, 37.24)]),   # VNOM 2025: the closing day August 18 stands (rule 4, guard)
    'BBG000C1XKF6': ('rule4', [('2026-01-12', 'merger', '', '', False, None)],
        [('2026-01-12', 'merger', '2025-12-31', 'closing_day', True, 95.41)]),   # PNFP 2025: the closing day December 31 stands (rule 4, guard)
}

# the guards: securities whose outcome no rule of 5d changes
STAY = {
    'BBG000BGYDX9': [('2023-06-30', 'liquidation', '2023-05-26', 'midas', False, 0.25)],   # DBD 2023: MIDAS's May 26 stands; the same CUSIP went to DBDQQ (guard, ruling)
    'BBG000BT0093': [('2024-09-10', 'exchange_transfer', '2024-09-10', '', True, 2.67)],   # SIRI 2024: no text day, so MIDAS is not bounded by New Sirius's start (guard)
    'BBG000BV18Z1': [('2017-05-18', 'liquidation', '2017-07-31', '', True, 0.93)],   # TDW 2017: a bankruptcy fallback keeps its last sighting (guard)
    'BBG000C070N2': [('2008-08-08', 'merger', '2008-07-28', 'nasdaq_halt', False, 8.17)],   # XMSR 2008: the Nasdaq halt's July 28 (guard)
    'BBG000C0NY96': [('2019-08-11', 'merger', '2019-07-31', 'ex99_notice', False, 42.04)],   # TCF 2019: the new TCF's first fails row carries Chemical's close; no MIDAS bound (guard)
    'BBG000C1TTV4': [('2008-02-08', 'merger', '2008-01-28', 'nasdaq_halt', False, 89.45)],   # HET 2008: the feed's 09:30:05 halt against the 8-K's close of business on January 28 (guard)
    'BBG000F2XXP2': [('2023-05-31', 'merger', '2023-05-31', '', True, 14.84)],   # SBGI 2023: Sinclair Inc's first fails row lags its first day; no MIDAS bound (guard)
    'BBG005DKMJ67': [('2023-11-30', 'compliance_failure', '2023-10-27', 'midas', False, 0.21)],   # LTRPA 2023: MIDAS's October 27 stands (guard)
    'BBG00GBV88T6': [('2016-05-14', 'liquidation', '2016-04-12', 'midas', False, 2.07)],   # BTU 2016: no own row under BTU in the window, so no tenure bound (guard)
    'BBG00Z6DX554': [('2020-07-30', 'liquidation', '2020-06-26', 'midas', False, 11.85)],   # CHK 2020: no own row under CHK in the window, so no tenure bound (guard)
}


@pytest.mark.parametrize("sec_id", sorted(MOVES), ids=lambda s: lc.DATA["cases"][s]["note"].split(":")[0])
def test_a_case_moves_when_its_rule_is_built(sec_id):
    rule, before, after = MOVES[sec_id]
    assert lc.outcome(sec_id) == (after if rule in RULES_DONE else before)


@pytest.mark.parametrize("sec_id", sorted(STAY), ids=lambda s: lc.DATA["cases"][s]["note"].split(":")[0])
def test_a_guard_keeps_its_outcome(sec_id):
    assert lc.outcome(sec_id) == STAY[sec_id]


def test_every_case_of_the_fixture_is_a_move_or_a_guard():
    assert set(MOVES) | set(STAY) == set(lc.DATA["cases"]) and not set(MOVES) & set(STAY)
