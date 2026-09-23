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
    # The AET Form 25 (filed 2018-11-29) takes effect 2018-12-09; MIDAS is only
    # ignored once its last volume day reaches effective + SEEN_AFTER_DAYS(5) =
    # 2018-12-14 (issuer Form 25s take effect 10 days after filing and trading
    # legitimately continues until then) -- so pick a MIDAS day well past that.
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    (ev,), _ = DelistingFinder(edgar, clf, midas=_Midas(date(2018, 12, 20))).find(_ctx(sec))
    assert ev.last_trade.source == "ex99_notice" and ev.last_trade.day == date(2018, 11, 28)


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
    unreadable = [r for r in review if r.flag == "form25_unreadable"]
    assert [(r.flag, r.delist_date) for r in unreadable] == [("form25_unreadable", "2019-01-20")]


def test_unclassified_form25_class_goes_to_review(fake_edgar):
    fake_edgar.submissions_by_cik[9900] = [EdgarSubmission("p1", "25", "2019-02-01", "", "", "p.xml")]
    fake_edgar.raws["p1"] = _f25_raw("New York Stock Exchange LLC", class_text="")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_P", 9900, "PPP", "2015-01-01", "2019-01-31", "PPP CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2019-01-31"))
    assert events == []
    assert any(r.flag == "form25_unclassified" for r in review)


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
