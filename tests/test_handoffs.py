"""Ticker handoffs (handoff plan, Part 2): one security stops trading under a
ticker and another security of the run starts under it within days."""
from datetime import date

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import SUCCESSOR_UNKNOWN, Delisting
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.handoffs import (
    CONTINUATION_DAYS, OVERLAP_DAYS, TAKEOVER_DAYS, HandoffDecision, HandoffPair, apply_handoffs, continuation_filing,
    cusip_switch, decide_handoff, drop_resolved_shared, find_handoffs,
)
from delist_detection.history import Sighting
from delist_detection.last_trade import LastTrade
from delist_detection.review_triage import ReviewItem
from delist_detection.security_master import Security


def _sig(*items):
    """(day, ticker[, source]) -> date-sorted Sightings."""
    return sorted(Sighting(d, t, s[0] if s else "ftd") for d, t, *s in items)


def _pairs(sightings):
    return [(p.ticker, p.a, p.b, p.a_last, p.b_first) for p in find_handoffs(sightings)]


def test_the_proposed_windows():
    assert (OVERLAP_DAYS, CONTINUATION_DAYS, TAKEOVER_DAYS) == (10, 10, 120)


def test_a_clean_adjoin_is_a_candidate():
    """MNST 2015: the old line's last sighting 2015-06-12, the holding company's
    first 2015-06-15."""
    pairs = find_handoffs({
        "OLD": _sig(("2014-12-31", "MNST", "observation"), ("2015-06-12", "MNST")),
        "NEW": _sig(("2015-06-15", "MNST"), ("2015-12-31", "MNST", "observation")),
    })
    assert pairs == [HandoffPair("MNST", "OLD", "NEW", "2015-06-12", "2015-06-15", "2015-06-15")]
    assert pairs[0].gap == 3


def test_the_same_day_is_a_candidate():
    """ST 2018 (NL -> UK): both lines sighted on 2018-03-28."""
    assert _pairs({"OLD": _sig(("2018-03-01", "ST"), ("2018-03-28", "ST")),
                   "NEW": _sig(("2018-03-28", "ST"), ("2018-06-29", "ST"))}) == [
        ("ST", "OLD", "NEW", "2018-03-28", "2018-03-28")]


def test_an_eight_day_overlap_is_a_candidate_and_the_taker_keeps_its_earlier_life():
    """CZR 2020: Eldorado (ERI) took the CZR ticker on 2020-07-22, while old
    Caesars' fails rows run to 2020-07-30. The taker's first sighting under any
    ticker (as ERI) is years earlier."""
    (p,) = find_handoffs({
        "CAESARS": _sig(("2019-12-31", "CZR", "observation"), ("2020-07-30", "CZR")),
        "ELDORADO": _sig(("2015-06-30", "ERI", "observation"), ("2020-07-20", "ERI"), ("2020-07-22", "CZR"),
                         ("2020-12-31", "CZR", "observation")),
    })
    assert (p.ticker, p.a, p.b, p.gap, p.b_first_any) == ("CZR", "CAESARS", "ELDORADO", -8, "2015-06-30")


def test_a_74_day_gap_is_a_candidate():
    """COHR 2022: Coherent's last sighting 2022-06-30, II-VI (renamed Coherent
    Corp) first under COHR 2022-09-12."""
    assert _pairs({"COHERENT": _sig(("2022-06-30", "COHR")),
                   "IIVI": _sig(("2012-06-29", "IIVI"), ("2022-09-12", "COHR"))}) == [
        ("COHR", "COHERENT", "IIVI", "2022-06-30", "2022-09-12")]


@pytest.mark.parametrize("a_last,b_first", [("2020-01-02", "2020-05-02"), ("2020-01-20", "2020-01-05")])
def test_a_pair_outside_the_window_is_not(a_last, b_first):
    """121 days apart, or an overlap of more than OVERLAP_DAYS (two lines that
    traded side by side under one ticker are no handoff)."""
    assert _pairs({"A": _sig(("2019-06-28", "XX"), (a_last, "XX")),
                   "B": _sig((b_first, "XX"), ("2020-12-31", "XX"))}) == []


