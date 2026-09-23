from datetime import date
from pathlib import Path

from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingFinder, SecurityContext
from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import SecurityRef
from delist_detection.observations import Observation, split_eras
from delist_detection.security_master import Security
from delist_detection.ticker_resolver import TickerResolver

FIX = Path(__file__).parent / "fixtures" / "form25"
AET_RAW = (FIX / "aet_25nse.txt").read_text(encoding="utf-8", errors="replace")

CHICAGO_RAW = """<TYPE>25
<notificationOfRemoval><exchange><entityName>Chicago Stock Exchange, Inc.</entityName></exchange>
<descriptionClassSecurity>Common Stock</descriptionClassSecurity>
<ruleProvision>17 CFR 240.12d2-2(c)</ruleProvision></notificationOfRemoval>"""


def _sec(sec_id, cik, ticker, first, last, name):
    era = split_eras([Observation(ticker, first, name), Observation(ticker, last, name)])[0]
    return Security(sec_id, cik, "COMMON", name, "Common Stock", True, "cusip", "common", [era])


class _Midas:
    def __init__(self, day):
        self.day, self.calls = day, []

    def last_trade_day(self, ticker, lo, hi):
        self.calls.append((ticker, lo, hi))
        return self.day


def _aet_edgar(fake_edgar):
    fake_edgar.submissions_by_cik[1122304] = [
        EdgarSubmission("0000876661-18-001269", "25-NSE", "2018-11-29", "", "", "primary_doc.xml"),
        EdgarSubmission("0001122304-18-000178", "8-K", "2018-11-28", "2018-11-28",
                        "2.01,3.01,3.03,5.01,5.02,5.03,9.01", "k.htm"),
        EdgarSubmission("0001122304-18-000184", "15-12B", "2018-12-10", "", "", "f.htm"),
    ]
    fake_edgar.company_map["AET"] = {"cik_str": 1122304, "ticker": "AET", "title": "AETNA INC /PA/"}
    fake_edgar.raws["0000876661-18-001269"] = AET_RAW
    fake_edgar.texts["0001122304-18-000178"] = ("Item 3.01 Notice of Delisting. requested that trading be suspended "
                                                "prior to the opening of trading on November 29, 2018 " + "x" * 300)
    return fake_edgar


def _ctx(sec, *, listed=False, seen_after=False, last_seen="2018-11-28"):
    return SecurityContext(security=sec, siblings=[SecurityRef(sec.sec_id, sec.share_class, sec.kind)],
                           ticker_on=lambda d: sec.eras[-1].ticker, last_seen=last_seen,
                           seen_after=lambda d: seen_after, listed_today=listed, expected_name=sec.name)


def _f25_raw(entity_name, class_text="Common Stock", rule="17 CFR 240.12d2-2(a)(3)", form_tag="25"):
    return (f"<TYPE>{form_tag}\n<notificationOfRemoval><exchange><entityName>{entity_name}</entityName>"
            f"</exchange>\n<descriptionClassSecurity>{class_text}</descriptionClassSecurity>\n"
            f"<ruleProvision>{rule}</ruleProvision></notificationOfRemoval>")


NYSE_COMMON_RAW = _f25_raw("New York Stock Exchange LLC")
NYSE_ARCA_COMMON_RAW = _f25_raw("NYSE Arca, Inc.")
NASDAQ_COMMON_RAW = _f25_raw("The Nasdaq Stock Market LLC")


