from datetime import date
from pathlib import Path

from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import (
    Form25, SecurityRef, class_kind, class_label, effective_date, exchange_label, exchanges_named,
    list_form25, match_security, notice_last_trade, parse_form25,
)

FIX = Path(__file__).parent / "fixtures" / "form25"


def _load(name, accession, filing_date):
    return parse_form25((FIX / name).read_text(encoding="utf-8", errors="replace"),
                        accession=accession, form="25-NSE", filing_date=filing_date)


def test_parse_aet():
    f = _load("aet_25nse.txt", "0000876661-18-001269", "2018-11-29")
    assert f.exchange == "NYSE"
    assert f.class_text == "Common Stock"
    assert f.rule.endswith("(a)(3)")
    assert "suspended from trading on November 29, 2018" in f.notice_text
    assert notice_last_trade(f) == (date(2018, 11, 28), "notice_a")


def test_notice_dates_for_involuntary_removals():
    rsh = _load("rsh_25nse.txt", "0000876661-15-000132", "2015-03-20")
    assert notice_last_trade(rsh) == (date(2015, 2, 2), "notice_close")
    save = _load("save_25nse.txt", "0000876661-24-001142", "2024-12-05")
    assert notice_last_trade(save) == (date(2024, 11, 18), "notice_b_unconfirmed")


def test_notice_text_patterns_synthetic():
    mk = lambda text, rule="17 CFR 240.12d2-2(b)": Form25("a", "25-NSE", "2016-05-20", "NASDAQ", "Common Stock",
                                                        rule, text)
    assert notice_last_trade(mk("trading in the Companys securities would be suspended on May 19, 2016")) \
        == (date(2016, 5, 18), "notice_nasdaq")
    assert notice_last_trade(mk("suspended prior to the opening of trading on January 2, 2009")) \
        == (date(2008, 12, 31), "notice_open")
    assert notice_last_trade(mk("")) == (None, "")


def test_discovery_series_c():
    f = _load("discovery_series_c.txt", "0001354457-22-000231", "2022-04-08")
    assert f.exchange == "NASDAQ"
    assert class_label(f.class_text) == "SERIES C"
    refs = [SecurityRef("BBG_A", "CLASS A", "common"), SecurityRef("BBG_B", "CLASS B", "common"),
            SecurityRef("BBG_C", "CLASS C", "common")]
    assert match_security(f, refs) == ("BBG_C", "class C")


def test_match_rules():
    common = Form25("a", "25-NSE", "2018-11-29", "NYSE", "Common Stock", "", "")
    pref = Form25("b", "25-NSE", "2018-11-29", "NYSE", "6.375% Series A Preferred Stock", "", "")
    single = [SecurityRef("BBG1", "COMMON", "common")]
    assert match_security(common, single) == ("BBG1", "only security of its kind")
    assert match_security(pref, single) == (None, "no observed preferred security")
    two = [SecurityRef("A", "CLASS A", "common"), SecurityRef("C", "CLASS C", "common")]
    assert match_security(common, two) == (None, "ambiguous class")


def test_class_kind():
    assert class_kind("Common Stock, $.01 par value, and Associated Preferred Stock Purchase Rights") == "common"
    assert class_kind("Class A Common Stock") == "common"
    assert class_kind("Ordinary Shares") == "common"
    assert class_kind("American Depositary Shares") == "common"
    assert class_kind("Depositary Shares, each representing 1/1000th of a share of 6.00% Preferred Stock") == "preferred"
    assert class_kind("Units, each consisting of one share of Class A Common Stock and one-half of one Warrant") == "unit"
    assert class_kind("Warrants to purchase Common Stock") == "warrant"
    assert class_kind("6.125% Notes due 2060") == "debt"
    assert class_kind("iShares MSCI Brazil ETF") == "fund"
    assert class_kind("") == "other"


def test_class_kind_misreads():
    assert class_kind("Corporate Units") == "unit"
    assert class_kind("Equity Units") == "unit"
    assert class_kind("Tangible Equity Units") == "unit"
    assert class_kind("Stock Purchase Contracts") == "unit"
    assert class_kind("Redeemable warrants, each whole warrant exercisable for one share "
                      "of Class A common stock") == "warrant"
    assert class_kind("Capital Securities") == "preferred"
    assert class_kind("Trust Preferred Securities") == "preferred"
    assert class_kind("Trust Certificates") == "preferred"
    assert class_kind("American Depositary Shares, each representing one ordinary share") == "common"


def test_exchange_labels():
    assert exchange_label("NEW YORK STOCK EXCHANGE LLC") == "NYSE"
    assert exchange_label("NYSE American LLC") == "NYSE AMERICAN"
    assert exchange_label("NYSE MKT LLC") == "NYSE AMERICAN"
    assert exchange_label("NYSE Arca, Inc.") == "NYSE ARCA"
    assert exchange_label("The Nasdaq Stock Market LLC") == "NASDAQ"
    assert exchange_label("NASDAQ OMX BX, Inc.") == "BOSTON"
    assert exchange_label("Chicago Stock Exchange, Inc.") == "CHICAGO"
    assert exchange_label("Cboe BZX Exchange, Inc.") == "CBOE BZX"
    assert exchange_label("Pacific Exchange") == "PACIFIC"
    assert exchange_label("nothing here") == ""
    assert exchanges_named("New York Stock Exchange; Chicago Stock Exchange") == {"NYSE", "CHICAGO"}
    assert exchanges_named("NYSE Arca") == {"NYSE ARCA"}
    assert exchanges_named("The Nasdaq Stock Market LLC") == {"NASDAQ"}


def test_list_form25_and_effective_date():
    subs = [EdgarSubmission("x2", "25-NSE", "2020-01-02", "", "", "p"),
            EdgarSubmission("x1", "25", "2019-01-02", "", "", "p"),
            EdgarSubmission("x3", "8-K", "2019-01-02", "", "3.01", "p")]
    assert [s.accession for s in list_form25(subs)] == ["x1", "x2"]
    assert effective_date("2018-11-29") == "2018-12-09"
