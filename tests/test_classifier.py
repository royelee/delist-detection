from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.ticker_resolver import TickerResolver


def test_altair_classifies_as_merger(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("ALTR", "2025-03-26")

    assert rec.cik == 1701732
    assert rec.bucket is CrspBucket.MERGER
    assert rec.crsp_code in (200, 231, 233)
    assert rec.confidence == "high"
    assert "2.01" in rec.evidence["anchor_8k"]["items"]


def test_compliance_failure_classifies_correctly(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("BAD", "2023-05-10")

    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE
    assert rec.crsp_code == 570
    assert rec.evidence["delist_filing"]["form"] == "25-NSE"


def test_deregistration_without_any_evidence_is_unknown_not_liquidation(fake_edgar):
    """Form 25 + Form 15 + non-merger 8-K, with no distress evidence, is UNKNOWN
    (rendered at par), not LIQUIDATION or COMPLIANCE_FAILURE — those would
    apply -90% / -100% in training."""
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("LIQ", "2019-11-06")

    assert rec.bucket is CrspBucket.UNKNOWN
    assert rec.evidence["deregistered"] is True
    assert "no_evidence_default" in rec.evidence["flags"]


def test_unknown_ticker_returns_unknown(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    classifier = DelistClassifier(fake_edgar, resolver)
    rec = classifier.classify_ticker("NOPE", "2024-01-01")
    assert rec.bucket is CrspBucket.UNKNOWN
    assert rec.cik is None


def test_a_current_ticker_map_hit_is_flagged(fake_edgar):
    resolver = TickerResolver(fake_edgar)
    rec = DelistClassifier(fake_edgar, resolver).classify_ticker("ALTR", "2025-03-26")
    assert rec.evidence["resolution_source"] == "company_tickers"
    assert rec.evidence["flags"] == ["resolved_by_current_ticker_map"]


from delist_detection.edgar import EdgarSubmission


class _TextEdgar:
    def __init__(self, filings, texts):
        self.filings, self.texts = filings, texts
    def company_tickers(self):
        return {"REORG": {"cik_str": 5, "ticker": "REORG", "title": "Reorg Co"}}
    def recent_filings(self, cik):
        return list(self.filings)
    def submissions(self, cik):
        return {"name": "Reorg Co", "formerNames": [], "sic": "1311"}
    def fetch_filing_text(self, cik, acc, doc):
        return self.texts.get(acc, "")


def test_bankruptcy_history_beats_continued_filings():
    fs = [
        EdgarSubmission("A1", "8-K", "2020-09-30", "2020-09-29", "1.01,1.03,7.01", "a.htm"),
        EdgarSubmission("A2", "25-NSE", "2020-10-27", "", "", "p.xml"),
        EdgarSubmission("A3", "10-Q", "2021-08-05", "", "", "q.htm"),   # reorganized company keeps filing
    ]
    e = _TextEdgar(fs, {"A1": "Item 1.03 Bankruptcy or Receivership. On September 29, 2020, "
                              "the Company filed voluntary petitions under chapter 11"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2020-11-20")
    assert rec.bucket is CrspBucket.LIQUIDATION and rec.crsp_code == 470


def test_a_1_03_tag_without_bankruptcy_text_is_not_a_bankruptcy():
    fs = [
        EdgarSubmission("B1", "8-K", "2024-11-27", "2024-11-27", "1.01,1.03,2.01,3.01,3.03,5.01", "b.htm"),
        EdgarSubmission("B2", "25-NSE", "2024-11-27", "", "", "p.xml"),
        EdgarSubmission("B3", "15-12G", "2024-12-09", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {"B1": "completion of the merger; each share converted into the right to receive"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-11-27")
    assert rec.bucket is CrspBucket.MERGER
    assert "bankruptcy_tag_unconfirmed" in rec.evidence["flags"]


def test_bankruptcy_wording_outside_a_1_03_section_does_not_confirm_the_tag():
    # A takeover 8-K mis-tagged 1.03 (KCI, VRTV): the credit-agreement boilerplate
    # says "bankruptcy", but the filing has no Item 1.03 section.
    fs = [
        EdgarSubmission("K1", "8-K", "2024-11-27", "2024-11-27", "1.02,1.03,2.01,3.01,5.01", "k.htm"),
        EdgarSubmission("K2", "25-NSE", "2024-11-27", "", "", "p.xml"),
        EdgarSubmission("K3", "15-12G", "2024-12-09", "", "", "f.htm"),
    ]
    text = ("Item 1.02 Termination of a Material Definitive Agreement. The credit agreement, whose "
            "obligations accelerate upon the bankruptcy or insolvency of the borrower, was terminated. "
            "Item 2.01 Completion of Acquisition or Disposition of Assets. Item 5.01 Changes in Control.")
    e = _TextEdgar(fs, {"K1": text})
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-11-27")
    assert rec.bucket is CrspBucket.MERGER and rec.crsp_code == 231
    assert "bankruptcy_tag_unconfirmed" in rec.evidence["flags"]


def test_a_1_03_tag_whose_text_is_missing_is_confirmed_and_flagged():
    fs = [
        EdgarSubmission("L1", "8-K", "2020-09-30", "2020-09-29", "1.03,7.01", "l.htm"),
        EdgarSubmission("L2", "25-NSE", "2020-10-27", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {})          # the text fetch missed
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2020-11-20")
    assert rec.bucket is CrspBucket.LIQUIDATION and rec.crsp_code == 470
    assert rec.evidence["flags"].count("bankruptcy_text_missing") == 1


def test_an_old_form25_from_another_event_is_not_the_anchor():
    # 1,037 days: inside the 1,500-day window, so the operating-filings rule is what rejects it
    fs = [
        EdgarSubmission("C1", "25-NSE", "2021-08-16", "", "", "p.xml"),          # warrant delisting
        EdgarSubmission("C2", "8-K", "2021-08-16", "2021-08-16", "8.01,9.01", "c.htm"),
        EdgarSubmission("C3", "10-Q", "2023-11-05", "", "", "q.htm"),
        EdgarSubmission("C4", "8-K", "2024-06-18", "2024-06-18", "7.01,9.01", "d.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2024-06-18")
    assert rec.evidence.get("delist_filing") is None
    assert rec.bucket is not CrspBucket.COMPLIANCE_FAILURE


def test_an_earlier_merger_form25_marks_a_frozen_tail():
    fs = [
        EdgarSubmission("D1", "8-K", "2010-06-25", "2010-06-25", "3.01,3.03,5.01", "a.htm"),
        EdgarSubmission("D2", "25-NSE", "2010-06-28", "", "", "p.xml"),
        EdgarSubmission("D3", "10-K", "2011-02-25", "", "", "k.htm"),              # registered debt
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2013-02-07")
    assert rec.evidence["delist_filing"]["accession"] == "D2"
    assert any(f.startswith("frozen_tail:") for f in rec.evidence["flags"])


import pytest


@pytest.mark.parametrize("items, code", [
    ({"3.01", "3.03", "5.01", "5.02", "5.03"}, 231),        # BCR, GXP, IRF: target 8-K without 2.01
    ({"3.01", "5.01", "9.01"}, 231),                         # FWLT
    ({"3.03", "5.01", "5.02"}, 231),
    ({"1.01", "2.04", "3.01", "3.03", "5.01"}, 231),         # ONXX, SLXP: notes put on change in control
    ({"2.04", "3.01"}, 470),                                 # distress lead-in stays distress
    ({"3.01", "8.01"}, 570),
    ({"1.03", "3.01"}, 470),
])
def test_item_fingerprints(items, code):
    c = DelistClassifier(edgar=None, resolver=None)
    assert c._classify_items(items)[0] == code


class _RenameEdgar(_TextEdgar):
    def submissions(self, cik):
        return LC_LIKE


LC_LIKE = {"name": "Happen, Inc.", "sic": "6141", "formerNames": [
    {"name": "Reorg Co", "from": "2007-08-15T04:00:00.000Z", "to": "2026-06-18T04:00:00.000Z"}]}


def test_rename_while_still_operating_is_an_exchange_transfer():
    fs = [
        EdgarSubmission("E0", "10-K", "2026-02-20", "", "", "k.htm"),   # existed before the date
        EdgarSubmission("E1", "8-K", "2026-06-02", "2026-06-02", "3.01,7.01,9.01", "a.htm"),
        EdgarSubmission("E2", "25", "2026-06-18", "", "", "p.xml"),
        EdgarSubmission("E3", "8-K", "2026-07-27", "2026-07-27", "2.02,9.01", "b.htm"),
    ]
    e = _RenameEdgar(fs, {"E1": "Item 3.01 ... transfer the listing to The Nasdaq Stock Market"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2026-06-01")
    assert rec.bucket is CrspBucket.EXCHANGE_TRANSFER and rec.crsp_code == 304


class _MergerRenameEdgar(_TextEdgar):
    def submissions(self, cik):
        return TARGETCO_LIKE


TARGETCO_LIKE = {"name": "Acquirer Co", "sic": "1311", "formerNames": [
    {"name": "TargetCo, Inc.", "from": "2010-01-01T04:00:00.000Z", "to": "2026-06-01T04:00:00.000Z"}]}


def test_merger_fingerprint_blocks_the_rename_rule():
    """A merger 8-K (2.01+3.01+5.01) near a name change at closing, with the
    surviving debt still reporting afterward and no Form 15, is a MERGER —
    not an EXCHANGE_TRANSFER just because renamed_near fires."""
    fs = [
        EdgarSubmission("M0", "10-K", "2026-02-20", "", "", "k.htm"),          # well before the date
        EdgarSubmission("M1", "8-K", "2026-06-01", "2026-06-01", "2.01,3.01,5.01", "a.htm"),
        EdgarSubmission("M2", "25-NSE", "2026-06-01", "", "", "p.xml"),
        EdgarSubmission("M3", "10-Q", "2026-09-29", "", "", "q.htm"),          # 120 days later
    ]
    e = _MergerRenameEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2026-06-01")
    assert rec.bucket is CrspBucket.MERGER and rec.crsp_code == 231


class _BareDispositionRenameEdgar(_TextEdgar):
    def submissions(self, cik):
        return RENAMED_LIKE


RENAMED_LIKE = {"name": "Renamed Co", "sic": "6141", "formerNames": [
    {"name": "OldCo, Inc.", "from": "2010-01-01T04:00:00.000Z", "to": "2026-06-01T04:00:00.000Z"}]}


def test_a_bare_201_does_not_block_a_rename():
    """2.01 alone (a disposition, not a change in control) is not a merger
    fingerprint and must not block the rename rule."""
    fs = [
        EdgarSubmission("N0", "10-K", "2026-02-20", "", "", "k.htm"),
        EdgarSubmission("N1", "8-K", "2026-06-02", "2026-06-02", "2.01,9.01", "a.htm"),
        EdgarSubmission("N2", "8-K", "2026-07-27", "2026-07-27", "2.02,9.01", "b.htm"),
    ]
    e = _BareDispositionRenameEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2026-06-01")
    assert rec.bucket is CrspBucket.EXCHANGE_TRANSFER and rec.crsp_code == 304


class _SpacEdgar(_TextEdgar):
    def submissions(self, cik):
        return {"name": "Blue Whale Acquisition Corp I", "sic": "6770", "formerNames": []}


def test_spac_liquidation_is_expiration_even_with_a_late_filing_notice():
    fs = [
        EdgarSubmission("S1", "8-K", "2023-04-25", "2023-04-25", "3.01,9.01", "a.htm"),
        EdgarSubmission("S2", "NT 10-K", "2023-03-31", "", "", "n.htm"),
        EdgarSubmission("S3", "25-NSE", "2023-08-04", "", "", "p.xml"),
        EdgarSubmission("S4", "15-12G", "2023-08-14", "", "", "f.htm"),
    ]
    e = _SpacEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-08-11")
    assert rec.bucket is CrspBucket.EXPIRATION and rec.crsp_code == 600
    assert "spac" in rec.evidence["flags"]


def test_form25_form15_with_a_merger_proxy_is_a_merger():
    fs = [
        EdgarSubmission("M1", "DEFM14A", "2015-08-20", "", "", "d.htm"),
        EdgarSubmission("M2", "25-NSE", "2015-11-18", "", "", "p.xml"),
        EdgarSubmission("M3", "8-K", "2015-11-18", "2015-11-18", "8.01,9.01", "a.htm"),
        EdgarSubmission("M4", "15-12G", "2015-11-30", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2015-11-18")
    assert rec.bucket is CrspBucket.MERGER and rec.crsp_code == 231


def test_form25_form15_with_2_01_alone_is_a_merger():
    fs = [
        EdgarSubmission("U1", "8-K", "2016-01-22", "2016-01-22", "1.01,2.01,9.01", "a.htm"),
        EdgarSubmission("U2", "25-NSE", "2016-01-22", "", "", "p.xml"),
        EdgarSubmission("U3", "15-12G", "2016-02-01", "", "", "f.htm"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2016-02-01")
    assert rec.bucket is CrspBucket.MERGER and rec.crsp_code == 233


def test_a_3_01_notice_citing_a_deficiency_stays_compliance():
    fs = [
        EdgarSubmission("N1", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
        EdgarSubmission("N2", "25-NSE", "2023-05-10", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {"N1": "Item 3.01 ... has not regained compliance with the minimum bid price requirement"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-05-10")
    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE


def test_a_deficiency_notice_beats_an_older_merger_proxy():
    """A deal that fell through can precede a real compliance delisting: the
    deficiency wording in the 3.01 notice outranks a proxy 200 days earlier."""
    fs = [
        EdgarSubmission("P1", "DEFM14A", "2022-10-22", "", "", "d.htm"),   # 200 days before the Form 25
        EdgarSubmission("P2", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
        EdgarSubmission("P3", "25-NSE", "2023-05-10", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {"P2": "Item 3.01 ... has not regained compliance with the minimum bid price requirement"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-05-10")
    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE and rec.crsp_code == 570


def test_a_bare_3_01_without_a_form25_is_unknown():
    fs = [
        EdgarSubmission("Q1", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
    ]
    e = _TextEdgar(fs, {"Q1": "Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule "
                              "or Standard; Transfer of Listing. The Company notified Nasdaq of its intent "
                              "to delist its common stock."})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-05-10")
    assert rec.evidence.get("delist_filing") is None
    assert rec.bucket is CrspBucket.UNKNOWN
    assert "no_evidence_default" in rec.evidence["flags"]
    assert rec.evidence["deregistered"] is False


def test_an_uppercase_item_heading_still_reads_the_deficiency_notice():
    fs = [
        EdgarSubmission("V1", "8-K", "2019-06-05", "2019-06-05", "3.01,9.01", "a.htm"),
        EdgarSubmission("V2", "25-NSE", "2019-06-07", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {"V1": "ITEM 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule or "
                              "Standard. The Company is not in compliance with the continued listing standards "
                              "regarding low selling price issues"})           # Nobilis 0001409916-19-000036
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2019-06-07")
    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE and rec.crsp_code == 570


def test_a_3_01_notice_whose_text_is_missing_is_flagged():
    fs = [
        EdgarSubmission("W1", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
        EdgarSubmission("W2", "25-NSE", "2023-05-10", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-05-10")
    assert rec.bucket is CrspBucket.UNKNOWN
    assert "notice_text_missing" in rec.evidence["flags"]


def test_a_deficiency_notice_with_a_late_filing_is_580():
    fs = [
        EdgarSubmission("X0", "NT 10-K", "2023-03-31", "", "", "n.htm"),
        EdgarSubmission("X1", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
        EdgarSubmission("X2", "25-NSE", "2023-05-10", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {"X1": "Item 3.01 ... has not regained compliance with the minimum bid price requirement"})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-05-10")
    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE and rec.crsp_code == 580


def test_a_late_filing_alone_is_580_measured_from_the_form25():
    """NT 10-K 360 days before the Form 25 but 400 days before the vendor's last
    row: inside the window only when it is measured from the Form 25."""
    fs = [
        EdgarSubmission("Y0", "NT 10-K", "2022-05-15", "", "", "n.htm"),
        EdgarSubmission("Y1", "8-K", "2023-05-08", "2023-05-08", "3.01,8.01", "a.htm"),
        EdgarSubmission("Y2", "25-NSE", "2023-05-10", "", "", "p.xml"),
    ]
    e = _TextEdgar(fs, {"Y1": "Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule "
                              "or Standard. The Company notified the exchange of its intent to delist."})
    from delist_detection.ticker_resolver import TickerResolver
    rec = DelistClassifier(e, TickerResolver(e)).classify_ticker("REORG", "2023-06-19")
    assert rec.evidence["anchor_gap_days"] == 40
    assert rec.bucket is CrspBucket.COMPLIANCE_FAILURE and rec.crsp_code == 580
