"""Sub-plan 5c's real cases: what the run gives each security of tests/fixtures/issuer_role/ (built once, offline,
from the local caches by scripts/build_issuer_role_fixtures.py), through the run's own stage-5, stage-8b and
stage-9 code (tests/issuer_role_cases.py). A case the sub-plan moves (MOVES) keeps its outcome from before 5c until
the task that builds a rule of its sequence adds the rule to RULES_DONE; it then has that rule's outcome (CWENA
moves twice: stage 5 makes it an exchange transfer, stage 9 links it). A guard (STAY) keeps its outcome throughout.
An outcome is the case's delistings after stage 9, each (delist_date, bucket, CRSP code, successor sec_id, how the
successor was found). The fixture's world holds only the cases' and their successors' issuers, so a link needing
a unique candidate can find one the full run does not (MSG 2015's same_issuer link): the full run is Task 9's
replay."""
from __future__ import annotations

import pytest

from tests import issuer_role_cases as ic

# The rules of sub-plan 5c built so far, in task order; each task adds its own
RULES_DONE: set[str] = set()
ORDER = ("stage5", "r1", "links")

# sec_id -> (its outcome before 5c, [(rule, its outcome once the rule is built), ...] in ORDER)
MOVES = {
    'CIK1126294-COMMON': ([('2010-12-03', 'merger', 231, '', '')], [('stage5', [('2010-12-03', 'exchange_transfer', 304, '', '')])]),   # RRI 2010
    'CIK1363851-COMMON': ([('2012-07-24', 'merger', 231, '', '')], [('stage5', [('2012-07-24', 'exchange_transfer', 304, 'BBG000KBQZ88', 'same_issuer')])]),   # SXCI 2012
    'CIK1308161-COMMON': ([('2009-01-08', 'exchange_transfer', 304, 'CIK1308161-COMMON', ''), ('2013-07-01', 'merger', 231, '', '')], [('stage5', [('2009-01-08', 'exchange_transfer', 304, 'CIK1308161-COMMON', ''), ('2013-07-01', 'exchange_transfer', 304, '', '')])]),   # NWS-A 2013
    'CIK1308161-CLASS-A': ([('2013-06-28', 'merger', 231, '', '')], [('stage5', [('2013-06-28', 'exchange_transfer', 304, '', '')])]),   # NCRA 2013
    'CIK38079-COMMON': ([('2015-01-25', 'merger', 200, '', '')], [('stage5', [('2015-01-25', 'compliance_failure', 570, '', '')])]),   # FST 2014
    'BBG000BQHGR6': ([('2026-09-28', 'unknown', None, '', '')], [('stage5', [('2026-09-28', 'exchange_transfer', 304, '', '')])]),   # OKE 2026
    'BBG000BHBK84': ([('2017-09-11', 'merger', 231, '', '')], [('r1', [('2017-09-11', 'exchange_transfer', 304, 'BBG00BN961G4', 'new_issuer')])]),   # DOW 2017
    'BBG000BPQD31': ([('2020-11-26', 'merger', 231, '', '')], [('r1', [('2020-11-26', 'exchange_transfer', 304, 'BBG00Y4RQNH4', 'new_issuer')])]),   # MYL 2020
    'BBG000CGQ6M4': ([('2018-11-10', 'merger', 231, '', '')], [('r1', [('2018-11-10', 'exchange_transfer', 304, 'BBG00GVR8YQ9', 'new_issuer')])]),   # PX 2018
    'BBG000CHWP52': ([('2022-04-18', 'merger', 200, '', '')], [('r1', [('2022-04-18', 'exchange_transfer', 304, 'BBG011386VF4', 'same_issuer_class')])]),   # DISCA 2022
    'BBG000F2XXP2': ([('2023-05-31', 'merger', 231, '', '')], [('r1', [('2023-05-31', 'exchange_transfer', 304, 'BBG01GJ3NY88', 'new_issuer')])]),   # SBGI 2023
    'BBG000G0PPW3': ([('2016-12-11', 'merger', 231, '', '')], [('r1', [('2016-12-11', 'exchange_transfer', 304, 'BBG00D3CHRC0', 'new_issuer')])]),   # AMSG 2016
    'BBG000VMWHH5': ([('2022-04-18', 'merger', 200, '', '')], [('r1', [('2022-04-18', 'exchange_transfer', 304, 'BBG011386VF4', 'same_issuer_class')])]),   # DISCK 2022
    'BBG001YMS0B8': ([('2015-07-12', 'merger', 231, '', '')], [('r1', [('2015-07-12', 'exchange_transfer', 304, 'BBG005CPNTQ2', 'new_issuer')])]),   # KRFT 2015
    'BBG01HMFL081': ([('2025-12-25', 'merger', 200, '', '')], [('r1', [('2025-12-25', 'exchange_transfer', 304, 'BBG01YY256K1', 'new_issuer')])]),   # LLYVA 2025
    'BBG01HMFLTN1': ([('2025-12-25', 'merger', 200, '', '')], [('r1', [('2025-12-25', 'exchange_transfer', 304, 'BBG01YYX1Z14', 'new_issuer')])]),   # LLYVK 2025
    'CIK104207-COMMON': ([('2015-01-09', 'merger', 231, '', '')], [('r1', [('2015-01-09', 'exchange_transfer', 304, 'BBG000BWLMJ4', 'new_issuer')])]),   # WAG 2014
    'CIK944868-COMMON': ([('2009-11-29', 'merger', 231, '', '')], [('r1', [('2009-11-29', 'exchange_transfer', 304, 'BBG000FL1TC8', 'new_issuer')])]),   # DTV 2009
    'BBG000BD4VG8': ([('2017-07-15', 'exchange_transfer', 304, '', '')], [('links', [('2017-07-15', 'exchange_transfer', 304, 'BBG00GBVBK51', 'new_issuer')])]),   # BHI 2017
    'BBG000BFTJ91': ([('2015-12-21', 'exchange_transfer', 304, '', '')], [('links', [('2015-12-21', 'exchange_transfer', 304, 'BBG000BFT2L4', 'same_issuer_class')])]),   # CMCSK 2015
    'BBG000J453J8': ([('2019-05-12', 'exchange_transfer', 304, '', '')], [('links', [('2019-05-12', 'exchange_transfer', 304, 'BBG000SSC5C9', 'own_registration')])]),   # CCO 2019
    'BBG000MJRJJ2': ([('2023-08-24', 'exchange_transfer', 304, '', '')], [('links', [('2023-08-24', 'exchange_transfer', 304, 'BBG01HTMDZ54', 'new_issuer')])]),   # HHC 2023
    'CIK48898-CLASS-B': ([('2016-01-03', 'exchange_transfer', 304, '', '')], [('links', [('2016-01-03', 'exchange_transfer', 304, 'BBG000BLK267', 'same_issuer_class')])]),   # HUB-B 2015
    'BBG004P33PN3': ([('2026-05-11', 'unknown', None, '', '')], [('stage5', [('2026-05-11', 'exchange_transfer', 304, '', '')]), ('links', [('2026-05-11', 'exchange_transfer', 304, 'BBG008LJ4TF3', 'same_issuer_class')])]),   # CWENA 2026
}

