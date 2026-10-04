"""Sub-plan 5g's readers (distress.py), on real filing sentences and fails rows of the cases they decide."""
from datetime import date

import pytest

from delist_detection.distress import (
    liquidating, otc_symbol_from_fails, otc_symbol_from_text, plan_ratio, price_only, substitutes_new_shares,
)
from delist_detection.ftd import FtdRow


def rows(*spec):
    """(date, symbol, price) triples under one CUSIP."""
    return [FtdRow(d, "123456789", s, "ISSUER INC", p) for d, s, p in spec]


# -- the OTC symbol from the security's own CUSIP's fails rows --------------------------------------------------

def test_the_first_other_symbol_after_the_last_trade_is_the_otc_symbol():
    # GPOR 2020: the Nasdaq symbol settles two days, then GPORQ
    got = otc_symbol_from_fails(rows(("2020-11-24", "GPOR", 0.16), ("2020-11-27", "GPOR", 0.15),
                                     ("2020-11-30", "GPORQ", 0.11), ("2020-12-01", "GPORQ", 0.10)),
                                "GPOR", date(2020, 11, 25))
    assert got == "GPORQ"


def test_the_first_of_two_otc_symbols_wins():
    # WFT 2019: WFTIF from 2019-05-16, WFTIQ once the Chapter 11 was filed
    got = otc_symbol_from_fails(rows(("2019-05-14", "WFT", 0.38), ("2019-05-16", "WFTIF", 0.06),
                                     ("2019-05-30", "WFTIF", 0.05), ("2019-07-08", "WFTIQ", 0.04)),
                                "WFT", date(2019, 5, 10))
    assert got == "WFTIF"


def test_the_exchange_symbol_that_keeps_trading_is_the_otc_symbol():
    # LKSD 2019: LKSD trades on at changing prices for months; LKSDQ comes only in April
    spec = [("2019-12-30", "LKSD", 0.10), ("2020-01-08", "LKSD", 0.09), ("2020-01-15", "LKSD", 0.08),
            ("2020-01-22", "LKSD", 0.07), ("2020-04-17", "LKSDQ", 0.05)]
    assert otc_symbol_from_fails(rows(*spec), "LKSD", date(2019, 12, 27)) == "LKSD"


def test_fails_still_settling_under_the_exchange_symbol_say_nothing():
    # SIVB 2023: a day of settling fails, no other symbol
    assert otc_symbol_from_fails(rows(("2023-03-10", "SIVB", 106.04)), "SIVB", date(2023, 3, 9)) is None
    # a settling tail at the last close only, however long
    spec = [("2009-08-18", "CNB", 0.41), ("2009-08-19", "CNB", 0.41), ("2009-09-02", "CNB", 0.41)]
    assert otc_symbol_from_fails(rows(*spec), "CNB", date(2009, 8, 17)) is None


def test_deleted_unassigned_masked_and_late_symbols_are_no_otc_symbol():
    spec = [("2018-07-05", "SDRLXXXX", 0.10), ("2018-07-06", "SDRLZZZZ", 1.0), ("2018-07-09", "**********", 0.1),
            ("2018-09-20", "SDRLQ", 0.02)]           # more than 30 days after the last trade
    assert otc_symbol_from_fails(rows(*spec), "SDRL", date(2018, 7, 2)) is None


def test_rows_on_or_before_the_last_trade_do_not_count():
    assert otc_symbol_from_fails(rows(("2020-11-25", "GPORQ", 0.1)), "GPOR", date(2020, 11, 25)) is None


# -- the OTC symbol the 3.01 notice names --------------------------------------------------------------------------

