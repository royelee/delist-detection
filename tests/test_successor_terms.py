"""successors.successor_by_terms and pipeline stage 8b (sub-plan 5c, ruling R1): the security a one-for-one, no-cash
exchange made the holders' shares, and the merger rows R1 rewrites as continuations."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from delist_detection import pipeline
from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.endings.delistings import SUCCESSOR_UNKNOWN, Delisting
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.endings.exchange_terms import OwnExchange
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.endings.last_trade import LastTrade
from delist_detection.endings.own_shares import NEW_ISSUER_DAYS
from delist_detection.endings.successors import NEW_ISSUER, SAME_ISSUER_CLASS, SecurityStart, successor_by_terms
from tests import issuer_role_cases as ic

DAY = date(2020, 6, 30)


def _delisting(cik=1, ticker="OLD", day=DAY):
    rec = DelistRecord(ticker, cik, day.isoformat(), 304, CrspBucket.EXCHANGE_TRANSFER, "medium", "r",
                       {"flags": [SUCCESSOR_UNKNOWN]}, sec_id="OLD-ID", delist_date="2020-07-10")
    return Delisting("OLD-ID", cik, ticker, "2020-07-10", rec, LastTrade(day, "midas", ()), None, None, "NYSE")


def _own(names=("Newco",), letter="", own=False, ratio=1.0, cash=False):
    return OwnExchange(ratio, cash, "of Newco common stock", tuple(names), letter, own, "s")


class _Books:
    """An EDGAR double for the issuer record: each CIK's first filing (`since`, ISO) and its EDGAR names (current
    first)."""

    def __init__(self, since=None, names=None):
        self.since, self.names = since or {}, names or {}

    def recent_filings(self, cik):
        day = self.since.get(int(cik))
        return [EdgarSubmission("0000000000-00-000001", "10-K", day, "", "", "k.htm")] if day else []

    def submissions(self, cik):
        current, *former = self.names.get(int(cik), ("",))
        return {"name": current, "formerNames": [{"name": n} for n in former]}


def _ask(starts, own, *, since=None, names=None):
    return successor_by_terms(_delisting(), own, DAY, starts, issuers=IssuerRecord(_Books(since, names)))


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


def test_a_split_off_subsidiarys_target_is_the_new_issuer_not_a_class_of_the_registrants_old_name():
    """Liberty Capital 2011 (FB-003): Liberty Media Corp (CIK 1355096, renamed Liberty Interactive) redeemed each
    Series A Liberty Capital share for one Series A share of Splitco, the new Liberty Media Corporation (CIK 1507934).
    The target names the registrant's former name too, so its own Series A line is a same-issuer candidate; the
    statement's target is a subsidiary (`target_subsidiary`), and the new issuer it names wins, as in
    `OwnShares.target_issuer`. Without a new-issuer candidate the registrant's class stands."""
    own = replace(_own(names=("Splitco Liberty", "Liberty Media Corporation"), letter="A"), target_subsidiary=True)
    starts = {"NEW": SecurityStart("2020-07-01", 2, {"LCPAD"}, "2026-01-01", "CLASS A"),
              "QVCA": SecurityStart("2008-01-02", 1, {"QVCA"}, "2026-09-25", "SERIES A")}
    names = {1: ("Liberty Interactive Corp", "Liberty Media Corp"), 2: ("Liberty Media Corp",)}
    assert _ask(starts, own, since={2: "2019-10-25"}, names=names) == ("NEW", NEW_ISSUER)
    assert _ask({"QVCA": starts["QVCA"]}, own, since={2: "2019-10-25"}, names=names) == ("QVCA", SAME_ISSUER_CLASS)
    # not a subsidiary: the two candidates of one letter tie, as before
    assert _ask(starts, replace(own, target_subsidiary=False), since={2: "2019-10-25"}, names=names) is None


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