def test_three_securities_in_sequence_give_two_pairs():
    """A -> B -> C under one ticker: each hands off to the next, never A to C."""
    assert _pairs({"A": _sig(("2010-01-04", "TT"), ("2010-06-30", "TT")),
                   "B": _sig(("2010-07-01", "TT"), ("2010-08-31", "TT")),
                   "C": _sig(("2010-09-01", "TT"), ("2011-06-30", "TT"))}) == [
        ("TT", "A", "B", "2010-06-30", "2010-07-01"), ("TT", "B", "C", "2010-08-31", "2010-09-01")]


def test_a_later_line_that_began_under_the_ticker_first_is_no_successor():
    """The pair runs forwards only: B must begin under the ticker after A did."""
    assert _pairs({"A": _sig(("2010-06-01", "TT"), ("2010-06-30", "TT")),
                   "B": _sig(("2010-01-04", "TT"), ("2010-06-25", "TT"))}) == []


def test_separator_spellings_are_one_ticker():
    assert _pairs({"A": _sig(("2010-06-30", "BF-B")), "B": _sig(("2010-07-01", "BFB"))}) == [
        ("BF-B", "A", "B", "2010-06-30", "2010-07-01")]


# --- deciding a pair (Task 4) ------------------------------------------------------------


def _pair(a_last, b_first, b_first_any=None, ticker="TT"):
    return HandoffPair(ticker, "A", "B", a_last, b_first, b_first_any or b_first)


FILING = ("8-K12B", "0001104659-20-041234", "2020-04-01")


def test_a_successor_issuers_filing_makes_a_continuation():
    """AON 2020: Aon plc (Ireland) filed an 8-K12B naming Aon plc (UK)."""
    d = decide_handoff(_pair("2020-04-01", "2020-04-01"), filing=FILING, same_issuer=False, cusip_switch=False)
    assert d == HandoffDecision(_pair("2020-04-01", "2020-04-01"), "continuation",
                                "8-K12B 0001104659-20-041234", True)


def test_the_filing_wins_over_timing_and_over_a_long_gap():
    """LH 2024: the old line's last fails row 2024-04-24, the holding company's
    first 2024-05-22 (sparse fails); the 8-K12B settles it, past CONTINUATION_DAYS."""
    d = decide_handoff(_pair("2024-04-24", "2024-05-22"), filing=FILING, same_issuer=True, cusip_switch=True)
    assert (d.kind, d.by_filing, d.evidence) == ("continuation", True, "8-K12B 0001104659-20-041234")


@pytest.mark.parametrize("same_issuer,switch,evidence", [(True, False, "timing:cik"), (False, True, "timing:cusip"),
                                                         (True, True, "timing:cik")])
def test_a_new_line_right_after_the_old_one_of_the_same_issuer_or_cusip_switch_is_a_continuation(
        same_issuer, switch, evidence):
    d = decide_handoff(_pair("2015-06-12", "2015-06-15"), filing=None, same_issuer=same_issuer, cusip_switch=switch)
    assert (d.kind, d.by_filing, d.evidence) == ("continuation", False, evidence)


def test_timing_needs_a_link_a_brand_new_line_and_a_short_gap():
    assert decide_handoff(_pair("2015-06-12", "2015-06-15"), filing=None, same_issuer=False,
                          cusip_switch=False) is None                     # no issuer or CUSIP link
    assert decide_handoff(_pair("2015-06-12", "2015-06-30"), filing=None, same_issuer=True,
                          cusip_switch=True) is None                      # 18 days: past CONTINUATION_DAYS
    d = decide_handoff(_pair("2015-06-12", "2015-06-15", "2010-01-04"), filing=None, same_issuer=True,
                       cusip_switch=False)
    assert d.kind == "takeover"                                          # B traded (as another ticker) before


