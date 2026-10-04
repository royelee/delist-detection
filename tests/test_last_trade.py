from datetime import date

import pytest

from delist_detection.last_trade import (CLOSING_DAY, LastTrade, closing_day, decide_last_trade,
                                         eightk_last_trade)


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