def test_a_delistings_anchor_reads_its_form25_and_its_anchor_8k():
    """`Delisting.anchor` hands the last trade module (`last_trade.anchor_day`) its Form 25 and its anchor 8-K."""
    d = _delisting()
    assert d.anchor == DAY
    d.last_trade = LastTrade(None, "", ())
    d.record.evidence["anchor_8k"] = {"filing_date": "2020-07-02"}
    assert d.anchor == date(2020, 7, 2)
    d.record.evidence = {}
    assert d.anchor == date(2020, 7, 10)


# --- stage 8b on the real cases (tests/fixtures/issuer_role/) ---

def _stage8b(sec_id, terms=None):
    c = ic.clients()
    found, _ = ic.find(sec_id, c)
    securities, _, cusips, ftd = ic.world()
    sightings = {sid: pipeline.ticker_sightings(s, ftd, cusips[sid]) for sid, s in securities.items()}
    ctx = pipeline._RunContext(c, ic.AS_OF, lambda *a: None, 1, pipeline.run_manifest.StageMeter(lambda *a: None))
    values = ic._payouts(sec_id, found)
    if terms is not None:
        values.records = {k: replace(v, llm=replace(v.llm, cash_per_share=terms[0], stock_ratio=terms[1]))
                          for k, v in values.records.items()}
    r1 = pipeline._r1_continuations(ctx, found, securities, sightings, values)
    return found, values, r1


def test_a_rewritten_merger_drops_its_payout_reads_and_keeps_its_old_bucket_in_review():
    found, values, r1 = _stage8b("BBG000BHBK84")                                          # DOW 2017
    d = found[0]
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (
        CrspBucket.EXCHANGE_TRANSFER, 304, "BBG00BN961G4")
    assert pipeline.R1_CONTINUATION in d.flags and values.get(d.key) is None
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
    values = ic._payouts("BBG000BHBK84", found)
    values.caller_terms = {"BBG000BHBK84": {"stock_ratio": 1.0}}
    pipeline._r1_continuations(ctx, found, securities, sightings, values)
    assert found[0].record.bucket is CrspBucket.MERGER


# --- stage 8b's 8-K12B path (final fix wave) ---
from types import SimpleNamespace as _NS  # noqa: E402

import requests  # noqa: E402

from delist_detection.terms.llm_merger_extractor import MergerTerms  # noqa: E402
from delist_detection.terms.merger_value import MergerValue, MergerValues  # noqa: E402
from delist_detection.identity.security_master import Security  # noqa: E402

_ROVI_8K = EdgarSubmission("0001-16-1", "8-K", "2016-09-07", "", "2.01,3.01,5.01", "d.htm")


class _RoviBooks(_Books):
    """Rovi (CIK 1) and its 8-K stating what each share became; TITAN TECHNOLOGIES CORP (CIK 999), a new issuer."""

    def __init__(self, target):
        super().__init__({999: "2016-06-01"}, {999: ("TITAN TECHNOLOGIES CORP",), 1: ("ROVI CORP",)})
        self.text = (f"At the effective time, each share of the Company's common stock was converted into one share "
                     f"of {target} common stock.")
        self.full_text_search = lambda *a, **k: []

    def recent_filings(self, cik):
        return [_ROVI_8K] if int(cik) == 1 else super().recent_filings(cik)

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.text if accession == _ROVI_8K.accession else ""


