"""exchange_terms: what a filing says the registrant's own shares became (sub-plan 5c, ruling R1). The real cases
read their texts from tests/fixtures/issuer_role/ (built once from the local caches)."""
from __future__ import annotations

from datetime import date

import pytest

from delist_detection import exchange_terms as X
from delist_detection.form25 import parse_form25
from tests import issuer_role_cases as ic


def _text(acc: str) -> str:
    if acc in ic.EDGAR["raws"]:
        return parse_form25(ic.EDGAR["raws"][acc], accession=acc, form="25-NSE", filing_date="2000-01-01").notice_text
    return ic.EDGAR["texts"][acc]


# case -> (texts, the registrant's names before the event, class letter, class words) and what own_exchange reads:
# (ratio, cash, ambiguous, target letter, target names the registrant, a name the target carries, special dividends)
REAL = {
    "BHI": ((["0001193125-17-220863", "0000876661-17-000381"], ["BAKER HUGHES INC"], "", ()),
            (1.0, False, False, "A", False, "BHGE", (17.5,))),
    "HHC": ((["0001104659-23-090461"], ["Howard Hughes Corp"], "", ()),
            (1.0, False, False, "", False, "Howard Hughes Holdings Inc.", ())),
    "CMCSK": ((["0000950103-15-009516"], ["COMCAST CORP", "COMCAST SPECIAL CORP CLASS A"], "A", ("SPECIAL",)),
              (1.0, False, False, "A", True, None, ())),
    "HUB-B": ((["0001193125-15-412174"], ["HUBBELL INC", "HUBBELL INC. CL B"], "B", ()),
              (1.0, False, False, "", True, None, ())),
    "CWENA": ((["0001104659-26-053557"], ["Clearway Energy, Inc."], "A", ()),
              (1.0, False, False, "C", True, None, ())),
    "DISCA": ((["0001193125-22-103051"], ["Discovery, Inc."], "A", ()), (1.0, False, False, "", False, "WBD", ())),
    "DISCK": ((["0001193125-22-103051"], ["Discovery, Inc."], "C", ()), (1.0, False, False, "", False, "WBD", ())),
    "MYL": ((["0001193125-20-298224"], ["Mylan N.V."], "", ()), (1.0, False, False, "", False, "Viatris", ())),
    "SBGI": ((["0001193125-23-158935"], ["SINCLAIR BROADCAST GROUP INC"], "A", ()),
             (1.0, False, False, "A", False, "Sinclair, Inc.", ())),
    "WAG": ((["0001193125-14-457669"], ["WALGREEN CO"], "", ()), (1.0, False, False, "", False, "WBA", ())),
    "DTV": ((["0001104659-09-066017"], ["DIRECTV GROUP INC"], "", ()), (1.0, False, False, "A", False, "DIRECTV", ())),
    "ROVI": ((["0001193125-16-704222"], ["Rovi Corp"], "", ()),
             (1.0, False, False, "", False, "Titan Technologies Corporation", ())),
    "OKE": ((["0000876661-26-000770"], ["ONEOK INC /NEW/"], "", ()), (1.0, False, False, "", False, None, ())),
    "LLYVA": ((["0001104659-25-121236"], ["Liberty Media Corp"], "A", ()),
              (1.0, False, False, "A", False, "Liberty Live Holdings", ())),
    "DOW": ((["0001193125-17-274845"], ["DOW CHEMICAL CO /DE/"], "", ()),
            (1.0, False, False, "", False, "DowDuPont", ())),
    "KRFT": ((["0001193125-15-244355"], ["Kraft Foods Group, Inc."], "", ()),
             (1.0, False, False, "", False, "The Kraft Heinz Company", (16.5,))),
    "CCO": ((["0001193125-19-135029"], ["Clear Channel Outdoor Holdings, Inc."], "A", ()),
            (1.0, False, False, "", True, None, ())),
    "FCL": ((["0000950123-09-028243"], ["Foundation Coal Holdings, Inc."], "", ()),
            (1.084, False, False, "", False, None, ())),
    "CHTR": ((["0001193125-16-596195"], ["CHARTER COMMUNICATIONS, INC. /MO/"], "A", ()),
             (0.9042, False, False, "A", False, None, ())),
    "SIRI": ((["0001104659-24-098260"], ["SIRIUS XM HOLDINGS INC."], "", ()), (0.1, False, False, "", False, None, ())),
}


