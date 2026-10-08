from datetime import date
from pathlib import Path

from delist_detection.edgar import EdgarSubmission
from delist_detection.form25 import (
    Form25, SecurityRef, class_kind, class_label, exchange_label, exchanges_named,
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
    """Spec 8.8: an involuntary (b) notice's date is the decision day, to be
    confirmed by MIDAS or a halt, whatever its wording: RadioShack's "announcement
    ... at the close of the trading session on February 2, 2015 of the
    suspension" too."""
    rsh = _load("rsh_25nse.txt", "0000876661-15-000132", "2015-03-20")
    assert notice_last_trade(rsh) == (date(2015, 2, 2), "notice_b_unconfirmed")
    save = _load("save_25nse.txt", "0000876661-24-001142", "2024-12-05")
    assert notice_last_trade(save) == (date(2024, 11, 18), "notice_b_unconfirmed")


def test_notice_text_patterns_synthetic():
    mk = lambda text, rule="17 CFR 240.12d2-2(b)": Form25("a", "25-NSE", "2016-05-20", "NASDAQ", "Common Stock",
                                                        rule, text)
    nasdaq = "trading in the Companys securities would be suspended on May 19, 2016"
    opening = "suspended prior to the opening of trading on January 2, 2009"
    assert notice_last_trade(mk(nasdaq, "17 CFR 240.12d2-2(a)(3)")) == (date(2016, 5, 18), "notice_nasdaq")
    assert notice_last_trade(mk(opening, "17 CFR 240.12d2-2(a)(3)")) == (date(2008, 12, 31), "notice_open")
    # the same wordings on an involuntary (b) notice: same day, not confirmed
    assert notice_last_trade(mk(nasdaq)) == (date(2016, 5, 18), "notice_b_unconfirmed")
    assert notice_last_trade(mk(opening)) == (date(2008, 12, 31), "notice_b_unconfirmed")
    assert notice_last_trade(mk("the Common Stock was suspended from trading on May 19, 2016")) \
        == (date(2016, 5, 18), "notice_b_unconfirmed")
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


def test_list_form25():
    subs = [EdgarSubmission("x2", "25-NSE", "2020-01-02", "", "", "p"),
            EdgarSubmission("x1", "25", "2019-01-02", "", "", "p"),
            EdgarSubmission("x3", "8-K", "2019-01-02", "", "3.01", "p")]
    assert [s.accession for s in list_form25(subs)] == ["x1", "x2"]


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


def test_a_class_named_for_another_group_leaves_that_letters_siblings_untied():
    """The Series C of Liberty SiriusXM's Form 25 is not Formula One's or Liberty
    Live's Series C: neither is named by the class's words, so neither is tied;
    the letter-less SiriusXM line the words do name is."""
    f = Form25("a", "25-NSE", "2024-09-09", "NASDAQ",
               "Series A Liberty SiriusXM Common Stock (LSXMA), and Series C Liberty SiriusXM Common Stock (LSXMK)",
               "", "")
    refs = [SecurityRef("LSXMA", "CLASS A", "common", "LIBERTY MEDIA LIBERTY SIRIUSXM COR"),
            SecurityRef("LSXMK", "COMMON", "common", "LIBERTY MEDIA LIBERTY SIRIUSXM COR"),
            SecurityRef("FWONK", "CLASS C", "common", "LIBERTY MEDIA FORMULA ONE SERIES C"),
            SecurityRef("LLYVK", "CLASS C", "common", "LIBERTY MEDIA LIBERTY LIVE CORP SE")]
    assert match_securities(f, refs)[0] == ["LSXMA"]
    assert tied_securities(f, refs) == {"LSXMK"}


def test_a_letterless_sibling_no_class_names_is_not_tied():
    """U-Haul's 2022 Form 25 names its Series N non-voting stock, which matches;
    the voting common line has no letter, and no class's words name it."""
    f = Form25("a", "25", "2022-12-16", "NYSE",
               "Common Stock, par value $0.25 and Series N Non-Voting Common Stock, par value $0.001", "", "")
    refs = [SecurityRef("UHAL", "COMMON", "common", "U HAUL HOLDING"),
            SecurityRef("UHALB", "SERIES N", "common", "U HAUL NON VOTING SERIES N")]
    assert match_securities(f, refs)[0] == ["UHALB"]
    assert tied_securities(f, refs) == set()


# --- sub-plan 5b, R6b: a notice that says the class was acquired ---

import pytest  # noqa: E402

from delist_detection.form25 import notice_says_acquired  # noqa: E402
from tests import form25_cases as fc  # noqa: E402


@pytest.mark.parametrize("accession,acquired", [
    ("0000876661-10-000366", True),    # NTY 2010: "converted into the right to receive $55.00 in cash"
    ("0001354457-07-000287", True),    # BMET 2007: "Acquired by LVB Acquisition Inc"
    ("0000876661-15-000665", False),   # HUB-B 2015: "the reclassification of ... dual-class common stock"
    ("0000876661-23-000651", False),   # HHC 2023: "the formation of a holding company ... one share"
    ("0001354457-21-000304", False),   # APA 2021: "APACHE CORPORATION REORGANIZED AS APA CORPORATION"
    ("0001354457-15-000245", False),   # CMCSK 2015: no notice text
], ids=["NTY", "BMET", "HUB-B", "HHC", "APA", "CMCSK"])
def test_a_real_notice_says_the_class_was_acquired_only_without_a_reorganization(accession, acquired):
    f = parse_form25(fc.EDGAR["raws"][accession], accession=accession, form="25-NSE", filing_date="2000-01-01")
    assert notice_says_acquired(f) is acquired


# --- sub-plan 5b, R3: a Form 25 about another class ---

from delist_detection.form25 import other_class  # noqa: E402

LIBERTY_2011 = ("Series A Liberty Capital Common Stock, Series B Liberty Capital Common Stock, Liberty Starz Ser A "
                "Common Stock, Liberty Starz Ser B Common Stock")
LIBERTY_NAMES = ("QVC Group, Inc.", "Qurate Retail, Inc.", "Liberty Interactive Corp", "LIBERTY MEDIA CORP",
                 "Liberty Media Holding CORP")


def test_a_form25_of_other_tracking_groups_is_not_about_the_series_a_of_another():
    """Liberty Media's 2011 25-NSE removed the Liberty Capital and Liberty Starz groups; the Series A placeholder
    of Liberty Interactive (later Qurate) kept trading."""
    f = Form25("a", "25-NSE", "2011-09-23", "NASDAQ", LIBERTY_2011, "", "")
    ref = SecurityRef("CIK1355096-SERIES-A", "SERIES A", "common", "QURATE RETAIL GROUP CORP SERIES A")
    assert other_class(f, ref, LIBERTY_NAMES) == "names another group (CAPITAL)"


@pytest.mark.parametrize("class_text,name", [
    ("Series A Liberty Ventures Common Stock & Series B Liberty Ventures Common Stock",
     "LIBERTY INTERACTIVE VENTURE CORP S"),                                      # LVNTA 2018: VENTURE, VENTURES
    ("Class A Special Common Stock", "COMCAST SPECIAL CORP CLASS A"),             # CMCSK 2015: SPECIAL is no group
    ("Series N Non-Voting Common Stock", "U HAUL NON VOTING SERIES N"),           # U-Haul 2022
    ("Series A Liberty SiriusXM Common Stock", "LIBERTY MEDIA LIBERTY SIRIUSXM COR"),
    ("Common Stock", "BIOMET INC"),
], ids=["LVNTA", "CMCSK", "UHALB", "LSXMA", "plain"])
def test_a_form25_of_the_securitys_own_group_or_of_no_group_is_its_own(class_text, name):
    f = Form25("a", "25-NSE", "2018-03-09", "NASDAQ", class_text, "", "")
    assert other_class(f, SecurityRef("S", "SERIES A", "common", name), LIBERTY_NAMES) == ""


def test_a_form25_that_relates_solely_to_the_rights_is_not_about_the_common():
    """Biomet 2006 (0001104659-06-082100): "Common Shares; Preferred Share Purchase Rights", and the notification
    "relates solely to the withdrawal from listing of the Preferred Share Purchase Rights"."""
    raw = fc.EDGAR["raws"]["0001104659-06-082100"]
    f = parse_form25(raw, accession="0001104659-06-082100", form="25", filing_date="2006-12-18")
    assert (f.class_text, f.solely) == ("Common Shares; Preferred Share Purchase Rights",
                                        "Preferred Share Purchase Rights")
    assert other_class(f, SecurityRef("CIK351346-COMMON", "COMMON", "common", "BIOMET INC")) == \
        "relates solely to Preferred Share Purchase Rights"


# --- sub-plan 5b, R2: a letterless common takes the letter its own fails descriptions name ---

SUNPOWER_2011 = Form25("a", "25-NSE", "2011-11-16", "NASDAQ", "Common Stock Class A & Common Stock Class B", "", "")


def test_a_class_no_siblings_share_class_carries_goes_to_the_letterless_one_its_fails_name():
    """SunPower 2011: the class A placeholder ("SUNPOWER CORP CL A") and the recombined SPWR line, both letterless;
    without the hint the 25-NSE ties them."""
    refs = [SecurityRef("CIK867773-COMMON", "COMMON", "common", "SUNPOWER CORP", "A"),
            SecurityRef("BBG000FVQ185", "COMMON", "common", "SUNPOWER CORP.")]
    assert match_securities(SUNPOWER_2011, refs) == (["CIK867773-COMMON"], "class A")
    no_hint = [SecurityRef(r.sec_id, r.share_class, r.kind, r.name) for r in refs]
    assert match_securities(SUNPOWER_2011, no_hint) == ([], "ambiguous class")


def test_a_hint_never_competes_with_a_share_class_that_carries_the_letter():
    """LVNTA 2018: the duplicate placeholder's fails say SER A too; LVNTA's own Series A takes the Form 25."""
    f = Form25("a", "25-NSE", "2018-03-09", "NASDAQ",
               "Series A Liberty Ventures Common Stock & Series B Liberty Ventures Common Stock", "", "")
    refs = [SecurityRef("BBG0038K9G41", "SERIES A", "common", "LIBERTY INTERACTIVE VENTURE CORP S"),
            SecurityRef("CIK1355096-COMMON", "COMMON", "common", "LIBERTY INTERACTIVE VENTURE CORP S", "A"),
            SecurityRef("BBG000PCQQL6", "SERIES A", "common", "QURATE RETAIL INC SERIES A")]
    assert match_securities(f, refs)[0] == ["BBG0038K9G41"]


def test_two_letterless_siblings_both_hinted_the_letter_stay_tied():
    """Review Focus (R2): a FIGI line and a placeholder of one class A, both letterless and both "CL A" in their
    fails: the hint cannot tell them apart, so the Form 25 stays ambiguous, as before."""
    refs = [SecurityRef("BBG_A", "COMMON", "common", "SUNPOWER CORP", "A"),
            SecurityRef("CIK_A", "COMMON", "common", "SUNPOWER CORP", "A")]
    assert match_securities(SUNPOWER_2011, refs) == ([], "ambiguous class")
    assert tied_securities(SUNPOWER_2011, refs) == {"BBG_A", "CIK_A"}


@pytest.mark.parametrize("class_text,solely", [
    ("Common Stock and Warrants", "Common Stock and Warrants"),
    ("Class A Common Stock and Warrants", "Class A Common Stock and Warrants"),
])
def test_a_spac_form25_solely_about_common_and_warrants_is_the_commons(class_text, solely):
    f = Form25("a", "25-NSE", "2022-01-03", "NASDAQ", class_text, "", "", solely)
    assert other_class(f, SecurityRef("S", "COMMON", "common", "SOME ACQUISITION CORP")) == ""


@pytest.mark.parametrize("class_text", [
    "Class A Subordinate Voting Common Stock", "Class A Convertible Common Stock",
    "Series A Non-Voting Common Stock",
])
def test_a_generic_class_descriptor_is_no_tracking_group(class_text):
    f = Form25("a", "25-NSE", "2022-01-03", "NASDAQ", class_text, "", "")
    assert other_class(f, SecurityRef("S", "CLASS A", "common", "SOME CORP CLASS A"), ("Some Corp",)) == ""


def test_a_class_expiry_outside_the_removal_window_is_no_last_trade():
    """Roivant 2023: a Form 25 signed 2023-09-01 for "Warrant expiring 09/30/2026": no last trade."""
    f = Form25("0001354457-23-000619", "25-NSE", "2023-09-01", "NASDAQ", "Warrant expiring 09/30/2026",
               "17 CFR 240.12d2-2(a)(2)", "")
    assert notice_last_trade(f) == (None, "")
    early = Form25("a", "25-NSE", "2021-05-03", "NYSE", "Warrants expiring May 3, 2020", "", "")
    assert notice_last_trade(early) == (None, "")


NYSE_B_NOTICE = ("3. Pursuant to the above authorization, a press release was issued on {press} and an announcement "
                 "was made on the 'ticker' of the Exchange at the close of the trading session on {press} of the "
                 "suspension of trading in the Common Stock.{open}")


def test_the_nyse_b_template_press_day_is_no_last_trade():
    """TMA, IDARQ 2008: "an announcement was made on the 'ticker' of the Exchange at the close of the trading
    session on D" gives the press day D, never a last trade; a stated opening ("before the opening of the trading
    session on D2") is read, a bare template reads nothing."""
    base = dict(accession="a", form="25-NSE", filing_date="2009-01-15", exchange="NYSE",
                class_text="Common Stock", rule="17 CFR 240.12d2-2(b)(1)")
    bare = Form25(**base, notice_text=NYSE_B_NOTICE.format(press="December 1, 2008", open=""))
    assert notice_last_trade(bare) == (None, "")
    opened = Form25(**base, notice_text=NYSE_B_NOTICE.format(
        press="December 1, 2008", open=" Trading was suspended before the opening of the trading session on "
                                       "December 5, 2008."))
    assert notice_last_trade(opened) == (date(2008, 12, 4), "notice_b_unconfirmed")


def test_a_rights_class_expiring_on_a_day_last_traded_that_day():
    """TMUSR 2020 (5d): Nasdaq's 25-NSE for "Subscription Rights Expiring 7/27/2020" carries an empty notice; the
    class text dates the expiry, the rights' last trading day (operator ruling of the 5b pre-check)."""
    f = Form25("0001354457-20-000356", "25-NSE", "2020-07-27", "NASDAQ", "Subscription Rights Expiring 7/27/2020",
               "17 CFR 240.12d2-2(a)(2)", "2 form25.txt form25")
    assert notice_last_trade(f) == (date(2020, 7, 27), "notice_expiry")
    warrants = Form25("a", "25-NSE", "2021-05-03", "NYSE", "Warrants expiring May 3, 2021", "", "")
    assert notice_last_trade(warrants) == (date(2021, 5, 3), "notice_expiry")
    # a common stock's text never dates an expiry; a notice's own day wins over the class text
    assert notice_last_trade(Form25("a", "25-NSE", "2020-07-27", "NASDAQ", "Common Stock", "", "")) == (None, "")
    stated = Form25("a", "25-NSE", "2020-07-27", "NASDAQ", "Rights Expiring 7/27/2020", "17 CFR 240.12d2-2(a)(3)",
                    "the security was suspended from trading on July 24, 2020")
    assert notice_last_trade(stated) == (date(2020, 7, 23), "notice_a")