def _rovi_stage(monkeypatch, target):
    """Stage 8b over a ROVI-shaped merger row (its terms one share and no cash), the 8-K12B search scripted to find
    TITAN TECHNOLOGIES CORP: the row and the stage's answer."""
    cand = _NS(composite="BBGTITAN", ticker="TTEC", name="TITAN TECHNOLOGIES CORP", security_type="Common Stock")
    monkeypatch.setattr(pipeline, "successor_search_name", lambda *a: "Rovi Corp")
    monkeypatch.setattr(pipeline, "successor_from_8k12b", lambda *a, **k: (999, cand, "2016-09-08"))
    books = _RoviBooks(target)
    clients = pipeline.Clients(edgar=books, resolver=None, classifier=None, figi=None, ftd_client=None,
                               issuers=IssuerRecord(books))
    ctx = pipeline._RunContext(clients, date(2026, 9, 25), lambda *a: None, 1,
                               pipeline.run_manifest.StageMeter(lambda *a: None))
    rec = DelistRecord("ROVI", 1, "2016-09-07", 231, CrspBucket.MERGER, "medium", "merger", {"flags": []},
                       sec_id="R", delist_date="2016-09-08")
    d = Delisting("R", 1, "ROVI", "2016-09-08", rec, LastTrade(date(2016, 9, 7), "midas", ()), None, None, "NASDAQ")
    sec = Security("R", 1, "COMMON", "ROVI CORP", "Common Stock", True, "cusip")
    values = MergerValues({d.key: MergerValue(d.key, llm=MergerTerms("stock", None, 1.0, None, "TTEC", "high", "x",
                                                                       ""))})
    return d, pipeline._r1_continuations(ctx, [d], {"R": sec}, {}, values)


def test_an_8k12b_successor_needs_the_name_tie(monkeypatch):
    """ROVI-shaped: the candidate the R1 statement names is taken and added; one it does not name is refused."""
    d, r1 = _rovi_stage(monkeypatch, "Titan Technologies Corporation")
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBGTITAN")
    assert list(r1.added) == ["BBGTITAN"] and r1.links[d.key] == ("BBGTITAN", pipeline.BY_TERMS)
    assert d.own_shares is not None and d.own_shares.statement.target_names == ("Titan Technologies Corporation",)
    d, r1 = _rovi_stage(monkeypatch, "Some Other Holdings")
    assert d.record.bucket is CrspBucket.MERGER and r1.added == {} and r1.links == {}


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
    r1 = pipeline._r1_continuations(ctx, found, securities, sightings, ic._payouts("BBG000BHBK84", found))
    assert found[0].record.bucket is CrspBucket.MERGER and r1.added == {}
    assert "resolution_degraded" in found[0].flags
    assert [i.flag for i in r1.review] == ["resolution_degraded"]


# --- batch 3 gate, FNFV 2017: terms that failed the payout gate do not outvote the registrant's own statement ---

class _TitanBooks(_RoviBooks):
    """ROVI's books, with EDGAR's ticker file listing the new issuer."""

    def company_tickers(self):
        return {"TTEC": {"cik_str": 999, "ticker": "TTEC", "title": "TITAN TECHNOLOGIES CORP"}}


def _failed_gate_stage(monkeypatch, *, flags, ratio=0.3066, target="Titan Technologies Corporation", answers=None,
                       with_values=False):
    """Stage 8b over a merger row whose LLM terms (`ratio` of another acquirer's shares, read from the wrong filing)
    are not one share, `flags` the payout gate's; no 8-K12B candidate."""
    monkeypatch.setattr(pipeline, "successor_search_name", lambda *a: "Rovi Corp")
    monkeypatch.setattr(pipeline, "successor_from_8k12b", lambda *a, **k: None)
    books = _TitanBooks(target)
    clients = pipeline.Clients(edgar=books, resolver=None, classifier=None, figi=None, ftd_client=None,
                               issuers=IssuerRecord(books))
    ctx = pipeline._RunContext(clients, date(2026, 9, 25), lambda *a: None, 1,
                               pipeline.run_manifest.StageMeter(lambda *a: None))
    rec = DelistRecord("ROVI", 1, "2016-09-07", 231, CrspBucket.MERGER, "medium", "merger", {"flags": list(flags)},
                       sec_id="R", delist_date="2016-09-08")
    d = Delisting("R", 1, "ROVI", "2016-09-08", rec, LastTrade(date(2016, 9, 7), "midas", ()), None, None, "NASDAQ")
    sec = Security("R", 1, "COMMON", "ROVI CORP", "Common Stock", True, "cusip")
    values = MergerValues({d.key: MergerValue(d.key, llm=MergerTerms("stock", None, ratio, None, "BKI", "high", "x", ""),
                                              flags=tuple(flags))})
    r1 = pipeline._r1_continuations(ctx, [d], {"R": sec}, {}, values, answers)
    return (d, r1, values) if with_values else (d, r1)


