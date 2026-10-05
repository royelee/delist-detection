"""Sub-plan 5i's real cases (tests/verdict_cases.py): each case's verdict reasons, recomputed offline from the
committed run's rows. The `before` column is the committed run's (the rules' targets lose their reason; every guard
keeps its own)."""
import pytest

from delist_detection.verdict_rules import Reading
from tests import verdict_cases as vc

CASES, EDGAR = vc.load()

# case -> (the ending's key or the security, its reasons before 5i, its reasons now)
ENDINGS = {
    # theme 1: a merger relabel with its own Form 25 is settled; a deficiency relabel, a merger with no Form 25 and a
    # liquidation keep the doubt
    "PRE": (("BBG000BBBP59", "2016-03-28"), "resolved_from_continued_filings", ""),
    "WMG": (("BBG000C7B169", "2011-07-31"), "issuer_from_todays_ticker_map;resolved_from_continued_filings", ""),
    "MDRX": (("BBG000BLDXH5", "2024-05-05"), "resolved_from_continued_filings", "resolved_from_continued_filings"),
    "FCL": (("BBG000BM1RP0", "2009-08-14"),
            "resolved_from_continued_filings;last_trade_not_exchange_print:closing_day;last_trade_date_unconfirmed",
            "resolved_from_continued_filings;last_trade_not_exchange_print:closing_day;last_trade_date_unconfirmed"),
    "EQC": (("BBG000BLG1L7", "2025-04-21"), "resolved_from_continued_filings", "resolved_from_continued_filings"),
    # themes 2 and 6a: a successor registration or a handoff by 8-K12B confirms the continuation; CHTR's own 8-K12B
    # states 0.9042 (a truth merger, R1), so its relabel stays too; SIRI's states 0.1 (a reverse split of the same
    # class, R2: a continuation) and no ratio doubt is raised: it keeps only today's ticker map (no Form 25)
    "BHI": (("BBG000BD4VG8", "2017-07-15"), "resolved_from_continued_filings", ""),
    "CHTR": (("BBG000PYZSR8", "2016-05-18"), "issuer_from_todays_ticker_map;resolved_from_continued_filings",
             "continuation_not_one_for_one:ratio:0.9042;issuer_from_todays_ticker_map;"
             "resolved_from_continued_filings"),
    "SIRI": (("BBG000BT0093", "2024-09-10"), "issuer_from_todays_ticker_map;resolved_from_continued_filings",
             "issuer_from_todays_ticker_map"),
    "GOOGL": (("BBG000BHSKN9", "2015-10-12"), "no_evidence_default", ""),
    # theme 7 (stage 9g): a 3.03 stating a one-for-one exchange confirms; Liberty's 2023 reclassification (a second
    # Liberty Live leg) and Dell's class V election do not
    "APA": (("BBG000BC2C10", "2021-03-14"), "continued_filings_rule", ""),
    "CMCSK": (("BBG000BFTJ91", "2015-12-21"), "continued_filings_rule", ""),
    "LSXMA": (("BBG00BFHD827", "2023-08-13"), "continuation_by_timing_only", "continuation_by_timing_only"),
    "DVMT": (("BBG00DJ2LJF5", "2019-01-07"), "continued_filings_rule", "continued_filings_rule"),
    "HHC": (("BBG000MJRJJ2", "2023-08-24"), "continued_filings_rule", ""),
    "HUB-B": (("CIK48898-CLASS-B", "2016-01-03"), "security_uncertain;continued_filings_rule", "security_uncertain"),
    # theme 3: the issuer's own Form 25 confirms today's ticker map; another CIK's Form 25, a name mismatch and no
    # Form 25 keep it
    "EA": (("BBG000BP0KQ8", "2026-08-14"), "issuer_from_todays_ticker_map", ""),
    "BTU": (("BBG000FW00S1", "2016-05-14"), "issuer_from_todays_ticker_map", ""),
    "SPB": (("BBG000P4BQM9", "2018-07-26"), "issuer_from_todays_ticker_map;continuation_by_timing_only",
            "issuer_from_todays_ticker_map"),
    "CHK": (("BBG00Z6DX554", "2020-07-30"), "issuer_from_todays_ticker_map", "issuer_from_todays_ticker_map"),
    "CBL": (("BBG000B9YSK6", "2020-11-02"), "issuer_from_todays_ticker_map", "issuer_from_todays_ticker_map"),
    # theme 4: a missing acquirer price is unpriced; a lagged close still tests the terms (MDP's miss a leg)
    # (GRUB's contract row publishes the acquirer ticker "NULL", its delistings row none: a missing ticker is a doubt
    # about the terms, so it stays uncertain until the extractor names the acquirer)
    "GRUB": (("BBG001KWG293", "2021-06-25"), "assumed_par_after_failed_gate", "assumed_par_after_failed_gate"),
    "MDP": (("BBG000BNVNY4", "2021-12-12"), "assumed_par_after_failed_gate", "assumed_par_after_failed_gate"),
    "PNRA": (("BBG000G6BN50", "2017-07-28"), "assumed_par_after_failed_gate", "assumed_par_after_failed_gate"),
    # theme 5: a stale seed after a settled merger no longer makes it uncertain; one after a worked-out last trade
    # still does
    "BOL": (("BBG000BDLLR9", "2007-11-05"), "security_uncertain", ""),
    "AT": (("CIK65873-COMMON", "2007-11-30"), "security_uncertain;resolved_from_continued_filings", ""),
    # MEL (one share per share, no cash: R1's continuation, published as a merger) and FRK (a Nasdaq halt day against
    # the NYSE notice's, last_trade_date_conflict) are doubts their own rows carry: they stay uncertain
    "MEL": (("BBG000BNXLK1", "2007-07-12"), "security_uncertain", "security_uncertain"),
    "FRK": (("BBG000BJV732", "2007-12-01"), "security_uncertain", "security_uncertain"),
    "CDWC": (("BBG000BHD665", "2007-10-22"),
             "security_uncertain;last_trade_not_exchange_print:closing_day;last_trade_date_unconfirmed",
             "security_uncertain;last_trade_not_exchange_print:closing_day;last_trade_date_unconfirmed"),
}
SECURITIES = {
    "BOL": ("BBG000BDLLR9", "seeds_outside_history:1 from 2008-01-16", ""),
    "MEL": ("BBG000BNXLK1", "seeds_outside_history:1 from 2008-01-16", "seeds_outside_history:1 from 2008-01-16"),
    "FRK": ("BBG000BJV732", "seeds_outside_history:1 from 2008-01-16", "seeds_outside_history:1 from 2008-01-16"),
    "CDWC": ("BBG000BHD665", "seeds_outside_history:1 from 2008-01-16", "seeds_outside_history:1 from 2008-01-16"),
    "WW": ("BBG000DY6735", "", "closed_no_event:2013-12-31"),
    "NCRA": ("CIK1308161-CLASS-A", "placeholder_without_ticker_filing:CIK 1308161",
             "placeholder_without_ticker_filing:CIK 1308161;closed_no_event:2013-06-28"),
    "AZN": ("BBG000BZ0DK8", "", ""),
}


