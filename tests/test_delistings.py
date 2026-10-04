from dataclasses import replace
from datetime import date
from pathlib import Path

from delist_detection.classifier import DelistClassifier, DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import DelistingFinder, SecurityContext
from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import SecurityRef
from delist_detection.last_trade import LastTrade
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


def _ctx(sec, *, listed=False, seen_after=False, last_seen="2018-11-28", trades_after=False):
    return SecurityContext(security=sec, siblings=[SecurityRef(sec.sec_id, sec.share_class, sec.kind)],
                           ticker_on=lambda d: sec.eras[-1].ticker, last_seen=last_seen,
                           seen_after=lambda d: seen_after, listed_today=listed, expected_name=sec.name,
                           trades_after=lambda d: trades_after)


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
    # ambiguous. The security is still neither listed nor delisted,
    # so spec 8.10's `ended_without_delisting` row is written next to the
    # ambiguity row: accepting the Form 25
    # row as "not about this security" must not drop the security from review.
    assert events == []
    assert [r.flag for r in review] == ["form25_unmatched", "ended_without_delisting"]
    assert review[1].last_seen == "2018-11-28" and review[1].delist_date == ""


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


RSH_RAW = (FIX / "rsh_25nse.txt").read_text(encoding="utf-8", errors="replace")


def test_an_involuntary_notice_date_that_nothing_confirms_is_flagged_unconfirmed(fake_edgar):
    """Spec 8.8: on an involuntary (rule 12d2-2(b)) notice the date is the
    Exchange's decision day, to be confirmed by MIDAS or a Nasdaq halt. NYSE's
    RadioShack notice announces the suspension "at the close of the trading
    session on February 2, 2015"; with no MIDAS or halt to confirm it (MIDAS
    starts in 2012, so every earlier (b) notice is in this case) the date is
    kept but flagged last_trade_date_unconfirmed."""
    fake_edgar.submissions_by_cik[96289] = [
        EdgarSubmission("0000876661-15-000132", "25-NSE", "2015-03-20", "", "", "primary_doc.xml")]
    fake_edgar.raws["0000876661-15-000132"] = RSH_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BRSH01", 96289, "RSH", "2014-06-30", "2014-12-31", "RADIOSHACK CORP")
    (ev,), _ = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-02-02"))
    assert (ev.last_trade.day, ev.last_trade.source) == (date(2015, 2, 2), "ex99_notice")
    assert "last_trade_date_unconfirmed" in ev.last_trade.flags
    assert "last_trade_date_unconfirmed" in ev.record.evidence["flags"]
    # confirmed by MIDAS on the same day: no flag
    (ev,), _ = DelistingFinder(fake_edgar, clf, midas=_Midas(date(2015, 2, 2))).find(
        _ctx(sec, last_seen="2015-02-02"))
    assert ev.last_trade.source == "midas" and ev.last_trade.flags == ()




def test_unreadable_form25_goes_to_review(fake_edgar):
    fake_edgar.submissions_by_cik[9800] = [EdgarSubmission("o1", "25-NSE", "2019-01-10", "", "", "p.xml")]
    # fake_edgar.raws["o1"] left unset: fetch_filing_raw returns ""
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_O", 9800, "OOO", "2015-01-01", "2019-01-09", "OOO CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2019-01-09"))
    assert events == []
    # Not listed and not delisted: ended_without_delisting is written next to
    # the form25_unreadable row.
    assert [(r.flag, r.delist_date) for r in review] == [("form25_unreadable", "2019-01-20"),
                                                         ("ended_without_delisting", "")]


def test_unclassified_form25_class_goes_to_review(fake_edgar):
    fake_edgar.submissions_by_cik[9900] = [EdgarSubmission("p1", "25", "2019-02-01", "", "", "p.xml")]
    fake_edgar.raws["p1"] = _f25_raw("New York Stock Exchange LLC", class_text="")
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_P", 9900, "PPP", "2015-01-01", "2019-01-31", "PPP CORP")
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2019-01-31"))
    assert events == []
    # Not listed and not delisted: ended_without_delisting is written next to
    # the form25_unclassified row.
    assert [r.flag for r in review] == ["form25_unclassified", "ended_without_delisting"]


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


