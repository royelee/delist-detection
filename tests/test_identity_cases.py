"""Sub-plan 5h's real cases: each era's FIGI (stage 3) and each name-search answer's check (stage 2b) over
tests/fixtures/identity/ (built once, offline, from the local caches by scripts/build_identity_fixtures.py),
through the run's own identity stage (`identity.identify`, tests/identity_cases.py). A case the sub-plan moves
(MOVES) has its new resolution; a guard (STAY) keeps the one the committed run gave it."""
from __future__ import annotations

import pytest

from delist_detection.outputs.contract import id_change_rows
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
    # FB-006: "IAC INTERACTIVE" is IACINTERACTIVECORP (run together), so the stale era is IAC's, not a placeholder
    "IAC@2012-06-29": ("BBG000BKQG80", "backfill"),
    # FB-006: "LIBERTY INTERACTIVE VENTURE CORP S" is "LIBERTY VENTURES - SER A" (a plural S), so the one-observation
    # era the name split cut from LVNTA@2012-12-31 is no era of its own; it was the placeholder's, and FB-005's overlap
    "LVNTA@2012-12-31": ("BBG0038K9G41", "ticker"),
    # FB-003: Washington Post's name states no class, its CUSIP's descriptions say "CLB" and its issuer's only other
    # era is Graham Holdings' class B: the old CUSIP ended as GHC's began, so one line, not an `exchange` ending
    "WPO@2008-01-16": ("BBG000C3FGH9", "handoff"),
    # FB-003: the old Ingersoll-Rand eras reached today's composite by the ticker IR (their CUSIPs are on no US venue);
    # the new Ingersoll Rand's CUSIP confirms it, and the old plc's CUSIP ended as both it and Trane's began
    "IR@2008-01-16": ("BBG000BM6788", "handoff"),     # ... which then goes where Ingersoll-Rand plc went: Trane
    "IR@2014-12-31": ("BBG000BM6788", "handoff"),
    # FB-001: old Chesapeake (CUSIP 165167107) reached post-bankruptcy Chesapeake's composite by ticker; one issuer, and
    # the issuer's Item 1.03 8-K of 2020-06 falls in the year before the new CUSIP's first row
    "CHK@2008-01-16": ("CIK895126-COMMON", "placeholder"),
    # FB-005: Liberty's tracking stocks are no FIGI's and state no class, so they shared CIK1355096-COMMON; LINTA and its
    # later QVCA share a CUSIP (one line), LCAPA's CUSIP trades beside it (another): each placeholder is named by its
    # line's first CUSIP
    "LINTA@2008-01-16": ("CIK1355096-COMMON-53071M104", "placeholder"),
    "QVCA@2014-12-31": ("CIK1355096-COMMON-53071M104", "placeholder"),
    "LCAPA@2008-01-16": ("CIK1355096-COMMON-53071M302", "placeholder"),
    # FB-004 part c: the snapshots of 2008-11 to 2009-06 still listed Bear Stearns (merged 2008-05-30) and Clear Channel
    # (LBO 2008-07-30) while the tickers' rows were another security's (an ETN under BSC, the Chilean CCU): each era is
    # its dead line's stale tail, not a placeholder that no Form 25 can end
    "BSC@2008-11-18": ("BBG000BDRQ10", "backfill"),
    "CCU@2008-11-18": ("BBG000BF8BH2", "backfill"),
}

# era key -> (sec_id, FIGI source), unchanged by 5h
STAY = {
    "HUB-B@2008-01-16": ("CIK48898-CLASS-B", "placeholder"),   # class B reclassified into the plain common (R1)
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
    "IR@2020-06-30": ("BBG002R1CW27", "cusip"),                # the new Ingersoll Rand keeps the composite
    "GDI@2017-06-30": ("BBG00RRH0RM9", "cusip"),
    "TT@2020-06-30": ("BBG000BM6788", "cusip"),
    "CHK@2022-06-30": ("BBG00Z6DX554", "cusip"),               # post-bankruptcy Chesapeake, later Expand Energy
    "EXE@2024-12-31": ("BBG00Z6DX554", "cusip"),
}


@pytest.mark.parametrize("key", sorted(MOVES))
def test_a_case_takes_its_line(stage3, key):
    res = stage3.resolutions
    assert (res[key].sec_id, res[key].source) == MOVES[key]