def test_terms_that_failed_the_gate_give_way_to_a_one_for_one_statement_into_a_new_issuer(monkeypatch):
    """FNFV 2017: the LLM read BKI's 0.3066 from the wrong filing (terms_gate_failed:fail_sanity); the registrant's
    own 8-K says each FNFV share was redeemed for one Cannae share, a new issuer the run holds no security of. The row
    stays a merger whose terms are the statement's (FB-003, the consumer's ask): one share of the new issuer, a
    received close asked under its EDGAR ticker with its EDGAR name, no gate; no continuation without a successor."""
    d, r1, values = _failed_gate_stage(monkeypatch, flags=["terms_gate_failed:fail_sanity"], with_values=True)
    assert d.record.bucket is CrspBucket.MERGER and r1.links == {} and r1.restated == [d.key]
    assert pipeline.R1_CONTINUATION not in d.flags and SUCCESSOR_UNKNOWN not in d.flags
    v = values.get(d.key)
    assert (v.statement.stock_ratio, v.statement.ticker, v.statement.name) == (1.0, "TTEC", "TITAN TECHNOLOGIES CORP")
    assert v.request == ("TTEC", "") and v.flags == ("terms_gate_skipped:own_statement",)
    assert values.requests([{"sec_id": "R", "delist_date": "2016-09-08"}]) == {
        d.key: ("TTEC", "", "TITAN TECHNOLOGIES CORP")}
    assert values.table_terms(d.key).stock_ratio == 1.0 and values.table_terms(d.key).acquirer_price is None


def test_an_answered_close_prices_the_statements_stock_leg(monkeypatch):
    """A second run with the request answered: the received close under the new issuer's ticker prices the leg."""
    from delist_detection.outputs.price_requests import PriceAnswers, PriceKey
    answers = PriceAnswers({PriceKey("R", "2016-09-07", "received_close", "TTEC", "2016-09-08"): 21.5})
    d, _, values = _failed_gate_stage(monkeypatch, flags=["llm_gate_failed"], answers=answers, with_values=True)
    assert values.table_terms(d.key).acquirer_price == 21.5


def test_terms_the_gate_kept_still_outvote_the_statement(monkeypatch):
    """Jefferies 2013: terms the gate has no complaint about (0.81 of Leucadia) keep the merger."""
    d, r1 = _failed_gate_stage(monkeypatch, flags=[], ratio=0.81)
    assert d.record.bucket is CrspBucket.MERGER and r1.links == {}


@pytest.mark.parametrize("flag", ["terms_gate_failed:no_last_close", "terms_gate_failed:no_acq_price",
                                  "terms_gate_failed:no_ratio"])
def test_terms_the_gate_could_not_check_still_outvote_the_statement(monkeypatch, flag):
    """Paramount Global's class A 2025 (batch 3 gate): the Skydance merger's cash ($15, the closing 8-K) failed the
    gate only for want of a last close; a gate that could not compare the terms with a close refused nothing, so a
    one-for-one sentence about some holders' shares does not make the merger a continuation."""
    d, r1 = _failed_gate_stage(monkeypatch, flags=[flag])
    assert d.record.bucket is CrspBucket.MERGER and r1.links == {}


def test_failed_terms_and_a_statement_into_no_new_issuer_keep_the_merger(monkeypatch):
    d, r1 = _failed_gate_stage(monkeypatch, flags=["llm_gate_failed"], target="Some Other Holdings")
    assert d.record.bucket is CrspBucket.MERGER and r1.links == {}

