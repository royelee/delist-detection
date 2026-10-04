"""pipeline._follow_lines (stage 4b) on its own: the rounds, the holders, the failures that must stop a run and the
reads that must not be cached. The fails-row side (`candidate_steps`) and the filings check (`corroborate`) are
scripted here; tests/test_line_follow.py and test_pipeline.py cover them with real rows."""
from datetime import date
from types import SimpleNamespace

import pytest
import requests

import delist_detection.pipeline as pipeline
from delist_detection.edgar import EdgarBlocked
from delist_detection.line_follow import MAX_ROUNDS, SWITCH, LineStep
from delist_detection.manifest import StageMeter
from delist_detection.observations import TickerEra
from delist_detection.openfigi import OpenFigiUnavailable
from delist_detection.pipeline import Clients, _IssuerReads, _RunContext
from delist_detection.sec_stats import SEC_STATS
from delist_detection.security_master import EraResolution, Issuer, build_securities


def _answer(composite):
    return {"data": [{"figi": composite, "compositeFIGI": composite, "exchCode": "US", "ticker": "RS",
                      "name": "RS CO", "securityType": "Common Stock", "securityType2": "Common Stock"}]}


class _Figi:
    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.asked = answers or {}, error, []

    def map(self, jobs, use_cache=True):
        if self.error:
            raise self.error
        self.asked += [j["idValue"] for j in jobs]
        return [self.answers.get(j["idValue"], {"warning": "No identifier found."}) for j in jobs]


class _Edgar:
    def __init__(self, submissions=lambda cik: {}):
        self.submissions_fn, self.calls = submissions, 0

    def submissions(self, cik, fresh_after=None):
        self.calls += 1
        return self.submissions_fn(cik)

    def recent_filings(self, cik):
        return []

    def fetch_filing_text(self, cik, accession, primary_doc):
        return ""


class _Ftd:
    def extend(self, *a, **k):
        pass

    def last_date(self):
        return "2026-09-25"


def _world(specs):
    """specs: (sec_id, cik, ticker, [cusips]) -> (securities, resolutions, era_by_key, sec_cusips, answers)."""
    eras, res, issuers, cusips = {}, {}, {}, {}
    for sid, cik, ticker, cs in specs:
        era = TickerEra(ticker, "2008-01-01", "2009-01-01")
        eras[era.key] = era
        res[era.key] = EraResolution(era.key, sid, "placeholder" if sid.startswith("CIK") else "cusip", None, (),
                                     tuple(cs))
        issuers[era.key] = Issuer(cik)
        cusips[sid] = list(cs)
    return build_securities(res, eras, issuers), res, eras, cusips, SimpleNamespace(issuers=issuers)


def _stage(monkeypatch, specs, nxt, *, figi=None, edgar=None, line_end=None):
    """Stage 4b over `specs`, every line's step scripted: `nxt` maps a CUSIP to the one it switches to."""
    def steps_of(sid, cusips, tickers, ftd, **kw):
        if cusips and cusips[-1] in nxt:
            return [LineStep(sid, SWITCH, cusips[-1], nxt[cusips[-1]], "RS", "2012-01-01", "2012-01-02")]
        return []

    monkeypatch.setattr(pipeline, "candidate_steps", steps_of)
    monkeypatch.setattr(pipeline, "line_end", lambda *a, **k: line_end)
    monkeypatch.setattr(pipeline, "corroborate", lambda step, **kw: ("8-K 5.03", ""))
    log = lambda *a: None
    ctx = _RunContext(Clients(edgar=edgar or _Edgar(), resolver=None, classifier=None, figi=figi or _Figi(),
                              ftd_client=None), date(2026, 9, 25), log, 1, StageMeter(log))
    securities, res, eras, cusips, answers = _world(specs)
    return pipeline._follow_lines(ctx, securities, res, eras, cusips, _Ftd(), date(2004, 1, 1), answers)


def _flags(lines):
    return [(r.sec_id, r.flag) for r in lines.review]


def test_a_chain_of_switches_is_followed_up_to_max_rounds_and_no_further(monkeypatch):
    """WIN: two reverse splits are two steps of one line; the follow takes MAX_ROUNDS steps at most."""
    chain = {"C1": "C2", "C2": "C3", "C3": "C4", "C4": "C5", "C5": "C6"}
    lines = _stage(monkeypatch, [("BBGA", 1, "AA", ["C1"])], chain)
    assert MAX_ROUNDS == 3
    assert lines.sec_cusips["BBGA"] == ["C1", "C2", "C3", "C4"]          # the C4 -> C5 step is a fourth
    short = _stage(monkeypatch, [("BBGA", 1, "AA", ["C1"])], {"C1": "C2", "C2": "C3"})
    assert short.sec_cusips["BBGA"] == ["C1", "C2", "C3"]
    assert [f for _, f in _flags(short)] == ["line_followed", "line_followed"]


