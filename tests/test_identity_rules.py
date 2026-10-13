"""Sub-plan 5h's rules on small doubles built from their real cases' answers (the cached EDGAR, OpenFIGI and fails
data the run read): the issuer in force kept for an era its ticker's rows decided (ERA 2013), ONEOK's 2026 holding
company past the fails data's last day, and no continued-filings guess at the last sighting of a security with no
CUSIP (WW 2013). Rule F, the ticker tier's post-bankruptcy holder (CRC, BTU), is the line follow's: its cases run
through `line_follow.follow_lines` in tests/test_line_stage.py."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from delist_detection import pipeline
from delist_detection.sources.cik_lookup import CikNameIndex, normalize_name
from delist_detection.endings.classifier import DelistClassifier
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.endings.delistings import Delisting, DelistingFinder, SecurityContexts
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex, FtdRow
from delist_detection.endings.last_trade import LastTrade
from delist_detection.outputs.manifest import StageMeter
from delist_detection.identity.observations import Observation, split_eras
from delist_detection.identity.security_master import Security
from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.identity.ticker_resolver import TickerResolver


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


def test_a_failed_read_of_the_issuer_in_force_is_a_resolution_degraded_row():
    """Final review M4: stage 10c3 (the contract's issuer timeline) reports a submissions read that failed as stage
    4c does: a `resolution_degraded` row for each security whose timeline asked that CIK, none for the others."""
    import requests

    def submissions(cik):
        if int(cik) == 1525221:
            raise requests.ConnectionError("down")
        return ERA_SUBS[int(cik)]
    ctx = _in_force_ctx()
    ctx.clients.edgar.submissions = submissions
    rows = [{"sec_id": "CIK1525221-COMMON", "as_of": "2013-06-28", "name": "BRISTOW GROUP INC.", "ticker": "ERA",
             "issuer_cik": "1525221", "status": "mapped", "era": "ERA@2013-06-28"},
            {"sec_id": "BBGBRS", "as_of": "2008-06-30", "name": "BRISTOW GROUP INC", "ticker": "BRS",
             "issuer_cik": "73887", "status": "mapped", "era": "BRS@2008-06-30"}]
    review = []
    timeline = pipeline._issuers_in_force(ctx, rows, review=review)
    assert timeline["BBGBRS"] == [("2008-06-30", "73887")]
    assert [(r.sec_id, r.ticker, r.cik, r.flag) for r in review] == [
        ("CIK1525221-COMMON", "ERA", 1525221, "resolution_degraded")]
    assert "the issuer in force" in review[0].reason


# --- FB-015: the issuer in force on a seed list, where one sighting is all the caller gives ----------------------

def _recent(*pairs):
    return {"recent": {"form": [f for f, _ in pairs], "filingDate": [d for _, d in pairs]}}


SEED_SUBS = {
    64670: {"name": "MEDTRONIC INC", "formerNames": [], "filings": _recent(("25-NSE", "2015-01-30"))},
    1613103: {"name": "Medtronic plc", "formerNames": []},
    64978: {"name": "MERCK SHARP & DOHME LLC", "formerNames": [
        {"name": "MERCK & CO INC", "from": "1994-03-16T05:00:00.000Z", "to": "2009-11-02T05:00:00.000Z"}],
        "filings": _recent(("25", "2008-12-01"), ("25-NSE", "2009-11-04"), ("15-12B", "2009-11-18"))},
    310158: {"name": "Merck & Co., Inc.", "formerNames": [
        {"name": "SCHERING PLOUGH CORP", "from": "1994-12-29T05:00:00.000Z", "to": "2009-11-03T05:00:00.000Z"}]},
}


def _seed_ctx(company_tickers=lambda: {"MRK": {"cik_str": 310158}, "MDT": {"cik_str": 1613103}}):
    edgar = SimpleNamespace(submissions=lambda cik: SEED_SUBS[int(cik)], company_tickers=company_tickers)
    clients = SimpleNamespace(edgar=edgar, issuers=IssuerRecord(edgar))
    return SimpleNamespace(clients=clients, meter=StageMeter(lambda *a: None), as_of=date(2026, 9, 25))


def _seed_row(sec_id, ticker, as_of, name, cik):
    return {"sec_id": sec_id, "as_of": as_of, "name": name, "ticker": ticker, "issuer_cik": str(cik),
            "status": "mapped", "era": f"{ticker}@{as_of}"}


def test_a_derived_line_changes_the_issuer_in_force_on_its_first_day():
    """MDT: the seed is Medtronic Inc's (64670); the line the library derived after the CUSIP change of 2015-01-27 is
    Medtronic plc's (1613103), and contract/security_history.csv says so from that day. A derived line of a
    security the caller never sighted makes no timeline."""
    from delist_detection.identity.issuer_in_force import Sighting
    rows = [_seed_row("BBGMDT", "MDT", "2008-01-16", "MEDTRONIC INC", 64670)]
    derived = [Sighting("BBGMDT", "2015-01-27", "", "1613103"), Sighting("BBGOTHER", "2015-01-27", "", "1613103")]
    assert pipeline._issuers_in_force(_seed_ctx(), rows) == {"BBGMDT": [("2008-01-16", "64670")]}
    assert pipeline._issuers_in_force(_seed_ctx(), rows, derived=derived) == {
        "BBGMDT": [("2008-01-16", "64670"), ("2015-01-27", "1613103")]}


def test_an_open_history_ends_with_the_company_sec_lists_its_ticker_under():
    """MRK: old Merck (64978) kept filing after November 2009, so no era names the registrant since; SEC lists MRK
    under 310158, whose name agrees from 2009-11-04, the day of old Merck's Form 25. A security that is not open,
    or whose listed company is already its last issuer, keeps its timeline."""
    rows = [_seed_row("BBGMRK", "MRK", "2008-01-16", "MERCK & CO INC", 64978),
            _seed_row("BBGMDT", "MDT", "2015-06-30", "MEDTRONIC PLC", 1613103)]
    assert pipeline._issuers_in_force(_seed_ctx(), rows)["BBGMRK"] == [("2008-01-16", "64978")]
    open_lines = {"BBGMRK": ("MRK", "MERCK & CO INC"), "BBGMDT": ("MDT", "MEDTRONIC PLC")}
    assert pipeline._issuers_in_force(_seed_ctx(), rows, open_lines=open_lines) == {
        "BBGMRK": [("2008-01-16", "64978"), ("2009-11-04", "310158")], "BBGMDT": [("2015-06-30", "1613103")]}


def test_a_ticker_map_that_cannot_be_read_is_asked_once_and_reviewed():
    import requests
    asked = []

    def company_tickers():
        asked.append(1)
        raise requests.ConnectionError("down")
    rows = [_seed_row("BBGMRK", "MRK", "2008-01-16", "MERCK & CO INC", 64978),
            _seed_row("BBGMDT", "MDT", "2015-06-30", "MEDTRONIC PLC", 1613103)]
    open_lines = {"BBGMRK": ("MRK", "MERCK & CO INC"), "BBGMDT": ("MDT", "MEDTRONIC PLC")}
    review = []
    out = pipeline._issuers_in_force(_seed_ctx(company_tickers), rows, review=review, open_lines=open_lines)
    assert out == {"BBGMRK": [("2008-01-16", "64978")], "BBGMDT": [("2015-06-30", "1613103")]}
    assert len(asked) == 1 and [(r.sec_id, r.flag) for r in review] == [("BBGMRK", "resolution_degraded")]


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
    from delist_detection.outputs.review_triage import FilingRef, ReviewItem
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
    ctx = SimpleNamespace(clients=SimpleNamespace(figi=None, edgar=None), as_of=date(2026, 9, 25),
                          meter=StageMeter(lambda *a: None), log=lambda m: None)
    owner = SimpleNamespace(form25_sub=SimpleNamespace(accession="0000876661-26-000770"))
    out = pipeline._successor_endings(ctx, finder, {added.security.sec_id: added}, {}, {}, FtdIndex([]), [owner])
    assert out.review == [other]


def test_a_new_cusip_the_fails_data_reaches_must_show_its_rows():
    """Guard: when the fails data runs past the day and the new CUSIP has no row under the line's tickers, no link
    (as before 5h: the rows are the evidence the holders' shares went on there)."""
    link, found = _oke(OLD_ROWS + [FtdRow("2026-09-15", "999999999", "XYZ", "SOMETHING ELSE", 1.0)])
    assert link is None and not found.added


# --- rule G, WW 2013: no continued-filings ending at the last sighting of a security with no CUSIP --------------

def _ww(fake_edgar, cusips):
    """WW 2012-2013, a 2018 name and ticker a snapshot carried back onto Weight Watchers (WTW then): no Form 25 in
    reach, the issuer kept filing its 10-Qs; the security holds no CUSIP (`cusips` empty: its old one maps to another
    composite)."""
    fake_edgar.submissions_by_cik[105319] = [
        EdgarSubmission("q1", "10-Q", "2014-05-01", "2014-03-31", "", "q1.htm"),
        EdgarSubmission("q2", "10-Q", "2014-08-01", "2014-06-30", "", "q2.htm"),
        EdgarSubmission("k1", "10-K", "2015-02-27", "2014-12-31", "", "k1.htm")]
    era = split_eras([Observation("WW", "2012-06-29", "WW INTERNATIONAL INC"),
                      Observation("WW", "2013-12-31", "WW INTERNATIONAL INC")])
    sec = Security("BBG000DY6735", 105319, "COMMON", "WW INTERNATIONAL INC", "Common Stock", True, "ticker",
                   "common", era)
    ctx = SecurityContexts.observed({sec.sec_id: sec}, {sec.sec_id: cusips}, FtdIndex([]))(sec, False)
    assert ctx.record.last_seen == "2013-12-31" and ctx.record.has_cusips is bool(cusips)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    return DelistingFinder(fake_edgar, clf).find(ctx)


def test_a_security_with_no_cusip_gets_no_continued_filings_guess_at_its_last_sighting(fake_edgar):
    events, review = _ww(fake_edgar, [])
    assert events == [] and [r.flag for r in review] == ["ended_without_delisting"]


def test_a_security_with_its_cusip_keeps_the_continued_filings_ending(fake_edgar):
    """Guard: a security whose own CUSIP could show it stop keeps today's ending (a genuine no-Form-25 end)."""
    events, _ = _ww(fake_edgar, ["948626106"])
    assert [(e.delist_date, e.record.crsp_code) for e in events] == [("2013-12-31", 304)]




# --- FB-014, SandRidge 2016: a line a bankruptcy left behind while its ticker went on as other shares ------------

SD_OLD, SD_NEW, SD_CIK = "80007P307", "80007P869", 1349436


def _sd_rows(*, old_tail=(("SDOC", "2016-01-12"), ("SDOC", "2016-05-16"), ("SDOCQ", "2016-05-19"),
                          ("SDOCQ", "2016-10-13")), new_from=("2016-10-07", "2020-01-02", "2026-08-19")):
    """SandRidge's fails rows: the old CUSIP under SD to 2016-01-11, then under the OTC symbols `old_tail`; the
    post-bankruptcy CUSIP under SD from `new_from`."""
    rows = [FtdRow(d, SD_OLD, "SD", "SANDRIDGE ENERGY, INC.", 1.0) for d in ("2014-12-01", "2015-06-30", "2016-01-11")]
    rows += [FtdRow(d, SD_OLD, sym, "SANDRIDGE ENERGY, INC.", 0.03) for sym, d in old_tail]
    rows += [FtdRow(d, SD_NEW, "SD", "SANDRIDGE ENERGY INC COM NEW", 20.0) for d in new_from]
    return rows


class _Filings:
    """An EDGAR client that knows one issuer's filings."""

    def __init__(self, filings=()):
        self._filings = list(filings)

    def submissions(self, cik, fresh_after=None):
        return {"name": "SANDRIDGE ENERGY INC", "formerNames": []}

    def recent_filings(self, cik):
        return list(self._filings)


def _left_behind(rows, filings=()):
    from delist_detection.identity.identity import _LeftBehind, _went_bankrupt
    ftd = FtdIndex(rows)
    return _LeftBehind(ftd, _went_bankrupt(ftd, IssuerRecord(_Filings(filings))))


def test_a_line_whose_cusip_ended_under_a_bankruptcy_symbol_as_another_took_its_ticker_is_left_behind():
    """SandRidge: the old CUSIP left SD for SDOC and SDOCQ and stopped on 2016-10-13; the post-bankruptcy stock's
    CUSIP holds SD from 2016-10-07. The old line is not the one that trades as SD today."""
    assert _left_behind(_sd_rows())("SD", [SD_OLD], SD_CIK) is True


def test_a_new_cusip_with_no_bankruptcy_leaves_no_line_behind():
    """Equinix 2015, Thomson Reuters 2018: the shares went on under a new CUSIP the line follow could not confirm.
    The old CUSIP stopped and another holds the ticker, but nothing says the old shares were cancelled."""
    rows = _sd_rows(old_tail=())
    assert _left_behind(rows)("SD", [SD_OLD], SD_CIK) is False


def test_an_item_1_03_8k_before_the_new_cusip_is_a_bankruptcy_without_a_q_symbol():
    """No OTC symbol in the fails rows (the old stock never failed over the counter): the issuer's Item 1.03 8-K in
    the year before the new CUSIP's first row, no earlier than 60 days before the old CUSIP's last, says it."""
    rows = _sd_rows(old_tail=(("SD", "2016-05-10"),))
    eightk = EdgarSubmission("0001193125-16-591230", "8-K", "2016-05-16", "2016-05-16", "1.01,1.03,2.04", "k.htm")
    assert _left_behind(rows, [eightk])("SD", [SD_OLD], SD_CIK) is True
    assert _left_behind(rows)("SD", [SD_OLD], SD_CIK) is False


def test_a_line_whose_own_cusip_still_trades_is_not_left_behind():
    """The old CUSIP trades on long after another CUSIP took the ticker (two securities side by side, or equity
    that survived the bankruptcy under its own symbol): the line was not cancelled."""
    rows = _sd_rows(old_tail=(("SDOC", "2016-01-12"), ("SDOCQ", "2016-05-19"), ("SDOCQ", "2017-03-01")))
    assert _left_behind(rows)("SD", [SD_OLD], SD_CIK) is False


def test_a_bankrupt_line_whose_ticker_nobody_took_is_not_left_behind():
    """Seventy Seven Energy: the ticker did not go on as other shares, so EDGAR lists nothing under it for the
    listed answer to mistake for the old line. The delisting search ends it without this rule."""
    assert _left_behind(_sd_rows(new_from=()))("SD", [SD_OLD], SD_CIK) is False
    assert _left_behind(_sd_rows())("SD", [SD_NEW], SD_CIK) is False       # the new line itself: nobody after it


class _ListedFigi:
    """OpenFIGI has nothing to say of a placeholder; any composite it is asked about trades on a US venue."""

    def map(self, jobs, use_cache=True):
        return [{"data": [{"exchCode": "UN"}]} for _ in jobs]


def _sd_stage5(fake_edgar, rows):
    """Stage 5 over old SandRidge's placeholder, EDGAR listing SD on the NYSE for the issuer today."""
    sid = "CIK1349436-COMMON"
    fake_edgar.listings[SD_CIK] = [("SD", "NYSE")]
    fake_edgar.submissions_by_cik[SD_CIK] = []
    sec = Security(sid, SD_CIK, "COMMON", "SANDRIDGE ENERGY INC.", "", True, "placeholder", "common",
                   split_eras([Observation("SD", "2014-12-31", "SANDRIDGE ENERGY INC.")]))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    clients = SimpleNamespace(edgar=fake_edgar, classifier=clf, midas=None, halts=None, figi=_ListedFigi(),
                              issuers=IssuerRecord(fake_edgar), full_text_search=None)
    ctx = SimpleNamespace(clients=clients, log=lambda *a: None, sec_workers=1, as_of=date(2026, 9, 25),
                          meter=StageMeter(lambda *a: None))
    return pipeline._find_delistings(ctx, {sid: sec}, {sid: [SD_OLD]}, FtdIndex(rows), lambda s: "security_master").listed[sid]


def test_stage_5_takes_a_placeholder_a_bankruptcy_left_behind_as_not_listed_today(fake_edgar):
    """FB-014: EDGAR lists SD for SandRidge today, and that is the stock issued under the 2016 plan. The old stock's
    placeholder, whose CUSIP ended under SDOCQ as another took SD, is not listed; one nobody took the ticker from
    still reads EDGAR's listing as its own."""
    assert _sd_stage5(fake_edgar, _sd_rows()) is False
    assert _sd_stage5(fake_edgar, _sd_rows(new_from=())) is True


# --- FB-003, Fox 2019: another registrant took the class's place at a CUSIP switch (`_Replaced`) ---------------------

FOX_OLD, FOX_NEW, FOX_OLD_CIK, FOX_NEW_CIK = "90130A101", "35137L105", 1308161, 1754301


def _f(form, day, items=""):
    return EdgarSubmission(f"{form}-{day}", form, day, day, items, "d.htm")


class _PerCik:
    """An EDGAR client that knows each issuer's filings, and the tickers SEC lists today (ticker -> CIK)."""

    def __init__(self, filings, listed=None):
        self.by_cik, self.listed = filings, listed or {}

    def submissions(self, cik, fresh_after=None):
        return {"name": "ISSUER", "formerNames": []}

    def recent_filings(self, cik):
        return list(self.by_cik.get(int(cik), []))

    def company_tickers(self):
        return {t: {"cik_str": c, "ticker": t, "title": t} for t, c in self.listed.items()}


def _replaced(old_filings, new_filings):
    from delist_detection.identity.identity import _Replaced
    ftd = FtdIndex([FtdRow("2019-03-21", FOX_NEW, "FOXA", "FOX CORP CL A (DE)", 50.0),
                    FtdRow("2019-03-22", FOX_NEW, "FOXA", "FOX CORP CL A (DE)", 50.5)])
    got = _Replaced(ftd, IssuerRecord(_PerCik({FOX_OLD_CIK: old_filings, FOX_NEW_CIK: new_filings})))
    return got(FOX_OLD, FOX_NEW, FOX_OLD_CIK, FOX_NEW_CIK)


FOX_CLOSED = [_f("25-NSE", "2019-03-20"), _f("8-K", "2019-03-20", "1.01,2.01,3.01,5.01,5.03,9.01")]
FOX_REGISTERED = [_f("10-12B", "2019-01-07"), _f("10-12B/A", "2019-01-23"), _f("8-A12B", "2019-03-20")]


def test_a_class_the_old_registrant_lost_to_a_company_registered_anew_is_replaced():
    """Twenty-First Century Fox's FOXA to Fox Corporation's, 2019-03-21: the old registrant's Form 25 and its closing
    8-K (items 2.01, 3.01, 5.01); the new company's Form 10-12B in January and its 8-A12B on 2019-03-20."""
    assert _replaced(FOX_CLOSED, FOX_REGISTERED) is True


def test_a_successor_registration_is_not_a_replacement():
    """Disney 2019 and Express Scripts 2012: the new holding company's 8-K12B says it is the old registrant's stock,
    one for one (Disney's new registrant filed no Form 10 at all; a company that filed one is still a
    successor)."""
    successor = _f("8-K12B", "2019-03-20", "1.01,2.01,3.03,5.01")
    assert _replaced(FOX_CLOSED, [successor]) is False
    assert _replaced(FOX_CLOSED, [*FOX_REGISTERED, successor]) is False
    assert _replaced(FOX_CLOSED, [*FOX_REGISTERED, _f("8-K12G3", "2019-03-21")]) is False


def test_a_new_registrant_that_registered_by_an_exchange_of_shares_is_not_a_replacement():
    """Clearwire 2008: the new Clearwire registered its class A stock by an S-4 and an 8-A12B, to issue it one for one
    for the old Clearwire's. An 8-A lists a class however it came about; only a Form 10 (a spin-off: shares handed
    out, never exchanged) says the new stock is not the old one."""
    exchanged = [_f("S-4", "2019-01-07"), _f("8-A12B", "2019-03-20")]
    assert _replaced(FOX_CLOSED, exchanged) is False
    assert _replaced(FOX_CLOSED, [*exchanged, _f("10-12B", "2019-01-07")]) is True


def test_a_new_registrant_that_registered_nothing_new_is_not_a_replacement():
    """Merck 2009: Schering-Plough was registered and listed long before it took Merck's name, and filed no Form 10
    or 8-A for the switch."""
    assert _replaced(FOX_CLOSED, [_f("10-Q", "2019-03-18"), _f("8-K", "2019-03-19", "2.01")]) is False


def test_an_old_registrant_with_no_form_25_or_no_closing_8k_near_the_switch_is_not_replaced():
    assert _replaced([_f("8-K", "2019-03-20", "2.01,5.01")], FOX_REGISTERED) is False          # no Form 25
    assert _replaced([_f("25-NSE", "2019-03-20"), _f("8-K", "2019-03-20", "8.01")], FOX_REGISTERED) is False
    assert _replaced([_f("25-NSE", "2018-01-02"), *FOX_CLOSED[1:]], FOX_REGISTERED) is False   # a Form 25 a year before


def test_one_registrant_or_a_cusip_with_no_rows_is_no_replacement():
    from delist_detection.identity.identity import _Replaced
    ftd = FtdIndex([FtdRow("2019-03-21", FOX_NEW, "FOXA", "FOX CORP CL A (DE)", 50.0)])
    got = _Replaced(ftd, IssuerRecord(_PerCik({FOX_OLD_CIK: FOX_CLOSED + FOX_REGISTERED})))
    assert got(FOX_OLD, FOX_NEW, FOX_OLD_CIK, FOX_OLD_CIK) is False
    assert got(FOX_OLD, FOX_NEW, None, FOX_NEW_CIK) is False
    assert got(FOX_OLD, "999999999", FOX_OLD_CIK, FOX_NEW_CIK) is False


# --- FB-003, Fox 2019: the company listed under a ticker today had not filed yet (`_RegistrantAfter`) --------------

def _after(filings, listed, ticker="FOXA", cik=FOX_OLD_CIK, first="2013-12-31"):
    from delist_detection.identity.identity import _RegistrantAfter
    return _RegistrantAfter(IssuerRecord(_PerCik(filings, listed)))(ticker, cik, first)


def test_a_ticker_listed_under_a_company_that_registered_after_the_eras_first_sighting_is_flagged():
    fox = [_f("DRS", "2018-10-09"), *FOX_REGISTERED]
    assert _after({FOX_NEW_CIK: fox}, {"FOXA": FOX_NEW_CIK}) is True
    assert _after({FOX_NEW_CIK: fox}, {"FOXA": FOX_NEW_CIK}, first="2019-06-30") is False       # it had filed by then


def test_a_ticker_listed_under_the_eras_own_issuer_or_nobody_or_a_successor_registrant_is_not_flagged():
    fox = [_f("DRS", "2018-10-09")]
    assert _after({FOX_NEW_CIK: fox}, {"FOXA": FOX_OLD_CIK}) is False
    assert _after({FOX_NEW_CIK: fox}, {}) is False
    assert _after({FOX_NEW_CIK: fox}, {"FOXA": FOX_NEW_CIK}, cik=None) is False
    holding = [_f("S-4", "2011-10-06"), _f("8-K12B", "2012-04-02")]          # Express Scripts' holding company
    assert _after({1532063: holding}, {"ESRX": 1532063}, ticker="ESRX", cik=885721, first="2011-03-01") is False
