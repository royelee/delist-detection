"""The last trade module (architecture step 4), at its interface: the readers (`eightk_last_trade`,
`closing_day`), the source order (`decide_last_trade`), the anchor day and the first day after (`anchor_day`,
`first_day_after`; `LastTrade`'s facts and the row reading are exit_kind's, tests/test_exit_kind.py), the handoff
rule (`at_handoff`), and `Dating`: a Form 25
group's windows, the MIDAS and halt confirmations through fake adapters, rule 3's tenure (read from the security's
trading record, `trading_record.TradingRecord`, whose own rules are tests/test_trading_record.py's), rule 4's closing
day, the no-Form-25 fallback and stage 9c's re-dating from a notice."""
from datetime import date
from pathlib import Path

import pytest

from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.filings.form25 import parse_form25
from delist_detection.sources.ftd import FtdIndex, FtdRow
from delist_detection.identity.history import Sighting
from delist_detection.endings.last_trade import (
    CLOSING_DAY, EIGHTK_301, EX99_NOTICE, LAST_SIGHTING, MIDAS, NASDAQ_HALT, NO_DAY, UNCONFIRMED, UNSOURCED,
    Dating, LastTrade, anchor_day, at_handoff, closing_day, decide_last_trade, eightk_last_trade,
    first_day_after, handoff_day, sections_3_01,
)
from delist_detection.sources.nasdaq_halts import Halt
from delist_detection.identity.security_master import Security
from delist_detection.endings.trading_record import TradingRecord

_SECURITY = Security("BBG_T", 1, "COMMON", "SOME CORP", "Common Stock", True, "cusip")


def _trading(sightings=(), *, cusips=(), fails=None) -> TradingRecord:
    """A security's trading record as the last trade module reads it: its sightings, its own CUSIPs and the fails
    index their rows come from (none: no rows, no tenure bound)."""
    return TradingRecord(_SECURITY, sightings, tuple(cusips), fails)


def _k(item301: str, extra: str = "") -> str:
    return f"Item 2.01 Completion of Acquisition. {extra} Item 3.01 Notice of Delisting. {item301} Item 5.01 Changes."


def test_eightk_phrases():
    assert eightk_last_trade(_k("requested that trading be suspended prior to the opening of trading on "
                                "November 29, 2018")) == (date(2018, 11, 28), "8k_open")
    assert eightk_last_trade(_k("requested that Nasdaq suspend trading at the close of the market on "
                                "March 26, 2025")) == (date(2025, 3, 26), "8k_close")
    assert eightk_last_trade(_k("Trading was suspended immediately after the close on February 2, 2015")) \
        == (date(2015, 2, 2), "8k_close")
    # Test with straight quotes (Closing Date)
    assert eightk_last_trade(_k("requested a halt prior to the open of trading on the Closing Date",
                                extra='On October 13, 2023 (the "Closing Date"), the merger closed.')) \
        == (date(2023, 10, 12), "8k_open_closing")
    # Test with typographic left double quote (Closing Date) — real EDGAR text
    assert eightk_last_trade(_k("requested a halt prior to the open of trading on the Closing Date",
                                extra='On October 13, 2023 (the “Closing Date”), the merger closed.')) \
        == (date(2023, 10, 12), "8k_open_closing")
    # Test 8k_close_closing pattern with typographic quotes
    assert eightk_last_trade(_k("requested that trading at the close of trading on the Closing Date",
                                extra='On February 28, 2024 (the “Closing Date”), the merger closed.')) \
        == (date(2024, 2, 28), "8k_close_closing")
    assert eightk_last_trade(_k("trading in the Common Stock was suspended immediately on November 18, 2024")) \
        == (date(2024, 11, 18), "8k_suspended_unconfirmed")
    assert eightk_last_trade(_k("The last day of trading was January 5, 2017.")) == (date(2017, 1, 5), "8k_last_day")
    assert eightk_last_trade(_k("nothing dated here")) == (None, "")
    assert eightk_last_trade("") == (None, "")


def test_decide_prefers_midas_and_flags_conflict():
    lt = decide_last_trade(notice=(None, ""), eightk=(date(2025, 3, 26), "8k_close"),
                           midas=date(2025, 3, 25), halt=date(2025, 3, 25))
    assert lt == LastTrade(date(2025, 3, 25), "midas", ("last_trade_date_conflict",))


def test_decide_halt_then_text():
    assert decide_last_trade(notice=(None, ""), eightk=(None, ""), midas=None, halt=date(2015, 12, 24)) \
        == LastTrade(date(2015, 12, 24), "nasdaq_halt", ())
    assert decide_last_trade(notice=(date(2018, 11, 28), "notice_a"), eightk=(date(2018, 11, 28), "8k_open"),
                             midas=None, halt=None) == LastTrade(date(2018, 11, 28), "ex99_notice", ())
    assert decide_last_trade(notice=(None, ""), eightk=(date(2018, 11, 28), "8k_open"), midas=None, halt=None) \
        == LastTrade(date(2018, 11, 28), "8k_301", ())


def test_decide_unconfirmed_and_missing():
    lt = decide_last_trade(notice=(date(2024, 11, 18), "notice_b_unconfirmed"), eightk=(None, ""),
                           midas=None, halt=None)
    assert lt == LastTrade(date(2024, 11, 18), "ex99_notice", ("last_trade_date_unconfirmed",))
    assert decide_last_trade(notice=(None, ""), eightk=(None, ""), midas=None, halt=None) \
        == LastTrade(None, "", ("no_last_trade_date",))


