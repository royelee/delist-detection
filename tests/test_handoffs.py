"""Ticker handoffs (handoff plan, Part 2): one security stops trading under a
ticker and another security of the run starts under it within days."""
from datetime import date

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.delistings import Delisting
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.handoffs import (
    CONTINUATION_DAYS, OVERLAP_DAYS, TAKEOVER_DAYS, HandoffDecision, HandoffPair, apply_handoffs, continuation_filing,
    cusip_switch, own_continuation_filing, decide_handoff, drop_resolved_shared, find_handoffs, issuer_carries_on, predecessor_names,
)
from delist_detection.history import Sighting
from delist_detection.last_trade import LastTrade
from delist_detection.llm_merger_extractor import MergerTerms
from delist_detection.merger_value import MergerValue, MergerValues, TableTerms
from delist_detection.review_triage import FilingRef, ReviewItem
from delist_detection.rewrites import SUCCESSOR_UNKNOWN, Rule, rewrite_by
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
    assert pairs == [HandoffPair("MNST", "OLD", "NEW", "2015-06-12", "2015-06-15", "2015-06-15", "2015-06-12")]
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


def test_a_line_that_lived_on_under_another_ticker_is_continued_by_nobody():
    """DLPH 2017: Delphi Automotive renamed itself Aptiv and moved to APTV on
    2017-12-05; the spun-off Delphi Technologies (a new CUSIP under DLPH from
    2017-12-07) took the old ticker. The CUSIP switch under DLPH is real, but A
    lived on: no continuation, whatever the evidence."""
    (p,) = find_handoffs({
        "DELPHI": _sig(("2017-06-30", "DLPH", "observation"), ("2017-12-05", "DLPH"), ("2017-12-06", "APTV"),
                       ("2018-06-29", "APTV", "observation")),
        "DLPHTECH": _sig(("2017-12-07", "DLPH"), ("2017-12-29", "DLPH", "observation")),
    })
    assert (p.a_last, p.a_last_any) == ("2017-12-05", "2018-06-29")
    assert decide_handoff(p, filing=None, same_issuer=False, cusip_switch=True) is None
    assert decide_handoff(p, filing=FILING, same_issuer=False, cusip_switch=True) is None


def test_an_issuer_that_carries_on_in_another_line_hands_its_ticker_to_nobody():
    """LMCA 2013: old Liberty Media (CIK 1507934) went on as Starz (STRZA, a new
    line of its own from 2013-01-17), while the spun-off Liberty Media (CIK
    1560385) took LMCA. By timing, no continuation; the same issuer's new
    lines of a reclassification (FWONA and LSXMA, one CIK) do not count."""
    secs = {"OLD": _sec("OLD", cik=1507934), "STARZ": _sec("STARZ", cik=1507934),
            "NEWLMC": _sec("NEWLMC", cik=1560385)}
    p = HandoffPair("LMCA", "OLD", "NEWLMC", "2013-01-16", "2013-01-23", "2013-01-17", "2013-01-16")
    first = {"OLD": "2011-11-30", "STARZ": "2013-01-17", "NEWLMC": "2013-01-17"}
    assert issuer_carries_on(p, secs, first)
    assert decide_handoff(p, filing=None, same_issuer=False, cusip_switch=True, issuer_carries_on=True) is None
    reclass = {"FWONA": _sec("FWONA", cik=1560385), "FWONA2": _sec("FWONA2", cik=1560385),
               "LSXMA2": _sec("LSXMA2", cik=1560385)}
    q = HandoffPair("FWONA", "FWONA", "FWONA2", "2023-08-04", "2023-08-07", "2023-08-07", "2023-08-04")
    assert not issuer_carries_on(q, reclass, {"FWONA": "2017-01-26", "FWONA2": "2023-08-07", "LSXMA2": "2023-08-07"})


