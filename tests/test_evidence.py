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