@pytest.mark.parametrize("sentence, last_day", [
    ("trading in the shares will be suspended prior to the market opening on October 2, 2015", date(2015, 10, 1)),
    ("the common stock will be suspended prior to the commencement of trading on July 2, 2018", date(2018, 6, 29)),
    ("the listing will be suspended as of the open of business on July 1, 2020", date(2020, 6, 30)),
    ("trading was suspended at the opening of business on August 18, 2022", date(2022, 8, 17)),
])
def test_eightk_suspension_before_the_open_in_other_words(sentence, last_day):
    """GOOGL/GOOG/XRX, WTNY, ANAT and ENDPQ's 8-K wordings: the last trade day
    is the trading day before D (July 2, 2018 is a Monday)."""
    assert eightk_last_trade(_k(sentence)) == (last_day, "8k_open")


@pytest.mark.parametrize("sentence, last_day", [
    ("trading in the Company's common stock would be suspended prior to the market opening on Friday, "
     "November 21, 2008", date(2008, 11, 20)),                                                      # IDARQ 2008
    ("the common stock would be suspended from trading prior to market opening on Friday, December 5, 2008",
     date(2008, 12, 4)),                                                                            # TMA 2008
])
def test_a_weekday_may_come_before_the_date(sentence, last_day):
    assert eightk_last_trade(_k(sentence)) == (last_day, "8k_open")
    # a close: the day itself (LNT 2018)
    assert eightk_last_trade(_k("Alliant's common stock will cease trading at market close on Friday, "
                                "December 28, 2018")) == (date(2018, 12, 28), "8k_close")


def test_a_stated_close_on_a_day_with_no_session_is_the_trading_day_before():
    """CNDT 2019: "will end at market close on December 22, 2019" (a Sunday): Friday the 20th."""
    got = eightk_last_trade(_k("listing and trading of the Common Stock on NYSE will end at market close on "
                               "December 22, 2019, and that trading will begin on Nasdaq at market open on "
                               "December 23, 2019"))
    assert got == (date(2019, 12, 20), "8k_close")


def test_r8_with_the_date_first_is_the_trading_day_before():
    """CBL 2020: "On November 2, 2020, ... was notified by the NYSE ... that the REIT's common stock had been
    suspended from trading": the last trade was Friday October 30."""
    s = ("On November 2, 2020, CBL & Associates Properties, Inc. (the “REIT”) was notified by the New York Stock "
         "Exchange (“NYSE”) that the REIT’s common stock, par value $.01 per share – ticker symbol CBL – had been "
         "suspended from trading due to its “abnormally low” trading price levels.")
    assert eightk_last_trade(_k(s)) == (date(2020, 10, 30), "8k_suspended")


@pytest.mark.parametrize("sentence", [
    # BMC 2013: the merger closed and, the same day, trading was suspended (the day itself traded)
    "On September 10, 2013, the Company completed the Merger, and on the same day trading in the Common Stock was "
    "suspended",
    "On September 10, 2013, the NYSE announced that trading in the Common Stock would be suspended",
    "On September 10, 2013, the NYSE notified the Company that on September 12, 2013 trading was suspended",
])
def test_r8_with_the_date_first_refuses_a_completion_a_modal_or_another_date(sentence):
    assert eightk_last_trade(_k(sentence)) == (None, "")


def test_r8_with_the_date_first_leaves_an_immediate_suspension_unconfirmed():
    """WeWork 2023: "suspended immediately" keeps D itself, unconfirmed (5d's rule)."""
    s = "On November 7, 2023, the NYSE notified the Company that trading in the Common Stock was suspended immediately"
    assert eightk_last_trade(_k(s)) != (date(2023, 11, 6), "8k_suspended")


def test_a_notice_received_on_a_day_is_not_a_suspension():
    assert eightk_last_trade(_k("On August 18, 2022, the Company received a notice from the Exchange")) == (None, "")


# -- sub-plan 5d, rule 1: the 3.01 section read sentence by sentence (real wordings of the truth cases) -----------
@pytest.mark.parametrize("sentence, extra, reading", [
    ("The trading of the Common Stock on NASDAQ will be suspended after the close of trading on NASDAQ on "
     "December 1, 2011.", "", (date(2011, 12, 1), "8k_close")),                                       # GLBL
    ("Trading of shares of Company common stock on NASDAQ has ceased effective as of the close of trading on "
     "October 20, 2009.", "", (date(2009, 10, 20), "8k_close")),                                      # SEPR
    ("Trading of the Common Stock on Nasdaq will be suspended after the closing of trading on December 5, 2011.",
     "", (date(2011, 12, 5), "8k_close")),                                                             # PPDI
    ("TMHC notified the New York Stock Exchange (“NYSE”) of the anticipated completion of the Merger and requested "
     "that NYSE (i) suspend trading of TMHC Common Stock on the NYSE following the closing of trading on July 24, "
     "2026 and (ii) file a notification of removal from listing on Form 25.", "", (date(2026, 7, 24), "8k_close")),
    ("As a result of the merger, the Company no longer fulfills the numerical listing requirements of The NASDAQ "
     "Global Select Market (“NASDAQ”), and at the close of business on April 27, 2011, the Company’s common stock "
     "ceased trading on NASDAQ.", "", (date(2011, 4, 27), "8k_close")),                                # NOVL
    ("Accordingly, Biomet has requested that the Common Share, be withdrawn from listing on Nasdaq as of the close "
     "of business on September 25, 2007.", "", (date(2007, 9, 25), "8k_close")),                      # BMET
    ("The Common Stock will continue to be listed through February 28, 2011 and will no longer be listed on "
     "March 1, 2011.", "", (date(2011, 2, 28), "8k_last_day")),                                        # KG
    ("As previously reported, the NYSE halted trading of TPG’s common stock on October 21, 2011, which was the last "
     "day that TPG’s common stock traded on the NYSE.", "", (date(2011, 10, 21), "8k_last_day")),     # PMI
    ("The decision was reached in view of the “abnormally low” trading price of the Company’s common stock, which "
     "traded as low as $0.15 prior to the regulatory trading halt in the Company’s securities at the NYSE market "
     "open on September 26, 2008.", "", (date(2008, 9, 25), "8k_open")),                               # WM (R8)
    ("The shares of CCE Common Stock were suspended from trading on the NYSE effective as of the opening of trading "
     "on May 31, 2016.", "", (date(2016, 5, 27), "8k_open")),                                         # CCE
    ("Prior to the open of trading on the NYSE on September 6, 2016, trading in Company common stock was suspended "
     "by the NYSE, and at the open of trading the Johnson Controls ordinary shares began trading under the symbol "
     "“JCI.”", "", (date(2016, 9, 2), "8k_open")),                                                     # JCI
    ("Trading in the Company’s ordinary shares was also suspended on October 12, 2020.", "",
     (date(2020, 10, 9), "8k_suspended")),                                                             # MNK (R8)
    ("The NYSE also indefinitely suspended trading of the Company’s common shares on June 2, 2023.", "",
     (date(2023, 6, 1), "8k_suspended")),                                                              # DBD (R8)
    ("Common Shares will cease trading on NASDAQ effective as of the close of trading on the Closing Date and will "
     "be delisted from NASDAQ.", "In anticipation of the completion of the Arrangement, effective as of July 23, "
     "2015 (the “Closing Date”), all fees were paid.", (date(2015, 7, 23), "8k_close_closing")),       # CTRX
    ("Trading of the Ordinary Shares on Nasdaq was halted following the closing of trading on the Closing Date.",
     "On July 5, 2023 (the “ Closing Date ”), pursuant to the Merger Agreement, Merger Sub merged with and into the "
     "Company.", (date(2023, 7, 5), "8k_close_closing")),                                             # DSEY
    ("On December 15, 2025, the Company notified Nasdaq of the completion of the Split-Off and requested that its "
     "Liberty Live common stock, which traded under the symbols “LLYVA” and “LLYVK”, be delisted from Nasdaq "
     "effective on December 15, 2025 following the Effective Time.",
     "On December 15, 2025 at 4:05 p.m., New York City time (the “ Effective Time ”), Liberty Media Corporation "
     "completed its previously announced split-off.", (date(2025, 12, 15), "8k_close_effective")),    # LLYVA
])
def test_eightk_reads_the_3_01_wordings_of_the_5d_cases(sentence, extra, reading):
    assert eightk_last_trade(_k(sentence, extra)) == reading


