from datetime import date

from delist_detection.identity.issuer_in_force import (
    Sighting, agreeing_since, in_force, issuer_changes, listed_issuer,
)

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


# --- FB-015: the issuer in force on a seed list (one sighting per security) -------------------------------------

LUMEN = {"name": "Lumen Technologies, Inc.", "formerNames": [
    {"name": "CENTURYLINK, INC", "from": "2010-11-09T05:00:00.000Z", "to": "2021-01-20T05:00:00.000Z"}]}
BEC = {"name": "LUMEN TECHNOLOGIES INC", "formerNames": [
    {"name": "BEC GROUP INC", "from": "1996-05-13T04:00:00.000Z", "to": "1998-03-26T05:00:00.000Z"}]}


def _filed(days_by_cik):
    """A `filed` read: each CIK's (form, day) pairs."""
    def filed(cik, form):
        return [date.fromisoformat(d) for f, d in days_by_cik.get(cik, ()) if f.startswith(form)]
    return filed


def test_a_company_that_stopped_filing_long_before_the_sighting_is_not_the_issuer_in_force():
    """LUMN 2020-12-31: EDGAR dated CenturyLink's rename 2021-01-21, so 18926 carried the old name that day, and the
    one other company listed under exactly LUMEN TECHNOLOGIES INC (CIK 1008114, once BEC Group) last filed in 2003.
    A company that was filing then (old Merck in 2008) is still taken."""
    subs = {18926: LUMEN, 1008114: BEC}
    exact = lambda n: [18926, 1008114] if n == "LUMEN TECHNOLOGIES INC" else []
    s = Sighting("S", "2020-12-31", "LUMEN TECHNOLOGIES INC", "18926")
    dead = _filed({1008114: [("10-K", "1998-03-30"), ("15-15D", "1999-02-23"), ("SC 13G", "2003-05-08")]})
    assert in_force(s, subs.get, exact) == "1008114"                   # no filing days known: as before
    assert in_force(s, subs.get, exact, dead) == "18926"
    alive = _filed({1008114: [("10-Q", "2020-11-05")]})
    assert in_force(s, subs.get, exact, alive) == "1008114"
    assert issuer_changes([Sighting("S", "2014-12-31", "CENTURYLINK INC", "18926"), s], subs.get, exact, dead) == {
        "S": [("2014-12-31", "18926")]}
    merck = _filed({64978: [("10-K", "2008-02-28"), ("10-Q", "2008-05-05")]})
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "310158"), submissions, exact_names, merck) == "64978"


def test_a_company_edgar_holds_no_filing_of_is_not_the_issuer_in_force():
    """MAN 2013-06-28, sighted as MANPOWER INC while EDGAR's name for 871763 was ManpowerGroup Inc.: of the other
    companies listed under exactly MANPOWER INC, CIK 76356 ("MANPOWER INC /DE/") has no filing at all and CIK 62072
    only the Schedule 13Gs its holders filed, to 2016: no report of its own. Neither is the issuer; a filing list
    that is not known is not judged."""
    subs = {871763: {"name": "ManpowerGroup Inc.", "formerNames": []},
            76356: {"name": "MANPOWER INC /DE/", "formerNames": []}, 62072: {"name": "MANPOWER INC", "formerNames": []}}
    exact = lambda n: [76356, 62072, 871763] if n == "MANPOWER INC" else []
    s = Sighting("S", "2013-06-28", "MANPOWER INC", "871763")
    known = {62072: [("SC 13G", "1997-02-03"), ("SC 13G/A", "2014-02-12"), ("NO ACT", "2016-02-10")]}
    assert in_force(s, subs.get, exact, lambda c, f: _filed(known)(c, f)) == "871763"
    unknown = lambda c, f: None if c == 76356 else _filed(known)(c, f)
    assert in_force(s, subs.get, exact, unknown) == "76356"


def test_a_sighting_with_no_name_changes_the_issuer_on_its_own_day():
    """MDT on a seed list: the line the library derived after the CUSIP change is a sighting on its first day with
    its era's CIK and no observed name."""
    subs = {64670: {"name": "MEDTRONIC INC", "formerNames": []},
            1613103: {"name": "Medtronic plc", "formerNames": [
                {"name": "Medtronic Holdings Ltd", "from": "2014-07-14T04:00:00.000Z", "to": "2014-11-21T05:00:00.000Z"}]}}
    rows = [Sighting("S", "2008-01-16", "MEDTRONIC INC", "64670"), Sighting("S", "2015-01-27", "", "1613103")]
    filed = _filed({64670: [("25-NSE", "2015-01-30")]})
    assert issuer_changes(rows, subs.get, lambda n: [], filed) == {"S": [("2008-01-16", "64670"),
                                                                        ("2015-01-27", "1613103")]}


