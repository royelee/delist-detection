"""successors.successor_by_terms and pipeline stage 8b (sub-plan 5c, ruling R1): the security a one-for-one, no-cash
exchange made the holders' shares, and the merger rows R1 rewrites as continuations."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from delist_detection import pipeline
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import SUCCESSOR_UNKNOWN, Delisting
from delist_detection.exchange_terms import OwnExchange
from delist_detection.last_trade import LastTrade
from delist_detection.successors import (NEW_ISSUER, NEW_ISSUER_DAYS, SAME_ISSUER_CLASS, SecurityStart,
                                         successor_anchor, successor_by_terms)
from tests import issuer_role_cases as ic

DAY = date(2020, 6, 30)


def _delisting(cik=1, ticker="OLD", day=DAY):
    rec = DelistRecord(ticker, cik, day.isoformat(), 304, CrspBucket.EXCHANGE_TRANSFER, "medium", "r",
                       {"flags": [SUCCESSOR_UNKNOWN]}, sec_id="OLD-ID", delist_date="2020-07-10")
    return Delisting("OLD-ID", cik, ticker, "2020-07-10", rec, LastTrade(day, "midas", ()), None, None, "NYSE")


def _own(names=("Newco",), letter="", own=False, ratio=1.0, cash=False):
    return OwnExchange(ratio, cash, "of Newco common stock", tuple(names), letter, own, "s")


def _ask(starts, own, *, since=None, names=None):
    since = since or {}
    names = names or {}
    return successor_by_terms(_delisting(), own, DAY, starts, issuer_since=lambda c: since.get(c),
                              issuer_names=lambda c: names.get(c, ()))


def test_a_new_issuers_security_named_by_the_target_is_the_successor():
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"NEWC"}, "2026-01-01", "COMMON")}
    assert _ask(starts, _own(), since={2: "2019-10-25"}, names={2: ("Newco Inc",)}) == ("NEW", NEW_ISSUER)
    # by its ticker alone (BHI: "one share of BHGE's Class A common stock")
    assert _ask(starts, _own(names=("NEWC",)), since={2: "2019-10-25"}) == ("NEW", NEW_ISSUER)


@pytest.mark.parametrize("age,linked", [(548, True), (NEW_ISSUER_DAYS, True), (NEW_ISSUER_DAYS + 1, False),
                                        (4125, False)], ids=["DowDuPont", "limit", "past", "Progressive"])
def test_only_a_new_issuer_is_a_continuation(age, linked):
    """DowDuPont was 548 days old (Linde 517, Viatris 388): new holding companies; Progressive Waste (4,125 days),
    GCI Liberty (8,442) and Willis (5,347) existed, so their deals stay mergers."""
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"NEWC"}, "", "COMMON")}
    since = {2: (DAY - timedelta(days=age)).isoformat()}
    assert (_ask(starts, _own(), since=since, names={2: ("Newco Inc",)}) is not None) is linked


def test_without_a_name_tie_a_new_registrant_sighted_in_the_window_is_no_successor():
    """AABA and BHGE, MSG and Alphabet: a new registrant first sighted near the end is not named by the target."""
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"BHGE"}, "", "COMMON")}
    assert _ask(starts, _own(names=("Holdco",)), since={2: "2020-01-01"}, names={2: ("Baker Hughes Co",)}) is None


def test_a_new_issuer_first_sighted_outside_the_window_is_no_successor():
    starts = {"NEW": SecurityStart("2020-08-01", 2, {"NEWC"}, "", "COMMON")}
    assert _ask(starts, _own(), since={2: "2020-01-01"}, names={2: ("Newco Inc",)}) is None


def test_the_same_issuers_class_the_target_names_alive_after_the_end():
    """CMCSK into CMCSA (Class A, sighted since 2007), CWENA into CWEN (Class C), HUB-B into HUBB (the common)."""
    starts = {"A": SecurityStart("2007-12-17", 1, {"CMCSA"}, "2026-09-25", "CLASS A"),
              "C": SecurityStart("2008-01-02", 1, {"CMCSC"}, "2026-09-25", "CLASS C"),
              "GONE": SecurityStart("2008-01-02", 1, {"CMCSG"}, "2020-06-01", "CLASS A")}
    assert _ask(starts, _own(names=(), letter="A", own=True)) == ("A", SAME_ISSUER_CLASS)
    assert _ask(starts, _own(names=(), letter="C", own=True)) == ("C", SAME_ISSUER_CLASS)
    assert _ask(starts, _own(names=(), letter="B", own=True)) is None


def test_two_new_lines_of_one_issuer_are_told_apart_by_the_class_letter_and_two_of_one_class_tie():
    """Liberty Live Holdings' Series A and Series C, both first sighted 2025-12-17."""
    starts = {"LA": SecurityStart("2020-07-02", 2, {"LLYVA"}, "", "CLASS A"),
              "LC": SecurityStart("2020-07-02", 2, {"LLYVK"}, "", "CLASS C")}
    names = {2: ("Liberty Live Holdings, Inc.",)}
    own = _own(names=("Liberty Live Holdings",), letter="A")
    assert _ask(starts, own, since={2: "2020-01-01"}, names=names) == ("LA", NEW_ISSUER)
    starts["LA2"] = SecurityStart("2020-07-02", 2, {"LLYVB"}, "", "CLASS A")
    assert _ask(starts, own, since={2: "2020-01-01"}, names=names) is None