@pytest.mark.parametrize("sentence", [
    "Holders of record as of the close of business on September 5, 2007 were entitled to vote at the meeting.",
    # MYL 2020: the date is the closing's, the suspension is undated
    "In connection with the closing of the transactions on November 16, 2020, Mylan notified The Nasdaq Stock Market "
    "LLC (“Nasdaq”) of the closing of the transactions and requested that trading of ordinary shares of Mylan "
    "should be suspended and listing of the Mylan Shares on Nasdaq should be removed.",
    # SUNW 2010: suspended on the completion, the day not stated
    "In connection with the completion of the Merger on January 26, 2010, Sun has notified NASDAQ that the Merger has "
    "been completed, and trading of Sun common stock on the NASDAQ Global Select Market has been suspended.",
    "Upon the filing of the Form 15, the Company’s reporting obligations under Section 15(d) will be suspended on "
    "March 1, 2011.",
    # a merger's closing is not the close of trading
    "Following the closing of the Merger on July 5, 2023, the Company ceased to be a public company.",
])
def test_eightk_reads_no_day_from_these(sentence):
    assert eightk_last_trade(_k(sentence)) == (None, "")


def test_a_3_01_section_runs_past_a_cross_reference():
    """NOVL 2011: "described in Item 1.01 above" is not the next item's heading; the stated day comes after it."""
    text = ("Item 3.01 Notice of Delisting. On April 27, 2011, immediately following the consummation of the patent "
            "sale described in Item 1.01 above, the merger was completed. As a result of the merger, at the close of "
            "business on April 27, 2011, the Company’s common stock ceased trading on NASDAQ. " + "x " * 120
            + "Item 3.03 Material Modification. At the effective time of the merger on April 27, 2011 ...")
    assert eightk_last_trade(text) == (date(2011, 4, 27), "8k_close")


def test_a_3_01_heading_spaced_out_by_the_html_stripping_is_its_section():
    """Wave 1 (5d's reader under 5g's spaced item numbers, CBL 2020's "ITEM 3 . 01"): the spaced heading opens the
    3.01 section and a spaced "ITEM 5 . 01" heading ends it, so another item's later sentence is not read."""
    text = ("ITEM 3 . 01 Notice of Delisting. The NYSE will suspend trading in the shares prior to the open of trading "
            "on November 2, 2020. " + "x " * 120 + "ITEM 5 . 01 Changes in Control. The shares will cease trading "
            "at the close of trading on November 5, 2020.")
    assert sections_3_01(text)[0].startswith("ITEM 3 . 01") and "November 5" not in sections_3_01(text)[0]
    assert eightk_last_trade(text) == (date(2020, 10, 30), "8k_open")


def test_a_stated_timing_beats_a_bare_suspension_in_one_filing():
    text = _k("Trading in the shares was suspended on June 2, 2016. The shares ceased trading at the close of "
              "trading on June 2, 2016.")
    assert eightk_last_trade(text) == (date(2016, 6, 2), "8k_close")


# -- rule 2: source order ---------------------------------------------------------------------------------------
def test_an_8k_timing_beats_a_notice_bare_date_that_disagrees():
    """TMHC 2026: the NYSE notice's "suspended from trading on July 24" (the 23rd) against the 8-K's "following the
    closing of trading on July 24"."""
    lt = decide_last_trade(notice=(date(2026, 7, 23), "notice_a"), eightk=(date(2026, 7, 24), "8k_close"),
                           midas=None, halt=None)
    assert lt == LastTrade(date(2026, 7, 24), "8k_301", ("last_trade_date_conflict",))


def test_a_notice_that_states_the_close_keeps_winning():
    lt = decide_last_trade(notice=(date(2020, 3, 2), "notice_close"), eightk=(date(2020, 2, 28), "8k_open"),
                           midas=None, halt=None)
    assert lt == LastTrade(date(2020, 3, 2), "ex99_notice", ("last_trade_date_conflict",))


