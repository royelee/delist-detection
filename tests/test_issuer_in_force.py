from datetime import date

from delist_detection.cik_lookup import CikNameIndex
from delist_detection.issuer_in_force import Sighting, agreeing_since, in_force, issuer_changes
from delist_detection.ticker_resolver import TickerResolver

OLD_MERCK = {"name": "MERCK SHARP & DOHME CORP",
             "formerNames": [{"name": "MERCK & CO INC", "from": "1994-01-01T00:00:00.000Z",
                              "to": "2009-11-03T00:00:00.000Z"}]}
NEW_MERCK = {"name": "Merck & Co., Inc.",
             "formerNames": [{"name": "SCHERING PLOUGH CORP", "from": "1994-01-01T00:00:00.000Z",
                              "to": "2009-11-03T00:00:00.000Z"}]}
SUBS = {64978: OLD_MERCK, 310158: NEW_MERCK}


def submissions(cik):
    return SUBS.get(cik)


def exact_names(name):
    return [64978, 310158] if name == "MERCK & CO INC" else []


def test_a_sighting_takes_the_one_cik_that_carried_its_name_that_day():
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "310158"), submissions, exact_names) == "64978"
    assert in_force(Sighting("S", "2012-06-29", "MERCK & CO INC", "310158"), submissions, exact_names) == "310158"


def test_without_one_agreeing_alternative_the_era_cik_stays():
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "310158"), submissions, lambda n: []) == "310158"
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "999"), lambda c: None, exact_names) == "999"
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", ""), submissions, exact_names) == ""


def test_agreeing_since_is_the_first_day_of_the_agreeing_name():
    assert agreeing_since(NEW_MERCK, "MERCK & CO INC", date(2012, 6, 29)) == date(2009, 11, 4)
    assert agreeing_since(OLD_MERCK, "MERCK & CO INC", date(2008, 6, 30)) == date(1994, 1, 1)
    assert agreeing_since(NEW_MERCK, "MERCK & CO INC", date(2008, 6, 30)) is None


def test_the_timeline_changes_on_the_day_the_new_issuer_took_the_name():
    rows = [Sighting("S", d, "MERCK & CO INC", "310158") for d in ("2008-01-16", "2009-06-30", "2010-06-30")]
    assert issuer_changes(rows, submissions, exact_names) == {"S": [("2008-01-16", "64978"),
                                                                    ("2009-11-04", "310158")]}


def test_a_change_date_never_falls_on_or_before_the_last_sighting_under_the_old_issuer():
    rows = [Sighting("S", "2009-12-31", "MERCK & CO INC", "64978"), Sighting("S", "2010-06-30", "MERCK & CO INC", "310158")]
    subs = {64978: {"name": "MERCK & CO INC", "formerNames": []}, 310158: NEW_MERCK}
    out = issuer_changes(rows, subs.get, lambda n: [])
    assert out == {"S": [("2009-12-31", "64978"), ("2010-01-01", "310158")]}


def test_the_resolver_hands_out_its_name_index(fake_edgar):
    index = CikNameIndex.from_text("MERCK & CO INC:0000064978:\n")
    assert TickerResolver(fake_edgar, name_index=index).name_index() is index
    assert TickerResolver(fake_edgar).name_index() is None
