"""Which refused steps of stage 4b are lines of the run (`derived_lines.derivable`), and the rounds that give the run
those lines (`identify_with_lines`)."""
from datetime import date
from types import SimpleNamespace

import delist_detection.identity.derived_lines as derived_lines
from delist_detection.identity.derived_lines import derivable, old_line_names
from delist_detection.identity.line_follow import NEW_SYMBOL, SWITCH, LineStep, RefusedStep
from delist_detection.identity.observations import DerivedFrom, Observation, TickerEra
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
    assert set(got) == {("CI", "NEWCUSIP1"), ("CIGNA", "NEWCUSIP1")}


def test_each_refusal_of_another_registrant_or_a_name_is_derivable_and_no_other_is():
    s = {"BBGOLD": _security()}
    for why, derived in [("merged_out", True), ("other_registrant", True), ("name", True), ("no_filing", False),
                         ("bankruptcy", False), ("unsettled", False), ("otc_move", False), ("taken", False)]:
        got = derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), why)], s, NO_PROFILE)
        assert bool(got) is derived, why


def test_a_new_symbol_a_reused_ticker_and_an_unknown_security_are_no_derived_line():
    s = {"BBGOLD": _security(eras_name="SPECTRA ENERGY CORP", tickers=("SE",))}
    assert derivable([RefusedStep("BBGOLD", _step(["SEA LTD ADR (CYM)"]), "name")], s, NO_PROFILE) == {}   # SE 2017
    assert derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP"], kind=NEW_SYMBOL), "merged_out")],
                     {"BBGOLD": _security()}, NO_PROFILE) == {}
    assert derivable([RefusedStep("BBGOLD", _step(["CIGNA CORP"]), "merged_out")], {}, NO_PROFILE) == {}


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
    assert set(got) == {("BF-B", "NEWCUSIP1")}


def test_a_profile_decides_which_issuer_names_count_through_derivable():
    """The issuer's former name ended on the step's first day, where its current name began: a description naming
    the former name is the old line's, one naming only the current name is the new line's."""
    profile = {"name": "QUARTZ TOOLS INC", "formerNames": [
        {"name": "ZENITH PAINT INC", "from": "2001-01-01T00:00:00.000Z", "to": "2018-12-21T00:00:00.000Z"}]}
    s = {"BBGOLD": _security(eras_name="SOMETHING ELSE CO")}
    got = lambda desc: derivable([RefusedStep("BBGOLD", _step([desc]), "merged_out")], s, lambda cik: profile)
    assert got("QUARTZ TOOLS INC COM") == {}
    assert set(got("ZENITH PAINT INC COM")) == {("CI", "NEWCUSIP1")}


def test_derivable_returns_the_origin_of_each_pair_and_keeps_the_first_of_two_steps_naming_one():
    """The security the step was refused from, its issuer, the refusal, the step's old CUSIP and its first day."""
    s = _security(cik=77, tickers=("CI", "CIGNA"))
    first = RefusedStep("BBGOLD", _step(["CIGNA CORP NEW COM STK"]), "merged_out")
    later = RefusedStep("BBGOLD", LineStep("BBGOLD", SWITCH, "OTHEROLD1", "NEWCUSIP1", "CI", "2019-01-02", "2019-01-08",
                                           ("CIGNA CORP NEW COM STK",)), "name")
    origin = DerivedFrom("BBGOLD", 77, "merged_out", "OLDCUSIP1", "2018-12-21")
    assert derivable([first], {"BBGOLD": s}, NO_PROFILE) == {("CI", "NEWCUSIP1"): origin,
                                                              ("CIGNA", "NEWCUSIP1"): origin}
    assert derivable([first, later], {"BBGOLD": s}, NO_PROFILE)[("CI", "NEWCUSIP1")] == origin
    assert derivable([later, first], {"BBGOLD": s}, NO_PROFILE)[("CI", "NEWCUSIP1")] == DerivedFrom(
        "BBGOLD", 77, "name", "OTHEROLD1", "2019-01-08")
    no_issuer = derivable([first], {"BBGOLD": _security(cik=None)}, NO_PROFILE)
    assert no_issuer[("CI", "NEWCUSIP1")].issuer_cik is None