def test_a_bare_suspension_in_the_8k_beats_an_unconfirmed_notice():
    """MNK 2020 (R8): the 8-K's "suspended on October 12" gives the 9th, the involuntary notice's decision day the
    12th."""
    lt = decide_last_trade(notice=(date(2020, 10, 12), "notice_b_unconfirmed"),
                           eightk=(date(2020, 10, 9), "8k_suspended"), midas=None, halt=None)
    assert lt == LastTrade(date(2020, 10, 9), "8k_301", ("last_trade_date_conflict",))


def test_a_halt_the_8k_puts_at_the_open_dates_the_day_before():
    """WM 2008 (R8): the feed stamps the code-D halt 09:30:06 on September 26; the 8-K says the halt came "at the NYSE
    market open on September 26", so the last trade is the 25th. HET 2008: the feed's 09:30:05 halt on January 28
    against an 8-K that says "at the close of business on January 28": the halt day stands."""
    wm = decide_last_trade(notice=(date(2008, 9, 29), "notice_b_unconfirmed"), eightk=(date(2008, 9, 25), "8k_open"),
                           midas=None, halt=date(2008, 9, 26))
    assert wm == LastTrade(date(2008, 9, 25), "8k_301", ("last_trade_date_conflict",))
    het = decide_last_trade(notice=(date(2008, 1, 25), "notice_a"), eightk=(date(2008, 1, 28), "8k_close"),
                            midas=None, halt=date(2008, 1, 28))
    assert het == LastTrade(date(2008, 1, 28), "nasdaq_halt", ("last_trade_date_conflict",))


# -- rule 4: the closing day when nothing states the last trade --------------------------------------------------
@pytest.mark.parametrize("text, lo, hi, reading", [
    ("Pursuant to the terms of the Merger Agreement, at 8:28 A.M. (Eastern) on November 24, 2008 (the “Effective "
     "Time”), the Purchaser completed the merger of the Purchaser with and into the Company.",
     date(2008, 11, 14), date(2008, 11, 24), date(2008, 11, 21)),                                      # IMCL
    ("The effective time of the Merger was 8:00 p.m., Eastern Time, on June 30, 2020. The Reorganization is "
     "intended to be tax-free.", date(2020, 6, 21), date(2020, 7, 1), date(2020, 6, 30)),              # ODP
    ("Item 7.01. Regulation FD Disclosure. On the evening of December 3, 2007, Fiserv, Inc. (“Fiserv”) completed its "
     "acquisition of CheckFree.", date(2007, 11, 24), date(2007, 12, 4), date(2007, 12, 3)),           # CKFR
    ("This Current Report on Form 8-K is being filed in connection with the consummation on November 3, 2009 (the "
     "“Closing Date”), of the transactions contemplated by the Merger Agreement.",
     date(2009, 10, 25), date(2009, 11, 14), date(2009, 11, 3)),                                       # SGP
    ("Pursuant to the Merger Agreement, on April 8, 2011, Parent completed its acquisition of Genzyme.",
     date(2011, 3, 29), date(2011, 4, 8), date(2011, 4, 8)),                                           # GENZ
    ("Item 2.01 Completion of Acquisition or Disposition of Assets On July 31, 2009, Alpha Natural Resources, Inc. "
     "(“Old Alpha”) merged (the “Merger”) with and into Foundation Coal Holdings, Inc. (“Foundation”). On August 1, "
     "2009, in connection with the Merger, FCC merged with and into New Alpha.", date(2009, 7, 26),
     date(2009, 8, 8), date(2009, 7, 31)),                                                             # FCL
    ("On August 1, 2025, pursuant to the previously announced Agreement and Plan of Merger dated as of May 3, 2024, by "
     "and between Uniti Group LLC, a Delaware corporation (f/k/a Uniti Group Inc.) (“Uniti”), and Windstream, as "
     "amended by Amendment No. 1 to the Agreement and Plan of Merger, dated as of July 17, 2024 (the “ Merger "
     "Agreement ”), Uniti and Windstream completed the previously announced merger.", date(2025, 7, 22),
     date(2025, 8, 4), date(2025, 8, 1)),                                                              # UNIT
    ("On March 1, 2021, Apache Corporation, a Delaware corporation (“ Apache ”), implemented a holding company "
     "reorganization pursuant to an Agreement and Plan of Merger.", date(2021, 2, 22), date(2021, 3, 4),
     date(2021, 3, 1)),                                                                                # APA
    ("In connection with the closing of the transactions on November 16, 2020, Mylan notified The Nasdaq Stock "
     "Market LLC of the closing.", date(2020, 11, 6), date(2020, 11, 16), date(2020, 11, 16)),        # MYL
])
def test_closing_day_reads_the_completion(text, lo, hi, reading):
    assert closing_day([text], lo, hi) == (reading, CLOSING_DAY)


def test_a_closing_on_a_holiday_last_traded_the_trading_day_before():
    """PNFP 2026: "On January 1, 2026, ... completed the merger": New Year's Day is no session; the 31st is."""
    text = "On January 1, 2026, Pinnacle completed the previously announced merger with Synovus."
    assert closing_day([text], date(2025, 12, 23), date(2026, 1, 2)) == (date(2025, 12, 31), CLOSING_DAY)


@pytest.mark.parametrize("text", [
    "On May 14, 2008, TPC and Millennium announced the completion of the Offer.",       # a tender offer, not the merger
    "Holders of record as of 5:00 p.m., New York City time, on Thursday, October 9, 2025 were entitled to vote.",
    "On January 2, 2009, the Company completed its acquisition of Foo Corp.",          # outside the window
    # HLTH 2009: an asset sale of a subsidiary, not the security's merger
    "On May 10, 2008, HLTH completed the sale of Porex to Porex Holding Corporation, a company formed by the "
    "Purchasers to own Porex after the acquisition.",
    "",
])
def test_closing_day_reads_nothing_from_these(text):
    assert closing_day([text], date(2008, 5, 4), date(2008, 5, 14)) is None


