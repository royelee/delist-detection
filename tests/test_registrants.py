"""FB-004 part b: the issuer in force after a holding-company reorganization (`registrants`, stage 5's
`pipeline._search_security`, the contract's issuer timeline). Doubles over the finder's own contexts, as
tests/test_form25_ties.py builds them: Disney 2019 and WestRock 2018/2024 in miniature."""
from __future__ import annotations

from datetime import date

from delist_detection.endings.classifier import DelistClassifier
from delist_detection.endings.delistings import DelistingFinder, SecurityContexts
from delist_detection.endings.registrants import MAX_REGISTRANTS, Registrant, SuccessorRegistrants, goes_on
from delist_detection.filings.filing_search import successor_query
from delist_detection.identity.issuer_in_force import with_registrants
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.identity.ticker_resolver import TickerResolver
from delist_detection.pipeline import _search_security
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex
from delist_detection.vocabulary.crsp_codes import CrspBucket
from tests.test_delistings import _f25_raw, _sec, _trading

OLD, NEW = 6001, 6002              # the 2019 registrant (now a shell) and its successor registrant
SEC_ID = "BBG_HOLD"
HIT = {"_source": {"ciks": ["0000006002"], "display_names": ["Holdco Entertainment Co (HLD) (CIK 0000006002)"],
                   "file_date": "2019-03-20", "form": "8-K12B"}}


def _world(fake_edgar, *, later_form25=False, search=True, weeks=861):
    """HOLD trades weekly from 2008 to 2024-07-09 under one CUSIP. The old registrant's 25-NSE of 2019-03-20 removed
    the old shares as the new registrant's took their place (the CUSIP, the ticker and the trading go on); the new
    registrant's 25-NSE of 2024-07-08 (`later_form25`) is the merger that ended the security."""
    fake_edgar.submissions_by_cik[OLD] = [
        EdgarSubmission("o25", "25-NSE", "2019-03-20", "", "", "p.xml"),
        EdgarSubmission("o8k", "8-K", "2019-03-19", "2019-03-19", "2.01,3.01,3.03,5.01,5.03,9.01", "k.htm")]
    fake_edgar.raws["o25"] = _f25_raw("New York Stock Exchange LLC", form_tag="25-NSE")
    fake_edgar.texts["o8k"] = ("Item 3.01 Notice of Delisting. requested that trading be suspended prior to the "
                               "opening of trading on March 20, 2019 " + "x" * 300)
    fake_edgar.company_map["HLD"] = {"cik_str": NEW, "ticker": "HLD", "title": "Holdco Entertainment Co"}
    fake_edgar.submissions_by_cik[NEW] = [EdgarSubmission("n8k", "8-K12B", "2019-03-20", "", "", "k.htm")]
    if later_form25:
        fake_edgar.submissions_by_cik[NEW].append(EdgarSubmission("n25", "25-NSE", "2024-07-08", "", "", "p.xml"))
        fake_edgar.raws["n25"] = _f25_raw("New York Stock Exchange LLC", form_tag="25-NSE")
    fake_edgar.searches = []

    def full_text_search(q, forms, lo, hi):
        fake_edgar.searches.append((q, forms, lo, hi))
        return [HIT] if "HOLDCO ENTERTAINMENT" in q.upper() or "HOLD" in q.upper() else []

    fake_edgar.full_text_search = full_text_search if search else None
    sec = _sec(SEC_ID, OLD, "HLD", "2008-01-02", "2024-07-09", "HOLDCO ENTERTAINMENT CO")
    rows = _trading("HLD", "2008-01-02", n=weeks, cusip="HLD000001")      # weekly; 861 weeks to 2024-07-09
    contexts = SecurityContexts.observed({SEC_ID: sec}, {SEC_ID: ["HLD000001"]}, FtdIndex(rows))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    finder = DelistingFinder(fake_edgar, clf)
    registrants = SuccessorRegistrants(IssuerRecord(fake_edgar), fake_edgar.full_text_search, fake_edgar)
    return sec, contexts, finder, registrants


