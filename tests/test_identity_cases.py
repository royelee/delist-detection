"""Sub-plan 5h's real cases: each era's FIGI (stage 3) and each name-search answer's check (stage 2b) over
tests/fixtures/identity/ (built once, offline, from the local caches by scripts/build_identity_fixtures.py),
through the run's own stage-1, stage-2b and stage-3 code (tests/identity_cases.py). A case the sub-plan moves
(MOVES) has its new resolution; a guard (STAY) keeps the one the committed run gave it."""
from __future__ import annotations

import pytest

from delist_detection import pipeline
from delist_detection.contract import id_change_rows
from tests import identity_cases as ic


@pytest.fixture(scope="module")
def cases():
    return ic.Cases(ic.load_backend())


@pytest.fixture(scope="module")
def stage3(cases):
    return cases.stage3()


# era key -> (sec_id, FIGI source) once 5h's rules are built; each was its issuer's placeholder before
MOVES = {
    "UAC-C@2016-06-30": ("BBG009DTD8H2", "cusip"),     # rule A: FTD's "UAC" rows (UNDER ARMOUR INC CL C) are UAC-C's
    "MSG@2012-06-29": ("BBG000NS03H7", "handoff"),     # rule B: class A renamed MSG Networks ("MSG NETWORKS INC- A")
    "LMCA@2012-06-29": ("BBG000PCNTM2", "handoff"),    # rule B: class A renamed Starz ("STARZ - A")
    "UAG@2008-01-16": ("BBG000H6K1B0", "backfill"),    # rule C: UBS's E-TRACS rows under UAG; PAG's CUSIP traded then
}

# era key -> (sec_id, FIGI source), unchanged by 5h
STAY = {
    "HUB-B@2008-01-16": ("CIK48898-CLASS-B", "placeholder"),   # class B reclassified into the plain common (R1)
    "LVNTA@2016-12-30": ("CIK1355096-COMMON", "placeholder"),  # series A tracking stocks: a shared CUSIP joins none
    "QVCA@2014-12-31": ("CIK1355096-COMMON", "placeholder"),
    "LINTA@2008-01-16": ("CIK1355096-COMMON", "placeholder"),
    "LVNTA@2017-06-30": ("BBG0038K9G41", "cusip"),
    "MSG@2015-12-31": ("BBG007FG0C23", "cusip"),               # the new MSG took the ticker: another issuer
    "LMCA@2013-06-28": ("BBG003P9ZSL3", "cusip"),              # the new Liberty Media took the ticker
    "LMCK@2014-12-31": ("BBG005SW6TK5", "cusip"),
    "GOOG@2015-12-31": ("BBG009S3NB30", "cusip"),              # Alphabet's two classes stay two
    "GOOGL@2015-12-31": ("BBG009S39JX6", "cusip"),
    "HEI@2016-06-30": ("BBG000BL16Q7", "cusip"),               # a class ticker's base symbol is another line's
    "HEI-A@2016-06-30": ("BBG000F0CD91", "cusip"),
    "LEN@2008-01-16": ("BBG000BN5HF7", "cusip"),
    "LEN-B@2015-06-30": ("BBG000KKVD81", "cusip"),
    "VIA@2015-06-30": ("BBG000DHM3H8", "cusip"),
    "VIA-B@2008-01-16": ("BBG000DHSPT0", "cusip"),
    "UA@2016-12-30": ("BBG009DTD8H2", "cusip"),
    "PAG@2014-06-30": ("BBG000H6K1B0", "cusip"),
    "IAC@2012-06-29": ("CIK891103-COMMON", "placeholder"),     # a stale ticker with no rows: no span backfill
    "WPO@2008-01-16": ("CIK104889-COMMON", "placeholder"),     # its line's OpenFIGI name states no letter of it
}


@pytest.mark.parametrize("key", sorted(MOVES))
def test_a_case_takes_its_line(stage3, key):
    res, _, _ = stage3
    assert (res[key].sec_id, res[key].source) == MOVES[key]


@pytest.mark.parametrize("key", sorted(STAY))
def test_a_guard_keeps_its_resolution(stage3, key):
    res, _, _ = stage3
    assert (res[key].sec_id, res[key].source) == STAY[key]


def test_a_class_tickers_base_rows_are_its_own_only_when_they_name_its_class(stage3):
    """Rule A: FTD lists Under Armour's class C as "UAC" (UNDER ARMOUR INC CL C), the snapshot as "UAC-C". The base
    of HEI-A, LEN-B and VIA-B is another line's own symbol (HEICO CORP, LENNAR CORP CL A, VIACOM INC CL A)."""
    _, _, ftd = stage3
    assert {r.cusip for r in ftd.by_symbol("UAC-C", "2016-04-01", "2016-12-31")} == {"904311206"}
    for ticker, base_cusips in (("HEI-A", {"422806109"}), ("LEN-B", {"526057104"}),
                                ("VIA-B", {"92553P102", "925524100"})):
        assert not {r.cusip for r in ftd.by_symbol(ticker)} & base_cusips, ticker
    assert {r.cusip for r in ftd.by_symbol("HEI")} == {"422806109"}


