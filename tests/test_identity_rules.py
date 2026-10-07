"""Sub-plan 5h's rules on small doubles built from their real cases' answers (the cached EDGAR, OpenFIGI and fails
data the run read): the issuer in force kept for an era its ticker's rows decided (ERA 2013), ONEOK's 2026 holding
company past the fails data's last day, the ticker tier's post-bankruptcy holder (CRC, BTU), and no
continued-filings guess at the last sighting of a security with no CUSIP (WW 2013)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from delist_detection import pipeline
from delist_detection.cik_lookup import CikNameIndex, normalize_name
from delist_detection.classifier import DelistClassifier
from delist_detection.crsp_codes import CrspBucket
from delist_detection.delistings import Delisting, DelistingFinder, SecurityContext
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import FigiCandidate
from delist_detection.form25 import SecurityRef
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.last_trade import LastTrade
from delist_detection.line_follow import FOLD, SUCCESSOR, Decision
from delist_detection.manifest import StageMeter
from delist_detection.observations import Observation, split_eras
from delist_detection.security_master import EraResolution, Security, line_class_letter
from delist_detection.classifier import DelistRecord
from delist_detection.issuer_record import IssuerRecord
from delist_detection.ticker_resolver import TickerResolver


# --- rule D, ERA 2013: the issuer in force follows the fails rows, not the refuted observed name ----------------

ERA_SUBS = {    # the cached submissions' names
    1525221: {"name": "Bristow Group Inc.", "formerNames": [
        {"name": "ERA GROUP INC.", "from": "2011-08-02T04:00:00.000Z", "to": "2020-06-09T04:00:00.000Z"}]},
    73887: {"name": "Bristow Group Inc", "formerNames": [
        {"name": "OFFSHORE LOGISTICS INC", "from": "1994-07-07T00:00:00.000Z", "to": "2006-01-26T00:00:00.000Z"}]},
}


def _in_force_ctx():
    index = CikNameIndex([(normalize_name("BRISTOW GROUP INC"), 73887, "BRISTOW GROUP INC"),
                          (normalize_name("BRISTOW GROUP INC."), 1525221, "BRISTOW GROUP INC.")])
    edgar = SimpleNamespace(submissions=lambda cik: ERA_SUBS[int(cik)])
    clients = SimpleNamespace(edgar=edgar, issuers=IssuerRecord(edgar, name_index=index))
    return SimpleNamespace(clients=clients, meter=StageMeter(lambda *a: None))


def test_an_era_its_tickers_rows_decided_keeps_its_cik_in_force():
    """The snapshot named ERA 2013 BRISTOW GROUP INC, Era Group's 2020 name, which old Bristow (CIK 73887) carried
    then. Stage 2b took Era Group (CIK 1525221) from the rows under ERA; the issuer in force must not hand the
    sighting back to old Bristow by that name (its 2019 Form 25 would end Era Group's security)."""
    rows = [{"sec_id": "CIK1525221-COMMON", "as_of": "2013-06-28", "name": "BRISTOW GROUP INC",
             "issuer_cik": "1525221", "status": "mapped", "era": "ERA@2013-06-28"}]
    assert pipeline._issuers_in_force(_in_force_ctx(), rows) == {"CIK1525221-COMMON": [("2013-06-28", "73887")]}
    assert pipeline._issuers_in_force(_in_force_ctx(), rows, {"ERA@2013-06-28"}) == \
        {"CIK1525221-COMMON": [("2013-06-28", "1525221")]}


# --- rule E, OKE 2026: a holding company's new CUSIP the notice names, after the fails data's last day ----------

def _oke(ftd_rows, day=date(2026, 9, 9)):
    """ONEOK 2026: the 8-K12B of 2026-09-10 in the registrant's own list, the Form 25 notice naming "ONEOK, Inc.
    (New, CUSIP: 30609A109)", OpenFIGI's own composite for it (BBG024TZWVN1), the old CUSIP's last fails row
    2026-08-28 (the cached data's end)."""
    filings = [EdgarSubmission("0001039684-26-000001", "8-K12B", "2026-09-10", "", "", "k.htm")]
    figi = SimpleNamespace(map=lambda jobs: [{"data": [{"compositeFIGI": "BBG024TZWVN1", "ticker": "OKE",
                                                        "name": "ONEOK INC", "exchCode": "US",
                                                        "securityType": "Common Stock"}]} for _ in jobs])
    edgar = SimpleNamespace(recent_filings=lambda cik: filings)
    ctx = SimpleNamespace(clients=SimpleNamespace(edgar=edgar, issuers=IssuerRecord(edgar), figi=figi))
    era = split_eras([Observation("OKE", "2008-01-16", "ONEOK INC"), Observation("OKE", "2026-06-30", "ONEOK INC")])
    sec = Security("BBG000BQHGR6", 1039684, "COMMON", "ONEOK INC", "Common Stock", True, "cusip", "common", era)
    rec = DelistRecord("OKE", 1039684, "2026-09-28", 304, CrspBucket.EXCHANGE_TRANSFER, "medium", "", {})
    e = Delisting("BBG000BQHGR6", 1039684, "OKE", "2026-09-28", rec, LastTrade(day, "ex99_notice", ()),
                  None, None, "NYSE")
    texts = ["ONEOK, Inc. (New, CUSIP: 30609A109) common stock, par value $0.01 per share"]
    found = pipeline._Successors()
    link = pipeline._own_registration_link(ctx, e, texts, day, {sec.sec_id: sec},
                                           {sec.sec_id: ["682680103"]}, FtdIndex(ftd_rows), set(), found)
    return link, found


OLD_ROWS = [FtdRow("2026-08-28", "682680103", "OKE", "ONEOK INC (NEW)", 94.72)]


def test_a_named_new_cusip_after_the_fails_datas_end_is_the_successor():
    link, found = _oke(OLD_ROWS)
    assert link == ("BBG024TZWVN1", pipeline.BY_OWN_REGISTRATION)
    added = found.added["BBG024TZWVN1"]
    assert (added.ticker, added.span()) == ("OKE", ("2026-09-10", "2026-09-10"))


def test_a_line_successors_first_day_is_a_trading_day():
    """A Friday last trade starts the added successor on Monday, never on the Saturday."""
    link, found = _oke(OLD_ROWS, day=date(2026, 9, 11))
    assert found.added["BBG024TZWVN1"].span()[0] == "2026-09-14"


def test_the_predecessors_own_form_25_raises_no_unmatched_row_for_the_added_successor(monkeypatch):
    """Stage 9d searches the successor's Form 25s under the shared CIK: Legacy ONEOK's 25-NSE already owns the
    predecessor's ending, so its `form25_unmatched` item is not repeated for the successor (read from the item's
    typed filing, never its reason)."""
    from delist_detection.added_securities import AddedLineSuccessor
    from delist_detection.review_triage import FilingRef, ReviewItem
    link, found = _oke(OLD_ROWS)
    added = found.added["BBG024TZWVN1"]
    item = ReviewItem("BBG024TZWVN1", "OKE", 1039684, "form25_unmatched",
                      "25-NSE 0000876661-26-000770 ('COMMON'): ambiguous class",
                      filing=FilingRef("25-NSE", "0000876661-26-000770", "2026-09-18"))
    other = ReviewItem("BBG024TZWVN1", "OKE", 1039684, "form25_unmatched",
                       "25-NSE 0000876661-26-000999 ('COMMON'): ambiguous class",
                       filing=FilingRef("25-NSE", "0000876661-26-000999", "2026-09-18"))
    finder = SimpleNamespace(find=lambda ctx, fallback: ([], [item, other]))
    monkeypatch.setattr(pipeline, "listed_today", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "_context_builder", lambda *a, **k: (lambda s, listed: None))
    ctx = SimpleNamespace(clients=SimpleNamespace(figi=None, edgar=None), as_of=date(2026, 9, 25),
                          meter=StageMeter(lambda *a: None), log=lambda m: None)
    owner = SimpleNamespace(form25_sub=SimpleNamespace(accession="0000876661-26-000770"))
    out = pipeline._successor_endings(ctx, finder, {added.security.sec_id: added}, {}, {}, FtdIndex([]), None,
                                      [owner])
    assert out.review == [other]


def test_a_new_cusip_the_fails_data_reaches_must_show_its_rows():
    """Guard: when the fails data runs past the day and the new CUSIP has no row under the line's tickers, no link
    (as before 5h: the rows are the evidence the holders' shares went on there)."""
    link, found = _oke(OLD_ROWS + [FtdRow("2026-09-15", "999999999", "XYZ", "SOMETHING ELSE", 1.0)])
    assert link is None and not found.added


# --- rule F, CRC and BTU: the ticker tier's composite is the line that took the ticker over later --------------

def _cand(composite, ticker, name):
    return FigiCandidate(composite, name, ticker, "Common Stock", ())


def _ticker_line(sec_id, ticker, cand_ticker, name):
    era = split_eras([Observation(ticker, "2014-12-31", name), Observation(ticker, "2015-12-31", name)])
    sec = Security(sec_id, 1609253, "COMMON", name, "Common Stock", True, "ticker", "common", era)
    res = {era[0].key: EraResolution(era[0].key, sec_id, "ticker", _cand(sec_id, cand_ticker, name), (), ())}
    return sec, res


def test_a_ticker_pick_today_holding_the_ticker_folds_into_the_lines_next_composite():
    """CRC 2014-2016: the ticker gave BBG00Y04KP80 (CRC today, the post-2020 line); the 2016 reverse split's CUSIP
    13057Q206 is BBG0060B3M63, whose ticker is now CRCQQ (it went bankrupt in 2020): one security, BBG0060B3M63."""
    sec, res = _ticker_line("BBG00Y04KP80", "CRC", "CRC", "CALIFORNIA RESOURCES CORP")
    succ = Decision(SUCCESSOR, "BBG0060B3M63", candidate=_cand("BBG0060B3M63", "CRCQQ", "CALIFORNIA RESOURCES CORP"))
    assert pipeline._today_holder_fold(succ, sec, res, {"CRC"}) == Decision(FOLD, "BBG0060B3M63",
                                                                            candidate=succ.candidate)


def test_a_line_successor_that_kept_the_ticker_or_a_cusip_line_stays_a_successor():
    """Guards: the new composite holds the ticker today (a holding company's new line: the old one ended); the
    ticker pick names another ticker (an old line OpenFIGI still lists); a line confirmed by its CUSIP."""
    sec, res = _ticker_line("BBG00Y04KP80", "CRC", "CRC", "CALIFORNIA RESOURCES CORP")
    keeps = Decision(SUCCESSOR, "BBG0060B3M63", candidate=_cand("BBG0060B3M63", "CRC", "CALIFORNIA RESOURCES CORP"))
    assert pipeline._today_holder_fold(keeps, sec, res, {"CRC"}) == keeps
    sec2, res2 = _ticker_line("BBG00Y04KP80", "CRC", "CRCX", "CALIFORNIA RESOURCES CORP")
    moved = Decision(SUCCESSOR, "BBG0060B3M63", candidate=_cand("BBG0060B3M63", "CRCQQ", "CALIFORNIA RESOURCES CORP"))
    assert pipeline._today_holder_fold(moved, sec2, res2, {"CRC"}) == moved
    sec3 = Security(sec.sec_id, 1609253, "COMMON", sec.name, "Common Stock", True, "cusip", "common", sec.eras)
    assert pipeline._today_holder_fold(moved, sec3, res, {"CRC"}) == moved


# --- rule G, WW 2013: no continued-filings ending at the last sighting of a security with no CUSIP --------------

def _ww(fake_edgar, has_cusips):
    """WW 2012-2013, a 2018 name and ticker a snapshot carried back onto Weight Watchers (WTW then): no Form 25 in
    reach, the issuer kept filing its 10-Qs; the security holds no CUSIP (its old one maps to another composite)."""
    fake_edgar.submissions_by_cik[105319] = [
        EdgarSubmission("q1", "10-Q", "2014-05-01", "2014-03-31", "", "q1.htm"),
        EdgarSubmission("q2", "10-Q", "2014-08-01", "2014-06-30", "", "q2.htm"),
        EdgarSubmission("k1", "10-K", "2015-02-27", "2014-12-31", "", "k1.htm")]
    era = split_eras([Observation("WW", "2012-06-29", "WW INTERNATIONAL INC"),
                      Observation("WW", "2013-12-31", "WW INTERNATIONAL INC")])
    sec = Security("BBG000DY6735", 105319, "COMMON", "WW INTERNATIONAL INC", "Common Stock", True, "ticker",
                   "common", era)
    ctx = SecurityContext(security=sec, siblings=[SecurityRef(sec.sec_id, sec.share_class, sec.kind)],
                          ticker_on=lambda d: "WW", last_seen="2013-12-31", seen_after=lambda d: False,
                          listed_today=False, expected_name=sec.name, has_cusips=has_cusips)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    return DelistingFinder(fake_edgar, clf).find(ctx)


def test_a_security_with_no_cusip_gets_no_continued_filings_guess_at_its_last_sighting(fake_edgar):
    events, review = _ww(fake_edgar, has_cusips=False)
    assert events == [] and [r.flag for r in review] == ["ended_without_delisting"]


def test_a_security_with_its_cusip_keeps_the_continued_filings_ending(fake_edgar):
    """Guard: a security whose own CUSIP could show it stop keeps today's ending (a genuine no-Form-25 end)."""
    for has in (True, None):
        events, _ = _ww(fake_edgar, has_cusips=has)
        assert [(e.delist_date, e.record.crsp_code) for e in events] == [("2013-12-31", 304)], has


# --- rule B's class reading of an OpenFIGI name ----------------------------------------------------------------

def test_the_class_letter_an_openfigi_name_ends_with():
    assert [line_class_letter(n) for n in ("MSG NETWORKS INC- A", "STARZ - A", "GRAHAM HOLDINGS CO-CLASS B",
                                           "HUBBELL INC", "ALPHABET INC-CL A", "WW INTERNATIONAL INC")] == \
        ["A", "A", "B", None, "A", None]