def test_an_ending_the_security_trades_through_goes_on_and_a_dead_one_does_not(fake_edgar):
    sec, contexts, finder, _ = _world(fake_edgar)
    (d,) = finder.find(contexts(sec, False))[0]
    record = contexts.records[SEC_ID]
    # Disney 2019: a merger 231 with a confirmed last trade, after which the CUSIP trades on weekly for years
    assert d.record.bucket is CrspBucket.MERGER and d.last_trade.confirmed and goes_on(d, record)
    d.record.bucket = CrspBucket.LIQUIDATION                  # a kind that always ends the security
    assert not goes_on(d, record)
    d.record.bucket, d.record.successor_sec_id = CrspBucket.MERGER, SEC_ID    # a security that is its own successor
    assert goes_on(d, record)


def test_a_successor_registrants_8k12b_naming_the_old_one_is_found_for_an_ending_that_goes_on(fake_edgar):
    sec, contexts, finder, registrants = _world(fake_edgar)
    found, _ = finder.find(contexts(sec, False))
    assert registrants.of(contexts.records[SEC_ID], found) == [Registrant(NEW, "2019-03-20")]
    q, forms, lo, hi = fake_edgar.searches[0]
    assert (q, forms) == ('"HOLDCO ENTERTAINMENT CO"', "8-K12B,8-K12G3")
    assert (lo, hi) == successor_query("x", found[0].anchor)[2:]


def test_a_successor_registration_alone_changes_nothing(fake_edgar):
    """An ending that ended its security (a merger the security did not trade through) has a registrant that took
    its place for the acquirer's stock, not for the security: no successor registrant, and no search."""
    sec, contexts, finder, registrants = _world(fake_edgar, weeks=580)          # the last row is 2019-03-12
    found, _ = finder.find(contexts(sec, False))
    assert [d.record.bucket for d in found] == [CrspBucket.MERGER]
    assert registrants.of(contexts.records[SEC_ID], found) == [] and fake_edgar.searches == []


def test_without_the_search_capability_there_is_no_registrant(fake_edgar):
    sec, contexts, finder, registrants = _world(fake_edgar, search=False)
    found, _ = finder.find(contexts(sec, False))
    assert registrants.of(contexts.records[SEC_ID], found) == []


def test_the_search_reads_the_new_registrants_form25_and_its_listing(fake_edgar):
    """WRK 2018 to 2024: the 25-NSE of 2024-07-08 is the new registrant's, never searched before; the listed-today
    answer of the last search is the one read through the registrant's CIK (`listed_of(cik)`)."""
    sec, contexts, finder, registrants = _world(fake_edgar, later_form25=True)
    asked = []

    def listed_of(cik):
        asked.append(cik)
        return False

    found, review, regs, listed = _search_security(finder, registrants, contexts, sec, listed_of)
    assert regs == [Registrant(NEW, "2019-03-20")] and listed is False and asked == [None, NEW]
    assert [(d.delist_date, d.cik, d.record.bucket.value) for d in found][0][:2] == ("2019-03-30", OLD)
    last = found[-1]
    assert (last.cik, last.form25_sub.accession) == (NEW, "n25") and last.delist_date == "2024-07-18"


def test_the_old_registrants_own_search_finds_no_2024_ending(fake_edgar):
    """Before FB-004: the finder read only the old CIK's Form 25s."""
    sec, contexts, finder, _ = _world(fake_edgar, later_form25=True)
    found, _ = finder.find(contexts(sec, False))
    assert [d.form25_sub.accession for d in found] == ["o25"]


def test_a_security_with_no_ending_that_goes_on_is_searched_once(fake_edgar):
    sec, contexts, finder, registrants = _world(fake_edgar)
    fake_edgar.submissions_by_cik[OLD] = []
    calls = []
    found, review, regs, listed = _search_security(finder, registrants, contexts, sec,
                                                   lambda cik: calls.append(cik) or True)
    assert (found, regs, listed, calls) == ([], [], True, [None]) and fake_edgar.searches == []


def test_the_chain_of_reorganizations_is_bounded(fake_edgar):
    assert MAX_REGISTRANTS >= 2