def test_the_form_25_bound_reads_the_filing_days_it_is_given():
    """The run's submissions read keeps no filings block (`IssuerRecord.profile`), so the old registrant's Form 25
    comes from the `filed` read: ICE 2013 changes on 2013-11-13 with it, on the day after the last old sighting
    without."""
    bare = {k: {x: v for x, v in sub.items() if x != "filings"} for k, sub in {1174746: ICE_OLD, 1571949: ICE_NEW}.items()}
    rows = [Sighting("S", "2013-06-28", "INTERCONTINENTALEXCHANGE INC.", "1174746"),
            Sighting("S", "2013-12-31", "INTERCONTINENTALEXCHANGE INC", "1571949")]
    assert issuer_changes(rows, bare.get, lambda n: [])["S"][1] == ("2013-06-29", "1571949")
    filed = _filed({1174746: [("10-Q", "2013-11-05"), ("25-NSE", "2013-11-13"), ("15-12B", "2013-11-25")]})
    assert issuer_changes(rows, bare.get, lambda n: [], filed)["S"][1] == ("2013-11-13", "1571949")


MERCK_FILED = _filed({64978: [("25", "2008-12-01"), ("25-NSE", "2009-11-04"), ("15-12B", "2009-11-18")]})


def test_an_open_history_takes_the_company_sec_lists_its_ticker_under():
    """MRK on a seed list: one 2008 sighting under old Merck (64978), which kept filing as a subsidiary, so no later
    era names the registrant since November 2009. SEC lists MRK under 310158 and its EDGAR name agrees: it is the
    issuer in force from the day it took the name, no earlier than old Merck's Form 25 once it had."""
    timeline = [("2008-01-16", "64978")]
    out = listed_issuer(timeline, 310158, "MERCK & CO INC", date(2026, 9, 25), "2008-01-16", submissions, MERCK_FILED)
    assert out == [("2008-01-16", "64978"), ("2009-11-04", "310158")]


def test_the_listed_company_changes_nothing_it_cannot_support():
    on, timeline = date(2026, 9, 25), [("2008-01-16", "64978")]
    same = [("2008-01-16", "64978"), ("2009-11-04", "310158")]
    assert listed_issuer(same, 310158, "MERCK & CO INC", on, "2012-06-29", submissions, MERCK_FILED) == same
    assert listed_issuer(timeline, None, "MERCK & CO INC", on, "2008-01-16", submissions, MERCK_FILED) == timeline
    assert listed_issuer([], 310158, "MERCK & CO INC", on, "", submissions, MERCK_FILED) == []
    # its name on the run date does not agree with the security's
    assert listed_issuer(timeline, 310158, "SCHERING PLOUGH CORP", on, "2008-01-16", submissions, MERCK_FILED) == timeline
    assert listed_issuer(timeline, 310158, "", on, "2008-01-16", submissions, MERCK_FILED) == timeline
    # its profile cannot be read
    assert listed_issuer(timeline, 310158, "MERCK & CO INC", on, "2008-01-16", lambda c: None, MERCK_FILED) == timeline
    # nothing dates the change: its name has no first day and the old issuer filed no Form 25 or 15
    undated = {310158: {"name": "Merck & Co., Inc.", "formerNames": []}}
    assert listed_issuer(timeline, 310158, "MERCK & CO INC", on, "2008-01-16", undated.get, _filed({})) == timeline


def test_the_listed_company_is_never_in_force_on_or_before_the_last_sighting():
    """A sighting under the old issuer after the new company took the name keeps the old issuer through that day."""
    timeline = [("2008-01-16", "64978")]
    out = listed_issuer(timeline, 310158, "MERCK & CO INC", date(2026, 9, 25), "2012-06-29", submissions, MERCK_FILED)
    assert out == [("2008-01-16", "64978"), ("2012-06-30", "310158")]


def test_the_listed_company_with_an_undated_name_changes_on_the_old_issuers_form_25():
    undated = {310158: {"name": "Merck & Co., Inc.", "formerNames": []}}
    out = listed_issuer([("2009-06-30", "64978")], 310158, "MERCK & CO INC", date(2026, 9, 25), "2009-06-30",
                        undated.get, MERCK_FILED)
    assert out == [("2009-06-30", "64978"), ("2009-11-04", "310158")]
