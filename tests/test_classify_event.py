from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.ticker_resolver import TickerResolver


def _clf(fake_edgar):
    return DelistClassifier(fake_edgar, TickerResolver(fake_edgar))


def test_event_with_known_form25_matches_classify_ticker(fake_edgar):
    clf = _clf(fake_edgar)
    f25 = next(f for f in fake_edgar.recent_filings(1701732) if f.form == "25-NSE")
    ev = clf.classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                            name="Altair Engineering Inc.", form25=f25)
    old = clf.classify_ticker("ALTR", "2025-03-26")
    assert ev.bucket is old.bucket is CrspBucket.MERGER
    assert ev.crsp_code == old.crsp_code
    assert ev.cik == 1701732
    assert ev.observed_delist_date == "2025-03-25"
    assert ev.evidence["delist_filing"]["accession"] == f25.accession
    assert ev.evidence["resolution_source"] == "security_master"


def test_event_without_form25_picks_one_like_classify_ticker(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="BAD", cik=999001, anchor_date="2023-05-10")
    assert ev.bucket is CrspBucket.COMPLIANCE_FAILURE and ev.crsp_code == 570


def test_event_non_equity_kind_is_expiration(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="GSF", cik=886982, anchor_date="2021-01-04", kind="debt")
    assert ev.bucket is CrspBucket.EXPIRATION and ev.crsp_code == 600 and ev.cik == 886982
    assert ev.evidence["asset_type"] == "debt"


def test_event_name_mismatch_is_flagged(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                                         expected_name="Monsanto Company")
    assert "member_name_mismatch" in ev.evidence["flags"]


def test_event_resolution_source_defaults_to_security_master(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25")
    assert ev.evidence["resolution_source"] == "security_master"


def test_event_resolution_source_passes_through(fake_edgar):
    ev = _clf(fake_edgar).classify_event(ticker="ALTR", cik=1701732, anchor_date="2025-03-25",
                                         resolution_source="cik_map")
    assert ev.evidence["resolution_source"] == "cik_map"


def test_delist_record_new_fields_default_none():
    r = DelistRecord("X", 1, "2020-01-01", 231, CrspBucket.MERGER, "high", "r")
    assert r.sec_id is None and r.delist_date is None and r.successor_sec_id is None
    assert r.to_dict()["sec_id"] is None


# --- sub-plan 5b: the Item 1.03 sections, and 5g sub-rule 2 ---

from delist_detection.classifier import _confirms_bankruptcy  # noqa: E402
from delist_detection.edgar import EdgarSubmission  # noqa: E402
from tests import form25_cases as fc  # noqa: E402

NASDAQ_REMOVAL = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>The Nasdaq Stock Market LLC"
                  "</entityName></exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
                  "<ruleProvision>17 CFR 240.12d2-2(b)</ruleProvision></notificationOfRemoval>")
CHAPTER_11 = ("Item 1.03 Bankruptcy or Receivership. On the petition date the Company commenced voluntary cases "
              "under chapter 11 of title 11 of the United States Code. " + "x" * 300)


def test_ascenas_real_8k_with_a_cross_referenced_item_103_confirms_its_bankruptcy():
    """Ascena 2020 (CIK 1498301, 8-K 0001104659-20-085810): its first 'Item 1.03' is a cross-reference in Item
    1.01; the item's own section reports the Chapter 11 cases."""
    assert _confirms_bankruptcy(fc.EDGAR["texts"]["0001104659-20-085810"])