def test_a_registrant_is_the_issuer_in_force_from_the_day_it_registered():
    timeline = [("2007-12-17", "1001039")]
    assert with_registrants(timeline, [("2019-03-20", "1744489")]) == [("2007-12-17", "1001039"),
                                                                       ("2019-03-20", "1744489")]
    assert with_registrants(timeline, [("2019-03-20", "1001039")]) == timeline          # already in force
    assert with_registrants([], [("2019-03-20", "1744489")]) == []                     # no sighting carried a CIK
    assert with_registrants([("2019-03-20", "1001039")], [("2019-03-20", "1744489")]) == [
        ("2019-03-20", "1001039"), ("2019-03-21", "1744489")]                          # the days strictly increase
    assert with_registrants(timeline, [("2018-11-07", "1732845"), ("2024-07-08", "5")]) == [
        ("2007-12-17", "1001039"), ("2018-11-07", "1732845"), ("2024-07-08", "5")]


class _Figi:
    """OpenFIGI lists the composite on a US exchange today (venue UN), as it does for a dead line too."""

    def map(self, jobs, use_cache=True):
        return [{"data": [{"exchCode": "UN"}]} for _ in jobs]


def _stage5(fake_edgar, *, search=True, listing=()):
    """Stage 5 over the world: `pipeline._find_delistings` with an OpenFIGI double and the issuer record."""
    from types import SimpleNamespace

    from delist_detection import pipeline
    from delist_detection.outputs.manifest import StageMeter
    sec, contexts, finder, _ = _world(fake_edgar, search=search)
    fake_edgar.listings[NEW] = list(listing)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    clients = SimpleNamespace(edgar=fake_edgar, classifier=clf, midas=None, halts=None, figi=_Figi(),
                              issuers=IssuerRecord(fake_edgar), full_text_search=fake_edgar.full_text_search)
    ctx = SimpleNamespace(clients=clients, log=lambda *a: None, sec_workers=1, as_of=date(2026, 9, 25),
                          meter=StageMeter(lambda *a: None))
    return sec, pipeline._find_delistings(ctx, {SEC_ID: sec}, {SEC_ID: ["HLD000001"]},
                                          FtdIndex(_trading("HLD", "2008-01-02", n=861, cusip="HLD000001")),
                                          lambda s: "security_master")


def test_stage_5_reads_the_successor_registrants_listing_and_keeps_the_registrant(fake_edgar):
    """Disney 2019: the old registrant lists nothing, so the history closed at the fails data's last day; the new
    registrant lists the ticker on the NYSE today."""
    sec, search = _stage5(fake_edgar, listing=[("HLD", "NYSE")])
    assert search.registrants == {SEC_ID: [Registrant(NEW, "2019-03-20")]}
    assert search.listed == {SEC_ID: True} and search.issuer_now(sec) == NEW
    assert [d.cik for d in search.delistings] == [OLD]


def test_without_the_search_the_issuer_lists_it_alone(fake_edgar):
    sec, search = _stage5(fake_edgar, search=False, listing=[("HLD", "NYSE")])
    assert search.registrants == {} and search.listed == {SEC_ID: False} and search.issuer_now(sec) == OLD


def test_the_contracts_issuer_timeline_names_the_registrant_from_its_registration():
    from types import SimpleNamespace

    from delist_detection import pipeline
    from delist_detection.outputs.manifest import StageMeter
    edgar = SimpleNamespace(submissions=lambda cik: {"name": "Holdco Entertainment Co", "formerNames": []})
    clients = SimpleNamespace(edgar=edgar, issuers=IssuerRecord(edgar))
    ctx = SimpleNamespace(clients=clients, meter=StageMeter(lambda *a: None))
    rows = [{"sec_id": SEC_ID, "as_of": "2008-06-30", "name": "HOLDCO ENTERTAINMENT CO", "ticker": "HLD",
             "issuer_cik": str(OLD), "status": "mapped", "era": "HLD@2008-06-30"}]
    assert pipeline._issuers_in_force(ctx, rows) == {SEC_ID: [("2008-06-30", str(OLD))]}
    assert pipeline._issuers_in_force(ctx, rows, registrants={SEC_ID: [Registrant(NEW, "2019-03-20")]}) == {
        SEC_ID: [("2008-06-30", str(OLD)), ("2019-03-20", str(NEW))]}
    assert pipeline._issuers_in_force(ctx, rows, registrants={"BBG_OTHER": [Registrant(NEW, "2019-03-20")]}) == {
        SEC_ID: [("2008-06-30", str(OLD))]}