@pytest.mark.parametrize("text, symbol", [
    # BTU 2016
    ("The Company’s common stock is expected to begin trading on the OTC Pink Sheets marketplace under the symbol "
     "BTUUQ on April 14, 2016. The Company can provide no assurance.", "BTUUQ"),
    # SPNV 2020
    ("The Company anticipates that, effective September 18, 2020, its common stock will commence trading on the "
     "OTCQX marketplace (the “OTCQX”) under the trading symbol “SPNX”.", "SPNX"),
    # CHK 2020
    ("Trading of Chesapeake’s Common Stock has commenced, effective as of June 30, 2020, on the OTC Pink Market or "
     "“pink sheets” market under the symbol “CHKAQ”.", "CHKAQ"),
    # DYN 2012
    ("Dynegy’s common stock is currently trading under the symbol “DYNIQ” in the over-the-counter market.", "DYNIQ"),
    # MDRX 2024: the exchange symbol is the OTC symbol
    ("While the Company’s common stock is suspended from trading on Nasdaq, the Company expects that its shares of "
     "common stock will be quoted on an over-the-counter market with its existing ticker symbol (MDRX).", "MDRX"),
    # WE 2023: the warrants' sentence is skipped, the common's read
    ("Effective August 23, 2023, the registrant’s warrants are trading on the OTC Pink Marketplace under the symbol "
     "“WEWOW.” As a result of the suspension and expected delisting, WeWork’s Common Stock commenced trading in the "
     "OTC Pink Marketplace under the symbol “WEWKQ”.", "WEWKQ"),
])
def test_the_notice_names_the_otc_symbol(text, symbol):
    assert otc_symbol_from_text(text) == symbol


def test_an_exchange_symbol_with_no_otc_venue_is_no_otc_symbol():
    # CNB 2009: the NYSE's own ticker symbol
    text = ("On August 17, 2009, the New York Stock Exchange (NYSE) announced that it had determined that the "
            "Company’s common stock (ticker symbol CNB) should be suspended immediately.")
    assert otc_symbol_from_text(text) == ""
    assert otc_symbol_from_text("") == ""


# -- a price deficiency and nothing else -------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # KWK 2015 (Form 25 notice)
    "The Exchange reached its decision pursuant to Section 802.01D in view of the abnormally low price of the Common "
    "Stock; the average closing price had fallen below $1.00 over a consecutive 30 trading-day period (802.01C).",
    # LTRPA 2023 (Nasdaq's Form 25 notice)
    "The Nasdaq Stock Market LLC determined to remove the stock pursuant to Listing Rule 5450(a)(1).",
    # WFT 2019 (8-K 3.01; the Chapter 11 is no listing standard)
    "NYSE determined to suspend trading in view of the abnormally low price levels of the ordinary shares, after the "
    "Company announced its intention to file a prepackaged chapter 11 case.",
])
def test_a_price_deficiency_alone_is_price(text):
    assert price_only(text)


@pytest.mark.parametrize("text", [
    # RHD 2009: a market capitalization standard beside the price
    "the Company had fallen below the NYSE's continued listing standard of average global market capitalization over "
    "a consecutive 30 trading-day period of less than $25,000,000 (802.01B); its average closing price was less than "
    "$1.00",
    # FST 2015: a back door listing beside the price (802.01C)
    "a back door listing that did not meet the initial listing standards of Section 102.01; average closing price "
    "less than $1.00 (802.01C)",
    # SPNV 2020
    "failure to maintain an average global market capitalization over a consecutive 30-day trading period of at "
    "least $15 million, pursuant to Section 802.01B",
    # MDRX 2024: a late annual report
    "the Company did not timely file its Annual Report on Form 10-K",
    "",
])
def test_another_standard_or_no_price_word_is_not_price(text):
    assert not price_only(text)


# -- a bankruptcy plan's new shares for the class (R6) -------------------------------------------------------------

SDRL = ("17 CFR 240.12d2-2(a)(3) That on July 3, 2018 the instruments representing the securities comprising the "
        "entire class of this security came to evidence, by operation of law or otherwise, other securities in "
        "substitution therefore and represent no other right except, if such be the fact, the right to receive an "
        "immediate cash payment. Seadrill Limited emerged from Bankruptcy on July 2, 2018. As a result, 1.9% of the "
        "New Common Stock will be issued to holders of existing common equity interest in the Company as of the "
        "Effective Date, an effective exchange ratio of approximately 0.0037345 New Common Stock per each Existing "
        "Share of Common Stock.")