def test_no_link_for_another_ratio_cash_or_two_readings():
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"NEWC"}, "", "COMMON")}
    since, names = {2: "2020-01-01"}, {2: ("Newco Inc",)}
    for own in (_own(ratio=0.9042), _own(cash=True), replace(_own(), ambiguous=True)):
        assert _ask(starts, own, since=since, names=names) is None


def test_the_anchor_is_the_last_trade_then_the_form25_then_the_anchor_8k():
    d = _delisting()
    assert successor_anchor(d) == DAY
    d.last_trade = LastTrade(None, "", ())
    d.record.evidence["anchor_8k"] = {"filing_date": "2020-07-02"}
    assert successor_anchor(d) == date(2020, 7, 2)
    d.record.evidence = {}
    assert successor_anchor(d) == date(2020, 7, 10)


# --- stage 8b on the real cases (tests/fixtures/issuer_role/) ---

def _stage8b(sec_id, terms=None):
    c = ic.clients()
    found, _ = ic.find(sec_id, c)
    securities, _, cusips, ftd = ic.world()
    sightings = {sid: pipeline.ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, ic.AS_OF, lambda *a: None, 1, pipeline.run_manifest.StageMeter(lambda *a: None))
    payouts = ic._payouts(sec_id, found)
    if terms is not None:
        payouts.llm_terms = {k: replace(t, cash_per_share=terms[0], stock_ratio=terms[1])
                             for k, t in payouts.llm_terms.items()}
    r1 = pipeline._r1_continuations(ctx, found, securities, sightings, payouts, pipeline.Overrides())
    return found, payouts, r1


def test_a_rewritten_merger_drops_its_payout_reads_and_keeps_its_old_bucket_in_review():
    found, payouts, r1 = _stage8b("BBG000BHBK84")                                         # DOW 2017
    d = found[0]
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (
        CrspBucket.EXCHANGE_TRANSFER, 304, "BBG00BN961G4")
    assert pipeline.R1_CONTINUATION in d.flags and d.key not in payouts.llm_terms
    assert [i.flag for i in r1.review] == [pipeline.R1_REBUCKETED] and "was merger (CRSP 231" in r1.review[0].reason


@pytest.mark.parametrize("cash,flips", [(16.50, True), (16.00, False), (None, True)], ids=["dividend", "cash", "none"])
def test_a_special_dividend_is_no_cash_but_other_cash_keeps_the_merger(cash, flips):
    """KRFT 2015: the LLM read $16.50 and one Kraft Heinz share; the 8-K calls the $16.50 a special cash dividend
    (operator ruling 2026-10-04: never consideration). $16.00 is not the dividend: cash in the exchange."""
    found, _, _ = _stage8b("BBG001YMS0B8", terms=(cash, 1.0))
    assert (found[0].record.bucket is CrspBucket.EXCHANGE_TRANSFER) is flips


def test_a_merger_terms_override_decides_the_row():
    c = ic.clients()
    found, _ = ic.find("BBG000BHBK84", c)
    securities, _, cusips, ftd = ic.world()
    sightings = {sid: pipeline.ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, ic.AS_OF, lambda *a: None, 1, pipeline.run_manifest.StageMeter(lambda *a: None))
    over = pipeline.Overrides(merger_terms={"BBG000BHBK84": {"stock_ratio": 1.0}})
    pipeline._r1_continuations(ctx, found, securities, sightings, ic._payouts("BBG000BHBK84", found), over)
    assert found[0].record.bucket is CrspBucket.MERGER