@pytest.mark.parametrize("key", sorted(STAY))
def test_a_guard_keeps_its_resolution(stage3, key):
    res = stage3.resolutions
    assert (res[key].sec_id, res[key].source) == STAY[key]


def test_a_class_tickers_base_rows_are_its_own_only_when_they_name_its_class(stage3):
    """Rule A: FTD lists Under Armour's class C as "UAC" (UNDER ARMOUR INC CL C), the snapshot as "UAC-C". The base
    of HEI-A, LEN-B and VIA-B is another line's own symbol (HEICO CORP, LENNAR CORP CL A, VIACOM INC CL A)."""
    ftd = stage3.ftd
    assert {r.cusip for r in ftd.by_symbol("UAC-C", "2016-04-01", "2016-12-31")} == {"904311206"}
    for ticker, base_cusips in (("HEI-A", {"422806109"}), ("LEN-B", {"526057104"}),
                                ("VIA-B", {"92553P102", "925524100"})):
        assert not {r.cusip for r in ftd.by_symbol(ticker)} & base_cusips, ticker
    assert {r.cusip for r in ftd.by_symbol("HEI")} == {"422806109"}


def test_the_placeholders_joined_across_a_class_label_are_renames(stage3):
    """Rule B's id_changes: a placeholder whose eras now hold one FIGI line is renamed to it, across a class label
    (CLASS-A onto MSG Networks' plain-named line); the guards' placeholders are not."""
    renames = stage3.renames(stage3.resolutions)
    assert renames["CIK1469372-CLASS-A"] == "BBG000NS03H7"
    assert renames["CIK1507934-CLASS-A"] == "BBG000PCNTM2"
    assert renames["CIK1336917-CLASS-C"] == "BBG009DTD8H2"
    assert renames["CIK1019849-COMMON"] == "BBG000H6K1B0"
    assert "CIK48898-CLASS-B" not in renames and "CIK1355096-COMMON" not in renames
    baseline = [{"sec_id": "CIK1469372-CLASS-A", "issuer_cik": "1469372", "share_class": "CLASS A",
                 "figi_source": "placeholder"}]
    now = [{"sec_id": "BBG000NS03H7", "issuer_cik": "1469372", "share_class": "COMMON", "figi_source": "cusip"}]
    assert [r["new_sec_id"] for r in id_change_rows(baseline, now, "2026-09-25", renames)] == ["BBG000NS03H7"]


def test_a_tracking_stock_with_no_issuer_takes_its_cusips_issuer_code(cases):
    """FB-004 part c, FNFV: the run's lookup found no issuer for FNFV GROUP INC (no EDGAR name of Fidelity National
    Financial, CIK 1331875, agrees with it), but its CUSIP 31620R402 shares the issuer code 31620R with the company's
    own, whose eras the lookup answered: rule D of the second pass gives the era that issuer, flagged issuer_inferred."""
    answers = {k: (c, "committed") for k, c in cases.backend.eras_issuer.items() if k.startswith("FNF@")}
    assert answers, "FNF's eras are in the fixture"
    identity = cases.identify({"FNF", "FNFV"}, answers)
    assert identity.issuers["FNFV@2014-12-31"].cik == 1331875
    assert [(i.flag, i.cik) for i in identity.review if i.flag == "issuer_inferred" and "FNFV" in i.reason] == [
        ("issuer_inferred", 1331875)]


def test_a_name_search_answer_is_checked_against_the_eras_span_and_its_tickers_rows(cases):
    """Rule D (stage 2b): ABBI 2008-09's name was the new Abraxis's (APP Pharmaceuticals dropped it in 2007); the
    rows under ERA in 2013 are Era Group's (later renamed Bristow Group Inc). TCF, Gannett and News Corp carried
    their names over their eras: the later holders of the name do not take them."""
    found, identity = cases.name_checks()
    assert found == {"ABBI@2008-01-16": (1409012, "name_in_force"), "ERA@2013-06-28": (1525221, "ticker_rows")}
    assert identity.rows_decided == {"ERA@2013-06-28"}      # stages 4c and 10g keep ERA's CIK in force


