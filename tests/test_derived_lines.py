"""Which refused steps of stage 4b are lines of the run (`derived_lines.derivable`), and the rounds that give the run
those lines (`identify_with_lines`)."""
from datetime import date
from types import SimpleNamespace

import delist_detection.identity.derived_lines as derived_lines
from delist_detection.identity.derived_lines import derivable, old_line_names
from delist_detection.identity.line_follow import NEW_SYMBOL, SWITCH, LineStep, RefusedStep
from delist_detection.identity.observations import Observation, TickerEra
from delist_detection.identity.security_master import Security


def _security(sid="BBGOLD", cik=1, eras_name="CIGNA CORP", tickers=("CI",)):
    eras = [TickerEra(t, "2008-01-16", "2008-01-16", [Observation(t, "2008-01-16", eras_name)]) for t in tickers]
    return Security(sid, cik, "COMMON", eras_name, "Common Stock", True, "cusip", eras=eras)


def _step(descs, kind=SWITCH, sid="BBGOLD", new="NEWCUSIP1"):
    return LineStep(sid, kind, "OLDCUSIP1", new, "CI", "2018-12-10", "2018-12-21", tuple(descs))


NO_PROFILE = lambda cik: None


def test_a_refused_switch_whose_new_rows_name_the_old_issuer_is_derived_for_each_of_its_tickers():
    s = _security(tickers=("CI", "CIGNA"))
    got = derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), "merged_out")], {"BBGOLD": s}, NO_PROFILE)
    assert got == {("CI", "NEWCUSIP1"), ("CIGNA", "NEWCUSIP1")}


def test_each_refusal_of_another_registrant_or_a_name_is_derivable_and_no_other_is():
    s = {"BBGOLD": _security()}
    for why, derived in [("merged_out", True), ("other_registrant", True), ("name", True), ("no_filing", False),
                         ("bankruptcy", False), ("unsettled", False), ("otc_move", False), ("taken", False)]:
        got = derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), why)], s, NO_PROFILE)
        assert bool(got) is derived, why


def test_a_new_symbol_a_reused_ticker_and_an_unknown_security_are_no_derived_line():
    s = {"BBGOLD": _security(eras_name="SPECTRA ENERGY CORP", tickers=("SE",))}
    assert derivable([RefusedStep("BBGOLD", _step(["SEA LTD ADR (CYM)"]), "name")], s, NO_PROFILE) == set()   # SE 2017
    assert derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP"], kind=NEW_SYMBOL), "merged_out")],
                     {"BBGOLD": _security()}, NO_PROFILE) == set()
    assert derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP"]), "merged_out")], {}, NO_PROFILE) == set()


def test_the_old_lines_names_are_its_observed_names_and_its_issuers_names_until_the_step():
    sub = {"name": "NEW NAME INC", "formerNames": [
        {"name": "OLD NAME INC", "from": "2001-01-01T00:00:00.000Z", "to": "2018-12-22T00:00:00.000Z"}]}
    names = old_line_names(_security(eras_name="OBSERVED CO"), sub, "2018-12-21")
    assert names == ["OBSERVED CO", "OLD NAME INC"]            # NEW NAME INC began after the step: the new line's


def test_a_security_gets_a_pair_for_the_tickers_of_its_eras_only():
    """A ticker the line follow learned from the fails files (their spelling, `BFB`) is not an era's: no pair."""
    s = _security(tickers=("BF-B",))
    s.line_tickers = frozenset({"BFB"})
    got = derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), "merged_out")], {"BBGOLD": s}, NO_PROFILE)
    assert got == {("BF-B", "NEWCUSIP1")}


def test_a_profile_decides_which_issuer_names_count_through_derivable():
    """The issuer's former name ended on the step's first day, where its current name began: a description naming
    the former name is the old line's, one naming only the current name is the new line's."""
    profile = {"name": "QUARTZ TOOLS INC", "formerNames": [
        {"name": "ZENITH PAINT INC", "from": "2001-01-01T00:00:00.000Z", "to": "2018-12-21T00:00:00.000Z"}]}
    s = {"BBGOLD": _security(eras_name="SOMETHING ELSE CO")}
    got = lambda desc: derivable([RefusedStep("BBGOLD", _step([desc]), "merged_out")], s, lambda cik: profile)
    assert got("QUARTZ TOOLS INC COM") == set()
    assert got("ZENITH PAINT INC COM") == {("CI", "NEWCUSIP1")}