def test_aet_merger_delisting(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    midas = _Midas(date(2018, 11, 28))
    events, review = DelistingFinder(edgar, clf, midas=midas).find(_ctx(sec))
    assert review == []
    (ev,) = events
    assert ev.sec_id == "BBG000FJLFX8" and ev.delist_date == "2018-12-09"
    assert ev.last_trade.day == date(2018, 11, 28) and ev.last_trade.source == "midas"
    assert ev.record.bucket is CrspBucket.MERGER
    assert ev.record.sec_id == "BBG000FJLFX8" and ev.record.delist_date == "2018-12-09"
    assert ev.record.observed_delist_date == "2018-11-28"
    assert ev.exchange == "NYSE"
    assert midas.calls[0][0] == "AET"


def test_midas_volume_past_the_window_is_ignored(fake_edgar):
    # The AET Form 25 group is a single filing (2018-11-29), so the finder's
    # MIDAS window is [earliest filed - 75d, latest effective + 10d] =
    # [2018-09-15, 2018-12-19], and effective = 2018-12-09. MIDAS is ignored
    # only once its last volume day is on or after effective + SEEN_AFTER_DAYS
    # (5) = 2018-12-14. Two boundary probes, both inside the requested window:
    #   2018-12-14 (== effective + 5d): ignored, falls back to the ex99 notice
    #   2018-12-13 (== effective + 4d): used as the last trade day
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")

    (ev_ignored,), _ = DelistingFinder(edgar, clf, midas=_Midas(date(2018, 12, 14))).find(_ctx(sec))
    assert ev_ignored.last_trade.source == "ex99_notice" and ev_ignored.last_trade.day == date(2018, 11, 28)

    (ev_used,), _ = DelistingFinder(edgar, clf, midas=_Midas(date(2018, 12, 13))).find(_ctx(sec))
    assert ev_used.last_trade.source == "midas" and ev_used.last_trade.day == date(2018, 12, 13)


def test_secondary_regional_withdrawal_is_skipped(fake_edgar):
    fake_edgar.submissions_by_cik[6769] = [EdgarSubmission("c1", "25", "2020-06-08", "", "", "p.xml")]
    fake_edgar.raws["c1"] = CHICAGO_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BBTJ69", 6769, "APA", "2019-06-28", "2020-12-31", "APACHE CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True, seen_after=True))
    assert events == [] and review == []


def test_ambiguous_class_goes_to_review(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    a = _sec("BBG_A", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    b = _sec("BBG_B", 1122304, "AETB", "2017-06-30", "2018-06-29", "AETNA INC")
    a.share_class, b.share_class = "CLASS A", "CLASS B"
    ctx = _ctx(a)
    ctx.siblings = [SecurityRef("BBG_A", "CLASS A", "common"), SecurityRef("BBG_B", "CLASS B", "common")]
    events, review = DelistingFinder(edgar, clf).find(ctx)
    # The fallback must not revive the same Form 25 the loop just rejected as
    # ambiguous (item 1); the ambiguity review item is the whole explanation,
    # so no `ended_without_delisting` piles on top of it either.
    assert events == []
    assert [r.flag for r in review] == ["form25_unmatched"]


def test_ended_without_delisting(fake_edgar):
    fake_edgar.submissions_by_cik[555] = [EdgarSubmission("q1", "10-Q", "2015-05-01", "", "", "q.htm")]
    fake_edgar.company_map["QQQQ"] = {"cik_str": 555, "ticker": "QQQQ", "title": "QUIET CO"}
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_Q", 555, "QQQQ", "2014-06-30", "2015-06-30", "QUIET CO")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-06-30"))
    assert events == []
    assert [(r.flag, r.last_seen) for r in review] == [("ended_without_delisting", "2015-06-30")]


def test_listed_today_without_form25_is_quiet(fake_edgar):
    fake_edgar.submissions_by_cik[556] = []
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_L", 556, "LIVE", "2020-06-30", "2026-06-30", "LIVE CO")
    assert DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True)) == ([], [])


# -- fix round 1 ----------------------------------------------------------


def test_unreadable_form25_goes_to_review(fake_edgar):
    fake_edgar.submissions_by_cik[9800] = [EdgarSubmission("o1", "25-NSE", "2019-01-10", "", "", "p.xml")]
    # fake_edgar.raws["o1"] left unset: fetch_filing_raw returns ""
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_O", 9800, "OOO", "2015-01-01", "2019-01-09", "OOO CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2019-01-09"))
    assert events == []
    # An unreadable filing sets had_unmatched too, so no ended_without_delisting
    # piles on top of it (item 5, fix round 2).
    assert [(r.flag, r.delist_date) for r in review] == [("form25_unreadable", "2019-01-20")]


def test_unclassified_form25_class_goes_to_review(fake_edgar):
    fake_edgar.submissions_by_cik[9900] = [EdgarSubmission("p1", "25", "2019-02-01", "", "", "p.xml")]
    fake_edgar.raws["p1"] = _f25_raw("New York Stock Exchange LLC", class_text="")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_P", 9900, "PPP", "2015-01-01", "2019-01-31", "PPP CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2019-01-31"))
    assert events == []
    # An unclassified filing sets had_unmatched too, so no ended_without_delisting
    # piles on top of it (item 5, fix round 2).
    assert [r.flag for r in review] == ["form25_unclassified"]