class _RecordingClassifier(DelistClassifier):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[dict] = []

    def classify_event(self, *args, **kwargs):
        self.calls.append(dict(kwargs))
        return super().classify_event(*args, **kwargs)


def test_form25_path_tells_the_classifier_whether_the_security_traded_after(fake_edgar):
    fake_edgar.submissions_by_cik[9003] = [
        EdgarSubmission("m1", "25", "2015-01-05", "", "", "p.xml"),
        EdgarSubmission("m2", "10-K", "2015-09-01", "", "", "k.htm"),
    ]
    fake_edgar.raws["m1"] = NYSE_COMMON_RAW
    clf = _RecordingClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_M", 9003, "MMM", "2010-01-01", "2015-01-04", "MMM CORP")
    DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=True, seen_after=True))
    assert clf.calls[-1]["trading_after"] is True
    clf.calls.clear()
    sec = _sec("BBG_M", 9003, "MMM", "2010-01-01", "2015-01-04", "MMM CORP")
    DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2015-01-04"))
    assert clf.calls[-1]["trading_after"] is False


def test_fallback_path_does_not_claim_trading_after(fake_edgar):
    fake_edgar.submissions_by_cik[9004] = [
        EdgarSubmission("n1", "10-K", "2012-03-01", "", "", "k.htm"),
    ]
    clf = _RecordingClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_N", 9004, "NNN", "2010-01-01", "2012-06-01", "NNN CORP")
    DelistingFinder(fake_edgar, clf).find(_ctx(sec, last_seen="2012-06-01"))
    assert clf.calls
    assert all(not c.get("trading_after", False) for c in clf.calls)


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
    ctx = _ctx(sec, listed=False, seen_after=True, trades_after=True, last_seen="2015-06-01")
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
    ctx = _ctx(sec, listed=False, seen_after=True, trades_after=True, last_seen="2018-03-15")
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
    # Fails-to-deliver rows of the security's own CUSIPs after the early
    # Form 25 show it kept trading: that filing ended something else (an old
    # exchange move), so it is not taken (sub-plan 5b, E: `trades_after`).
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2008-01-16", "2009-06-08", "EDWARDS AG INC")
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.trades_after = lambda d: d < "2009-06-01"
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert events == []
    assert [r.flag for r in review] == ["ended_without_delisting"]


def test_a_form25_older_than_the_early_window_is_still_the_fallbacks(fake_edgar):
    """The fallback still judges a Form 25 from before the early window (more than EARLY_REACH_DAYS before the
    floor): the classifier picks it, `_early_group` matches it, and fails rows under the security's own tickers
    after it refuse it."""
    edgar = _stale_snapshot_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG_AGE", 21000, "AGE", "2009-01-16", "2009-06-08", "EDWARDS AG INC")   # floor 2008-12-17
    (ev,), review = DelistingFinder(edgar, clf).find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert ev.form25_sub.accession == "w2" and "observed_after_delisting" in ev.flags
    ctx = _ctx(sec, listed=False, last_seen="2009-06-08")
    ctx.ftd_seen_after = lambda d: d < "2009-06-01"
    events, review = DelistingFinder(edgar, clf).find(ctx)
    assert events == [] and [r.flag for r in review] == ["ended_without_delisting"]


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


def test_the_second_class_a_form25_names_gets_its_delisting(fake_edgar):
    """The Liberty Live Form 25 names Series A and then Series C: the Series C
    line (LLYVK) is delisted by it as much as the Series A line, while the
    Formula One group's Series C sibling is not."""
    fake_edgar.submissions_by_cik[1560385] = [
        EdgarSubmission("l1", "8-K", "2025-12-15", "2025-12-15", "1.01,2.01,3.01,7.01,8.01,9.01", "k.htm"),
        EdgarSubmission("l2", "25-NSE", "2025-12-15", "", "", "p.xml")]
    fake_edgar.raws["l2"] = _f25_raw("The Nasdaq Stock Market LLC", class_text=(
        "Liberty Media Corporation Series A Liberty Live Common Stock &amp; "
        "Liberty Media Corporation Series C Liberty Live Common Stock"))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("LLYVK", 1560385, "LLYVK", "2023-08-04", "2025-12-12", "LIBERTY MEDIA LIBERTY LIVE CORP SE")
    sec.share_class = "CLASS C"
    ctx = _ctx(sec, last_seen="2025-12-12")
    ctx.siblings = [SecurityRef("LLYVA", "CLASS A", "common", "LIBERTY MEDIA LIBERTY LIVE CORP SE"),
                    SecurityRef("LLYVK", "CLASS C", "common", "LIBERTY MEDIA LIBERTY LIVE CORP SE"),
                    SecurityRef("FWONA", "CLASS A", "common", "LIBERTY MEDIA FORMULA ONE SERIES A"),
                    SecurityRef("FWONK", "CLASS C", "common", "LIBERTY MEDIA FORMULA ONE SERIES C")]
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert [r.flag for r in review if r.flag == "form25_unmatched"] == []
    (ev,) = events
    assert (ev.sec_id, ev.delist_date) == ("LLYVK", "2025-12-25")