# --- stage 8b's 8-K12B path (final fix wave) ---
from types import SimpleNamespace as _NS  # noqa: E402

import requests  # noqa: E402


class _Ages:
    def __init__(self, since="2016-06-01", names=("TITAN TECHNOLOGIES CORP",)):
        self._since, self._names = since, names

    def since(self, cik):
        return self._since

    def names(self, cik):
        return self._names


def _r1_ctx(monkeypatch, cand):
    monkeypatch.setattr(pipeline, "successor_search_name", lambda *a: "Rovi Corp")
    monkeypatch.setattr(pipeline, "successor_from_8k12b", lambda *a, **k: (999, cand, "2016-07-20"))
    edgar = _NS(full_text_search=lambda *a, **k: [])
    clients = _NS(edgar=edgar, figi=None)
    return pipeline._RunContext(clients, date(2026, 9, 25), lambda *a: None, 1,
                                pipeline.run_manifest.StageMeter(lambda *a: None))


def _r1_call(ctx, target, ages):
    own = OwnExchange(1.0, False, "of Titan Technologies Corporation common stock", (target,), "", False, "s")
    e = _NS(cik=1, ticker="ROVI", sec_id="R", delist_date="2016-07-20", last_trade=_NS(day=None))
    sec = _NS(share_class="COMMON", name="ROVI CORP", own_tickers=lambda: {"ROVI"})
    out = pipeline._R1()
    pending: dict = {}
    link = pipeline._r1_successor(ctx, e, sec, own, date(2016, 7, 20), {}, ages, {}, {}, out, pending)
    return link, pending


def test_an_8k12b_successor_needs_the_name_tie(monkeypatch):
    """ROVI-shaped: a candidate the R1 statement does not name is refused; the one it names is taken."""
    cand = _NS(composite="BBGTITAN", ticker="TTEC", name="TITAN TECHNOLOGIES CORP", security_type="Common Stock")
    ctx = _r1_ctx(monkeypatch, cand)
    link, pending = _r1_call(ctx, "Titan Technologies Corporation", _Ages())
    assert link == ("BBGTITAN", pipeline.BY_TERMS) and list(pending) == ["BBGTITAN"]
    link, pending = _r1_call(ctx, "Some Other Holdings", _Ages())
    assert link is None and pending == {}


def test_the_issuer_age_reads_survive_a_request_failure_and_count_it():
    from delist_detection.fatal import FATAL

    class _Edgar:
        def recent_filings(self, cik):
            raise requests.ConnectionError("down")

        def submissions(self, cik):
            raise requests.Timeout("slow")

    ages = pipeline._IssuerAge(_Edgar())
    assert ages.since(5) is None and ages.names(5) == () and ages.failures == 2

    class _Blocked(_Edgar):
        def recent_filings(self, cik):
            raise FATAL[0]("blocked")

    with pytest.raises(FATAL):
        pipeline._IssuerAge(_Blocked()).since(5)


def test_a_failed_issuer_age_read_makes_the_rewritten_row_resolution_degraded():
    """DOW 2017: reading the new issuer's filing list fails. The merger stays, flagged degraded on its own row and
    in review; no successor is added."""
    class _Edgar(ic.FixtureEdgar):
        owner = None                 # armed once the finder has read the registrant's own filings

        def recent_filings(self, cik):
            if self.owner is not None and cik != self.owner:
                raise requests.ConnectionError("down")
            return super().recent_filings(cik)

    edgar = _Edgar()
    c = ic.clients(edgar)
    found, _ = ic.find("BBG000BHBK84", c)
    edgar.owner = found[0].cik
    securities, _, cusips, ftd = ic.world()
    sightings = {sid: pipeline.ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, ic.AS_OF, lambda *a: None, 1, pipeline.run_manifest.StageMeter(lambda *a: None))
    r1 = pipeline._r1_continuations(ctx, found, securities, sightings, ic._payouts("BBG000BHBK84", found),
                                    pipeline.Overrides())
    assert found[0].record.bucket is CrspBucket.MERGER and r1.added == {}
    assert "resolution_degraded" in found[0].flags
    assert [i.flag for i in r1.review] == ["resolution_degraded"]