WOLF = ("That on September 29, 2025, the instruments representing the securities comprising the entire class of this "
        "security came to evidence, by operation of law or otherwise, other securities in substitution therefore. In "
        "connection with the Company's emergence from Chapter 11, the Company will effect a reincorporation. Holders "
        "of Common Stock of Wolfspeed, Inc. \"Old\", (CUSIP - 977852102) will receive shares of Common Stock of the "
        "reorganized Wolfspeed, Inc. \"New\" (CUSIP - 97785W106).")
WOLF_8K = ("Immediately prior to the Plan Effective Date, there were 156,479,390 outstanding shares of Wolfspeed’s "
           "common stock, $0.00125 par value per share (the “Old Common Stock”). Under the Plan, on the Plan Effective "
           "Date, all of the previously issued and outstanding shares of Old Common Stock were cancelled, and existing "
           "equity holders received their pro rata share of approximately 1,306,896 shares of New Common Stock. Also "
           "pursuant to the Plan, Wolfspeed issued an aggregate of approximately 25,840,656 shares of New Common Stock "
           "(inclusive of the aforementioned shares of New Common Stock issued to existing equity holders). However, "
           "if Regulatory Approvals are received by the Regulatory Trigger Deadline, holders of Old Common Stock "
           "immediately prior to the Plan Effective Date shall receive their pro rata portion of 871,287 shares of New "
           "Common Stock from the Share Reserve.")
WLL = ("That on September 01, 2020 the instruments representing the securities comprising the entire class of this "
       "security came to evidence, by operation of law or otherwise, other securities in substitution therefore. "
       "Pursuant to the mandatory exchange, which became effective on September 1, 2020, each share of the Whiting "
       "Petroleum Corporation (Old) Common Stock was converted into Whiting Petroleum Corporation (New) Common Stock, "
       "Series A Warrants and Series B Warrants.")
APA = ("That on March 1, 2021 the instruments representing the securities comprising the entire class of this "
       "security came to evidence, by operation of law or otherwise, other securities in substitution therefore. "
       "Each share of Apache Corporation common stock was converted into one share of APA Corporation common stock.")


def test_a_plan_notice_substitutes_new_shares():
    assert substitutes_new_shares(SDRL) and substitutes_new_shares(WOLF) and substitutes_new_shares(WLL)
    assert not substitutes_new_shares("pursuant to the provisions of Rule 12d2-2(b) because ... no longer suitable")
    assert not substitutes_new_shares(APA)          # a holding company's one-for-one: no "new" shares


def test_the_plan_ratio_is_the_notices_or_the_plan_8ks_counts():
    assert plan_ratio(SDRL, []) == ("0.0037345", "form25_notice")
    got = plan_ratio(WOLF, [WOLF_8K])
    assert got is not None and got[1] == "plan_8k" and float(got[0]) == pytest.approx(1_306_896 / 156_479_390)
    assert got[0] == "0.00835187"
    assert plan_ratio(WLL, []) is None              # each share into new shares and warrants: no ratio stated
    assert plan_ratio(WOLF, []) is None


def test_two_different_counts_for_old_holders_state_no_ratio():
    text = WOLF_8K + " Existing equity holders received 2,000,000 shares of New Common Stock."
    assert plan_ratio(WOLF, [text]) is None


# -- a liquidation (EQC 2025) ------------------------------------------------------------------------------------

def test_a_liquidating_distribution_or_a_plan_of_dissolution_is_a_liquidation():
    eqc = ("On April 1, 2025, Equity Commonwealth also announced that its Board of Trustees has authorized the "
           "Company’s final cash liquidating distribution of $1.60 per common share. After payment of the Final Cash "
           "Liquidating Distribution and delisting from NYSE, the Company will continue the process of winding down, "
           "transfer any remaining assets and liabilities to a Maryland liquidating trust.")
    assert liquidating(eqc)
    assert liquidating("the stockholders approved the Plan of Complete Liquidation and Dissolution")
    assert not liquidating("The Company's last day of trading on NYSE will be April 21, 2025.")
    assert not liquidating("the liquidation preference of the Series A Preferred Stock")
    assert not liquidating("")