def test_single_sibling_letter_mismatch_is_skipped(fake_edgar):
    fake_edgar.submissions_by_cik[10000] = [EdgarSubmission("q1", "25", "2019-04-01", "", "", "p.xml")]
    fake_edgar.raws["q1"] = _f25_raw("New York Stock Exchange LLC", class_text="Class B Common Stock")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_Q2", 10000, "QQQ", "2015-01-01", "2019-03-31", "QQQ CORP")
    sec.share_class = "CLASS A"
    ctx = _ctx(sec, listed=True)
    ctx.siblings = [SecurityRef(sec.sec_id, "CLASS A", "common")]
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert events == [] and review == []


def test_match_to_another_sibling_is_skipped(fake_edgar):
    fake_edgar.submissions_by_cik[9500] = [EdgarSubmission("m1", "25-NSE", "2020-05-01", "", "", "p.xml")]
    fake_edgar.raws["m1"] = _f25_raw("New York Stock Exchange LLC", class_text="Class B Common Stock")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    a = _sec("BBG_MA", 9500, "MMA", "2017-01-01", "2020-04-30", "MULTI CORP")
    b = _sec("BBG_MB", 9500, "MMB", "2017-01-01", "2020-04-30", "MULTI CORP")
    a.share_class, b.share_class = "CLASS A", "CLASS B"
    ctx = _ctx(a, last_seen="2020-04-30")
    ctx.siblings = [SecurityRef("BBG_MA", "CLASS A", "common"), SecurityRef("BBG_MB", "CLASS B", "common")]
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert events == []


def test_form25_for_another_class_on_same_exchange_is_skipped(fake_edgar):
    # A 10-K cover published after the Form 25 still lists the same exchange:
    # some other class of the issuer left that exchange, not this security.
    cover_text = ("Title of each class Trading Symbol Name of each exchange on which registered "
                  "Common Stock XYZ New York Stock Exchange")
    fake_edgar.submissions_by_cik[9600] = [
        EdgarSubmission("n1", "25", "2019-06-01", "", "", "p.xml"),
        EdgarSubmission("n2", "10-K", "2019-08-01", "", "", "cover.htm"),
    ]
    fake_edgar.raws["n1"] = NYSE_COMMON_RAW
    fake_edgar.texts["n2"] = cover_text
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_N", 9600, "NNN", "2015-01-01", "2019-05-31", "NNN CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True))
    assert events == [] and review == []


