from datetime import date

from delist_detection.evidence import name_at, names_near

SUB = {"name": "SunPower Inc.", "formerNames": [
    {"name": "Complete Solaria, Inc.", "from": "2023-03-10T05:00:00.000Z", "to": "2025-09-26T04:00:00.000Z"},
    {"name": "Freedom Acquisition I Corp.", "from": "2021-01-08T05:00:00.000Z", "to": "2023-07-20T04:00:00.000Z"},
]}
AVANOS = {"name": "AVANOS MEDICAL, INC.", "formerNames": [
    {"name": "Halyard Health, Inc.", "from": "2014-06-02T04:00:00.000Z", "to": "2018-06-28T04:00:00.000Z"}]}


def test_name_at_uses_the_former_name_covering_the_date():
    assert name_at(SUB, date(2024, 8, 20)) == "Complete Solaria, Inc."
    assert name_at(SUB, date(2026, 1, 1)) == "SunPower Inc."


def test_names_near_includes_a_name_that_ended_just_before_the_date():
    # EDGAR ends "Halyard Health" on 2018-06-28; the vendor's last HYH row is 2018-06-29.
    assert names_near(AVANOS, date(2018, 6, 29)) == ["Halyard Health, Inc.", "AVANOS MEDICAL, INC."]
    assert names_near(SUB, date(2024, 8, 20)) == ["Complete Solaria, Inc."]
    assert names_near({"name": "Solo Co", "formerNames": []}, date(2020, 1, 1)) == ["Solo Co"]


from delist_detection.edgar import EdgarSubmission
from delist_detection.evidence import bankruptcy_8ks, mentions_bankruptcy


def _8k(d, items, acc="A"):
    return EdgarSubmission(accession=acc, form="8-K", filing_date=d, report_date=d, items=items, primary_doc="x.htm")


def test_bankruptcy_8ks_window():
    fs = [_8k("2020-09-30", "1.01,1.03"), _8k("2018-01-01", "1.03", "B"), _8k("2020-11-20", "3.03,5.01", "C")]
    assert [f.accession for f in bankruptcy_8ks(fs, date(2020, 11, 20))] == ["A"]


def test_mentions_bankruptcy():
    assert mentions_bankruptcy("filed voluntary petitions under chapter 11 of title 11")
    assert not mentions_bankruptcy("completion of the merger with CSG")


from delist_detection.evidence import item_text, renamed_near, says_listing_transfer, still_operating

LC_SUB = {"name": "Happen, Inc.", "formerNames": [
    {"name": "LendingClub Corp", "from": "2007-08-15T04:00:00.000Z", "to": "2026-06-18T04:00:00.000Z"}]}


def test_renamed_near():
    assert renamed_near(LC_SUB, date(2026, 6, 1)) == "LendingClub Corp"
    assert renamed_near(LC_SUB, date(2025, 1, 1)) is None


def test_still_operating_needs_results_and_no_form15():
    fs = [_8k("2026-07-27", "2.02,9.01")]
    assert still_operating(fs, date(2026, 6, 1))
    fs.append(EdgarSubmission("F", "15-12G", "2026-07-13", "", "", "f.htm"))
    assert not still_operating(fs, date(2026, 6, 1))


def test_listing_transfer_text():
    t = ("Item 3.01 Notice of Delisting ... notified the NYSE of its intention to voluntarily "
         "withdraw the listing of its common stock from the NYSE and transfer the listing to Nasdaq")
    assert says_listing_transfer(item_text(t, "3.01"))
    assert not says_listing_transfer("Item 3.01 ... did not regain compliance with the minimum bid price")
    assert says_listing_transfer("the Company transferred its listing to NYSE American")


from delist_detection.evidence import is_spac


def test_is_spac_by_sic_or_name_at_the_date():
    assert is_spac({"sic": "6770", "name": "Blue Whale Acquisition Corp I"}, date(2023, 8, 11))
    assert is_spac({"sic": "6199", "name": "Far Peak Acquisition Corp"}, date(2023, 2, 1))
    desp = {"sic": "3711", "name": "Lucid Group", "formerNames": [
        {"name": "Churchill Capital Corp IV", "from": "2020-04-30T00:00:00.000Z", "to": "2021-07-23T00:00:00.000Z"}]}
    assert not is_spac(desp, date(2024, 1, 1))