def test_the_placeholders_joined_across_a_class_label_are_renames(stage3, cases):
    """Rule B's id_changes: a placeholder whose eras now hold one FIGI line is renamed to it, across a class label
    (CLASS-A onto MSG Networks' plain-named line); the guards' placeholders are not."""
    res, eras, _ = stage3
    issuers = cases.issuers(eras)
    renames = pipeline._era_renames(eras, res, issuers)
    assert renames["CIK1469372-CLASS-A"] == "BBG000NS03H7"
    assert renames["CIK1507934-CLASS-A"] == "BBG000PCNTM2"
    assert renames["CIK1336917-CLASS-C"] == "BBG009DTD8H2"
    assert renames["CIK1019849-COMMON"] == "BBG000H6K1B0"
    assert "CIK48898-CLASS-B" not in renames and "CIK1355096-COMMON" not in renames
    baseline = [{"sec_id": "CIK1469372-CLASS-A", "issuer_cik": "1469372", "share_class": "CLASS A",
                 "figi_source": "placeholder"}]
    now = [{"sec_id": "BBG000NS03H7", "issuer_cik": "1469372", "share_class": "COMMON", "figi_source": "cusip"}]
    assert [r["new_sec_id"] for r in id_change_rows(baseline, now, "2026-09-25", renames)] == ["BBG000NS03H7"]


def test_a_name_search_answer_is_checked_against_the_eras_span_and_its_tickers_rows(cases):
    """Rule D (stage 2b): ABBI 2008-09's name was the new Abraxis's (APP Pharmaceuticals dropped it in 2007); the
    rows under ERA in 2013 are Era Group's (later renamed Bristow Group Inc). TCF, Gannett and News Corp carried
    their names over their eras: the later holders of the name do not take them."""
    found, _ = cases.name_checks()
    assert {k: (v.cik, v.source) for k, v in found.items()} == {
        "ABBI@2008-01-16": (1409012, "name_in_force"), "ERA@2013-06-28": (1525221, "ticker_rows")}


def test_an_answer_the_eras_own_rows_fit_is_kept_whichever_holder_the_first_pass_named(cases):
    """Rule D decides by the era's own fails rows when it has enough: ERA 2013's rows say ERA GROUP INC, so a first
    pass that already answered 1525221 gets no replacement by 73887, which `name_in_force` alone would give (the
    snapshot's later name, Bristow Group Inc, was 73887's over 2013-2014)."""
    found, _ = cases.name_checks({"ERA@2013-06-28": 1525221})
    assert "ERA@2013-06-28" not in found
    assert found["ABBI@2008-01-16"].cik == 1409012      # ABBI has no rows of its own: the name period decides


def test_a_joined_lines_cusip_ranges_ignore_the_old_cusips_settling_rows(cases):
    """MSG 2015: the old class A CUSIP's MSGZZZZ rows settle to 10-07, after MSG Networks' CUSIP began on 10-06;
    they are no sighting of it, so the new CUSIP's range starts on its first row."""
    from types import SimpleNamespace

    from delist_detection.history import cusip_sightings, ranges_from_sightings
    _, ftd = cases.refine({"MSG", "MSGN"})
    sig = cusip_sightings(SimpleNamespace(eras=[]), ftd, ["55826P100", "553573106"])
    got = {r.value: (r.valid_from, r.valid_to)
           for r in ranges_from_sightings([s for s in sig if "2015-09-01" <= s.day <= "2015-10-31"], end=None,
                                          open_ended=False)}
    assert got["553573106"][0] == "2015-10-06"
    assert got["55826P100"][1] == "2015-10-05"


def test_a_ticker_range_carried_to_the_next_ticker_stops_before_another_securitys_first_day():
    """MSG 2015: the old line's MSG range runs to the day before its MSGN first row, one day into the new MSG's: it
    stops the day before the new security's first day under MSG (`history.Histories`)."""
    from datetime import date

    from delist_detection.crsp_codes import CrspBucket
    from delist_detection.ftd import FtdIndex
    from delist_detection.history import Ending, Histories, Sighting
    from delist_detection.last_trade import LastTrade
    from delist_detection.security_master import Security
    from delist_detection.store import DelistingKey

    secs = {sid: Security(sid, 1, "COMMON", sid, "Common Stock", True, "cusip") for sid in ("OLD", "NEW")}
    new = [Sighting("2015-10-05", "MSG", "ftd"), Sighting("2015-10-06", "MSG", "ftd")]

    def msg_ranges(old_msg, endings=(), listed=True):
        old = [Sighting(d, "MSG", "ftd") for d in ("2010-02-16", *old_msg)] + [
            Sighting("2015-10-06", "MSGN", "ftd"), Sighting("2015-10-07", "MSGN", "ftd")]
        history = Histories(secs, {"OLD": old, "NEW": new}, {}, FtdIndex(), endings,
                            listed={"OLD": listed, "NEW": True})
        return sorted((r["sec_id"], r["valid_to"] or "") for r in history.ticker_rows if r["ticker"] == "MSG")

    assert msg_ranges(["2015-10-02"]) == [("NEW", ""), ("OLD", "2015-10-04")]
    # a security still sighted under the ticker, or ended by its own ending, is left to ticker_shared
    assert msg_ranges(["2015-10-02", "2015-10-05"]) == [("NEW", ""), ("OLD", "2015-10-05")]
    ended = Ending(DelistingKey("OLD", "2015-10-15"), LastTrade(date(2015, 10, 5), "midas", ()),
                   CrspBucket.LIQUIDATION, None, "NASDAQ")
    assert msg_ranges(["2015-10-02"], [ended], listed=False) == [("NEW", ""), ("OLD", "2015-10-05")]
