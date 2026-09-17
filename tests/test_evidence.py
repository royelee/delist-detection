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