def test_a_line_that_traded_before_under_another_ticker_takes_the_ticker_over():
    """COHR 2022 (74 days, II-VI since 2012) and CZR 2020 (an 8-day overlap,
    Eldorado since 2015)."""
    cohr = _pair("2022-06-30", "2022-09-12", "2012-06-29", "COHR")
    assert decide_handoff(cohr, filing=None, same_issuer=False, cusip_switch=False) == HandoffDecision(
        cohr, "takeover", "timing", False)
    czr = _pair("2020-07-30", "2020-07-22", "2015-06-30", "CZR")
    assert decide_handoff(czr, filing=None, same_issuer=False, cusip_switch=False).kind == "takeover"


def test_otherwise_nothing():
    """A new, unrelated line that takes a ticker weeks later: no link either way."""
    assert decide_handoff(_pair("2015-06-12", "2015-08-15"), filing=None, same_issuer=False,
                          cusip_switch=False) is None


def test_continuation_filing_is_one_the_successor_issuer_filed():
    calls = []
    hits = [{"_source": {"ciks": ["0000000999"], "form": "8-K12B", "file_date": "2020-03-31", "adsh": "X-1",
                         "display_names": ["Other Co (OTH) (CIK 0000000999)"]}},
            {"_source": {"ciks": ["0000315293"], "form": "8-K12B", "file_date": "2020-04-01",
                         "adsh": "0001104659-20-041234", "display_names": ["Aon plc (AON) (CIK 0000315293)"]}}]

    def search(q, forms, lo, hi):
        calls.append((q, forms, lo, hi))
        return hits

    assert continuation_filing(search, name="Aon plc", day=date(2020, 4, 1), successor_cik=315293) == FILING
    assert calls == [('"Aon plc"', "8-K12B,8-K12G3", date(2020, 3, 2), date(2020, 5, 31))]
    assert continuation_filing(search, name="Aon plc", day=date(2020, 4, 1), successor_cik=1) is None


def test_a_cusip_switch_under_the_ticker_near_the_handoff():
    """ITT 2016: 450911201 last fails under ITT 2016-05-17, 45073V108 first 2016-05-18."""
    ftd = FtdIndex([FtdRow("2016-05-02", "450911201", "ITT", "ITT CORP", 35.0),
                    FtdRow("2016-05-17", "450911201", "ITT", "ITT CORP", 35.1),
                    FtdRow("2016-05-18", "45073V108", "ITT", "ITT INC", 35.2),
                    FtdRow("2016-06-01", "45073V108", "ITT", "ITT INC", 36.0)])
    p = _pair("2016-05-17", "2016-05-18", ticker="ITT")
    assert cusip_switch(ftd, p, ["450911201"], ["45073V108"])
    assert not cusip_switch(ftd, p, ["450911201"], ["450911201"])        # one CUSIP: no switch
    assert not cusip_switch(ftd, p, ["450911201"], ["99999Z999"])        # B's CUSIP never fails under ITT
    late = _pair("2016-05-17", "2016-05-18", ticker="ITT")
    far = FtdIndex([FtdRow("2016-01-04", "450911201", "ITT", "ITT CORP", 35.0),
                    FtdRow("2016-05-18", "45073V108", "ITT", "ITT INC", 35.2)])
    assert not cusip_switch(far, late, ["450911201"], ["45073V108"])     # A's CUSIP stopped months before


# --- acting on a pair (Task 5) -----------------------------------------------------------


def _sec(sid, cik=315293, name="AON PLC", ticker="AON"):
    return Security(sid, cik, "COMMON", name, "Common Stock", True, "cusip")


def _delisting(sid, dd, bucket, last_trade, code=231, cik=315293, ticker="AON", flags=()):
    rec = DelistRecord(ticker, cik, last_trade, code, bucket, "high", "M&A 2.01+3.01+5.01",
                       evidence={"flags": list(flags)}, sec_id=sid, delist_date=dd)
    return Delisting(sid, cik, ticker, dd, rec, LastTrade(date.fromisoformat(last_trade), "midas", ()), None, None,
                     "NYSE")