def _ascena_like(fake_edgar):
    """A Nasdaq removal (2020-08-11, last trade 2020-08-03) 11 days after a Chapter 11 8-K whose first 'Item
    1.03' is a cross-reference, an asset sale (item 2.01) in November, and a 10-Q filed in March."""
    fake_edgar.submissions_by_cik[30001] = [
        EdgarSubmission("bk1", "8-K", "2020-07-23", "2020-07-23", "1.01,1.03,2.04,7.01", "k.htm"),
        EdgarSubmission("f25", "25-NSE", "2020-08-11", "", "", "p.xml"),
        EdgarSubmission("sale", "8-K", "2020-11-24", "2020-11-23", "2.01,9.01", "s.htm"),
        EdgarSubmission("q", "10-Q", "2021-03-03", "2020-10-31", "", "q.htm")]
    fake_edgar.raws["f25"] = NASDAQ_REMOVAL
    fake_edgar.texts["bk1"] = (
        "Item 1.01 Entry into a Material Definitive Agreement. The information set forth below in Item 1.03 in this "
        "Current Report on Form 8-K under the captions Restructuring Support Agreement and Backstop Commitment "
        "Letter for the DIP Term Facility is hereby incorporated by reference in this Item 1.01. " + CHAPTER_11)
    return fake_edgar


def test_a_bankruptcy_whose_first_item_103_is_a_cross_reference_is_the_ending_not_the_asset_sale(fake_edgar):
    """Ascena 2020 (sub-plan 5b pulls in 5g sub-rule 2): the confirmed Chapter 11 8-K decides the Form 25's row,
    not the end-of-era resolver's completed sale."""
    edgar = _ascena_like(fake_edgar)
    sub = next(f for f in edgar.recent_filings(30001) if f.form == "25-NSE")
    rec = _clf(edgar).classify_event(ticker="ASNA", cik=30001, anchor_date="2020-08-03", form25=sub)
    assert (rec.crsp_code, rec.bucket) == (470, CrspBucket.LIQUIDATION)
    assert rec.reason == "Bankruptcy (8-K item 1.03 filed 2020-07-23)"


def test_a_bankruptcy_filed_within_the_resolvers_window_beats_the_completed_sale(fake_edgar):
    """5g sub-rule 2: the confirmed 1.03 8-K comes 53 days after the last trade (outside the bankruptcy branch's
    [-540, +30] days) and before the asset sale: the resolver's bankruptcy branch, not a merger."""
    fake_edgar.submissions_by_cik[30002] = [
        EdgarSubmission("f25", "25-NSE", "2020-01-10", "", "", "p.xml"),
        EdgarSubmission("bk2", "8-K", "2020-03-02", "2020-03-02", "1.03", "k.htm"),
        EdgarSubmission("sale2", "8-K", "2020-04-01", "2020-04-01", "2.01", "s.htm"),
        EdgarSubmission("q2", "10-Q", "2020-10-01", "2020-06-30", "", "q.htm")]
    fake_edgar.raws["f25"] = NASDAQ_REMOVAL
    fake_edgar.texts["bk2"] = CHAPTER_11
    sub = next(f for f in fake_edgar.recent_filings(30002) if f.form == "25-NSE")
    rec = _clf(fake_edgar).classify_event(ticker="SALE", cik=30002, anchor_date="2020-01-09", form25=sub)
    assert (rec.crsp_code, rec.bucket, rec.evidence["end_of_era"]) == (470, CrspBucket.LIQUIDATION, "bankruptcy")


# --- sub-plan 5b, R6a: a revocation after a matched Form 25 does not decide it ---

def _revoked_case(fake_edgar, revoked_on):
    """Colonial BancGroup-like: the exchange removed the common (2009-09-08, last trade 2009-08-17) after a
    Chapter 11 8-K (2009-08-20); SEC revoked the registration on `revoked_on`."""
    fake_edgar.submissions_by_cik[30003] = [
        EdgarSubmission("cb25", "25-NSE", "2009-09-08", "", "", "p.xml"),
        EdgarSubmission("cbbk", "8-K", "2009-08-20", "2009-08-20", "1.03", "k.htm"),
        EdgarSubmission("cbrv", "REVOKED", revoked_on, "", "", "")]
    fake_edgar.raws["cb25"] = NASDAQ_REMOVAL
    fake_edgar.texts["cbbk"] = CHAPTER_11
    return next(f for f in fake_edgar.recent_filings(30003) if f.form == "25-NSE")