def test_a_class_left_ambiguous_still_goes_to_review_when_another_class_matched(fake_edgar):
    """CBS's 2019 Form 25 names Class A and Class B. Class A matches its one
    sibling; Class B has two (the Class B FIGI line and a placeholder for the
    same stock) that no name word tells apart. The placeholder is not matched:
    its review rows say the class was ambiguous and, as it is neither listed
    nor delisted, that it ended without a delisting (accepting the first row
    must not drop the security from review)."""
    fake_edgar.submissions_by_cik[813828] = [EdgarSubmission("c1", "25", "2019-12-04", "", "", "p.xml")]
    fake_edgar.raws["c1"] = _f25_raw("New York Stock Exchange LLC", class_text=(
        "Class A Common Stock, par value $0.001 per share Class B Common Stock, par value $0.001 per share"))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("CIK813828-CLASS-B", 813828, "CBS", "2008-01-16", "2019-06-30", "CBS CORP CLASS B")
    sec.share_class = "CLASS B"
    ctx = _ctx(sec, last_seen="2019-12-06")
    ctx.siblings = [SecurityRef("BBG000BWDFD4", "CLASS A", "common", "PARAMOUNT GLOBAL CLASS A"),
                    SecurityRef("BBG000C496P7", "CLASS B", "common", "PARAMOUNT GLOBAL CLASS B"),
                    SecurityRef("CIK813828-CLASS-B", "CLASS B", "common", "CBS CORP CLASS B")]
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert events == []
    assert [r.flag for r in review] == ["form25_unmatched", "ended_without_delisting"]
    assert "no Form 25 matched it" in review[1].reason


def test_a_delistings_flags_are_its_records_evidence_flags():
    """One list: what the pipeline adds or clears on the event is what the
    delistings.csv row (built from record.evidence) carries, and a found
    successor clears successor_unknown from both views at once."""
    from delist_detection.delistings import Delisting
    rec = DelistRecord(ticker="GOOGL", cik=1288776, observed_delist_date="2015-10-02", crsp_code=300,
                       bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high", reason="holdco reorg",
                       evidence={"flags": ["successor_unknown"]}, sec_id="BBGGOOGLEA1", delist_date="2015-10-12")
    ev = Delisting("BBGGOOGLEA1", 1288776, "GOOGL", "2015-10-12", rec, LastTrade(date(2015, 10, 2), "", ()),
                        None, None, "NASDAQ")
    ev.add_flag("ftd_close_lagged")
    assert rec.evidence["flags"] == ev.flags == ["successor_unknown", "ftd_close_lagged"]
    ev.set_successor("BBG009S39JX6")
    assert rec.successor_sec_id == "BBG009S39JX6"
    assert rec.evidence["flags"] == ev.flags == ["ftd_close_lagged"]


class _FailingHalts:
    """A halt feed that fails every day it is asked for (a timeout), like
    NasdaqHaltClient: no halts, and the day listed by failed_days()."""

    def __init__(self):
        self.failed = []

    def deletion_halt(self, symbol, lo, hi, max_days=7):
        self.failed.append(lo)
        return None

    def failed_days(self):
        return tuple(self.failed)


class _AnsweringHalts(_FailingHalts):
    def deletion_halt(self, symbol, lo, hi, max_days=7):
        return None