def test_an_older_issuer_that_takes_the_ticker_is_a_takeover_even_unseen_before():
    """CZR 2020: Eldorado Resorts (CIK 1590895, filing since 2013), not observed
    as ERI, renamed itself Caesars Entertainment Inc and took CZR with a new
    CUSIP. Its line has no earlier sighting, but its issuer is an older,
    different company."""
    czr = _pair("2020-07-30", "2020-07-22", ticker="CZR")
    assert decide_handoff(czr, filing=None, same_issuer=False, cusip_switch=False) is None
    d = decide_handoff(czr, filing=None, same_issuer=False, cusip_switch=False, b_issuer_since="2013-10-01")
    assert (d.kind, d.evidence) == ("takeover", "timing:issuer")
    new = decide_handoff(czr, filing=None, same_issuer=False, cusip_switch=False, b_issuer_since="2020-03-01")
    assert new is None                                                   # a new issuer: a spin-off or a new holdco


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
AON_F25 = FilingRef("25-NSE", "0000876661-20-000266", "2020-03-31")
AON_UNMATCHED = ReviewItem("OLD", "AON", 315293, "form25_unmatched",
                           "25-NSE 0000876661-20-000266 ('Class A Ordinary Shares'): ambiguous class",
                           delist_date="2020-04-10", filing=AON_F25)


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
                         delist_date="2020-04-10", filing=AON_F25),
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
    handoff = rewrite_by(d, Rule.HANDOFF)          # the stage 9c cap, typed
    assert (handoff.successor, handoff.evidence, handoff.successor_from) == (
        "NEW", "8-K12B 0001104659-20-041234", "2020-04-01")


def test_a_continuation_by_timing_with_no_form25_is_dated_the_day_after_and_is_medium():
    out = apply_handoffs([HandoffDecision(AON, "continuation", "timing:cik", False)], [],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [])
    (d,) = out.added
    assert (d.delist_date, d.record.confidence) == ("2020-04-01", "medium")
    assert "timing:cik" in d.record.reason and "delist_filing" not in d.record.evidence
    assert out.counts["continuations_by_timing"] == 1


