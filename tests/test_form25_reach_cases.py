"""Sub-plan 5b's real cases: what the finder gives each security of tests/fixtures/form25_reach/ (built once,
offline, from the local caches by scripts/build_form25_fixtures.py), through the run's own stage-5 code
(tests/form25_cases.py). A case the sub-plan moves (MOVES) keeps its outcome from before 5b until the task that
builds its rule adds the rule to RULES_DONE; a guard (STAY) keeps its outcome throughout. An outcome is the
finder's delistings, each (delist_date, bucket, CRSP code, last trade day, successor is the security itself, Form
25 accession, filer CIK), and the flags of its review items."""
from __future__ import annotations

import dataclasses

import pytest

import delist_detection.endings.delistings as delistings
from delist_detection.endings.delistings import SecurityContexts
from tests import form25_cases as fc

# The rules of sub-plan 5b built so far; each task adds its own (the cases it moves change then, and only then)
RULES_DONE: set[str] = {"1.03", "R6a", "R6b", "C", "R7", "E", "R3", "L", "R2", "R5", "F4-read", "F4-tie", "F4-otc"}

# sec_id -> (the rule that moves it, its outcome before 5b, its outcome after)
MOVES = {
    # ASNA 2020
    'BBG000BGZ9V9': ('1.03',
        ([('2020-08-21', 'exchange_transfer', 304, '2020-08-03', True, '0001354457-20-000408', 1498301)], ['ended_without_delisting']),
        ([('2020-08-21', 'liquidation', 470, '2020-08-03', False, '0001354457-20-000408', 1498301)], [])),
    # CNB 2009
    'BBG000BF2JS9': ('R6a',
        ([('2009-09-18', 'compliance_failure', 573, '2009-08-17', False, '0000876661-09-000352', 92339)], []),
        ([('2009-09-18', 'liquidation', 470, '2009-08-17', False, '0000876661-09-000352', 92339)], [])),
    # NTY 2010
    'BBG000BPTDN6': ('R6b',
        ([('2010-10-11', 'exchange_transfer', 304, '2010-09-30', False, '0000876661-10-000366', 70793)], []),
        ([('2010-10-11', 'merger', 231, '2010-09-30', False, '0000876661-10-000366', 70793)], [])),
    # TMA 2008 (R6a; it moves once C stops its OTC tail from continuing it)
    'BBG000BBG3P1': ('C',
        ([('2009-01-25', 'compliance_failure', 573, '2008-12-01', False, '0000876661-09-000070', 892535)], []),
        # last trade 12-04 (was the notice's press day 12-01: 5d's review fix reads the 8-K's "Friday, December 5")
        ([('2009-01-25', 'compliance_failure', 580, '2008-12-04', False, '0000876661-09-000070', 892535)], [])),
    # IMB 2008 (likewise)
    'BBG000BLY636': ('C',
        ([('2008-08-17', 'compliance_failure', 573, '2008-07-14', False, '0000876661-08-000315', 773468)], []),
        ([('2008-08-17', 'liquidation', 470, '2008-07-14', False, '0000876661-08-000315', 773468)], [])),
    # MNI 2020
    'BBG000BP62Y3': ('C',
        ([('2017-09-28', 'exchange_transfer', 304, '', True, '0001104659-17-057627', 1056087)], ['ended_without_delisting']),
        ([('2017-09-28', 'exchange_transfer', 304, '', True, '0001104659-17-057627', 1056087), ('2020-03-02', 'liquidation', 470, '2020-02-12', False, '0001143313-20-000012', 1056087)], [])),
    # RHD 2009 (the deficiency wording of Task 3 decides its code)
    'BBG000BRF6B5': ('C',
        ([('2009-05-29', 'liquidation', 470, '2009-06-08', False, '', 30419)], []),
        ([('2009-01-26', 'compliance_failure', 570, '2008-12-31', False, '0000876661-09-000078', 30419)], [])),
    # XMSR 2008
    'BBG000C070N2': ('C',
        ([('2008-08-08', 'exchange_transfer', 304, '2008-07-28', True, '0001354457-08-000198', 1091530), ('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 1091530)], []),
        ([('2008-08-08', 'merger', 231, '2008-07-28', False, '0001354457-08-000198', 1091530)], [])),
    # SOV 2009
    'BBG000JXRXK2': ('C',
        ([('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 811830)], []),
        ([('2009-02-12', 'merger', 231, '2009-01-29', False, '0000876661-09-000094', 811830)], [])),
    # IAR 2008
    'BBG000PSSG77': ('C',
        ([('2009-01-01', 'exchange_transfer', 304, '2008-11-19', True, '0000876661-08-000579', 1367396), ('2009-03-31', 'liquidation', 470, '2009-06-08', False, '', 1367396)], []),
        # last trade 11-20 (was the notice's press day 11-19: 5d's review fix reads the 8-K's "Friday, November 21")
        ([('2009-01-01', 'compliance_failure', 570, '2008-11-20', False, '0000876661-08-000579', 1367396)], [])),
    # LTRPA 2023
    'BBG005DKMJ67': ('C',
        ([('2023-11-30', 'exchange_transfer', 304, '2023-10-27', True, '0001354457-23-000874', 1606745), ('2025-04-29', 'merger', 231, '2025-04-30', False, '', 1606745)], []),
        ([('2023-11-30', 'compliance_failure', 570, '2023-10-27', False, '0001354457-23-000874', 1606745)], [])),
    # LKSD 2020
    'BBG009R0CVG1': ('C',
        ([('2020-01-24', 'exchange_transfer', 304, '2019-12-27', True, '0000876661-20-000026', 1669812), ('2020-04-13', 'liquidation', 470, '2020-04-09', False, '', 1669812)], []),
        ([('2020-01-24', 'compliance_failure', 570, '2019-12-27', False, '0000876661-20-000026', 1669812)], [])),
    # KHC 2026 (5d rule 1 reads its 8-K's "at market close on September 11": the last Nasdaq day of the move)
    'BBG005CPNTQ2': ('R7',
        ([('2026-09-18', 'unknown', None, '', False, '0001637459-26-000062', 1637459)], []),
        ([('2026-09-18', 'exchange_transfer', 304, '2026-09-11', True, '0001637459-26-000062', 1637459)], [])),
    # TXU 2007
    'BBG000BVW841': ('E',
        ([('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 1023291)], []),
        ([('2007-11-02', 'merger', 231, '2007-10-10', False, '0000876661-07-000841', 1023291)], [])),
    # BMET 2007 (Task 5's notice reading decides its code)
    'CIK351346-COMMON': ('E',
        ([('2006-12-28', 'compliance_failure', 570, '', False, '0001104659-06-082100', 351346)], []),
        ([('2007-10-05', 'merger', 231, '2007-09-25', False, '0001354457-07-000287', 351346)], [])),   # 5d rule 1
    # STN 2007
    'CIK898660-COMMON': ('E',
        ([('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 898660)], []),
        ([('2007-11-18', 'merger', 231, '2007-11-07', False, '0000876661-07-000873', 898660)], [])),
    # Liberty Series A 2011
    'CIK1355096-SERIES-A': ('R3',
        ([('2011-10-03', 'merger', 200, '', False, '0001354457-11-000196', 1355096)], []),
        ([], ['ended_without_delisting'])),
    # MWW 2016
    'BBG000DGZ1B6': ('L',
        ([('2008-11-20', 'exchange_transfer', 304, '', True, '0001362310-08-006919', 1020416), ('2009-06-08', 'exchange_transfer', 304, '2009-06-08', False, '', 1020416)], []),
        ([('2008-11-20', 'exchange_transfer', 304, '', True, '0001362310-08-006919', 1020416), ('2016-11-11', 'merger', 231, '2016-10-31', False, '0000876661-16-001386', 1020416)], [])),
    # SPWRA 2011
    'CIK867773-COMMON': ('R2',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2011-11-26', 'exchange_transfer', 304, '2011-11-16', False, '0001354457-11-000248', 867773)], [])),   # 5d rule 4
    # SPB 2018
    'BBG000P4BQM9': ('R5',
        ([('2018-07-16', 'merger', 231, '2018-07-16', False, '', 109177)], []),
        ([('2018-07-26', 'merger', 200, '2018-07-13', False, '0000876661-18-000794', 1487730)], [])),
    # MTCH 2020
    'BBG00B6WH9G3': ('R5',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2020-07-11', 'merger', 200, '2020-06-30', False, '0001354457-20-000292', 1575189)], ['form25_unmatched'])),
    # FB-004 part a: a Form 25 the finder found and left unplaced. 'F4-tie': the sibling that stops at it owns it
    # (`DelistingFinder._tie_owner`); 'F4-read': the Form 25 is read (a rights offering is a right, a class text of
    # 1,500 characters and a national exchange beside a regional one are read, a letterless line the text names by its
    # group is a class no lettered sibling took).
    # GGP 2018 against Brookfield Property REIT
    'BBG000BG3HG3': ('F4-tie',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2018-09-07', 'merger', 231, '2018-08-27', False, '0000876661-18-000943', 1496048)], [])),
    # CG 2008 against Loews
    'BBG000C2DSX9': ('F4-tie',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2008-06-20', 'merger', 200, '', False, '0001193125-08-131145', 60086)], [])),
    # CIT 2009 against the reorganized CIT
    'BBG000MW0PF2': ('F4-tie',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2009-11-28', 'liquidation', 470, '2009-11-02', False, '0000876661-09-000439', 1171825)], [])),
    # Oasis 2020 against Chord Energy; the 2019 move of its class to Nasdaq stays
    'BBG000QFJ7H3': ('F4-tie',
        ([('2020-01-02', 'exchange_transfer', 304, '2019-12-23', True, '0001486159-19-000047', 1486159)], ['ended_without_delisting', 'form25_unmatched']),
        ([('2020-01-02', 'exchange_transfer', 304, '2019-12-23', True, '0001486159-19-000047', 1486159), ('2020-11-06', 'liquidation', 470, '2020-10-09', False, '0001354457-20-000638', 1486159)], [])),
    # Liberty SiriusXM 2024: the Series C line the Form 25's Series B and C name by their group
    'BBG01HLMB6H5': ('F4-read',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2024-09-19', 'merger', 200, '2024-09-09', False, '0001354457-24-000664', 1560385)], [])),
    # Liberty Broadband 2014: the subscription rights
    'CIK1611983-COMMON': ('F4-read',
        ([], ['ended_without_delisting', 'form25_unmatched']),
        ([('2015-01-19', 'expiration', 600, '2015-01-09', False, '0001354457-15-000004', 1611983)], [])),
    # FMCC, FNMA 2010: the common read (F4-read: a transfer the security went on through, neither 10-K cover being
    # cached); EDGAR lists both on the OTC market today and on no exchange, which makes the Form 25 a move to the OTC
    # market (F4-otc: `test_a_2010_nyse_delisting_followed_by_otc_trading_is_dropped_for_moving_otc` has the cover too)
    'BBG000BF7Y65': ('F4-otc',
        ([], ['ended_without_delisting', 'form25_unclassified']),
        ([('2010-07-08', 'compliance_failure', 520, '', False, '0001026214-10-000037', 1026214)], [])),
    'BBG000BJQ328': ('F4-otc',
        ([], ['ended_without_delisting', 'form25_unclassified']),
        ([('2010-07-08', 'compliance_failure', 520, '', False, '0000950123-10-061714', 310522)], [])),
    # LNWO 2025, RVIC 2022: a voluntary Form 25 the security traded on past over the counter. Before it, the OTC
    # trading read as the listing going on: a transfer (LNWO), and for RVIC, once the exchange was read, a merger.
    'BBG00JR5MM31': ('F4-otc',
        ([('2025-11-13', 'exchange_transfer', 304, '', True, '0000950157-25-000903', 750004)], ['ended_without_delisting']),
        ([('2025-11-13', 'compliance_failure', 520, '2025-11-12', False, '0000950157-25-000903', 750004)], [])),
    'BBG00L31HTW0': ('F4-otc',
        ([('2022-04-07', 'merger', 200, '2022-04-06', False, '0001193125-22-085937', 1735184)], []),
        ([('2022-04-07', 'compliance_failure', 520, '2022-04-06', False, '0001193125-22-085937', 1735184)], [])),
    # APA: the NYSE Form 25 of 2020-06-08 (the issuer's own, naming only the NYSE) was read as the Chicago's; it is the
    # class's move to Nasdaq
    'BBG000BC2C10': ('F4-read',
        ([('2021-03-14', 'exchange_transfer', 304, '2021-03-01', False, '0001354457-21-000304', 6769)], []),   # 5d rule 4: the 8-K's March 1
        ([('2020-06-18', 'exchange_transfer', 304, '', True, '0001193125-20-163490', 6769), ('2021-03-14', 'exchange_transfer', 304, '2021-03-01', False, '0001354457-21-000304', 6769)], [])),
}

# the guards: securities whose outcome no rule of 5b changes
STAY = {
    'CIK929351-COMMON': ([], ['ended_without_delisting', 'form25_unmatched']),   # LGF 2016: its A and B lines carry its name from the day it stopped (a reclassification, as Linde's): the tie stays
    'BBG000BKQG80': ([], ['ended_without_delisting', 'form25_unmatched']),   # IAC 2020: the old Match Group (issuer CIK 891103 in the run, in force 1575189) stops with it: two stop, one goes on
    'BBG000BFTJ91': ([('2015-12-21', 'exchange_transfer', 304, '2015-12-11', False, '0001354457-15-000245', 1166691)], []),   # CMCSK 2015
    'BBG000CNFQW6': ([], []),   # PRGO
    'BBG000CS7CB8': ([('2007-11-25', 'merger', 231, '2007-11-13', False, '0000876661-07-000879', 885708)], []),   # JNC 2007
    'BBG000D9DMK0': ([], ['ended_without_delisting', 'form25_unmatched']),   # LH
    'BBG000MJRJJ2': ([('2023-08-24', 'exchange_transfer', 304, '2023-08-11', False, '0000876661-23-000651', 1498828)], []),   # HHC 2023
    'BBG000VMWHH5': ([('2022-04-18', 'merger', 200, '2022-04-08', False, '0001354457-22-000231', 1437107)], ['form25_unmatched']),   # DISCK 2022
    'BBG001QD41M9': ([], ['ended_without_delisting', 'form25_unmatched']),   # APTV
    'BBG0038K9G41': ([('2018-03-19', 'merger', 200, '2018-03-09', False, '0001354457-18-000053', 1355096)], []),   # LVNTA 2018
    'BBG004P33PN3': ([('2026-05-11', 'unknown', None, '2026-04-30', False, '0000876661-26-000380', 1567683)], []),   # CWENA 2026
    'BBG00B4Z2YX0': ([], []),   # LAUR
    'BBG00GVR8YQ9': ([], ['ended_without_delisting', 'form25_unmatched']),   # LIN
    'CIK1469372-CLASS-A': ([('2015-08-03', 'exchange_transfer', 304, '2015-07-24', True, '0001193125-15-262759', 1469372), ('2015-10-02', 'exchange_transfer', 304, '2015-10-02', False, '', 1469372)], []),   # MSG 2015 (5d rule 1: the move's 8-K)
    'CIK48898-CLASS-B': ([('2016-01-03', 'exchange_transfer', 304, '2015-12-23', False, '0000876661-15-000665', 48898)], ['form25_unmatched']),   # HUB-B 2015
    'CIK65873-COMMON': ([('2007-11-30', 'merger', 231, '2007-11-16', False, '0000876661-07-000891', 65873)], []),   # AT 2007
    'BBG000QN4GY3': ([], ['ended_without_delisting']),   # HOUS 2026 under the LLC's CIK 1355001, as the run had it
    # FB-004 part c, under the issuer CIK the run had (the old registrant's, or none): see the test below for the right one
    'BBG000BB41G8': ([], ['ended_without_delisting']),   # ACV 2011 under the old registrant's CIK 3327
    'BBG006N7RYV7': ([], ['ended_without_delisting']),   # FNFV 2017, no issuer CIK
    'BBG000BH13K9': ([], ['ended_without_delisting']),   # DD 2017, no issuer CIK
    'BBG001KS9450': ([], ['ended_without_delisting']),   # TWOU 2024, no issuer CIK
    'BBG009CKXW23': ([], ['ended_without_delisting']),   # PTHN 2017 under the Canadian Patheon Inc.'s CIK 1400431
}


@pytest.mark.parametrize("sec_id", sorted(MOVES), ids=lambda s: fc.DATA["cases"][s]["note"].split(":")[0])
def test_a_case_moves_when_its_rule_is_built(sec_id):
    rule, before, after = MOVES[sec_id]
    assert fc.outcome(sec_id) == (after if rule in RULES_DONE else before)


@pytest.mark.parametrize("sec_id", sorted(STAY), ids=lambda s: fc.DATA["cases"][s]["note"].split(":")[0])
def test_a_guard_keeps_its_outcome(sec_id):
    assert fc.outcome(sec_id) == STAY[sec_id]


def test_every_case_of_the_fixture_is_a_move_or_a_guard():
    assert set(MOVES) | set(STAY) == set(fc.DATA["cases"]) and not set(MOVES) & set(STAY)


def test_a_security_listed_today_reads_no_form25_from_before_its_first_sighting():
    """LAUR: listed today, its observations from 2008 are of the old Laureate, and its one Form 25 (2007-08-17,
    not cached) lies before them: the finder never reads it (early reach needs `listed_today is False`)."""
    edgar = fc.FixtureEdgar()
    assert fc.find("BBG00B4Z2YX0", edgar=edgar) == ([], []) and edgar.raws_read == []


@pytest.mark.parametrize("sec_id,day", [("BBG00GVR8YQ9", "2023-03-12"), ("BBG001QD41M9", "2024-12-28"),
                                         ("BBG000D9DMK0", "2024-05-30")], ids=["LIN", "APTV", "LH"])
def test_the_sibling_slack_keeps_an_old_redomiciled_line_from_a_false_ending(sec_id, day, monkeypatch):
    """Must not change (binding, 2026-10-04): the old lines of Linde, Aptiv and Labcorp. The 30-day slack keeps the
    new line alive at its Form 25, so the filing stays ambiguous between the two lines and the old line takes no
    ending of its own; with a sibling alive only from its own first sighting, the old line would end there."""
    assert fc.outcome(sec_id)[0] == []
    monkeypatch.setattr(delistings, "SIBLING_ALIVE_BEFORE_DAYS", 0)
    assert [r[0] for r in fc.outcome(sec_id)[0]] == [day]


def test_reading_a_cik_in_force_over_part_of_the_span_would_give_perrigo_a_2013_row():
    """PRGO (binding: no 2013 ending): the old Perrigo Company (CIK 820096) was in force only until 2013, so R5
    reads no other CIK for it; reading that CIK would give the listed PRGO a 2013 row."""
    assert fc.outcome("BBG000CNFQW6") == ([], [])
    assert [r[0] for r in fc.outcome("BBG000CNFQW6", other_cik=820096)[0]] == ["2013-06-15"]


# FB-004: Freddie Mac's and Fannie Mae's July 2010 NYSE delistings. Their next 10-Ks (FMCC 0001026214-11-000005, FNMA
# 0000950123-11-017972) are in no cache, so the cover below is written to the registrants' layout: "Name of each
# exchange on which registered: None". The evidence cached is the Form 25 (the issuer's own, 12d2-2(c)), the 8-K item
# 3.01 of 2010-06-16 (the conservator's directive to withdraw from the NYSE; no other exchange named), no 8-A12B,
# the securities not listed today, and their own CUSIPs' fails rows under FMCC and FNMA through 2026.
NO_EXCHANGE_COVER = ("FORM 10-K ... Securities registered pursuant to Section 12(b) of the Act: Title of each class "
                     "Name of each exchange on which registered None Securities registered pursuant to Section 12(g) "
                     "of the Act: Common Stock, without par value ...")


class _CoverEdgar(fc.FixtureEdgar):
    def fetch_filing_text(self, cik, accession, primary_doc):
        if accession in ("0001026214-11-000005", "0000950123-11-017972"):
            return NO_EXCHANGE_COVER
        return super().fetch_filing_text(cik, accession, primary_doc)


@pytest.mark.parametrize("sec_id,accession,cik", [("BBG000BF7Y65", "0001026214-10-000037", 1026214),
                                                  ("BBG000BJQ328", "0000950123-10-061714", 310522)],
                         ids=["FMCC", "FNMA"])
def test_a_2010_nyse_delisting_followed_by_otc_trading_is_dropped_for_moving_otc(sec_id, accession, cik):
    assert fc.outcome(sec_id, edgar=_CoverEdgar()) == (
        [('2010-07-08', 'compliance_failure', 520, '', False, accession, cik)], [])
    found, _ = fc.find(sec_id, edgar=_CoverEdgar())
    assert [rw.rule.value for rw in found[0].rewrites] == ["moved_otc"]


# FB-004 part b: a voluntary Form 25 the security traded on past over the counter (the real cases)
def test_light_and_wonders_voluntary_nasdaq_withdrawal_is_a_move_to_the_otc_market():
    """LNWO 2025: the issuer's Form 25 of 2025-11-03; its 10-K's inline-XBRL cover has no column to read, and EDGAR
    lists LNWO and LAWIL on the OTC market today and on no exchange: dropped, not an exchange transfer."""
    found, _ = fc.find("BBG00JR5MM31")
    assert [(d.delist_date, d.record.bucket.value, d.record.crsp_code, d.record.successor_sec_id, d.cik)
            for d in found] == [("2025-11-13", "compliance_failure", 520, None, 750004)]
    assert [rw.rule.value for rw in found[0].rewrites] == ["moved_otc"]
    assert "OTC market" in found[0].record.reason


def test_retail_values_voluntary_nyse_move_is_a_move_to_the_otc_market_not_a_merger():
    """RVIC 2022: the Form 25 of 2022-03-28, an Item 2.01 of 2022-04-14 and its 10-K of 2023-02-24 naming no exchange;
    its shares traded over the counter until 2023-04-06."""
    found, _ = fc.find("BBG00L31HTW0")
    assert [(d.delist_date, d.record.bucket.value, d.record.crsp_code, d.record.successor_sec_id, d.cik)
            for d in found] == [("2022-04-07", "compliance_failure", 520, None, 1735184)]
    assert [rw.rule.value for rw in found[0].rewrites] == ["moved_otc"]
    assert "2023-02-24" in found[0].record.reason


def test_the_form25_of_anywhere_real_estate_inc_is_reached_through_its_own_cik_not_the_llcs():
    """HOUS 2026: the run had issuer CIK 1355001 (Realogy Group LLC, whose last Form 25 is of 2007), so the Compass
    merger's 25-NSE of 2026-01-09 was never searched. Under CIK 1398987 (Anywhere Real Estate Inc., the listed
    registrant) the finder reaches it; its raw is in no cache (a live run fetches it), so here it is `unreadable`."""
    securities, cusips, ftd = fc.world()
    sec = dataclasses.replace(securities["BBG000QN4GY3"], issuer_cik=1398987)
    ctx = SecurityContexts.observed({sec.sec_id: sec}, cusips, ftd)(sec, False)
    _, review = fc.finder().find(ctx)
    assert [(r.flag, r.filing.accession) for r in review if r.filing is not None] == [
        ("form25_unreadable", "0000876661-26-000018")]


# FB-004 part c: the finder under the issuer CIK the resolver now gives (ACV 1368457 by the name in force, FNFV 1331875 by
# its CUSIP's issuer code, DD 30554 by the name's letters, TWOU 1459417 by the name tier, PTHN 1643848 by the exact
# holder): delisting tuples as `fc.outcome`'s, and the Form 25s a live run must fetch (in no cache)
RIGHT = {
    'BBG000BB41G8': (1368457, [('2011-05-21', 'merger', 231, '2011-05-10', False, '0000876661-11-000210', 1368457)], []),
    'BBG006N7RYV7': (1331875, [('2017-11-30', 'merger', 231, '2017-11-17', False, '0000876661-17-000713', 1331875)], []),
    'BBG000BH13K9': (30554, [], [('ended_without_delisting', ''), ('form25_unreadable', '0000876661-17-000494')]),
    'BBG001KS9450': (1459417, [('2024-06-14', 'unknown', None, '2024-06-12', False, '', 1459417)],
                     [('form25_unreadable', '0001354457-24-000658')]),
    'BBG009CKXW23': (1643848, [], [('ended_without_delisting', ''), ('form25_unreadable', '0001104659-17-055224')]),
}


@pytest.mark.parametrize("sec_id", sorted(RIGHT), ids=lambda s: fc.DATA["cases"][s]["note"].split(":")[0])
def test_the_right_registrants_form25_is_reached_once_the_issuer_is_right(sec_id):
    """ACV: the old registrant (3327) had only the 2006 spin-off's 25-NSE; the spin-off's (1368457) is Unilever's
    acquisition. FNFV: Fidelity National Financial's 25-NSE of the Cannae split-off. DD, TWOU and PTHN: the Form 25's
    raw is in no cache, so it is `form25_unreadable` here (a live run fetches it and decides)."""
    cik, delistings, review = RIGHT[sec_id]
    securities, cusips, ftd = fc.world()
    sec = dataclasses.replace(securities[sec_id], issuer_cik=cik)
    ctx = SecurityContexts.observed({sec.sec_id: sec}, cusips, ftd)(sec, False)
    found, items = fc.finder().find(ctx)
    assert [(d.delist_date, d.record.bucket.value, d.record.crsp_code,
             d.last_trade.day.isoformat() if d.last_trade.day else "", d.record.successor_sec_id == sec_id,
             d.form25_sub.accession if d.form25_sub else "", d.cik) for d in found] == delistings
    assert sorted({(r.flag, r.filing.accession if r.filing else "") for r in items}) == review