def test_a_last_trade_decision_that_asked_a_failed_halt_feed_day_says_so(fake_edgar):
    """With no MIDAS day the finder asks the Nasdaq halt feed; a day it could not
    read is carried on the delisting's LastTrade, so the pipeline can flag it."""
    edgar = _aet_edgar(fake_edgar)
    clf = DelistClassifier(edgar, TickerResolver(edgar))
    sec = _sec("BBG000FJLFX8", 1122304, "AET", "2017-06-30", "2018-06-29", "AETNA INC")
    halts = _FailingHalts()
    (ev,), _ = DelistingFinder(edgar, clf, halts=halts).find(_ctx(sec))
    assert ev.last_trade.halt_feed_failed == tuple(halts.failed) != ()
    (ok,), _ = DelistingFinder(edgar, clf, halts=_AnsweringHalts()).find(_ctx(sec))
    assert ok.last_trade.halt_feed_failed == ()
    (no_feed,), _ = DelistingFinder(edgar, clf).find(_ctx(sec))
    assert no_feed.last_trade.halt_feed_failed == ()


def test_a_fallback_last_trade_keeps_the_failed_halt_feed_days(fake_edgar):
    """The no-Form-25 fallback replaces an undated last trade by the last
    sighting; the halt-feed days its decision failed to read stay with it."""
    fake_edgar.submissions_by_cik[13000] = [EdgarSubmission("v1", "REVOKED", "2018-01-15", "", "", "")]
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_V", 13000, "VVV", "2010-01-01", "2015-01-10", "VVV CORP")
    halts = _FailingHalts()
    (ev,), _ = DelistingFinder(fake_edgar, clf, halts=halts).find(_ctx(sec, last_seen="2015-01-10"))
    assert ev.last_trade.day == date(2015, 1, 10) and "last_trade_date_unconfirmed" in ev.last_trade.flags
    assert ev.last_trade.halt_feed_failed == tuple(halts.failed) != ()


def test_a_line_the_line_follow_moved_to_a_new_ticker_is_reviewed_under_it(fake_edgar):
    """U5 (sub-plan 5a): with no Form 25 and no fallback filing, a line that went on as NVRI is reviewed under
    its latest own ticker, NVRI, not its last era's."""
    fake_edgar.submissions_by_cik[45876] = []
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG000BLH3P8", 45876, "HSC", "2008-01-16", "2023-06-20", "HARSCO CORP")
    sec.line_tickers = frozenset({"NVRI"})
    ctx = replace(_ctx(sec, last_seen="2026-05-29"), ticker_on=lambda d: "NVRI" if d >= "2023-06-21" else "HSC")
    events, review = DelistingFinder(fake_edgar, clf).find(ctx)
    assert events == [] and [(r.flag, r.ticker) for r in review] == [("ended_without_delisting", "NVRI")]


# --- sub-plan 5a, U6: a Form 25 at the security's own CUSIP switch ---