# the guards: securities whose outcome no rule of 5c changes
STAY = {
    'BBG000BBLK04': [('2016-01-14', 'merger', 233, '', '')],   # TW 2016: Willis existed (5,347 days)
    'BBG000BDKN87': [('2010-02-26', 'merger', 231, '', '')],   # BNI 2010: renamed after its acquisition
    'BBG000BDXVW8': [('2010-10-14', 'merger', 231, '', '')],   # CAL 2010: 1.05 UAL
    'BBG000BHW628': [('2016-06-11', 'merger', 231, '', '')],   # WCN 2016: Progressive Waste existed (4,125 days)
    'BBG000BJ9D07': [('2016-09-08', 'merger', 233, '', '')],   # ROVI 2016: TiVo Corp is not in the run, no search here
    'BBG000BJCFP1': [('2013-03-11', 'merger', 231, '', '')],   # JEF 2013: the LLM's 0.81 LUK
    'BBG000BM1RP0': [('2009-08-14', 'merger', 233, '', '')],   # FCL 2009: 1.084 New Alpha
    'BBG000BSVZM9': [('2009-11-04', 'merger', 231, '', '')],   # SGP 2009: $10.50 and 0.5767 New Merck
    'BBG000BT0093': [('2024-09-10', 'exchange_transfer', 304, 'BBG01KJQM3Y8', 'same_issuer')],   # SIRI 2024
    'BBG000BVW841': [('2007-11-02', 'merger', 231, '', '')],   # TXU 2007: an LBO, renamed after
    'BBG000K1T0M8': [('2025-05-17', 'merger', 231, '', '')],   # LGFA 2025: the target of New Lionsgate
    'BBG000PYZSR8': [('2016-05-18', 'exchange_transfer', 304, 'BBG000VPGNR2', 'same_issuer')],   # CHTR 2016
    'BBG003444577': [('2014-12-25', 'merger', 231, '', '')],   # BKW 2014: 0.99 QSR and $3.00
    'BBG0038K9G41': [('2018-03-19', 'merger', 200, '', '')],   # LVNTA 2018: GCI Liberty existed (8,442 days)
    'CIK1011006-COMMON': [('2017-06-12', 'exchange_transfer', 304, '', '')],   # AABA 2017: no statement, no link
    'CIK1469372-CLASS-A': [('2015-08-03', 'exchange_transfer', 304, 'CIK1469372-CLASS-A', ''), ('2015-10-02', 'exchange_transfer', 304, 'BBG000NS03H7', 'same_issuer')],   # MSG 2015
}


def _expected(sec_id: str) -> list[tuple]:
    before, steps = MOVES[sec_id]
    done = [o for rule, o in steps if rule in RULES_DONE]
    return done[-1] if done else before


@pytest.mark.parametrize("sec_id", sorted(MOVES), ids=lambda s: ic.DATA["cases"][s]["note"].split(":")[0])
def test_a_case_moves_when_its_rule_is_built(sec_id):
    assert ic.outcome(sec_id) == _expected(sec_id)


@pytest.mark.parametrize("sec_id", sorted(STAY), ids=lambda s: ic.DATA["cases"][s]["note"].split(":")[0])
def test_a_guard_keeps_its_outcome(sec_id):
    assert ic.outcome(sec_id) == STAY[sec_id]


def test_every_case_of_the_fixture_is_a_move_or_a_guard():
    assert set(MOVES) | set(STAY) == set(ic.DATA["cases"]) and not set(MOVES) & set(STAY)
    assert all(rule in ORDER for _, steps in MOVES.values() for rule, _ in steps)