# -- a suspension at a stated clock time (architecture step 4) ---------------------------------------------------
def test_a_suspension_at_or_after_the_close_is_that_day_confirmed():
    """SPNV 2020 (8-K 0001193125-20-248926): suspended at 4:00 p.m. on September 17: the 17th traded."""
    s = ("Trading of the Company’s common stock was suspended effective as of approximately 4:00 p.m. Eastern Time "
         "on September 17, 2020.")
    assert eightk_last_trade(_k(s)) == (date(2020, 9, 17), "8k_close_clock")
    lt = decide_last_trade(notice=(date(2020, 9, 17), "notice_b_unconfirmed"), eightk=eightk_last_trade(_k(s)),
                           midas=None, halt=None)
    assert lt == LastTrade(date(2020, 9, 17), "8k_301", ()) and lt.confirmed


@pytest.mark.parametrize("sentence, last_day", [
    # Panera 2017, General Cable 2018: suspended at 9:00 a.m., before the open
    ("Trading of Class A Common Stock on the NASDAQ was suspended as of approximately 9:00 am EST on July 18, 2017.",
     date(2017, 7, 17)),
    ("Trading of the Shares on the NYSE was suspended as of approximately 9:00 a.m. EST on June 6, 2018.",
     date(2018, 6, 5)),
])
def test_a_suspension_before_the_open_is_the_trading_day_before(sentence, last_day):
    assert eightk_last_trade(_k(sentence)) == (last_day, "8k_open_clock")


@pytest.mark.parametrize("sentence", [
    "Trading of Class A Shares on the NASDAQ was suspended as of approximately 11:00 am EST on February 1, 2017.",
    # at the open itself is not before it (`OPEN_MINUTES`, as the effective-time and closing-day readers count)
    "Trading of the Common Stock on the Nasdaq was suspended as of approximately 9:30 am EST on November 29, 2018.",
])
def test_a_suspension_during_the_session_reads_no_day(sentence):
    assert eightk_last_trade(_k(sentence)) == (None, "")


# -- the anchor day and the first day after ------------------------------------------------------------------------
def test_the_anchor_is_the_last_trade_then_the_form25_then_the_anchor_8k_then_the_delisting_date():
    day = LastTrade(date(2020, 7, 1), MIDAS, ())
    none = LastTrade(None, UNSOURCED, (NO_DAY,))
    assert anchor_day(day, "2020-07-20", filed="2020-07-10", anchor_8k="2020-07-02") == date(2020, 7, 1)
    assert anchor_day(none, "2020-07-20", filed="2020-07-10", anchor_8k="2020-07-02") == date(2020, 7, 10)
    assert anchor_day(none, "2020-07-20", anchor_8k="2020-07-02") == date(2020, 7, 2)
    assert anchor_day(none, "2020-07-20") == date(2020, 7, 20)


def test_an_added_successors_first_day_is_the_next_trading_day():
    assert first_day_after(date(2026, 9, 25)) == date(2026, 9, 28)       # Friday -> Monday
    assert first_day_after(date(2025, 12, 31)) == date(2026, 1, 2)       # New Year's Day is no session
    assert first_day_after(date(2026, 9, 23)) == date(2026, 9, 24)


# -- the handoff stage ---------------------------------------------------------------------------------------------
def test_a_handoff_rows_day_is_the_last_sighting_before_the_successors_first():
    assert at_handoff(None, "2026-08-25", "2026-08-27") == LastTrade(date(2026, 8, 25), LAST_SIGHTING, ())
    # ST 2018: the fails rows meet (B's first row carries A's last close): the day before B's first
    assert at_handoff(None, "2018-03-02", "2018-03-02").day == date(2018, 3, 1)
    assert handoff_day("2018-03-02", "2018-03-02") == date(2018, 3, 1)


def test_a_kept_rows_day_at_a_handoff():
    """PNFP 2026: a row with no day takes the handoff's; a worked-out closing day past B's first sighting is capped
    (still unconfirmed); any other day stands."""
    none = LastTrade(None, UNSOURCED, (NO_DAY,), (date(2026, 1, 2),))
    assert at_handoff(none, "2026-01-02", "2026-01-05") == LastTrade(date(2026, 1, 2), LAST_SIGHTING, (),
                                                                     (date(2026, 1, 2),))
    late = LastTrade(date(2026, 1, 6), CLOSING_DAY, (UNCONFIRMED,))
    assert at_handoff(late, "2026-01-02", "2026-01-05") == LastTrade(date(2026, 1, 2), LAST_SIGHTING, (UNCONFIRMED,))
    early = LastTrade(date(2026, 1, 2), CLOSING_DAY, (UNCONFIRMED,))
    assert at_handoff(early, "2026-01-02", "2026-01-05") is early
    measured = LastTrade(date(2026, 1, 6), MIDAS, ())
    assert at_handoff(measured, "2026-01-02", "2026-01-05") is measured


# -- stage 9c: the re-dating from a notice ------------------------------------------------------------------------
_FORM25 = Path(__file__).parent / "fixtures" / "form25"
_LEG = {"form": "25-NSE", "filing_date": "2026-08-27", "accession": "0000876661-26-000712"}


class _Raws:
    def __init__(self, raw):
        self.raw, self.asked = raw, []

    def fetch_filing_raw(self, cik, accession):
        self.asked.append((cik, accession))
        return self.raw


def _sighted():
    return LastTrade(date(2026, 8, 25), LAST_SIGHTING, ())


def _notice(name):
    return (_FORM25 / name).read_text(encoding="utf-8", errors="replace")


