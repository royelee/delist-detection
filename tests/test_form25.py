from datetime import date
from pathlib import Path

from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import (
    Form25, SecurityRef, class_kind, class_label, effective_date, exchange_label, exchanges_named,
    list_form25, match_securities, match_security, notice_last_trade, parse_form25, tied_securities,
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


def test_class_kind_depositary_preference_shares():
    assert class_kind("Depositary Shares, each representing a 1/1,000th interest in a 5.750% "
                      "Series F Preference Share") == "preferred"
    assert class_kind("Depositary Shares, each representing a 1/1,000th interest in a share of "
                      "5.625% Perpetual Non-Cumulative Preference Shares") == "preferred"
    assert class_kind("Series A Preference Shares") == "preferred"
    assert class_kind("American Depositary Shares, each representing one ordinary share") == "common"


def test_class_kind_ownership_units_are_common():
    assert class_kind("Class A Units representing limited liability company interests") == "common"
    assert class_kind("Common Units Representing Limited Partner Interests") == "common"
    assert class_kind("Depositary Units Representing Limited Partner Interests") == "common"
    assert class_kind("Trust Units") == "common"
    assert class_kind("Units, each consisting of one share of Class A common stock and one-half "
                      "of one redeemable warrant") == "unit"
    assert class_kind("Corporate Units") == "unit"


def test_class_kind_warrants_named_after_common():
    assert class_kind("Common Stock Purchase Warrants") == "warrant"
    assert class_kind("Redeemable warrants included as part of the units, each exercisable for "
                      "one share of Class A common stock") == "warrant"
    assert class_kind("Common Stock, $0.01 par value, and associated Preferred Stock Purchase "
                      "Rights") == "common"


def test_class_label_only_from_the_securitys_own_segment():
    assert class_label("Common Stock, par value $0.01 per share, and associated Series A Junior "
                       "Participating Preferred Stock Purchase Rights") is None
    assert class_label("Series A Liberty SiriusXM Common Stock, par value $0.01") == "SERIES A"
    assert class_label("Class B Common Stock") == "CLASS B"
    assert class_label("Preferred Stock, Series C") == "SERIES C"
    assert class_label("5.750% Cumulative Preferred Stock, Series F") == "SERIES F"
    assert class_label("Depositary Shares, each representing a 1/1,000th interest in a share of "
                       "5.750% Series F Preference Share") == "SERIES F"
    assert class_label("6.375% Series A Preferred Stock") == "SERIES A"
    assert class_label("Class A Common Stock and associated Series B Preferred Stock Purchase "
                       "Rights") == "CLASS A"


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


def _load_text(name, accession, filing_date):
    return parse_form25((FIX / name).read_text(encoding="utf-8", errors="replace"),
                        accession=accession, form="25", filing_date=filing_date)


def test_issuer_filed_text_form25_reads_the_class_above_its_caption():
    """An issuer-filed Form 25 is an HTML cover with no XML: the class is the
    text right above "(Description of class of securities)", not what follows
    "...to strike the class of securities from listing and registration:" (the
    rule checkboxes, which the old reading returned as '☐ 17 CFR 240')."""
    aep = _load_text("aep_units_common_25.txt", "0000004904-20-000077", "2020-09-30")
    assert aep.exchange == "NYSE"
    assert aep.class_text.startswith("Common Stock, $6.50 par value")
    assert class_kind(aep.class_text) == "common"                 # AEP moved to Nasdaq in 2020
    aapl = _load_text("aapl_notes_25.txt", "0001193125-19-074874", "2019-03-14")
    assert aapl.class_text.startswith("1.000% Notes due 2022") and class_kind(aapl.class_text) == "debt"
    gme = _load_text("gme_rights_25.txt", "0001445305-14-004535", "2014-10-29")
    assert gme.class_text == "Preferred Stock Purchase Rights"


def test_class_kind_rights_plans_are_rights_not_preferred():
    """A rights plan names the preferred stock its rights buy, but the class
    withdrawn is the rights (GameStop's 2014 Form 25; Cheniere's)."""
    gme = _load_text("gme_rights_25.txt", "0001445305-14-004535", "2014-10-29")
    assert class_kind(gme.class_text) == "right"
    assert class_kind("Rights to Purchase Series A Junior Participating Preferred Stock") == "right"
    assert class_kind("Series A Junior Participating Preferred Stock Purchase Rights") == "right"
    assert class_kind("Series B Convertible Perpetual Preferred Stock") == "preferred"
    assert class_kind("Common Stock, par value $0.10 per share; Stock Purchase Rights") == "common"
    assert class_kind("Common Stock, $0.01 par value, and associated Preferred Stock Purchase "
                      "Rights") == "common"


def test_notice_wordings_before_market_open_and_suspended_by_the_exchange():
    """Real NYSE-family wordings the notice reader missed: "suspended from
    trading before market open on August 27, 2026" (Leggett & Platt; 43 cached
    notices say it this way) and "The security was suspended by the Exchange on
    June 27, 2011" (Wesco, NYSE Amex; 97 cached notices)."""
    leg = _load("leg_25nse_before_market_open.txt", "0000876661-26-000712", "2026-08-27")
    assert notice_last_trade(leg) == (date(2026, 8, 26), "notice_open")
    wsc = _load("wsc_25nse_suspended_by_exchange.txt", "0001143313-11-000058", "2011-06-27")
    assert notice_last_trade(wsc) == (date(2011, 6, 24), "notice_a")


def test_notice_market_open_and_close_variants_synthetic():
    mk = lambda text: Form25("a", "25-NSE", "2016-05-20", "NYSE", "Common Stock", "17 CFR 240.12d2-2(a)(3)", text)
    assert notice_last_trade(mk("this security was suspended from trading prior to market open on May 19, 2016")) \
        == (date(2016, 5, 18), "notice_open")
    assert notice_last_trade(mk("this security was suspended from trading after market close on May 19, 2016")) \
        == (date(2016, 5, 19), "notice_close")
    assert notice_last_trade(mk("suspended from trading before the opening on May 19, 2016")) \
        == (date(2016, 5, 18), "notice_open")


def test_edgars_bare_cboe_exchange_string_is_cboe_bzx():
    """EDGAR's submissions list Cboe Global Markets (CIK 1374310) on exchange
    "CBOE": its own shares trade on Cboe BZX. Only the bare string maps; a
    Cboe options-exchange entity name does not."""
    assert exchange_label("CBOE") == "CBOE BZX"
    assert exchange_label("Cboe") == "CBOE BZX"
    assert exchange_label("CBOE BZX") == "CBOE BZX" and exchange_label("BATS") == "CBOE BZX"
    assert exchange_label("Cboe Exchange, Inc.") == ""


LIBERTY_LIVE_CLASSES = ("Liberty Media Corporation Series A Liberty Live Common Stock & \t"
                        "Liberty Media Corporation Series C Liberty Live Common Stock")


def _liberty_refs():
    return [SecurityRef("LLYVA", "CLASS A", "common", "LIBERTY MEDIA LIBERTY LIVE CORP SE"),
            SecurityRef("LLYVK", "CLASS C", "common", "LIBERTY MEDIA LIBERTY LIVE CORP SE"),
            SecurityRef("FWONA", "CLASS A", "common", "LIBERTY MEDIA FORMULA ONE SERIES A"),
            SecurityRef("FWONK", "CLASS C", "common", "LIBERTY MEDIA FORMULA ONE SERIES C")]


def test_a_tracking_stock_form25_matches_each_named_class_by_its_group_name():
    """Liberty Media's 2025 Liberty Live split-off: one Form 25 names Series A
    and Series C Liberty Live Common Stock while the Formula One group's Series
    A and C (same issuer, same letters) keep trading. Each named class matches
    the sibling of its letter whose name carries that class's own words."""
    f = Form25("a", "25-NSE", "2025-12-15", "NASDAQ", LIBERTY_LIVE_CLASSES, "", "")
    assert match_securities(f, _liberty_refs()) == (["LLYVA", "LLYVK"], "class A, C by name")


def test_same_letter_siblings_with_no_distinguishing_name_stay_ambiguous():
    f = Form25("a", "25-NSE", "2025-12-15", "NASDAQ", "Series A Common Stock", "", "")
    refs = [SecurityRef("X1", "CLASS A", "common", "LIBERTY MEDIA CORP"),
            SecurityRef("X2", "CLASS A", "common", "LIBERTY MEDIA CORP")]
    assert match_securities(f, refs) == ([], "ambiguous class")
    assert match_security(f, refs) == (None, "ambiguous class")


def test_a_form25_naming_several_classes_matches_each_of_them():
    f = Form25("a", "25-NSE", "2020-01-02", "NYSE", "Class A Common Stock; Class B Common Stock", "", "")
    refs = [SecurityRef("A", "CLASS A", "common"), SecurityRef("B", "CLASS B", "common"),
            SecurityRef("C", "CLASS C", "common")]
    assert match_securities(f, refs) == (["A", "B"], "class A, B")


def test_a_sibling_with_no_class_letter_is_left_tied_when_the_form25_names_letters():
    """Liberty SiriusXM's 2024 Form 25 names Series A, B and C. Series A matches
    its line by name; the Series C line's FIGI name carries no letter, so it
    cannot be matched, and it is reported as tied (to review) rather than as a
    security the Form 25 is not about."""
    f = Form25("a", "25-NSE", "2024-09-09", "NASDAQ",
               "Series A Liberty SiriusXM Common Stock (LSXMA), Series B Liberty SiriusXM Common Stock (LSXMB), "
               "and Series C Liberty SiriusXM Common Stock (LSXMK)", "", "")
    refs = [SecurityRef("LSXMA", "CLASS A", "common", "LIBERTY MEDIA LIBERTY SIRIUSXM COR"),
            SecurityRef("LSXMK", "COMMON", "common", "LIBERTY MEDIA LIBERTY SIRIUSXM COR"),
            SecurityRef("FWONA", "CLASS A", "common", "LIBERTY MEDIA FORMULA ONE SERIES A")]
    assert match_securities(f, refs) == (["LSXMA"], "class A by name")
    assert tied_securities(f, refs) == {"LSXMK"}