def _switch_case(fake_edgar):
    fake_edgar.submissions_by_cik[1015820] = [EdgarSubmission("q1", "25-NSE", "2026-01-08", "", "", "p.xml")]
    fake_edgar.raws["q1"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    return DelistingFinder(fake_edgar, clf), _sec("BBG000GTYWL7", 1015820, "QGEN", "2010-01-01", "2026-06-30",
                                                  "QIAGEN NV")


def test_a_form25_at_the_securitys_own_cusip_switch_is_no_delisting_while_it_trades_on(fake_edgar):
    """QGEN 2026: a capital repayment gave the same line a new CUSIP (N72482206 -> N72482156, first row
    2026-01-07); the 25-NSE of 2026-01-08 removed the old CUSIP while QGEN went on trading."""
    finder, sec = _switch_case(fake_edgar)
    ctx = replace(_ctx(sec, listed=True, seen_after=True), cusip_switches=("2026-01-07",))
    events, review = finder.find(ctx)
    assert events == [] and review == []


def test_a_form25_far_from_any_own_switch_still_counts(fake_edgar):
    finder, sec = _switch_case(fake_edgar)
    for switches in ((), ("2025-06-02",)):
        events, _ = finder.find(replace(_ctx(sec, listed=True, seen_after=True), cusip_switches=switches))
        assert [e.delist_date for e in events] == ["2026-01-18"]


def test_a_form25_at_an_own_switch_of_a_security_that_stopped_trading_still_counts(fake_edgar):
    """The switch only explains a Form 25 the security traded through (`continued`)."""
    finder, sec = _switch_case(fake_edgar)
    events, _ = finder.find(replace(_ctx(sec, listed=False, seen_after=False), cusip_switches=("2026-01-07",)))
    assert [e.delist_date for e in events] == ["2026-01-18"]


# --- sub-plan 5b, C: what continues a security after a Form 25 ---

def _stale_merger(fake_edgar, rule="17 CFR 240.12d2-2(a)(3)"):
    """XM Satellite-like: Nasdaq removed the class A (25-NSE 2008-07-29) at the merger (8-K item 5.01 the next
    day); the issuer kept filing for its debt; a stale snapshot lists the security until 2009-06-08."""
    fake_edgar.submissions_by_cik[30101] = [
        EdgarSubmission("x25", "25-NSE", "2008-07-29", "", "", "p.xml"),
        EdgarSubmission("x8k", "8-K", "2008-07-30", "2008-07-30", "2.01,5.01", "k.htm"),
        EdgarSubmission("xq", "10-Q", "2009-05-01", "2009-03-31", "", "q.htm")]
    fake_edgar.raws["x25"] = _f25_raw("The Nasdaq Stock Market LLC", rule=rule)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_XMSR", 30101, "XMSR", "2008-01-16", "2009-06-08", "XM SATELLITE RADIO HLDGS")
    return DelistingFinder(fake_edgar, clf), sec


def test_a_stale_observation_after_the_form25_no_longer_continues_the_security(fake_edgar):
    finder, sec = _stale_merger(fake_edgar)
    events, _ = finder.find(_ctx(sec, listed=False, seen_after=True, last_seen="2009-06-08"))
    assert [(e.delist_date, e.record.bucket, e.record.successor_sec_id) for e in events] == [
        ("2008-08-08", CrspBucket.MERGER, None)]


def test_the_securitys_own_cusip_trading_on_after_the_form25_continues_it(fake_edgar):
    finder, sec = _stale_merger(fake_edgar)
    events, _ = finder.find(_ctx(sec, listed=False, trades_after=True, last_seen="2009-06-08"))
    assert (events[0].record.bucket, events[0].record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_XMSR")


def test_trading_on_after_a_removal_under_rule_b_is_the_otc_tail_not_the_listing(fake_edgar):
    """R.H. Donnelley, Idearc, LSC Communications: an exchange's removal under 12d2-2(b), then OTC trading under
    the same CUSIP; only a listing today continues such a security."""
    finder, sec = _stale_merger(fake_edgar, rule="17 CFR 240.12d2-2(b)")
    events, _ = finder.find(_ctx(sec, listed=False, trades_after=True, last_seen="2009-06-08"))
    assert [(e.record.bucket, e.record.successor_sec_id) for e in events] == [(CrspBucket.MERGER, None)]
    events, _ = finder.find(_ctx(sec, listed=True, trades_after=False, last_seen="2009-06-08"))
    assert [(e.record.bucket, e.record.successor_sec_id) for e in events] == [
        (CrspBucket.EXCHANGE_TRANSFER, "BBG_XMSR")]


def test_a_form25_at_the_own_cusip_switch_of_a_security_not_listed_today_still_removed_the_old_cusip(fake_edgar):
    """Review Focus (C with U6): Acxiom/LiveRamp 2018-like, not listed today: the new CUSIP's fails rows continue
    the security (`trades_after`), so the Form 25 at its own CUSIP switch is no delisting."""
    finder, sec = _switch_case(fake_edgar)
    ctx = replace(_ctx(sec, listed=False, trades_after=True), cusip_switches=("2026-01-07",))
    events, review = finder.find(ctx)
    assert all(e.form25_sub is None for e in events)


# --- sub-plan 5b, R7: the issuer's own Form 25 with its 8-A12B moves the class ---

def _exchange_move(fake_edgar, *, form="25", eight_a="2026-09-08", rule=""):
    """Kraft Heinz 2026: the issuer filed its own Form 25 (Nasdaq) and an 8-A12B (NYSE) the same day; no 8-K
    near it, so the classifier alone leaves the row `unknown`."""
    fake_edgar.submissions_by_cik[30201] = [
        EdgarSubmission("k25", form, "2026-09-08", "", "", "p.xml"),
        EdgarSubmission("k8a", "8-A12B", eight_a, "", "", "a.htm")]
    fake_edgar.raws["k25"] = _f25_raw("The Nasdaq Stock Market LLC", rule=rule, form_tag=form)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_KHC", 30201, "KHC", "2015-07-06", "2026-06-30", "KRAFT HEINZ CO")
    return DelistingFinder(fake_edgar, clf), sec


def test_the_issuers_form25_with_its_8a12b_is_an_exchange_transfer_of_the_security_itself(fake_edgar):
    finder, sec = _exchange_move(fake_edgar)
    (ev,), review = finder.find(_ctx(sec, listed=True, last_seen="2026-09-04"))
    assert (ev.record.crsp_code, ev.record.bucket, ev.record.successor_sec_id) == (
        304, CrspBucket.EXCHANGE_TRANSFER, "BBG_KHC")
    assert ev.record.reason == "Exchange transfer: the issuer's Form 25 2026-09-08 with its 8-A12B 2026-09-08"
    assert "no_evidence_default" not in ev.flags and review == []


def test_an_exchanges_form25_an_8a12b_eleven_days_off_or_a_removal_under_b_moves_nothing(fake_edgar):
    """DISCK and CWENA: an exchange's 25-NSE beside an 8-A12B for the replacement class is a real ending."""
    for kw in ({"form": "25-NSE"}, {"eight_a": "2026-08-28"}, {"rule": "17 CFR 240.12d2-2(b)"}):
        finder, sec = _exchange_move(fake_edgar, **kw)
        (ev,), _ = finder.find(_ctx(sec, listed=True, last_seen="2026-09-04"))
        assert ev.record.bucket is CrspBucket.UNKNOWN, kw


def test_the_issuers_exchange_move_continues_a_security_not_listed_today(fake_edgar):
    """Monster Worldwide 2008, MSG 2015: the move continues the security even with no fails rows after it."""
    finder, sec = _exchange_move(fake_edgar, eight_a="2026-08-29")
    events, _ = finder.find(_ctx(sec, listed=False, last_seen="2026-09-04"))
    assert events[0].record.successor_sec_id == "BBG_KHC"


def test_the_issuers_own_form25_in_a_group_with_the_exchanges_moves_the_class(fake_edgar):
    """Review Focus (R7): the exchange's 25-NSE first, the issuer's own Form 25 with its 8-A12B a day later: one
    group, and the move found on the issuer's filing."""
    finder, sec = _exchange_move(fake_edgar)
    fake_edgar.submissions_by_cik[30201] = [
        EdgarSubmission("kn", "25-NSE", "2026-09-07", "", "", "p.xml"),
        EdgarSubmission("k25", "25", "2026-09-08", "", "", "p.xml"),
        EdgarSubmission("k8a", "8-A12B", "2026-09-08", "", "", "a.htm")]
    fake_edgar.raws["kn"] = _f25_raw("The Nasdaq Stock Market LLC", form_tag="25-NSE")
    (ev,), _ = finder.find(_ctx(sec, listed=True, last_seen="2026-09-04"))
    assert (ev.record.crsp_code, ev.record.successor_sec_id) == (304, "BBG_KHC")


# --- sub-plan 5b, E: early reach ---

def _two_early_groups(fake_edgar):
    """TXU 2007: an older Form 25 (January 2007, another event) and the merger's 25-NSE (2007-10-23), both in the
    year before the floor of a security a stale snapshot first lists on 2008-01-16. The 8-K nearest the 25-NSE is
    an earnings release (item 2.02) and the issuer kept filing for its debt, so the classifier's own pick drops it
    (its frozen-tail rule) and the fallback reads a continued-filings transfer at the last sighting."""
    fake_edgar.submissions_by_cik[30301] = [
        EdgarSubmission("t1", "25-NSE", "2007-01-10", "", "", "p.xml"),
        EdgarSubmission("t8", "8-K", "2007-10-11", "2007-10-11", "2.01,3.01,5.01,9.01", "k.htm"),
        EdgarSubmission("t2", "25-NSE", "2007-10-23", "", "", "p.xml"),
        EdgarSubmission("te", "8-K", "2007-10-23", "2007-10-23", "2.02,9.01", "e.htm"),
        EdgarSubmission("tq", "10-Q", "2008-05-15", "2008-03-31", "", "q.htm"),
        EdgarSubmission("tk", "10-K", "2010-03-01", "2009-12-31", "", "k10.htm")]
    fake_edgar.raws["t1"] = NYSE_COMMON_RAW
    fake_edgar.raws["t2"] = NYSE_COMMON_RAW
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("BBG_TXU", 30301, "TXU", "2008-01-16", "2009-06-08", "TXU CORP")
    return DelistingFinder(fake_edgar, clf), sec


def test_the_latest_early_group_is_the_delisting_of_a_security_gone_today(fake_edgar):
    finder, sec = _two_early_groups(fake_edgar)
    (ev,), review = finder.find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert (ev.delist_date, ev.form25_sub.accession, ev.record.bucket) == ("2007-11-02", "t2", CrspBucket.MERGER)
    assert "observed_after_delisting" in ev.flags and review == []


def test_early_reach_needs_the_security_gone_today(fake_edgar):
    """Laureate (listed today; its 2008 observations are of the old Laureate): a Form 25 before the floor of a
    security listed today, or whose listing is unknown, is never judged."""
    finder, sec = _two_early_groups(fake_edgar)
    assert finder.find(_ctx(sec, listed=True, last_seen="2009-06-08")) == ([], [])
    events, review = finder.find(_ctx(sec, listed=None, last_seen="2009-06-08"))
    assert events == [] and [r.flag for r in review] == ["listing_status_unknown"]


def test_an_early_form25_waits_for_no_definitive_delisting_from_the_floor_on(fake_edgar):
    finder, sec = _two_early_groups(fake_edgar)
    fake_edgar.submissions_by_cik[30301].append(EdgarSubmission("t3", "25-NSE", "2009-06-01", "", "", "p.xml"))
    fake_edgar.raws["t3"] = NYSE_COMMON_RAW
    events, _ = finder.find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert [e.form25_sub.accession for e in events] == ["t3"]


def test_an_early_form25_whose_text_cannot_be_read_raises_no_review_row(fake_edgar):
    """Review Focus (E): about 300 early-window Form 25s are not cached; one that cannot be read is left to the
    fallback, with no `form25_unreadable` row (the floor's own filings keep that row)."""
    finder, sec = _two_early_groups(fake_edgar)
    del fake_edgar.raws["t2"]
    events, review = finder.find(_ctx(sec, listed=False, last_seen="2009-06-08"))
    assert not any(r.flag == "form25_unreadable" for r in review)
    assert all(e.form25_sub is None or e.form25_sub.accession != "t2" for e in events)


# --- sub-plan 5b, R3: a Form 25 about another class matches no security ---

def test_a_form25_of_other_tracking_groups_is_no_delisting_of_the_series_a(fake_edgar):
    """Liberty 2011: the 25-NSE of the Capital and Starz groups is not the Series A placeholder's (it matched by
    elimination before: the issuer's only common of the run alive then)."""
    fake_edgar.submissions_by_cik[30401] = [EdgarSubmission("l25", "25-NSE", "2011-09-23", "", "", "p.xml")]
    fake_edgar.company_map["LINTA"] = {"cik_str": 30401, "ticker": "LINTA", "title": "Liberty Interactive Corp"}
    fake_edgar.raws["l25"] = _f25_raw("The Nasdaq Stock Market LLC", class_text=(
        "Series A Liberty Capital Common Stock, Series B Liberty Capital Common Stock, Liberty Starz Ser A Common "
        "Stock, Liberty Starz Ser B Common Stock"))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    sec = _sec("CIK30401-SERIES-A", 30401, "LINTA", "2008-01-16", "2011-06-30", "QURATE RETAIL GROUP CORP SERIES A")
    sec.share_class = "SERIES A"
    events, review = DelistingFinder(fake_edgar, clf).find(_ctx(sec, listed=False, last_seen="2011-06-30"))
    assert events == [] and [r.flag for r in review] == ["ended_without_delisting"]
