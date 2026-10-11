from datetime import date

from delist_detection.identity.issuer_in_force import Sighting, agreeing_since, in_force, issuer_changes

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


AGREE = {1: {"name": "ACME INC", "formerNames": []}, 2: {"name": "ACME INC", "formerNames": []}}


def test_same_day_sightings_under_two_ciks_give_one_entry_for_that_day():
    rows = [Sighting("S", "2020-01-01", "ACME INC", "2"), Sighting("S", "2020-01-01", "ACME INC", "1")]
    assert issuer_changes(rows, AGREE.get, lambda n: []) == {"S": [("2020-01-01", "1")]}


def test_a_b_a_gives_strictly_increasing_dates():
    rows = [Sighting("S", "2020-01-01", "ACME INC", "1"), Sighting("S", "2020-01-02", "ACME INC", "2"),
            Sighting("S", "2020-01-03", "ACME INC", "1")]
    out = issuer_changes(rows, AGREE.get, lambda n: [])["S"]
    assert [c for _, c in out] == ["1", "2", "1"]
    days = [d for d, _ in out]
    assert days == sorted(set(days))


def test_input_order_does_not_change_the_timeline():
    rows = [Sighting("S", "2020-01-01", "ACME INC", "1"), Sighting("S", "2020-01-02", "ACME INC", "2"),
            Sighting("S", "2020-01-02", "ACME INC", "1"), Sighting("S", "2020-01-03", "ACME INC", "1")]
    assert issuer_changes(rows, AGREE.get, lambda n: []) == issuer_changes(rows[::-1], AGREE.get, lambda n: [])


# --- batch 3 gate, COHR: II-VI's own CIK, not the acquired Coherent Inc (the era's resolved CIK) ---

def test_ii_vi_sightings_under_the_acquired_coherents_cik_are_ii_vis_own_before_the_rename():
    """The observed name II VI INC agrees with 'II-VI INC' (820318's EDGAR name until 2022-09-01, FB-006's run-together
    words), not with Coherent Inc's (21510): the name index's one other holder is the issuer in force."""
    subs = {21510: {"name": "COHERENT INC", "formerNames": []},
            820318: {"name": "COHERENT CORP.", "formerNames": [
                {"name": "II-VI INC", "from": "1995-10-04T04:00:00.000Z", "to": "2022-09-01T04:00:00.000Z"}]}}
    rows = [Sighting("S", d, "II VI INC", "21510") for d in ("2012-06-29", "2020-06-30")]
    assert issuer_changes(rows, subs.get, lambda n: [820318, 21510] if n == "II VI INC" else []) == {
        "S": [("2012-06-29", "820318")]}


# --- batch 3 gate, ICE 2013: a holding company's name agrees long before it is the issuer ---

def _filings(*pairs):
    return {"recent": {"form": [f for f, _ in pairs], "filingDate": [d for _, d in pairs]}}


ICE_OLD = {"name": "Intercontinental Exchange Holdings, Inc.", "formerNames": [
    {"name": "INTERCONTINENTALEXCHANGE INC", "from": "2005-02-15T05:00:00.000Z", "to": "2014-05-08T04:00:00.000Z"}],
    "filings": _filings(("10-Q", "2013-11-05"), ("25-NSE", "2013-11-13"), ("15-12B", "2013-11-25"))}
ICE_NEW = {"name": "Intercontinental Exchange, Inc.", "formerNames": [
    {"name": "INTERCONTINENTALEXCHANGE INC", "from": "2013-03-20T04:00:00.000Z", "to": "2014-05-29T04:00:00.000Z"}],
    "filings": _filings(("S-4", "2013-03-21"), ("8-K", "2013-11-19"))}


def test_the_new_issuer_is_in_force_from_the_old_issuers_form_25_not_from_its_names_first_day():
    """The holding company (formed 2013-03-20) carries the agreeing name before it is the registrant of the listed
    stock; the old registrant's Form 25 (2013-11-13) ends its listing, and that is the day the change is dated."""
    rows = [Sighting("S", "2013-06-28", "INTERCONTINENTALEXCHANGE INC.", "1174746"),
            Sighting("S", "2013-12-31", "INTERCONTINENTALEXCHANGE INC", "1571949")]
    subs = {1174746: ICE_OLD, 1571949: ICE_NEW}
    assert issuer_changes(rows, subs.get, lambda n: []) == {"S": [("2013-06-28", "1174746"), ("2013-11-13", "1571949")]}


def test_an_old_issuers_form_25_after_the_new_sighting_is_not_in_the_gap():
    rows = [Sighting("S", "2013-06-28", "INTERCONTINENTALEXCHANGE INC.", "1174746"),
            Sighting("S", "2013-09-30", "INTERCONTINENTALEXCHANGE INC", "1571949")]
    subs = {1174746: ICE_OLD, 1571949: ICE_NEW}
    assert issuer_changes(rows, subs.get, lambda n: []) == {"S": [("2013-06-28", "1174746"), ("2013-06-29", "1571949")]}


def test_an_old_issuer_with_no_form_25_in_the_gap_changes_on_the_names_first_day_as_before():
    old = {**ICE_OLD, "filings": _filings(("10-Q", "2013-11-05"))}
    rows = [Sighting("S", "2013-06-28", "INTERCONTINENTALEXCHANGE INC.", "1174746"),
            Sighting("S", "2013-12-31", "INTERCONTINENTALEXCHANGE INC", "1571949")]
    assert issuer_changes(rows, {1174746: old, 1571949: ICE_NEW}.get, lambda n: []) == {
        "S": [("2013-06-28", "1174746"), ("2013-06-29", "1571949")]}