def test_a_handoff_row_takes_its_form25_notices_confirmed_day():
    got = Dating(_Raws(_notice("leg_25nse_before_market_open.txt"))).from_notice(
        58492, _LEG, _sighted(), before="2026-08-27", effective="2026-09-06")
    assert (got.day, got.source) == (date(2026, 8, 26), EX99_NOTICE) and got.confirmed


def test_a_handoff_row_keeps_its_sighting_without_a_confirmed_notice_day_before_the_successor():
    lt = _sighted()
    for raw in ("<TYPE>25-NSE no notice here", _notice("rsh_25nse.txt"), ""):     # none, unconfirmed, unreadable
        assert Dating(_Raws(raw)).from_notice(58492, _LEG, lt, before="2026-08-27", effective="2026-09-06") is lt
    leg = _notice("leg_25nse_before_market_open.txt")
    for before in ("2026-08-26", "2026-08-20"):                                     # on or after B's first sighting
        assert Dating(_Raws(leg)).from_notice(58492, _LEG, lt, before=before, effective="2026-09-06") is lt
    assert Dating(_Raws(leg)).from_notice(58492, _LEG, lt, before="", effective="2026-08-25") is lt   # past effect


def test_a_row_dated_another_way_or_without_a_form25_is_never_read():
    edgar = _Raws(_notice("leg_25nse_before_market_open.txt"))
    measured = LastTrade(date(2026, 8, 25), MIDAS, ())
    assert Dating(edgar).from_notice(58492, _LEG, measured, before="", effective="2026-09-06") is measured
    assert Dating(edgar).from_notice(58492, None, _sighted(), before="", effective="2026-09-06").source == LAST_SIGHTING
    assert edgar.asked == []


def test_a_failed_notice_read_keeps_the_sighting_and_trips_the_stages_watch():
    from delist_detection.outputs.degraded import DegradedWatch
    from delist_detection.sources.sec_stats import SEC_STATS

    class Failing(_Raws):
        def fetch_filing_raw(self, cik, accession):
            SEC_STATS.degraded("failed_request")
            return ""

    lt, watch = _sighted(), DegradedWatch()
    assert Dating(Failing("")).from_notice(58492, _LEG, lt, before="", effective="2026-09-06") is lt
    assert watch.tripped()


# -- dating a Form 25 group: the windows, the confirmations (fake MIDAS and halt adapters), rules 3 and 4 ---------
class _Midas:
    """MIDAS's adapter double: a last day with exchange volume per ticker (`days`), else one for every ticker."""

    def __init__(self, day=None, days=None):
        self.day, self.days, self.calls = day, days or {}, []

    def last_trade_day(self, ticker, lo, hi):
        self.calls.append((ticker, lo, hi))
        day = self.days.get(ticker, self.day)
        return day if day is not None and lo <= day <= hi else None


class _Halts:
    """The Nasdaq halt feed's adapter double: code-D halts by ticker, and the days it failed to read."""

    def __init__(self, halts=None, fail=False):
        self.halts, self.fail, self.failed, self.asked = halts or {}, fail, [], []

    def deletion_halt(self, symbol, lo, hi, max_days=7):
        self.asked.append((symbol, lo, hi))
        if self.fail:
            self.failed.append(lo)
            return None
        h = self.halts.get(symbol)
        return h if h is not None and lo <= h.halt_date <= hi else None

    def failed_days(self):
        return tuple(self.failed)


def _halt(symbol, day, at="09:30:06"):
    return Halt(symbol, "", "NASDAQ", "D", day, at, None)


AET_RAW = _notice("aet_25nse.txt")


def _f25(raw, accession="n1", form="25-NSE", filed="2018-11-29"):
    return EdgarSubmission(accession, form, filed, "", "", "p.xml"), parse_form25(raw, accession=accession,
                                                                                 form=form, filing_date=filed)


def _exchange_raw(rule="17 CFR 240.12d2-2(a)(3)", notice=""):
    text = (f"\n<TYPE>EX-99.25\n<TEXT>\n{notice}\n</TEXT>" if notice else "")
    return ("<TYPE>25-NSE\n<notificationOfRemoval><exchange><entityName>New York Stock Exchange LLC</entityName>"
            "</exchange>\n<descriptionClassSecurity>Common Stock</descriptionClassSecurity>\n"
            f"<ruleProvision>{rule}</ruleProvision></notificationOfRemoval>{text}")


def _group(dating, group, *, ticker="AET", trading=_trading(), continued=False, filings=()):
    return dating.of_group(1, list(filings), group, group[0], ticker=ticker, trading=trading, continued=continued)


def test_midas_volume_from_the_still_trading_cut_on_is_not_the_last_trade(fake_edgar):
    """AET 2018: the group's MIDAS window is [filed - 75 d, effective + 10 d]; a day on or after effective + 5 d
    (2018-12-14) is the security still trading somewhere, so the notice's day stands; the 13th is taken."""
    group = [_f25(AET_RAW)]
    late = _group(Dating(fake_edgar, midas=_Midas(date(2018, 12, 14))), group)
    assert (late.day, late.source) == (date(2018, 11, 28), EX99_NOTICE)
    used = _group(Dating(fake_edgar, midas=_Midas(date(2018, 12, 13))), group)
    assert (used.day, used.source) == (date(2018, 12, 13), MIDAS)
    midas = _Midas(date(2018, 11, 28))
    _group(Dating(fake_edgar, midas=midas), group)
    assert midas.calls == [("AET", date(2018, 9, 15), date(2018, 12, 19))]


def test_an_involuntary_notices_day_nothing_confirms_is_unconfirmed_until_midas_measures_it(fake_edgar):
    """Spec 8.8, RadioShack 2015: an involuntary notice's day is the exchange's decision day."""
    group = [_f25(_notice("rsh_25nse.txt"), filed="2015-03-20")]
    lt = _group(Dating(fake_edgar), group, ticker="RSH")
    assert (lt.day, lt.source, lt.confirmed) == (date(2015, 2, 2), EX99_NOTICE, False)
    lt = _group(Dating(fake_edgar, midas=_Midas(date(2015, 2, 2))), group, ticker="RSH")
    assert (lt.source, lt.flags, lt.confirmed) == (MIDAS, (), True)