def test_a_fold_chain_collapses_to_the_final_figi():
    securities, res, eras, cusips, _ = _world([("CIK1-COMMON", 1, "AA", ["C1"]), ("CIK2-COMMON", 2, "BB", ["D1"])])
    out = pipeline._Lines(securities, res, cusips, renames={"CIK1-COMMON": "CIK2-COMMON"})
    cand = SimpleNamespace(composite="BBGX1")
    pipeline._fold(out, "CIK2-COMMON", "BBGX1", cand, LineStep("CIK2-COMMON", SWITCH, "D1", "D2", "BB", "x", "y"), {})
    assert out.renames == {"CIK1-COMMON": "BBGX1", "CIK2-COMMON": "BBGX1"}
    assert out.sec_cusips == {"CIK1-COMMON": ["C1"], "BBGX1": ["D1", "D2"]}


def _fingerprint(lines):
    return ({k: (s.sec_id, s.issuer_cik, s.figi_source, tuple(e.key for e in s.eras), s.line_tickers)
             for k, s in lines.securities.items()},
            lines.sec_cusips, lines.renames, {k: (v.composite, v.step.new_cusip) for k, v in lines.successors.items()},
            sorted(_flags(lines)))


def test_the_securities_in_any_order_give_the_same_lines(monkeypatch):
    specs = [("BBGA", 1, "AA", ["A1"]), ("CIK5-COMMON", 5, "PP", ["P1"]), ("BBGF", 6, "FF", ["F1"])]
    nxt = {"A1": "A2", "P1": "P2", "F1": "F2"}
    figi = lambda: _Figi({"P2": _answer("BBGX1"), "F2": _answer("BBGY1")})
    fwd = _stage(monkeypatch, specs, nxt, figi=figi())
    rev = _stage(monkeypatch, list(reversed(specs)), nxt, figi=figi())
    assert _fingerprint(fwd) == _fingerprint(rev)
    assert fwd.renames == {"CIK5-COMMON": "BBGX1"} and set(fwd.successors) == {"BBGF"}
    assert fwd.sec_cusips == {"BBGA": ["A1", "A2"], "BBGX1": ["P1", "P2"], "BBGF": ["F1"]}


def test_a_new_cusip_one_security_took_is_held_for_the_rest_of_the_round(monkeypatch):
    """Two lines of the run both step to C9 (no US line for it): the first (sec_id order) takes it, the second is
    refused, in any input order."""
    specs = [("BBGA", 1, "AA", ["A1"]), ("BBGB", 1, "BB", ["B1"])]
    for order in (specs, list(reversed(specs))):
        lines = _stage(monkeypatch, order, {"A1": "C9", "B1": "C9"})
        assert lines.sec_cusips == {"BBGA": ["A1", "C9"], "BBGB": ["B1"]}
        assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGB", "line_follow_refused:taken")]


def test_a_new_cusip_whose_composite_another_issuers_security_holds_is_refused(monkeypatch):
    """The step is otherwise valid (corroborated, one composite): only R2's other_issuer refusal stops it."""
    specs = [("BBGA", 1, "AA", ["A1"]), ("BBGO", 2, "OO", ["O1"])]
    lines = _stage(monkeypatch, specs, {"A1": "C9"}, figi=_Figi({"C9": _answer("BBGO")}))
    assert lines.sec_cusips == {"BBGA": ["A1"], "BBGO": ["O1"]} and lines.successors == {}
    assert _flags(lines) == [("BBGA", "line_follow_refused:other_issuer")]


def test_openfigi_unavailable_inside_the_stage_stops_the_run(monkeypatch):
    with pytest.raises(OpenFigiUnavailable):
        _stage(monkeypatch, [("BBGA", 1, "AA", ["A1"])], {"A1": "A2"}, figi=_Figi(error=OpenFigiUnavailable("x")))


def test_a_refused_submissions_read_inside_the_stage_stops_the_run(monkeypatch):
    def blocked(cik):
        raise EdgarBlocked("403")

    with pytest.raises(EdgarBlocked):
        _stage(monkeypatch, [("BBGA", 1, "AA", ["A1"])], {"A1": "A2"}, edgar=_Edgar(blocked))