AON = HandoffPair("AON", "OLD", "NEW", "2020-03-31", "2020-04-01", "2020-04-01")
AON_UNMATCHED = ReviewItem("OLD", "AON", 315293, "form25_unmatched",
                           "25-NSE 0000876661-20-000266 ('Class A Ordinary Shares'): ambiguous class",
                           delist_date="2020-04-10")


def test_a_continuation_with_no_delisting_gets_an_exchange_transfer_row():
    """AON 2020: no row (the Form 25 was ambiguous between the two lines); the
    pass writes one, dated by that Form 25, ending on A's last sighting, a zero-
    return exchange transfer whose successor is the new line; the review rows it
    resolves (its ended_without_delisting, both lines' ambiguous-Form-25 rows)
    go."""
    review = [ReviewItem("OLD", "AON", 315293, "ended_without_delisting", "not listed today ...",
                         last_seen="2020-03-31"),
              AON_UNMATCHED,
              ReviewItem("NEW", "AON", 315293, "form25_unmatched",
                         "25-NSE 0000876661-20-000266 ('Class A Ordinary Shares'): ambiguous class",
                         delist_date="2020-04-10"),
              ReviewItem("OTHER", "ZZ", 1, "ended_without_delisting", "not listed today ...")]
    out = apply_handoffs([HandoffDecision(AON, "continuation", "8-K12B 0001104659-20-041234", True)], [],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, review)
    (d,) = out.added
    assert (d.sec_id, d.delist_date, d.ticker, d.cik) == ("OLD", "2020-04-10", "AON", 315293)
    assert d.last_trade.day == date(2020, 3, 31) and d.last_trade.source == "last_sighting"
    assert (d.record.bucket, d.record.crsp_code, d.record.confidence) == (CrspBucket.EXCHANGE_TRANSFER, 304, "high")
    assert d.record.successor_sec_id == "NEW" and d.record.ticker_successor_sec_id is None
    assert d.flags == ["handoff_continuation"]
    assert "8-K12B 0001104659-20-041234" in d.record.reason and "NEW" in d.record.reason
    assert d.record.evidence["delist_filing"] == {"form": "25-NSE", "filing_date": "2020-03-31",
                                                  "accession": "0000876661-20-000266"}
    assert [(r.sec_id, r.flag) for r in out.review] == [("OTHER", "ended_without_delisting")]
    assert out.counts == {"handoffs": 1, "continuations_by_filing": 1, "continuations_by_timing": 0,
                          "takeovers": 0, "conflicts": 0, "rows_added": 1}


def test_a_continuation_by_timing_with_no_form25_is_dated_the_day_after_and_is_medium():
    out = apply_handoffs([HandoffDecision(AON, "continuation", "timing:cik", False)], [],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [])
    (d,) = out.added
    assert (d.delist_date, d.record.confidence) == ("2020-04-01", "medium")
    assert "timing:cik" in d.record.reason and "delist_filing" not in d.record.evidence
    assert out.counts["continuations_by_timing"] == 1


def test_an_existing_exchange_transfer_near_the_handoff_takes_the_successor():
    """ITT 2016: the old line's fallback exchange_transfer row (successor_unknown)."""
    row = _delisting("OLD", "2016-05-17", CrspBucket.EXCHANGE_TRANSFER, "2016-05-17", code=304,
                     flags=(SUCCESSOR_UNKNOWN, "no_form25"))
    p = HandoffPair("ITT", "OLD", "NEW", "2016-05-17", "2016-05-18", "2016-05-18")
    out = apply_handoffs([HandoffDecision(p, "continuation", "timing:cik", False)], [row],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [])
    assert out.added == []
    assert row.record.successor_sec_id == "NEW" and SUCCESSOR_UNKNOWN not in row.flags
    assert "handoff_continuation" in row.flags and row.record.bucket is CrspBucket.EXCHANGE_TRANSFER