def test_ignores_form25_long_after_a_definitive_delisting(fake_edgar):
    fake_edgar.submissions_by_cik[8001] = [
        EdgarSubmission("j1", "25", "2016-06-01", "", "", "p.xml"),
        EdgarSubmission("j2", "25", "2022-09-01", "", "", "p.xml"),
    ]
    fake_edgar.raws["j1"] = NYSE_COMMON_RAW
    fake_edgar.raws["j2"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_J", 8001, "JJJ", "2010-01-01", "2016-05-31", "JJJ CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2016-05-31"))
    assert len(events) == 1
    assert events[0].record.delist_date == "2016-06-11"


def test_sibling_spans_filters_dead_sibling_from_matching(fake_edgar):
    fake_edgar.submissions_by_cik[10100] = [EdgarSubmission("r1", "25", "2022-01-01", "", "", "p.xml")]
    fake_edgar.raws["r1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_R", 10100, "RRR", "2015-01-01", "2016-01-01", "RRR CORP")
    ctx = _ctx(sec, last_seen="2016-01-01")
    ctx.sibling_spans = {"BBG_R": ("2015-01-01", "2016-01-01")}
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert events == [] and not any(r.flag == "form25_unmatched" for r in review)


def test_group_forms25_within_30_days_by_exchange_preference(fake_edgar):
    fake_edgar.submissions_by_cik[7001] = [
        EdgarSubmission("g1", "25-NSE", "2018-11-27", "", "", "p.xml"),
        EdgarSubmission("g2", "25-NSE", "2018-11-29", "", "", "p.xml"),
    ]
    fake_edgar.raws["g1"] = NYSE_ARCA_COMMON_RAW
    fake_edgar.raws["g2"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_G", 7001, "GGG", "2015-01-01", "2018-11-26", "GROUPCO")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True, seen_after=True))
    assert len(events) == 1
    assert events[0].exchange == "NYSE"
    assert events[0].delist_date == "2018-12-07"    # effective date of the earliest filing (g1, 2018-11-27)
    assert events[0].form25_sub.accession == "g2"   # the NYSE filing supplies form25/form25_sub


def test_group_by_distance_from_earliest_filing(fake_edgar):
    # Filings on day 0, day 28 and day 55: day 28 is within 30 days of day 0
    # (joins), but day 55 is 55 days from day 0 -- outside SAME_EVENT_DAYS
    # measured from the group's earliest filing -- so it's a second group.
    fake_edgar.submissions_by_cik[12000] = [
        EdgarSubmission("t1", "25", "2020-01-01", "", "", "p.xml"),
        EdgarSubmission("t2", "25", "2020-01-29", "", "", "p.xml"),
        EdgarSubmission("t3", "25", "2020-02-25", "", "", "p.xml"),
    ]
    fake_edgar.raws["t1"] = NYSE_COMMON_RAW
    fake_edgar.raws["t2"] = NYSE_COMMON_RAW
    fake_edgar.raws["t3"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_T", 12000, "TTT", "2015-01-01", "2019-12-31", "TTT CORP")
    ctx = _ctx(sec, last_seen="2019-12-31")
    ctx.seen_after = lambda d: d == "2020-02-25"   # lets the second group survive the item-3 ignore-gate
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert len(events) == 2


def test_group_last_trade_from_midas_across_issuer_and_exchange_form25(fake_edgar):
    notice_raw = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>The Nasdaq Stock Market LLC"
                 "</entityName></exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
                 "<ruleProvision>17 CFR 240.12d2-2(a)(3)</ruleProvision></notificationOfRemoval>\n"
                 "<TYPE>EX-99.25\n<TEXT>\nThe Exchange notifies the Commission that this security was "
                 "suspended from trading on March 11, 2019.\n</TEXT>")
    fake_edgar.submissions_by_cik[7002] = [
        EdgarSubmission("h1", "25", "2019-03-01", "", "", "p.xml"),
        EdgarSubmission("h2", "25-NSE", "2019-03-11", "", "", "p.xml"),
        EdgarSubmission("h3", "8-K", "2019-03-11", "2019-03-11", "3.01", "k.htm"),
    ]
    fake_edgar.raws["h1"] = NASDAQ_COMMON_RAW
    fake_edgar.raws["h2"] = notice_raw
    fake_edgar.texts["h3"] = ("Item 3.01 Notice of Delisting. trading was suspended prior to the opening "
                              "of trading on March 11, 2019 " + "x" * 300)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_H", 7002, "HHH", "2015-01-01", "2019-02-28", "HHHCO")
    events, review = DelistingFinder(fake_edgar, clf, midas=_Midas(date(2019, 3, 8))
                                     ).find(_ctx(sec, last_seen="2019-02-28"))
    assert len(events) == 1
    assert events[0].last_trade.day == date(2019, 3, 8) and events[0].last_trade.source == "midas"


def test_fallback_dates_by_bankruptcy_8k_not_later_form15(fake_edgar):
    fake_edgar.submissions_by_cik[11000] = [
        EdgarSubmission("s1", "8-K", "2015-01-12", "2015-01-12", "1.03", "k.htm"),
        EdgarSubmission("s2", "15-12G", "2016-03-01", "", "", "f.htm"),
    ]
    fake_edgar.texts["s1"] = "Item 1.03 Bankruptcy or Receivership. The Company filed a chapter 11 petition. " + "x" * 300
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_S", 11000, "SSS", "2010-01-01", "2015-01-20", "SSS CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-20"))
    (ev,) = events
    assert ev.record.delist_date == "2015-01-12"


def test_fallback_revocation_years_later_uses_last_seen_approx(fake_edgar):
    # SEC revocations of delinquent filers often come years after trading
    # stopped; a revocation this distant must not date the delisting.
    fake_edgar.submissions_by_cik[13000] = [
        EdgarSubmission("v1", "REVOKED", "2018-01-15", "", "", ""),   # ~3 years after last_seen
    ]
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_V", 13000, "VVV", "2010-01-01", "2015-01-10", "VVV CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-10"))
    (ev,) = events
    assert ev.record.delist_date == "2015-01-10"
    assert "delist_date_approx" in ev.flags


def test_fallback_revocation_within_window_is_used(fake_edgar):
    fake_edgar.submissions_by_cik[13100] = [
        EdgarSubmission("v2", "REVOKED", "2015-01-30", "", "", ""),   # last_seen + 20 days
    ]
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_V2", 13100, "VVW", "2010-01-01", "2015-01-10", "VVW CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-10"))
    (ev,) = events
    assert ev.record.delist_date == "2015-01-30"


def test_fallback_date_form15_window_bounds():
    # _fallback_date is a pure function of ctx.last_seen and the classifier's
    # evidence dict; test its Form-15/revocation window boundary directly
    # rather than contriving a classifier scenario for each of the three cases.
    finder = DelistingFinder(None, None)
    ctx = SecurityContext(security=None, siblings=[], ticker_on=lambda d: None, last_seen="2015-01-10",
                          seen_after=lambda d: False, listed_today=False, expected_name=None)
    outside_before = {"dereg_filing": {"filing_date": "2014-12-10"}}   # last_seen - 31d: outside
    assert finder._fallback_date(ctx, outside_before) == ("2015-01-10", ("delist_date_approx",))
    inside_after = {"dereg_filing": {"filing_date": "2015-05-10"}}     # last_seen + 120d: inside
    assert finder._fallback_date(ctx, inside_after) == ("2015-05-10", ())
    outside_after = {"dereg_filing": {"filing_date": "2015-05-11"}}    # last_seen + 121d: outside
    assert finder._fallback_date(ctx, outside_after) == ("2015-01-10", ("delist_date_approx",))


def test_successor_is_itself_when_continued(fake_edgar):
    fake_edgar.submissions_by_cik[9001] = [
        EdgarSubmission("k1", "25", "2015-01-05", "", "", "p.xml"),
        EdgarSubmission("k2", "10-K", "2015-09-01", "", "", "k.htm"),
    ]
    fake_edgar.raws["k1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_K", 9001, "KKK", "2010-01-01", "2015-01-04", "KKK CORP")
    events, _ = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True, seen_after=True))
    (ev,) = events
    assert ev.record.bucket is CrspBucket.EXCHANGE_TRANSFER
    assert ev.record.successor_sec_id == "BBG_K"
    assert "successor_unknown" not in ev.flags