def test_is_spac_a_stale_sic_after_a_completed_rename_is_not_a_spac():
    """A de-SPAC whose EDGAR SIC was never updated from 6770 must not read as
    a SPAC once its rename has completed: the SIC test alone would pre-empt
    a later real merger or compliance failure under the same CIK."""
    desp = {"sic": "6770", "name": "Lucid Group", "formerNames": [
        {"name": "Churchill Capital Corp IV", "from": "2020-04-30T00:00:00.000Z", "to": "2021-07-23T00:00:00.000Z"}]}
    assert not is_spac(desp, date(2024, 1, 1))


def test_is_spac_sic_6770_with_no_name_history_is_a_spac():
    """No 'Acquisition Corp' in the name, but SIC 6770 and no formerNames at
    all (never renamed): still a SPAC. FST/BWC/HMA/LEAP's underlying
    companies all look exactly like this."""
    assert is_spac({"sic": "6770", "name": "Ribbit LEAP, Ltd.", "formerNames": []}, date(2022, 8, 16))


def test_is_spac_sic_6770_when_the_only_rename_has_not_completed_by_the_date():
    """A formerNames entry whose `to` is after `on` hasn't completed by `on`
    — the SIC test still applies."""
    sub = {"sic": "6770", "name": "Some Trust Corp", "formerNames": [
        {"name": "Old Blank Check Co", "from": "2020-01-01T00:00:00.000Z", "to": "2026-12-31T00:00:00.000Z"}]}
    assert is_spac(sub, date(2023, 1, 1))


import pytest

from delist_detection.evidence import cites_listing_deficiency


@pytest.mark.parametrize("text, cites", [
    ("the Company's failure to comply with the continued listing standard set forth in Section 802.01B", True),  # CIE
    ("advising the Company of its failure to satisfy one or more continued listing rules or standards", True),    # SIVB
    ("the NYSE determined that the trading price of the Class A shares was abnormally low", True),               # FPAC
    ("an average global market capitalization over a consecutive 30-day trading period", True),                 # CIE
    ("the average global market capitalisation fell below $15 million", True),
    ("NYSE determined that the Company's common stock is no longer suitable for listing", True),                 # WeWork
    ("the securities are no longer suitable for continued listing", True),
    ("the NYSE had determined to commence proceedings to delist the Company's common stock", True),              # CIE
    ("NYSE Regulation commenced proceedings to delist the common stock", True),
    ("Item 3.01 Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; "
     "Transfer of Listing.", False),                                                                            # the heading alone
])
def test_cites_listing_deficiency_standard_exchange_wording(text, cites):
    assert cites_listing_deficiency(text) is cites


# --- R3: item_text returns the item's own section, not 1,500 chars from the cover index ---

COVER = ("Item 1.01 Entry into a Material Definitive Agreement "
         "Item 1.03 Bankruptcy or Receivership "
         "Item 9.01 Financial Statements and Exhibits "
         "Item 1.03 Bankruptcy or Receivership. Voluntary Petition for Bankruptcy "
         "On August 5, 2024, the Company filed a voluntary petition for relief under "
         "chapter 11 of title 11 of the United States Code in the United States Bankruptcy "
         "Court for the District of Delaware, and expects the common stock to be cancelled "
         "with no recovery for holders of the Company's equity. "
         "Item 2.04 Triggering Events that Accelerate a Direct Financial Obligation")


def test_item_text_skips_a_cover_page_index_entry():
    section = item_text(COVER, "1.03")
    assert section.startswith("Item 1.03 Bankruptcy or Receivership. Voluntary Petition")
    assert "Item 9.01" not in section


def test_item_text_stops_at_the_next_item_heading():
    section = item_text(COVER, "1.03")
    assert "Item 2.04" not in section
    assert section.rstrip().endswith("equity.")


def test_item_text_falls_back_to_the_first_match_when_every_section_is_short():
    t = "Item 3.01 Notice of Delisting. The Company is not in compliance."
    assert item_text(t, "3.01") == t


def test_item_text_with_no_match_is_empty():
    assert item_text("nothing here", "1.03") == ""


def test_edgar_names_lists_the_current_name_then_the_former_ones():
    from delist_detection.evidence import edgar_names
    sub = {"name": "Eversource Energy",
           "formerNames": [{"name": "NORTHEAST UTILITIES"}, {"name": " "}, {"name": None}, "junk"]}
    assert edgar_names(sub) == ("Eversource Energy", "NORTHEAST UTILITIES")
    assert edgar_names({"name": None, "formerNames": None}) == ()