@pytest.mark.parametrize("case", sorted(REAL))
def test_a_real_filing_says_what_the_securitys_own_shares_became(case):
    (accs, names, letter, words), (ratio, cash, ambiguous, target_letter, target_own, name, dividends) = REAL[case]
    own = X.own_exchange([_text(a) for a in accs], names=names, class_letter=letter, class_words=words)
    assert own is not None
    assert (own.ratio, own.cash, own.ambiguous, own.target_letter, own.target_own, own.special_dividends) == (
        ratio, cash, ambiguous, target_letter, target_own, dividends)
    if name is not None:
        assert name in own.target_names
    assert own.one_for_one is (ratio == 1.0 and not cash and not ambiguous)


def test_another_partys_ratio_beside_the_own_one_is_not_read_as_the_securitys():
    """DOW 2017: DuPont's 1.2820 is in the same 8-K; DTV 2009: LEI's 1.11130; SIRI 2024: Liberty Media's 0.8375."""
    for acc, names in (("0001193125-17-274845", ["DOW CHEMICAL CO /DE/"]), ("0001104659-09-066017", ["DIRECTV GROUP INC"]),
                       ("0001104659-24-098260", ["SIRIUS XM HOLDINGS INC."])):
        ratios = {st.ratio for st in X.own_statements([_text(acc)], names=names, class_letter="")}
        assert ratios <= {1.0, 0.1}, (acc, ratios)


def test_a_multi_step_deals_intermediate_one_for_one_is_read_but_the_llm_decides():
    """JEF 2013: Jefferies became New Jefferies one for one before the 0.81 Leucadia exchange; the reader reads the
    one-for-one (stage 8b needs the LLM's terms to agree, and they say 0.81)."""
    own = X.own_exchange([_text("0001193125-13-087969")], names=["JEFFERIES GROUP INC /DE/"], class_letter="")
    assert own is not None and own.one_for_one


@pytest.mark.parametrize("acc,names,expected", [
    ("0000950123-10-111604", ["RRI ENERGY INC"], "Mirant"),
    ("0001193125-12-296100", ["SXC Health Solutions Corp."], "Catalyst"),
    ("0001193125-14-450724", ["FOREST OIL CORP"], "issued an aggregate of 79,241,916"),
], ids=["RRI", "SXCI", "FST"])
def test_an_acquirer_whose_own_shares_were_not_exchanged(acc, names, expected):
    texts = [_text(acc)]
    assert X.own_exchange(texts, names=names, class_letter=None) is None
    assert expected in X.acquires(texts, names=names)


def test_a_distributor_whose_holders_kept_their_shares():
    """News Corp 2013: one new News Corp share for every four of the Company's, kept: a distribution, no exchange."""
    texts = [_text("0001193125-13-281456")]
    assert X.own_exchange(texts, names=["NEWS CORP"], class_letter=None) is None
    assert "for every four shares" in X.distributes(texts, names=["NEWS CORP"])


def test_a_target_is_no_acquirer_and_a_new_company_named_like_it_is_another():
    """'New Lionsgate' is another company than the registrant 'Old Lionsgate'; a target's own exchange stops the
    role reading (CCO's 'Old CCOH' is the registrant)."""
    text = ('Legacy LG Studios shareholders received, in exchange for each LG Studios common share they held, '
            'one New Lionsgate Common Share.')
    assert X.acquires([text], names=["LIONS GATE ENTERTAINMENT CORP"]) == ""
    cco = [_text("0001193125-19-135029")]
    assert X.own_exchange(cco, names=["Clear Channel Outdoor Holdings, Inc."], class_letter=None) is not None