def test_an_answer_the_eras_own_rows_fit_is_kept_whichever_holder_the_first_pass_named(cases):
    """Rule D decides by the era's own fails rows when it has enough: ERA 2013's rows say ERA GROUP INC, so a first
    pass that already answered 1525221 gets no replacement by 73887, which `name_in_force` alone would give (the
    snapshot's later name, Bristow Group Inc, was 73887's over 2013-2014)."""
    found, _ = cases.name_checks({"ERA@2013-06-28": 1525221})
    assert "ERA@2013-06-28" not in found
    assert found["ABBI@2008-01-16"][0] == 1409012       # ABBI has no rows of its own: the name period decides


GHC_SEED = {("GHC", "2012-06-29"), ("WPO", "2008-01-16")}
GHC_KEY = "GHC@2012-06-29"


def _ghc_seed(cases, first_pass=716314, tier="name_search"):
    """Graham Holdings as a seed-list input has it: the one GHC row of 2012-06-29, a ticker and a name the company
    took in November 2013, answered by the lookup as the run's was (Graham Corp, CIK 716314, by the name search)."""
    return cases.identify({"GHC", "WPO"}, {GHC_KEY: (first_pass, tier), "WPO@2008-01-16": (104889, "committed")},
                          seeds=GHC_SEED)


def test_a_backfilled_rows_issuer_is_the_company_its_ticker_is_listed_under(cases):
    """FB-013, GHC 2012: the snapshot of 2012-06-29 lists Washington Post Co under the ticker and name it took on
    2013-11-29. No fails row is under GHC near the row; the rows under GHC from 2013-11-29 are the company's SEC's
    ticker map lists GHC under (CIK 104889), which carried the observed name by then. The name search's Graham Corp
    (716314; GRAHAM CORP and GRAHAM HOLDINGS COMPANY CO compare as one word) gives way, flagged issuer_inferred."""
    identity = _ghc_seed(cases)
    assert (identity.issuers[GHC_KEY].cik, identity.tier(GHC_KEY)) == (104889, "later_ticker")
    assert [(i.flag, i.cik) for i in identity.review if i.flag == "issuer_inferred" and "GHC" in i.reason] == [
        ("issuer_inferred", 104889)]
    assert GHC_KEY in identity.rows_decided      # stages 4c and 10g keep its CIK in force: the name is a later one


def test_only_a_name_search_answer_gives_way_to_the_tickers_later_holder(cases):
    """The rule is stage 2b's: an answer another tier gave (here the committed run's) is not asked again."""
    identity = _ghc_seed(cases, tier="committed")
    assert (identity.issuers[GHC_KEY].cik, identity.tier(GHC_KEY)) == (716314, "committed")


def test_an_era_its_tickers_rows_confirm_keeps_its_name_search_answer(cases):
    """With every GHC sighting (2012 to 2020) the era's span holds its ticker's rows, so it is no backfilled row,
    and stage 2b's other rules decide as before."""
    identity = cases.identify({"GHC", "WPO"}, {GHC_KEY: (716314, "name_search"),
                                               "WPO@2008-01-16": (104889, "committed")})
    assert identity.tier(GHC_KEY) != "later_ticker"


def test_a_ticker_listed_under_a_company_that_never_carried_the_name_changes_nothing(cases, monkeypatch):
    """The ticker map alone is no evidence: GHC listed under Hubbell (which never carried a Graham name, and whose
    names the rows under GHC do not carry) leaves the name search's answer."""
    edgar = cases.backend.edgar
    monkeypatch.setattr(edgar, "company_tickers", lambda: {"GHC": {"cik_str": 48898, "ticker": "GHC"}})
    assert _ghc_seed(cases).issuers[GHC_KEY].cik == 716314


def _hubbell_ranges(cases, pins):
    """Hubbell's ticker ranges per security, its HUB-B sightings pinned as `pins` says (the committed issuers)."""
    from delist_detection.identity.history import ranges_from_sightings, ticker_sightings
    identity = cases.identify({"HUB-B", "HUBB"}, {k: (48898, "committed") for k in cases.backend.eras_issuer
                                                  if k.split("@")[0] in ("HUB-B", "HUBB")}, pins=pins)
    return {sid: [(r.value, r.valid_from, r.valid_to)
                  for r in ranges_from_sightings(ticker_sightings(sec, identity.ftd, identity.cusips[sid]),
                                                 end=None, open_ended=True)]
            for sid, sec in identity.securities.items()}