def test_the_confirmations_ask_every_ticker_the_security_carried_in_the_window(fake_edgar):
    """Spirit Airlines 2024: by its Form 25 the shares traded OTC as SAVEQ; MIDAS knows SAVE only."""
    group = [_f25(_notice("save_25nse.txt"), filed="2024-12-05")]
    trading = _trading([Sighting("2024-11-15", "SAVE", "ftd"), Sighting("2024-11-20", "SAVEQ", "ftd")])
    midas = _Midas(days={"SAVE": date(2024, 11, 15)})
    lt = _group(Dating(fake_edgar, midas=midas), group, ticker="SAVEQ", trading=trading)
    assert (lt.day, lt.source) == (date(2024, 11, 15), MIDAS)
    assert {t for t, _, _ in midas.calls} == {"SAVE", "SAVEQ"}


def test_a_halt_answers_when_midas_has_nothing_and_a_failed_feed_day_is_carried(fake_edgar):
    group = [_f25(AET_RAW)]
    lt = _group(Dating(fake_edgar, halts=_Halts({"AET": _halt("AET", date(2018, 11, 29), "16:30:00")})), group)
    assert (lt.day, lt.source) == (date(2018, 11, 29), NASDAQ_HALT)
    halts = _Halts(fail=True)
    lt = _group(Dating(fake_edgar, halts=halts), group)
    assert lt.halt_feed_failed == tuple(halts.failed) != () and lt.source == EX99_NOTICE
    assert _group(Dating(fake_edgar, halts=_Halts()), group).halt_feed_failed == ()
    assert _group(Dating(fake_edgar), group).halt_feed_failed == ()


def _tenure_rows():
    """The security's own CUSIP traded under JJJ to 2016-09-02's close; another CUSIP's first priced row under JJJ
    is 2016-09-07, so the ticker was taken from the 6th."""
    return [FtdRow("2016-08-31", "OWNCUSIP1", "JJJ", "OLD CO", 45.0), FtdRow("2016-09-06", "OWNCUSIP1", "JJJ", "OLD CO",
                                                                            45.04),
            FtdRow("2016-09-07", "NEWCUSIP1", "JJJ", "NEW PLC", 48.9)]


def test_rule_3_bounds_a_read_by_ticker_at_the_day_another_cusip_took_it(fake_edgar):
    """JCI 2016: MIDAS's September 6 under JCI is Johnson Controls plc's; the old JCI's 8-K says before the open on
    the 6th, so MIDAS is read up to the 2nd (the trading day before the 6th is the 2nd: Labor Day)."""
    fake_edgar.texts["k1"] = ("Item 3.01 Notice of Delisting. Prior to the open of trading on the NYSE on September 6, "
                              "2016, trading in Company common stock was suspended. " + "x" * 300)
    filings = [EdgarSubmission("k1", "8-K", "2016-09-06", "2016-09-06", "3.01", "k.htm")]
    group = [_f25(_exchange_raw(), filed="2016-09-06")]
    trading = _trading(cusips=["OWNCUSIP1"], fails=FtdIndex(_tenure_rows()))
    midas = _Midas(days={"JJJ": date(2016, 9, 6)})
    unbounded = _group(Dating(fake_edgar, midas=midas), group, ticker="JJJ", filings=filings)
    assert unbounded.day == date(2016, 9, 6)
    midas = _Midas(days={"JJJ": date(2016, 9, 6)})
    midas.last_trade_day = lambda t, lo, hi: date(2016, 9, 6) if hi >= date(2016, 9, 6) else date(2016, 9, 2)
    bounded = _group(Dating(fake_edgar, midas=midas), group, ticker="JJJ", trading=trading, filings=filings)
    assert (bounded.day, bounded.source) == (date(2016, 9, 2), MIDAS)


def test_rule_3_drops_a_halt_under_a_ticker_another_cusip_took(fake_edgar):
    """A halt after the 8-K's day, from the day another CUSIP traded under the ticker, is the other security's: the
    8-K's day stands. Without the tenure, the halt is taken."""
    fake_edgar.texts["k1"] = ("Item 3.01 Notice of Delisting. Trading in the common stock was suspended after the "
                              "close of trading on September 1, 2016. " + "x" * 300)
    filings = [EdgarSubmission("k1", "8-K", "2016-09-02", "2016-09-02", "3.01", "k.htm")]
    group = [_f25(_exchange_raw(), filed="2016-09-02")]
    rows = [FtdRow("2016-08-30", "OWNCUSIP1", "JJJ", "OLD CO", 45.0),
            FtdRow("2016-09-01", "OWNCUSIP1", "JJJ", "OLD CO", 45.04),
            FtdRow("2016-09-02", "NEWCUSIP1", "JJJ", "NEW PLC", 48.9)]
    trading = _trading(cusips=["OWNCUSIP1"], fails=FtdIndex(rows))
    halts = _Halts({"JJJ": _halt("JJJ", date(2016, 9, 2), "16:30:00")})
    lt = _group(Dating(fake_edgar, halts=halts), group, ticker="JJJ", trading=trading, filings=filings)
    assert (lt.day, lt.source) == (date(2016, 9, 1), EIGHTK_301)
    lt = _group(Dating(fake_edgar, halts=halts), group, ticker="JJJ", filings=filings)
    assert (lt.day, lt.source) == (date(2016, 9, 2), NASDAQ_HALT)