def test_successor_unknown_when_not_continued(fake_edgar):
    fake_edgar.submissions_by_cik[9002] = [
        EdgarSubmission("l1", "25", "2015-01-05", "", "", "p.xml"),
        EdgarSubmission("l2", "10-K", "2015-09-01", "", "", "k.htm"),
    ]
    fake_edgar.raws["l1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_L2", 9002, "LLZ", "2010-01-01", "2015-01-04", "LLZ CORP")
    events, _ = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-04"))
    (ev,) = events
    assert ev.record.bucket is CrspBucket.EXCHANGE_TRANSFER
    assert ev.record.successor_sec_id is None
    assert "successor_unknown" in ev.flags


def test_listing_status_unknown_when_no_delisting_found(fake_edgar):
    fake_edgar.submissions_by_cik[9700] = []
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_U", 9700, "UUU", "2015-01-01", "2020-01-01", "UUU CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=None, last_seen="2020-01-01"))
    assert events == []
    assert [(r.flag, r.last_seen) for r in review] == [("listing_status_unknown", "2020-01-01")]


def test_no_eras_returns_empty(fake_edgar):
    sec = Security("BBG_EMPTY", 1, "COMMON", "EMPTY CO", "Common Stock", True, "cusip", "common", [])
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    ctx = SecurityContext(security=sec, siblings=[], ticker_on=lambda d: None, last_seen="",
                          seen_after=lambda d: False, listed_today=False, expected_name=None)
    assert DelistingFinder(fake_edgar, clf).find(ctx) == ([], [])


def test_cik_none_not_listed_today_reports_review(fake_edgar):
    sec = _sec("BBG_NOCIK", None, "NOC", "2018-01-01", "2018-12-31", "NOCIK CO")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2018-12-31"))
    assert events == []
    assert [(r.flag, r.cik) for r in review] == [("ended_without_delisting", None)]


def test_cik_none_listed_today_is_quiet(fake_edgar):
    sec = _sec("BBG_NOCIK2", None, "NOC2", "2018-01-01", "2026-12-31", "NOCIK CO")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True))
    assert events == [] and review == []


# -- fix round 3 (final review, wave B) ------------------------------------