def test_a_sec_id_pin_joins_hub_b_to_hubbs_line_as_two_tickers(cases):
    """FB-013: the caller pins its HUB-B sightings to `BBG000BLK267`, the line OpenFIGI calls HUBB. The security
    was HUB-B under its old CUSIP and is HUBB from its new CUSIP's first row (2015-12-28), though SEC's fails files
    write HUBB on every row of both and the snapshots of 2012 to 2014 already wrote HUBB."""
    assert _hubbell_ranges(cases, {"HUB-B": "BBG000BLK267"}) == {
        "BBG000BLK267": [("HUB-B", "2008-01-16", "2015-12-27"), ("HUBB", "2015-12-28", None)]}


def test_unpinned_hubbell_keeps_its_two_securities_and_spellings(cases):
    """The guard: with no pin the class B sightings stay their placeholder's (STAY) and each security has the one
    spelling it was observed under."""
    got = _hubbell_ranges(cases, None)
    assert {sid: {t for t, _, _ in ranges} for sid, ranges in got.items()} == {
        "CIK48898-CLASS-B": {"HUB-B"}, "BBG000BLK267": {"HUBB"}}


def test_a_joined_lines_cusip_ranges_ignore_the_old_cusips_settling_rows(cases):
    """MSG 2015: the old class A CUSIP's MSGZZZZ rows settle to 10-07, after MSG Networks' CUSIP began on 10-06;
    they are no sighting of it, so the new CUSIP's range starts on its first row."""
    from types import SimpleNamespace

    from delist_detection.identity.history import cusip_sightings, ranges_from_sightings
    ftd = cases.stage3({"MSG", "MSGN"}).ftd
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

    from delist_detection.vocabulary.crsp_codes import CrspBucket
    from delist_detection.sources.ftd import FtdIndex
    from delist_detection.identity.history import Ending, Histories, Sighting
    from delist_detection.endings.last_trade import LastTrade
    from delist_detection.identity.security_master import Security
    from delist_detection.outputs.store import DelistingKey

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


def test_the_old_ingersoll_rand_eras_join_trane_and_the_composite_holds_one_issuer(stage3):
    secs = stage3.securities
    assert [e.key for e in secs["BBG002R1CW27"].eras] == ["IR@2020-06-30"] and secs["BBG002R1CW27"].issuer_cik == 1699150
    trane = secs["BBG000BM6788"]
    assert [e.key for e in trane.eras] == ["IR@2008-01-16", "TT@2012-06-29", "IR@2014-12-31", "TT@2020-06-30"]
    assert trane.issuer_cik == 1466258


def test_old_chesapeake_is_its_own_security_and_the_composite_starts_at_the_new_cusip(stage3):
    secs = stage3.securities
    assert [e.key for e in secs["CIK895126-COMMON"].eras] == ["CHK@2008-01-16"]
    assert [e.key for e in secs["BBG00Z6DX554"].eras] == ["CHK@2022-06-30", "EXE@2024-12-31"]


def test_a_failed_filings_read_in_the_composite_guard_keeps_the_pick_and_is_resolution_degraded(cases):
    """CHK: the guard asks the issuer's filings for the 2020 bankruptcy 8-K. With that read failing it finds none, so
    old Chesapeake stays on the composite its pick gave, and the era is reported degraded."""
    import requests

    class Down(ic.FixtureEdgar):
        def recent_filings(self, cik):
            if int(cik) == 895126:
                raise requests.ConnectionError("down")
            return super().recent_filings(cik)

    backend = cases.backend
    down = ic.Cases(ic.Backend(backend.observations, backend.eras_issuer, backend.ftd_client,
                               Down(backend.edgar._issuers), backend.figi, backend.index))
    found = down.stage3(["CHK", "EXE"])
    assert found.resolutions["CHK@2008-01-16"].sec_id == "BBG00Z6DX554"
    degraded = [r for r in found.review if r.flag == "resolution_degraded" and "bankruptcy" in r.reason]
    assert [r.reason.split(" ")[0] for r in degraded] == ["CHK@2008-01-16"]