def test_a_revocation_filed_after_the_matched_form25_does_not_decide_its_row(fake_edgar):
    sub = _revoked_case(fake_edgar, "2010-06-01")
    rec = _clf(fake_edgar).classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17", form25=sub)
    assert (rec.crsp_code, rec.bucket) == (470, CrspBucket.LIQUIDATION)


def test_a_revocation_still_decides_when_it_came_first_or_no_form25_owns_the_row(fake_edgar):
    """A revocation before the Form 25, a row with no matched Form 25 (the fallback's), and a Form 25 the
    security traded past (`trading_after`) keep today's revocation branch (573)."""
    sub = _revoked_case(fake_edgar, "2009-09-01")
    clf = _clf(fake_edgar)
    assert clf.classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17", form25=sub).crsp_code == 573
    sub = _revoked_case(fake_edgar, "2010-06-01")
    assert clf.classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17").crsp_code == 573
    assert clf.classify_event(ticker="CNB", cik=30003, anchor_date="2009-08-17", form25=sub,
                              trading_after=True).crsp_code == 573


# --- sub-plan 5b, R6b: the matched Form 25's notice owns a continued-filings row ---

def _notice_raw(text):
    return ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>\n"
            f"<TYPE>EX-99.25\n<TEXT>\n{text}\n</TEXT>")


def _continued_filer(fake_edgar, notice):
    """NBTY-like: the 25-NSE of 2010-10-01 and a 10-Q seven months later (the issuer kept filing for its debt),
    no 8-K near it: the continued-filings rule's default branch (304) unless the notice decides."""
    fake_edgar.submissions_by_cik[30004] = [
        EdgarSubmission("nt25", "25-NSE", "2010-10-01", "", "", "p.xml"),
        EdgarSubmission("ntq", "10-Q", "2011-05-01", "2011-03-31", "", "q.htm")]
    fake_edgar.raws["nt25"] = _notice_raw(notice)
    return next(f for f in fake_edgar.recent_filings(30004) if f.form == "25-NSE")


CASH_NOTICE = ("Pursuant to the merger, which became effective before the open on October 1, 2010, each outstanding "
               "share of Common Stock was converted into the right to receive $55.00 in cash.")


def test_a_notice_that_says_cash_turns_the_continued_filings_default_into_a_merger(fake_edgar):
    sub = _continued_filer(fake_edgar, CASH_NOTICE)
    rec = _clf(fake_edgar).classify_event(ticker="NTY", cik=30004, anchor_date="2010-09-30", form25=sub)
    assert (rec.crsp_code, rec.bucket, rec.evidence["end_of_era"]) == (231, CrspBucket.MERGER, "form25_notice")
    assert rec.reason == "Form 25 2010-10-01 notice: the class was acquired"
    assert "no_evidence_default" not in rec.evidence["flags"]


def test_a_reorganization_a_security_trading_on_or_no_notice_keeps_the_continued_filings_transfer(fake_edgar):
    clf = _clf(fake_edgar)
    for notice in ("Pursuant to the reclassification of the dual-class common stock, each share of Class B was "
                   "converted into one (1) share of Common Stock.", ""):
        sub = _continued_filer(fake_edgar, notice)
        rec = clf.classify_event(ticker="NTY", cik=30004, anchor_date="2010-09-30", form25=sub)
        assert (rec.crsp_code, rec.evidence["end_of_era"]) == (304, "continued_filings")
    sub = _continued_filer(fake_edgar, CASH_NOTICE)
    rec = clf.classify_event(ticker="NTY", cik=30004, anchor_date="2010-09-30", form25=sub, trading_after=True)
    assert (rec.crsp_code, rec.evidence["end_of_era"]) == (304, "trading")