def _before(case: dict, kind: str, sec_id: str, day: str | None = None) -> str:
    return next((r["reason"] for r in case["uncertain_before"]
                 if r["kind"] == kind and r["sec_id"] == sec_id and (day is None or r["date"] == day)), "")


@pytest.mark.parametrize("name", sorted(ENDINGS))
def test_each_cases_ending_verdict(name):
    key, before, now = ENDINGS[name]
    case = CASES[name]
    assert _before(case, "ending", *key) == before          # the fixture is the committed run's
    assert ";".join(vc.verdicts(case, EDGAR).endings[key].reasons) == now


@pytest.mark.parametrize("name", sorted(SECURITIES))
def test_each_cases_security_verdict(name):
    sec_id, before, now = SECURITIES[name]
    case = CASES[name]
    assert _before(case, "security", sec_id) == before
    assert ";".join(vc.verdicts(case, EDGAR).securities[sec_id].reasons) == now


def test_stage_9g_names_the_confirming_filing_and_the_contradicting_ratio():
    r = vc.readings
    assert r(CASES["APA"], EDGAR) == {("BBG000BC2C10", "2021-03-14"): Reading(filing="8-K 0001193125-21-063792")}
    assert r(CASES["HHC"], EDGAR) == {("BBG000MJRJJ2", "2023-08-24"): Reading(filing="8-K 0001104659-23-090461")}
    assert r(CASES["LSXMA"], EDGAR) == {} and r(CASES["DVMT"], EDGAR) == {}
    assert r(CASES["CHTR"], EDGAR) == {("BBG000PYZSR8", "2016-05-18"): Reading(doubt="ratio:0.9042")}
    assert r(CASES["SIRI"], EDGAR) == {}                  # 0.1: a reverse split, no doubt
