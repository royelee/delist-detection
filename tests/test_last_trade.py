from datetime import date

from delist_detection.last_trade import LastTrade, decide_last_trade, eightk_last_trade


def _k(item301: str, extra: str = "") -> str:
    return f"Item 2.01 Completion of Acquisition. {extra} Item 3.01 Notice of Delisting. {item301} Item 5.01 Changes."


def test_eightk_phrases():
    assert eightk_last_trade(_k("requested that trading be suspended prior to the opening of trading on "
                                "November 29, 2018")) == (date(2018, 11, 28), "8k_open")
    assert eightk_last_trade(_k("requested that Nasdaq suspend trading at the close of the market on "
                                "March 26, 2025")) == (date(2025, 3, 26), "8k_close")
    assert eightk_last_trade(_k("Trading was suspended immediately after the close on February 2, 2015")) \
        == (date(2015, 2, 2), "8k_close")
    assert eightk_last_trade(_k("requested a halt prior to the open of trading on the Closing Date",
                                extra='On October 13, 2023 (the "Closing Date"), the merger closed.')) \
        == (date(2023, 10, 12), "8k_open_closing")
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