def test_rule_4_an_undated_exchange_removal_takes_the_closing_day(fake_edgar):
    """The 8-Ks in [F - 10, F + 10] give the closing day for [F - 10, F]; with none, the Form 25 day F itself; source
    `closing_day`, unconfirmed, the halt feed's failed days kept."""
    fake_edgar.texts["c1"] = "On March 1, 2021, Apache Corporation implemented a holding company reorganization."
    filings = [EdgarSubmission("c1", "8-K", "2021-03-01", "2021-03-01", "2.01", "k.htm")]
    group = [_f25(_exchange_raw(), filed="2021-03-04")]
    lt = _group(Dating(fake_edgar, halts=_Halts(fail=True)), group, filings=filings)
    assert (lt.day, lt.source, lt.flags) == (date(2021, 3, 1), CLOSING_DAY, (UNCONFIRMED,)) and lt.worked_out
    assert lt.halt_feed_failed != ()
    bare = _group(Dating(fake_edgar), group)
    assert (bare.day, bare.source) == (date(2021, 3, 4), CLOSING_DAY)


def test_rule_4_never_dates_an_involuntary_removal_an_issuers_own_form25_or_a_continued_group(fake_edgar):
    """TMA 2008: a (b) Form 25 follows the suspension by weeks; the issuer's own Form 25 and a group the security
    went on after are no closing either."""
    involuntary = [_f25(_exchange_raw(rule="17 CFR 240.12d2-2(b)(1)"), filed="2012-09-14")]
    assert _group(Dating(fake_edgar), involuntary).day is None
    own = [_f25(_exchange_raw().replace("25-NSE", "25"), form="25", filed="2012-09-14")]
    assert _group(Dating(fake_edgar), own).day is None
    voluntary = [_f25(_exchange_raw(), filed="2012-09-14")]
    assert _group(Dating(fake_edgar), voluntary, continued=True).day is None
    assert _group(Dating(fake_edgar), voluntary).source == CLOSING_DAY


def test_rule_4s_closing_day_never_comes_before_the_last_day_the_own_rows_show_trading(fake_edgar):
    """AVGO 2018, Z 2015: the text says March 1; the own CUSIP's rows show it trading to March 3 (the trading day
    before the row that opens its last one-price run), no later than the Form 25 day, so March 3 stands."""
    fake_edgar.texts["c1"] = "On March 1, 2021, Apache Corporation implemented a holding company reorganization."
    filings = [EdgarSubmission("c1", "8-K", "2021-03-01", "2021-03-01", "2.01", "k.htm")]
    rows = [FtdRow("2021-03-02", "OWNCUSIP1", "APA", "APACHE", 19.0), FtdRow("2021-03-04", "OWNCUSIP1", "APA",
                                                                          "APACHE", 19.52),
            FtdRow("2021-03-05", "OWNCUSIP1", "APA", "APACHE", 19.52)]
    trading = _trading(cusips=["OWNCUSIP1"], fails=FtdIndex(rows))
    lt = _group(Dating(fake_edgar), [_f25(_exchange_raw(), filed="2021-03-04")], trading=trading, filings=filings)
    assert (lt.day, lt.source) == (date(2021, 3, 3), CLOSING_DAY)


# -- dating the no-Form-25 fallback --------------------------------------------------------------------------------
def test_the_fallback_reads_3_01_8ks_up_to_the_last_sighting_plus_five_days(fake_edgar):
    """VRM 2024: the suspension 8-K came 13 days after the bankruptcy 8-K that dates the fallback."""
    fake_edgar.texts["s2"] = ("Item 3.01 Notice of Delisting. Trading in the common stock will be suspended at the "
                              "opening of business on January 28, 2015. " + "x" * 300)
    filings = [EdgarSubmission("s2", "8-K", "2015-01-26", "2015-01-26", "3.01", "k2.htm")]
    lt = Dating(fake_edgar).of_fallback(1, filings, ticker="VVV", ended_by=date(2015, 1, 12),
                                        last_seen=date(2015, 1, 28), trading=_trading(), merger=False)
    assert (lt.day, lt.source, lt.confirmed) == (date(2015, 1, 27), EIGHTK_301, True)
    early = Dating(fake_edgar).of_fallback(1, filings, ticker="VVV", ended_by=date(2015, 1, 12),
                                           last_seen=date(2015, 1, 12), trading=_trading(), merger=False)
    assert early.source == UNSOURCED                  # the 8-K came past the last sighting + 5 days


def test_the_fallback_ends_on_its_last_sighting_unconfirmed_keeping_the_failed_halt_days(fake_edgar):
    halts = _Halts(fail=True)
    lt = Dating(fake_edgar, halts=halts).of_fallback(1, [], ticker="VVV", ended_by=date(2015, 1, 10),
                                                     last_seen=date(2015, 1, 10), trading=_trading(), merger=False)
    assert (lt.day, lt.source, lt.flags) == (date(2015, 1, 10), UNSOURCED, (UNCONFIRMED,))
    assert lt.halt_feed_failed == tuple(halts.failed) != ()


def test_a_fallback_merger_ends_on_the_closing_day_its_completion_8k_states(fake_edgar):
    """FCL 2009: merged on July 31, last sighted August 14; never after the last sighting."""
    fake_edgar.texts["m1"] = "On July 31, 2009, the Company completed its merger with Alpha Natural Resources."
    filings = [EdgarSubmission("m1", "8-K", "2009-07-31", "2009-07-31", "2.01,5.01", "k.htm")]
    lt = Dating(fake_edgar).of_fallback(1, filings, ticker="FCL", ended_by=date(2009, 8, 14),
                                        last_seen=date(2009, 8, 14), trading=_trading(), merger=True)
    assert (lt.day, lt.source) == (date(2009, 7, 31), CLOSING_DAY) and not lt.confirmed
    plain = Dating(fake_edgar).of_fallback(1, filings, ticker="FCL", ended_by=date(2009, 8, 14),
                                           last_seen=date(2009, 8, 14), trading=_trading(), merger=False)
    assert plain.source == UNSOURCED
    before = Dating(fake_edgar).of_fallback(1, filings, ticker="FCL", ended_by=date(2009, 7, 30),
                                            last_seen=date(2009, 7, 30), trading=_trading(), merger=True)
    assert before.day == date(2009, 7, 30) and before.source == UNSOURCED