def test_a_degraded_submissions_read_gives_the_security_a_resolution_degraded_row(monkeypatch):
    def stale(cik):
        SEC_STATS.degraded("submissions")        # a stale copy answered
        return {}

    lines = _stage(monkeypatch, [("BBGA", 1, "AA", ["A1"])], {"A1": "A2"}, edgar=_Edgar(stale))
    assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGA", "resolution_degraded")]


def test_a_failed_read_is_not_cached_and_marks_its_issuer_degraded():
    answers = iter([requests.ConnectionError("down"), {"name": "RS CO"}])

    def sub(cik):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    reads = _IssuerReads(_Edgar(sub))
    assert reads.sub(7) is None and reads.degraded == {7}
    assert reads.sub(7) == {"name": "RS CO"}          # asked again, not remembered as a failure
    assert reads.sub(7) == {"name": "RS CO"} and reads.edgar.calls == 2


def test_a_failed_read_inside_the_stage_gives_a_resolution_degraded_row(monkeypatch):
    def down(cik):
        raise requests.ConnectionError("down")

    lines = _stage(monkeypatch, [("BBGA", 1, "AA", ["A1"])], {"A1": "A2"}, edgar=_Edgar(down))
    assert ("BBGA", "resolution_degraded") in _flags(lines)


def test_two_lines_of_one_round_cannot_take_the_same_successor_composite(monkeypatch):
    """Two FIGI lines whose new CUSIPs both map to BBGX1: the first (sec_id order) is its successor, the second is
    refused `taken`, in any input order."""
    specs = [("BBGA", 1, "AA", ["A1"]), ("BBGB", 2, "BB", ["B1"])]
    for order in (specs, list(reversed(specs))):
        lines = _stage(monkeypatch, order, {"A1": "A2", "B1": "B2"},
                       figi=_Figi({"A2": _answer("BBGX1"), "B2": _answer("BBGX1")}))
        assert set(lines.successors) == {"BBGA"}
        assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGB", "line_follow_refused:taken")]


def test_a_failed_read_that_leaves_no_step_still_gives_a_resolution_degraded_row(monkeypatch):
    def down(cik):
        raise requests.ConnectionError("down")

    lines = _stage(monkeypatch, [("BBGA", 1, "AA", ["A1"])], {}, edgar=_Edgar(down))
    assert _flags(lines) == [("BBGA", "resolution_degraded")]


def test_a_failed_8k_text_read_that_leaves_no_step_gives_one_resolution_degraded_row(monkeypatch):
    from delist_detection.edgar import EdgarSubmission
    from delist_detection.line_follow import LineEnd

    class Down(_Edgar):
        def recent_filings(self, cik):
            return [EdgarSubmission("a1", "8-K", "2012-01-05", "", "5.03", "d.htm")]

        def fetch_filing_text(self, cik, accession, primary_doc):
            raise requests.ConnectionError("down")

    lines = _stage(monkeypatch, [("BBGA", 1, "AA", ["A1"])], {}, edgar=Down(),
                   line_end=LineEnd("A1", "2012-01-01", "2012-01-01"))
    assert _flags(lines) == [("BBGA", "resolution_degraded")]


def test_the_text_sources_filter_the_8ks_before_the_cap():
    """A busy issuer's coded 8-K among more than MAX_TEXTS uncoded ones nearer the day is still read."""
    from delist_detection.edgar import EdgarSubmission
    from delist_detection.line_follow import MAX_TEXTS, LineEnd

    uncoded = [EdgarSubmission(f"u{i}", "8-K", "2012-01-01", "", "8.01", "d.htm") for i in range(MAX_TEXTS + 2)]
    coded = EdgarSubmission("c1", "8-K", "2012-01-20", "", "5.03", "d.htm")
    read = []

    class Many(_Edgar):
        def recent_filings(self, cik):
            return [*uncoded, coded]

        def fetch_filing_text(self, cik, accession, primary_doc):
            read.append(accession)
            return "the CUSIP number changed to 316645100"

    securities, *_ = _world([("BBGA", 1, "AA", ["A1"])])
    symbols, cusips = pipeline._text_sources(_IssuerReads(Many()), securities["BBGA"],
                                             LineEnd("A1", "2012-01-01", "2012-01-01"))
    assert read == ["c1"] and cusips == {"316645100"}