def test_ticker_is_on_last_trade_date_not_form25_filing_date(fake_edgar):
    """The Form 25 filing date is 2018-11-29 but MIDAS confirms the last
    trade was 2018-11-28: the delisting's ticker must come from the last
    trade date, not the filing date."""
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    midas = _Midas(date(2018, 11, 28))
    ctx = _ctx(sec)
    ctx.ticker_on = lambda d: "AETOLD" if d < "2018-11-29" else "AET"
    events, review = DelistingFinder(edgar, clf, midas=midas).find(ctx)
    assert review == []
    (ev,) = events
    assert ev.last_trade.day == date(2018, 11, 28)
    assert ev.ticker == "AETOLD"
    assert ev.record.ticker == "AETOLD"


def test_ticker_falls_back_to_filing_date_when_last_trade_unknown(fake_edgar):
    """No MIDAS/halts evidence and an unreadable ex99 notice: last trade day
    stays unknown, so the ticker falls back to the Form 25 filing date."""
    fake_edgar.submissions_by_cik[9601] = [EdgarSubmission("z1", "25", "2019-06-01", "", "", "p.xml")]
    fake_edgar.raws["z1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_Z", 9601, "ZZZ", "2015-01-01", "2019-05-31", "ZZZ CORP")
    ctx = _ctx(sec, last_seen="2019-05-31")
    ctx.ticker_on = lambda d: "ZOLD" if d < "2019-06-01" else "ZNEW"
    events, _ = DelistingFinder(fake_edgar, clf).find(ctx)
    (ev,) = events
    assert ev.last_trade.day is None
    assert ev.ticker == "ZNEW"       # ctx.ticker_on(filing_date="2019-06-01")


def test_fallback_exchange_from_issuer_submissions(fake_edgar, monkeypatch):
    fake_edgar.submissions_by_cik[11000] = [
        EdgarSubmission("s1", "8-K", "2015-01-12", "2015-01-12", "1.03", "k.htm"),
        EdgarSubmission("s2", "15-12G", "2016-03-01", "", "", "f.htm"),
    ]
    fake_edgar.texts["s1"] = "Item 1.03 Bankruptcy or Receivership. The Company filed a chapter 11 petition. " + "x" * 300
    orig_submissions = fake_edgar.submissions

    def submissions_with_exchange(cik, fresh_after=None):
        d = orig_submissions(cik, fresh_after=fresh_after)
        d["tickers"] = ["SSS"]
        d["exchanges"] = ["Nasdaq"]
        return d

    monkeypatch.setattr(fake_edgar, "submissions", submissions_with_exchange)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_S", 11000, "SSS", "2010-01-01", "2015-01-20", "SSS CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-20"))
    (ev,) = events
    assert ev.exchange == "NASDAQ"


def test_fallback_exchange_is_empty_when_issuer_submissions_lack_it(fake_edgar):
    fake_edgar.submissions_by_cik[11001] = [
        EdgarSubmission("s1b", "8-K", "2015-01-12", "2015-01-12", "1.03", "k.htm"),
    ]
    fake_edgar.texts["s1b"] = "Item 1.03 Bankruptcy or Receivership. The Company filed a chapter 11 petition. " + "x" * 300
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_S2", 11001, "SS2", "2010-01-01", "2015-01-20", "SS2 CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-20"))
    (ev,) = events
    assert ev.exchange == ""