@pytest.mark.parametrize("sentence,ratio,cash", [
    ("Each outstanding share of the Company's common stock was converted into the right to receive one share of "
     "common stock of Holdco and $10.00 in cash.", 1.0, True),
    ("Each outstanding share of the Company's common stock was converted into one share of Holdco common stock, "
     "par value $0.01 per share, with cash paid in lieu of fractional shares.", 1.0, False),
    ("Each share of the Company's common stock was converted into one (1) share of Holdco common stock and a "
     "special cash dividend of $2.50 per share.", 1.0, False),
    ("Each share of the Company's common stock was converted into 1.2500 shares of Parent common stock.", 1.25, False),
    ("Each share of the Company's common stock was exchanged on a one-for-one basis for an equivalent share of "
     "Holdco common stock.", 1.0, False),
    ("Each share of the Company's common stock converted into an equal number of shares of Holdco common stock.",
     1.0, False),
], ids=["cash", "par-and-lieu", "special-dividend", "ratio", "basis", "equal-number"])
def test_the_consideration_of_a_sentence(sentence, ratio, cash):
    own = X.own_exchange([sentence], names=["Acme Corp"], class_letter="")
    assert own is not None and (own.ratio, own.cash) == (ratio, cash)


def test_another_class_or_a_merger_subs_shares_are_not_the_securitys():
    text = ("Each share of Merger Sub common stock was converted into one share of the surviving corporation. Each "
            "share of the Company's Class B common stock was converted into one share of Holdco Class B common stock.")
    assert X.own_exchange([text], names=["Acme Corp"], class_letter="A") is None
    assert X.own_exchange([text], names=["Acme Corp"], class_letter="B").target_letter == "B"


def test_two_own_readings_that_disagree_are_ambiguous():
    texts = ["Each share of the Company's common stock was converted into one share of Holdco common stock.",
             "Each share of the Company's common stock was converted into 0.81 shares of Parent common stock."]
    own = X.own_exchange(texts, names=["Acme Corp"], class_letter="")
    assert own is not None and own.ambiguous and not own.one_for_one


def test_cash_paid_only_for_another_class_is_not_the_securitys():
    """Hubbell 2015: $28.00 for each Class A share; Class B got one new share and no cash."""
    hub = [_text("0001193125-15-412174")]
    assert X.own_exchange(hub, names=["HUBBELL INC"], class_letter="B").cash is False
    assert X.own_exchange(hub, names=["HUBBELL INC"], class_letter="A").cash is True


def test_the_registrants_names_are_read_from_before_the_event():
    """Schering-Plough became "Merck & Co." the day of the merger: before it, it is read by its old name."""
    sub = {"name": "MERCK & CO., INC.", "formerNames": [{"name": "SCHERING PLOUGH CORP", "from": "1994-01-01",
                                                          "to": "2009-11-03"}]}
    assert X.registrant_names(sub, date(2009, 11, 4), "SCHERING PLOUGH CORP") == ["SCHERING PLOUGH CORP",
                                                                                  "SCHERING PLOUGH CORP"]
    assert X.class_of("CLASS A", "COMCAST SPECIAL CORP CLASS A") == ("A", ("SPECIAL",))
    assert X.class_of("COMMON", "ONEOK INC") == ("", ())


def test_read_texts_reads_the_8ks_around_each_day_and_the_notice():
    edgar = ic.FixtureEdgar()
    filings = edgar.recent_filings(1039684)
    raw = ic.EDGAR["raws"]["0000876661-26-000770"]
    f25 = parse_form25(raw, accession="0000876661-26-000770", form="25-NSE", filing_date="2026-09-18")
    texts = X.read_texts(edgar, 1039684, filings, [date(2026, 9, 9)], f25)
    assert "0001193125-26-387972" in edgar.texts_read and texts[-1] == f25.notice_text


def test_a_cash_take_private_whose_insiders_rolled_over_is_a_target_not_an_acquirer():
    """Continental Resources 2022: the public shares got $74.28 in cash; the Hamm family's rollover shares became
    the surviving company's. Its own exchange is a cash one, and no other party's shares became the registrant's."""
    text = ("Each share of common stock of the Company issued and outstanding (other than the Rollover Shares) was "
            "converted into the right to receive $74.28 in cash. Also at the Effective Time, the Rollover Shares "
            "owned by the Hamm Family were converted into an identical number of newly issued shares of the Company, "
            "as the surviving corporation.")
    own = X.own_exchange([text], names=["CONTINENTAL RESOURCES INC"], class_letter=None)
    assert own is not None and (own.ratio, own.cash, own.one_for_one) == (0.0, True, False)
    assert X.acquires([text], names=["CONTINENTAL RESOURCES INC"]) == ""