def test_a_merger_row_is_rewritten_on_filing_evidence_and_the_old_bucket_is_reviewed():
    """PNFP 2026 (verify): a merger row where the successor issuer's 8-K12B says
    the holders' shares became the holding company's."""
    row = _delisting("OLD", "2026-01-12", CrspBucket.MERGER, "2026-01-02")
    p = HandoffPair("PNFP", "OLD", "NEW", "2026-01-12", "2026-01-05", "2026-01-05")
    out = apply_handoffs([HandoffDecision(p, "continuation", "8-K12B 0000000000-26-000001", True)], [row],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], reconciled={row.key})
    assert (row.record.bucket, row.record.crsp_code, row.record.confidence) == (CrspBucket.EXCHANGE_TRANSFER, 304,
                                                                                "high")
    assert row.record.successor_sec_id == "NEW" and "handoff_continuation" in row.flags
    (item,) = out.review
    assert (item.sec_id, item.delist_date, item.flag) == ("OLD", "2026-01-12", "handoff_rebucketed")
    assert "merger" in item.reason and "231" in item.reason


def test_a_merger_row_with_a_reconciled_payout_stands_against_timing_evidence():
    row = _delisting("OLD", "2026-01-12", CrspBucket.MERGER, "2026-01-02")
    p = HandoffPair("PNFP", "OLD", "NEW", "2026-01-12", "2026-01-15", "2026-01-15")
    out = apply_handoffs([HandoffDecision(p, "continuation", "timing:cik", False)], [row],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], reconciled={row.key})
    assert row.record.bucket is CrspBucket.MERGER and row.record.successor_sec_id is None
    assert "handoff_continuation" not in row.flags
    (item,) = out.review
    assert (item.sec_id, item.flag) == ("OLD", "handoff_conflict") and "NEW" in item.reason
    assert out.counts["conflicts"] == 1


def test_a_takeover_fills_the_ticker_successor_on_the_targets_row():
    """COHR 2022: Coherent's merger row stays a merger; II-VI took the ticker."""
    row = _delisting("COHERENT", "2022-07-11", CrspBucket.MERGER, "2022-06-30", ticker="COHR")
    p = HandoffPair("COHR", "COHERENT", "IIVI", "2022-06-30", "2022-09-12", "2012-06-29")
    out = apply_handoffs([HandoffDecision(p, "takeover", "timing", False)], [row],
                         {"COHERENT": _sec("COHERENT"), "IIVI": _sec("IIVI", cik=820318)}, [])
    assert row.record.ticker_successor_sec_id == "IIVI"
    assert row.record.bucket is CrspBucket.MERGER and row.record.successor_sec_id is None
    assert out.review == [] and out.counts["takeovers"] == 1


def test_a_takeover_with_no_delisting_to_mark_is_reviewed():
    p = HandoffPair("COHR", "COHERENT", "IIVI", "2022-06-30", "2022-09-12", "2012-06-29")
    out = apply_handoffs([HandoffDecision(p, "takeover", "timing", False)], [],
                         {"COHERENT": _sec("COHERENT"), "IIVI": _sec("IIVI", cik=820318)}, [])
    (item,) = out.review
    assert (item.sec_id, item.ticker, item.flag) == ("COHERENT", "COHR", "handoff_takeover_no_delisting")
    assert "IIVI" in item.reason


def test_the_pairs_ticker_shared_rows_are_resolved():
    out = apply_handoffs([HandoffDecision(AON, "continuation", "timing:cik", False)], [],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [])
    shared = [ReviewItem("OLD", "AON", None, "ticker_shared",
                         "AON 2004-01-02..2020-04-01 (OLD) overlaps AON 2020-04-01.. (NEW)"),
              ReviewItem("OLD", "AON", None, "ticker_shared",
                         "AON 2004-01-02..2020-04-01 (OLD) overlaps AON 2001-04-01..2004-01-05 (THIRD)")]
    assert drop_resolved_shared(shared, out.resolved_pairs) == shared[1:]