def test_resolution_source_passes_through_from_context(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    ctx = _ctx(sec)
    ctx.resolution_source = "cik_map"
    events, _ = DelistingFinder(edgar, clf, midas=_Midas(date(2018, 11, 28))).find(ctx)
    (ev,) = events
    assert ev.record.evidence["resolution_source"] == "cik_map"


def test_resolution_source_defaults_to_security_master(fake_edgar):
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    events, _ = DelistingFinder(edgar, clf, midas=_Midas(date(2018, 11, 28))).find(_ctx(sec))
    (ev,) = events
    assert ev.record.evidence["resolution_source"] == "security_master"


def test_completeness_only_continued_event_still_gets_fallback_review(fake_edgar):
    """A security not listed today whose only event is a `continued`
    exchange transfer must still get review/fallback treatment -- not be
    silently dropped because `events` is non-empty."""
    fake_edgar.submissions_by_cik[9001] = [
        EdgarSubmission("k1", "25", "2015-01-05", "", "", "p.xml"),
        EdgarSubmission("k2", "10-K", "2015-09-01", "", "", "k.htm"),
    ]
    fake_edgar.raws["k1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_K", 9001, "KKK", "2010-01-01", "2015-01-04", "KKK CORP")
    ctx = _ctx(sec, listed=False, seen_after=True, last_seen="2015-06-01")
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert len(events) == 1
    assert events[0].record.bucket is CrspBucket.EXCHANGE_TRANSFER
    assert events[0].record.successor_sec_id == "BBG_K"
    assert [r.flag for r in review] == ["ended_without_delisting"]


def test_completeness_continued_transfer_then_later_merger_yields_both(fake_edgar):
    """A security transfers exchanges (continues trading), then later is
    truly acquired with no fresh Form 25 near the merger: the finder must
    report both the exchange-transfer event and the later merger."""
    fake_edgar.submissions_by_cik[20000] = [
        EdgarSubmission("e1", "25", "2015-01-05", "", "", "p.xml"),
        EdgarSubmission("e2", "10-K", "2015-09-01", "", "", "k.htm"),
        EdgarSubmission("e3", "8-K", "2018-03-10", "2018-03-10", "2.01,5.01", "k.htm"),
    ]
    fake_edgar.raws["e1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_TWO", 20000, "TWOD", "2010-01-01", "2014-12-31", "TWOD CORP")
    ctx = _ctx(sec, listed=False, seen_after=True, last_seen="2018-03-15")
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert len(events) == 2
    buckets = {ev.record.bucket for ev in events}
    assert CrspBucket.EXCHANGE_TRANSFER in buckets and CrspBucket.MERGER in buckets
    merger_ev = next(ev for ev in events if ev.record.bucket is CrspBucket.MERGER)
    assert merger_ev.delist_date == "2018-03-10"


def _stale_snapshot_edgar(fake_edgar):
    # A.G. Edwards-like: acquired 2007-10-01 (Form 25, 8-K 2.01, Form 15), but a
    # stale index snapshot still lists the ticker from 2008-01-16 to 2009-06-08.
    fake_edgar.submissions_by_cik[21000] = [
        EdgarSubmission("w1", "8-K", "2007-10-01", "2007-10-01", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("w2", "25-NSE", "2007-10-02", "", "", "p.xml"),
        EdgarSubmission("w3", "15-12B", "2007-10-12", "", "", "f.htm"),
    ]
    fake_edgar.raws["w2"] = NYSE_COMMON_RAW
    fake_edgar.texts["w1"] = ("Item 3.01 Notice of Delisting. trading was suspended prior to the opening of "
                              "trading on October 1, 2007 " + "x" * 300)
    return fake_edgar


def test_form25_before_a_stale_first_sighting_is_the_delisting(fake_edgar):
    """A snapshot that kept listing a security after it was acquired must not
    hide the real delisting: with no delisting found from the first sighting
    on and the security gone today, the Form 25 the classifier picks from
    before that sighting (the floor the main scan applies) is still matched
    and becomes the delisting, instead of an `ended_without_delisting` row."""
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.seen_after = lambda d: d < "2009-06-08"      # the stale observations run to 2009-06-08
    events, review = DelistingFinder(edgar, clf).find(ctx)
    (ev,) = events
    assert ev.delist_date == "2007-10-12" and ev.form25_sub.accession == "w2"
    assert ev.record.bucket is CrspBucket.MERGER
    assert ev.last_trade.day == date(2007, 9, 28)
    assert "observed_after_delisting" in ev.flags
    assert not any(r.flag == "ended_without_delisting" for r in review)


def test_form25_before_first_sighting_is_not_taken_for_another_class(fake_edgar):
    # The early Form 25 is still matched by class: one for a class the issuer's
    # observed security is not (here preferred stock) is never its delisting.
    edgar = _stale_snapshot_edgar(fake_edgar)
    edgar.raws["w2"] = _f25_raw("New York Stock Exchange LLC", class_text="6.25% Preferred Stock, Series A")
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    events, review = DelistingFinder(edgar, clf).find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert events == []
    assert [r.flag for r in review] == ["ended_without_delisting"]


def test_form25_before_first_sighting_is_not_taken_when_ftd_shows_trading_after_it(fake_edgar):
    # Fails-to-deliver rows under the security's own ticker after the early
    # Form 25 show it kept trading: that filing ended something else (an old
    # exchange move), so it is not revived.
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.ftd_seen_after = lambda d: d < "2009-06-01"
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert events == []
    assert [r.flag for r in review] == ["ended_without_delisting"]


def test_form25_before_first_sighting_is_ignored_while_listed(fake_edgar):
    # A security listed today never takes a Form 25 from before its first
    # sighting (an earlier life of the issuer, an old exchange move).
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    events, review = DelistingFinder(edgar, clf).find(_ctx(sec, listed=True, seen_after=True,
                                                           last_seen="2009-06-08"))
    assert events == [] and review == []


def test_a_merger_ends_the_security_even_when_sightings_follow_it(fake_edgar):
    """Dow Jones: acquired 2007-12-13 (Form 25 on 2007-12-18) while a stale
    snapshot lists DJ until 2009. The sightings after it make the Form 25
    `continued`, but only an exchange transfer continues a listing: a merger
    ends it, so no fallback runs and no ended_without_delisting row is added
    beside the delisting (72 such pairs in the first acceptance run; a
    bankrupt security's OTC tail did the same)."""
    fake_edgar.submissions_by_cik[29924] = [
        EdgarSubmission("dj1", "8-K", "2007-12-13", "2007-12-13", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("dj2", "25-NSE", "2007-12-18", "", "", "p.xml"),
        EdgarSubmission("dj3", "15-12B", "2007-12-24", "", "", "f.htm"),
    ]
    fake_edgar.raws["dj2"] = NYSE_COMMON_RAW
    fake_edgar.texts["dj1"] = ("Item 3.01 Notice of Delisting. trading was suspended prior to the opening of "
                               "trading on December 14, 2007 " + "x" * 300)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BH5K72", 29924, "DJ", "2007-12-01", "2009-06-08", "DOW JONES & CO INC")
    events, review = DelistingFinder(fake_edgar, clf).find(
        _ctx(sec, listed=False, seen_after=True, last_seen="2009-06-08"))
    (ev,) = events
    assert ev.record.bucket is CrspBucket.MERGER and ev.delist_date == "2007-12-28"
    assert review == []


class _TickerMidas:
    def __init__(self, days):
        self.days, self.calls = days, []

    def last_trade_day(self, ticker, lo, hi):
        self.calls.append(ticker)
        return self.days.get(ticker)


def test_last_trade_confirmation_asks_for_every_ticker_of_the_window(fake_edgar):
    """Spirit Airlines: NYSE suspended SAVE before the open on 2024-11-18 and
    filed its Form 25 on 2024-12-05, by when the shares traded OTC as SAVEQ
    (fails rows under SAVEQ). MIDAS, exchange trades only, knows SAVE, not
    SAVEQ: the confirmation must ask for every ticker the security carried in
    the window, not only the one on the Form 25's date."""
    notice = ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC"
              "</entityName></exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
              "<ruleProvision>17 CFR 240.12d2-2(b)</ruleProvision></notificationOfRemoval>\n"
              "<TYPE>EX-99.25\n<TEXT>\nOn November 18, 2024, the Exchange determined that the common stock "
              "of Spirit Airlines, Inc. should be suspended immediately.\n</TEXT>")
    fake_edgar.submissions_by_cik[1498710] = [
        EdgarSubmission("sv1", "8-K", "2024-11-18", "2024-11-18", "1.03,7.01,9.01", "k.htm"),
        EdgarSubmission("sv2", "25-NSE", "2024-12-05", "", "", "p.xml"),
    ]
    fake_edgar.raws["sv2"] = notice
    fake_edgar.texts["sv1"] = "Item 1.03 Bankruptcy or Receivership. filed voluntary petitions under chapter 11. " + "x" * 300
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BF6RQ9", 1498710, "SAVE", "2023-06-30", "2024-06-28", "SPIRIT AIRLINES INC")
    ctx = _ctx(sec, last_seen="2024-11-18")
    ctx.ticker_on = lambda d: "SAVE" if d < "2024-11-19" else "SAVEQ"
    ctx.tickers_between = lambda lo, hi: ["SAVE", "SAVEQ"]
    midas = _TickerMidas({"SAVE": date(2024, 11, 15)})
    (ev,), _ = DelistingFinder(fake_edgar, clf, midas=midas).find(ctx)
    assert ev.last_trade.day == date(2024, 11, 15) and ev.last_trade.source == "midas"
    assert set(midas.calls) == {"SAVE", "SAVEQ"}


def test_cik_none_listing_status_unknown(fake_edgar):
    sec = _sec("BBG_NOCIK3", None, "NOC3", "2018-01-01", "2020-01-01", "NOCIK CO")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=None, last_seen="2020-01-01"))
    assert events == []
    assert [(r.flag, r.cik, r.last_seen) for r in review] == [("listing_status_unknown", None, "2020-01-01")]