def test_the_old_line_ends_before_the_new_one_begins():
    """ST 2018: both lines sighted on 2018-03-28 (a fails row carries the day
    before's close): the old line's last trade is 2018-03-27. A kept row with
    no last-trade day (PNFP 2026) takes the same day."""
    st = HandoffPair("ST", "OLD", "NEW", "2018-03-28", "2018-03-28", "2018-03-28", "2018-03-28")
    (d,) = apply_handoffs([HandoffDecision(st, "continuation", "timing:cik", False)], [],
                          {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, []).added
    assert d.last_trade.day == date(2018, 3, 27) and d.delist_date == "2018-03-29"
    row = _delisting("OLD", "2026-01-12", CrspBucket.MERGER, "2026-01-02", flags=("no_last_trade_date",))
    row.last_trade = LastTrade(None, "", ("no_last_trade_date",))
    p = HandoffPair("PNFP", "OLD", "NEW", "2026-01-12", "2026-01-05", "2026-01-05", "2026-01-12")
    apply_handoffs([HandoffDecision(p, "continuation", "8-K12B X", True)], [row],
                   {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], payouts=MergerValues())
    assert row.last_trade.day == date(2026, 1, 4) and "no_last_trade_date" not in row.flags


def test_a_worked_out_closing_day_never_reaches_the_successors_first_day():
    """5d rule 4: a kept row's closing day (the Form 25 day, 2013-11-13) on the day the successor was first sighted
    under the ticker is cut to the old line's last day before it; one before it stands."""
    p = HandoffPair("X", "OLD", "NEW", "2013-11-12", "2013-11-13", "2013-11-13")
    late = _delisting("OLD", "2013-11-23", CrspBucket.EXCHANGE_TRANSFER, "2013-11-13", code=304)
    late.last_trade = LastTrade(date(2013, 11, 13), "closing_day", ("last_trade_date_unconfirmed",))
    early = _delisting("OLD", "2013-11-23", CrspBucket.EXCHANGE_TRANSFER, "2013-11-11", code=304)
    early.last_trade = LastTrade(date(2013, 11, 11), "closing_day", ("last_trade_date_unconfirmed",))
    for row, day, source in ((late, date(2013, 11, 12), "last_sighting"), (early, date(2013, 11, 11), "closing_day")):
        apply_handoffs([HandoffDecision(p, "continuation", "8-K12B X", True)], [row],
                       {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [])
        assert (row.last_trade.day, row.last_trade.source) == (day, source)


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
    assert row.record.reason.endswith("; successor by handoff (timing:cik)")


def test_a_merger_row_is_rewritten_on_filing_evidence_and_the_old_bucket_is_reviewed():
    """PNFP 2026 (verify): a merger row where the successor issuer's 8-K12B says
    the holders' shares became the holding company's."""
    row = _delisting("OLD", "2026-01-12", CrspBucket.MERGER, "2026-01-02")
    p = HandoffPair("PNFP", "OLD", "NEW", "2026-01-12", "2026-01-05", "2026-01-05")
    out = apply_handoffs([HandoffDecision(p, "continuation", "8-K12B 0000000000-26-000001", True)], [row],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], reconciled={row.key},
                         payouts=MergerValues())
    assert (row.record.bucket, row.record.crsp_code, row.record.confidence) == (CrspBucket.EXCHANGE_TRANSFER, 304,
                                                                                "high")
    assert row.record.successor_sec_id == "NEW" and "handoff_continuation" in row.flags
    (item,) = out.review
    assert (item.sec_id, item.delist_date, item.flag) == ("OLD", "2026-01-12", "handoff_rebucketed")
    assert "merger" in item.reason and "231" in item.reason


def test_a_rewritten_merger_drops_its_payout_reads_and_flags_and_a_rewritten_unknown_its_default():
    """AZPN 2022: the merger row the handoff makes a continuation carried its gate's flags and value; ENDP 2014 its
    lagged acquirer close; GOOGL 2015 (an `unknown` Form 25 at Alphabet's 8-K12B) the no-evidence default. A
    continuation carries none of them (`rewrites.continuation`); the last close's own flags stay."""
    azpn = _delisting("OLD", "2022-05-26", CrspBucket.MERGER, "2022-05-16", ticker="AZPN",
                      flags=("last_trade_date_unconfirmed", "ftd_close_prior:1", "acquirer_close_lagged"))
    values = MergerValues({azpn.key: MergerValue(azpn.key, llm=MergerTerms("cash", 87.69, None, None, None, "high",
                                                                          "8-K:X", ""),
                                                 flags=("payout_gate_failed:87.69", "terms_gate_failed:no_acq_ticker"))})
    p = HandoffPair("AZPN", "OLD", "NEW", "2022-05-17", "2022-05-18", "2022-05-18")
    apply_handoffs([HandoffDecision(p, "continuation", "8-K12B 0001140361-22-019477", True)], [azpn],
                   {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], payouts=values)
    assert (azpn.record.bucket, azpn.record.crsp_code, azpn.record.successor_sec_id) == (
        CrspBucket.EXCHANGE_TRANSFER, 304, "NEW")
    assert azpn.flags == ["last_trade_date_unconfirmed", "ftd_close_prior:1", "handoff_continuation"]
    assert values.get(azpn.key) is None and values.table_terms(azpn.key) == TableTerms()
    googl = _delisting("OLD", "2015-10-12", CrspBucket.UNKNOWN, "2015-10-02", code=None, ticker="GOOGL",
                       flags=("no_evidence_default",))
    p = HandoffPair("GOOGL", "OLD", "NEW", "2015-10-05", "2015-10-06", "2015-10-06")
    apply_handoffs([HandoffDecision(p, "continuation", "8-K12B 0001193125-15-336577", True)], [googl],
                   {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], payouts=MergerValues())
    assert googl.record.crsp_code == 304 and googl.flags == ["handoff_continuation"]


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


def test_a_merger_row_stands_against_a_cusip_switch_between_two_issuers():
    """IGT 2015: GTECH's new holding company, International Game Technology PLC,
    took IGT when it bought International Game Technology for $13.69 and 0.1819
    shares. A CUSIP switch between two issuers is no evidence of a one-for-one
    exchange: the merger row stands, reviewed as handoff_conflict. On the same
    issuer (a holding company of its own), timing rewrites it."""
    row = _delisting("OLD", "2015-04-17", CrspBucket.MERGER, "2015-04-07", ticker="IGT")
    p = HandoffPair("IGT", "OLD", "NEW", "2015-04-07", "2015-04-08", "2015-04-08", "2015-04-07")
    out = apply_handoffs([HandoffDecision(p, "continuation", "timing:cusip", False)], [row],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW", cik=1)}, [])
    assert row.record.bucket is CrspBucket.MERGER and row.record.successor_sec_id is None
    assert [i.flag for i in out.review] == ["handoff_conflict"]
    same = _delisting("OLD", "2016-09-30", CrspBucket.MERGER, "2016-09-19", ticker="ASH")
    q = HandoffPair("ASH", "OLD", "NEW", "2016-09-19", "2016-09-20", "2016-09-20", "2016-09-19")
    out = apply_handoffs([HandoffDecision(q, "continuation", "timing:cik", False)], [same],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [], payouts=MergerValues())
    assert same.record.bucket is CrspBucket.EXCHANGE_TRANSFER and same.record.successor_sec_id == "NEW"
    assert [i.flag for i in out.review] == ["handoff_rebucketed"]


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


def test_the_filing_is_searched_under_the_predecessors_names_around_the_handoff():
    """Ashland 2016: the old company's CIK is ASHLAND LLC today; the 8-K12B names
    Ashland Inc., its name at the handoff. The observed name, class words
    dropped, is tried last; each name once, state tags dropped."""
    sub = {"name": "ASHLAND LLC", "formerNames": [
        {"name": "ASHLAND INC.", "from": "2005-06-30T00:00:00.000Z", "to": "2016-09-20T00:00:00.000Z"},
        {"name": "ASHLAND INC /KY/", "from": "1994-01-01T00:00:00.000Z", "to": "2005-06-29T00:00:00.000Z"}]}
    assert predecessor_names(sub, "2016-09-19", "ASHLAND INC CLASS A") == ["ASHLAND INC.", "ASHLAND LLC",
                                                                          "ASHLAND INC"]
    assert predecessor_names(None, "2016-09-19", "HOLDCO INC") == ["HOLDCO INC"]


def _unmatched(sec_id, accession, delist_date, class_text="Common Stock"):
    filed = date.fromordinal(date.fromisoformat(delist_date).toordinal() - 10).isoformat()   # its effective date - 10
    return ReviewItem(sec_id, "TT", 1, "form25_unmatched", f"25-NSE {accession} ('{class_text}'): ambiguous class",
                      delist_date=delist_date, filing=FilingRef("25-NSE", accession, filed))


def test_the_continuation_row_takes_a_form25_effective_after_the_last_sighting_not_one_before():
    """FWONA 2023: the Braves split-off's Form 25 took effect on 2023-07-28, a
    week before the old Formula One line's last sighting (2023-08-04); the
    reclassification's own took effect on 2023-08-13. A delisting takes effect
    after the last trade: the row is dated by the later one, whose review rows
    the continuation resolves; the Braves rows stay."""
    p = HandoffPair("FWONA", "OLD", "NEW", "2023-08-04", "2023-08-07", "2023-08-07", "2023-08-04")
    braves = _unmatched("OLD", "0001354457-23-000512", "2023-07-28", "Series A Liberty Braves Common Stock")
    reclass = _unmatched("OLD", "0001354457-23-000564", "2023-08-13", "Series A Liberty Formula One Common Stock")
    out = apply_handoffs([HandoffDecision(p, "continuation", "timing:cik", False)], [],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [braves, reclass])
    (d,) = out.added
    assert d.delist_date == "2023-08-13"
    assert d.record.evidence["delist_filing"]["accession"] == "0001354457-23-000564"
    assert out.review == [braves]


def test_the_form25_window_runs_from_the_later_of_the_two_sightings():
    """LH 2024: old LabCorp's last fails row 2024-04-24 (sparse), the holding
    company's first 2024-05-22; old LabCorp's Form 25 took effect 2024-05-30,
    36 days after the first but 8 after the second."""
    p = HandoffPair("LH", "OLD", "NEW", "2024-04-24", "2024-05-22", "2024-05-22", "2024-04-24")
    f25 = _unmatched("OLD", "0000876661-24-000366", "2024-05-30", "Common Stock (CUSIP # 50540R409)")
    out = apply_handoffs([HandoffDecision(p, "continuation", "8-K12B 0000920148-24-000063", True)], [],
                         {"OLD": _sec("OLD"), "NEW": _sec("NEW")}, [f25])
    (d,) = out.added
    assert d.delist_date == "2024-05-30" and out.review == []


def _sub(form, day, acc="0000000001-19-000001"):
    return EdgarSubmission(accession=acc, form=form, filing_date=day, report_date="", items="", primary_doc="")


def test_own_continuation_filing_reads_the_successors_filing_list():
    filings = [_sub("8-K", "2019-07-31", "a"), _sub("8-K12B", "2019-07-31", "b"), _sub("10-Q", "2019-08-02", "c")]
    assert own_continuation_filing(filings, date(2019, 8, 1)) == ("8-K12B", "b", "2019-07-31")
    assert own_continuation_filing([_sub("8-K12G3", "2019-09-20", "d")], date(2019, 8, 1)) == ("8-K12G3", "d", "2019-09-20")


def test_own_continuation_filing_keeps_to_the_search_window():
    assert own_continuation_filing([_sub("8-K12B", "2019-06-30")], date(2019, 8, 1)) is None    # 32 days before
    assert own_continuation_filing([_sub("8-K12B", "2019-10-01")], date(2019, 8, 1)) is None    # 61 days after
    assert own_continuation_filing([_sub("8-K", "2019-07-31")], date(2019, 8, 1)) is None