ORIGIN = DerivedFrom("BBGOLD", 1, "merged_out", "OLDCUSIP1", "2018-12-21")


def _loop(monkeypatch, answers, verdicts=()):
    """`identify_with_lines` over scripted stages: round n's `derivable` answer is answers[n] (a set of pairs) and
    round n's identity holds the verdicts[n] (a mapping; none by default). `calls` holds each round's `derive`, `ftd`
    and `verdicts`."""
    calls, logs = [], []
    ftd = object()

    def identify(index, clients, **kw):
        calls.append((kw["derive"], kw["ftd"], kw["verdicts"]))
        n = len(calls)
        return SimpleNamespace(ftd=ftd, round=n, verdicts=dict(verdicts[n - 1]) if n <= len(verdicts) else {})

    monkeypatch.setattr(derived_lines, "identify", identify)
    monkeypatch.setattr(derived_lines, "follow_lines",
                        lambda identity, clients, **kw: SimpleNamespace(refused=[], securities={}))
    monkeypatch.setattr(derived_lines, "derivable",
                        lambda refused, securities, profile:
                        {p: ORIGIN for p in answers[min(len(calls), len(answers)) - 1]})
    clients = SimpleNamespace(issuers=SimpleNamespace(profile=lambda cik: None))
    identity, lines = derived_lines.identify_with_lines(None, clients, as_of=date(2026, 9, 25), log=logs.append)
    return calls, logs, identity, ftd


def test_the_loop_asks_again_until_a_round_derives_nothing_new_over_one_fails_index(monkeypatch):
    both = {("X", "AAA"), ("X", "BBB")}
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", "AAA")}, both, both])
    assert [set(c[0]) for c in calls] == [set(), {("X", "AAA")}, both]
    assert calls[0][1] is None and calls[1][1] is ftd and calls[2][1] is ftd      # the index is opened once
    assert identity.round == 3 and not any("not derived" in line for line in logs)


def test_the_loop_stops_at_the_bound_and_says_so(monkeypatch):
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", f"C{i}")} for i in range(10)])
    assert len(calls) == derived_lines.MAX_DERIVE_ROUNDS + 1
    assert any("not derived" in line for line in logs)


def test_a_run_with_no_derivable_step_asks_once(monkeypatch):
    calls, logs, identity, ftd = _loop(monkeypatch, [set()])
    assert len(calls) == 1


def test_the_loop_passes_each_rounds_verdicts_to_the_next_round(monkeypatch):
    asked = {("X", "AAA"): "without_old_issuer"}
    both = {("X", "AAA"), ("X", "BBB")}
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", "AAA")}, both, both], verdicts=[asked, asked])
    assert [dict(c[2]) for c in calls] == [{}, asked, asked] and len(calls) == 3


def test_a_pair_with_a_not_made_verdict_is_never_new_and_does_not_keep_the_loop_going(monkeypatch):
    """Round 2's identity judges AAA's era not made (rule J) and stage 4b refuses the step again: AAA is derived
    already and judged, so the loop ends after two rounds. A pair judged not made that `derivable` gives and `derive`
    does not hold (a verdict an earlier call made) is not new either."""
    judged = {("X", "AAA"): "not_made"}
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", "AAA")}] * 3, verdicts=[{}, judged])
    assert len(calls) == 2 and dict(identity.verdicts) == judged
    calls, logs, identity, ftd = _loop(monkeypatch, [{("X", "AAA"), ("X", "BBB")}] * 3, verdicts=[judged, judged])
    assert [set(c[0]) for c in calls] == [set(), {("X", "BBB")}] and len(calls) == 2
