"""FB-004 part a: a Form 25 its text leaves between sibling securities belongs to the one that stops trading at it
(`DelistingFinder._tie_owner`), and a security that traded on past a voluntary Form 25 into the OTC market, its 10-K
cover then naming no exchange, is dropped for it (`Rule.MOVED_OTC`, CRSP 520). Doubles over the finder's own
contexts, as tests/test_delistings.py builds them; the real cases are tests/test_form25_reach_cases.py's."""
from __future__ import annotations

from datetime import date, timedelta

from delist_detection.endings.classifier import DelistClassifier
from delist_detection.endings.delistings import DelistingFinder, SecurityContexts
from delist_detection.endings.rewrites import Rule
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex
from delist_detection.identity.ticker_resolver import TickerResolver
from delist_detection.vocabulary.crsp_codes import CrspBucket
from tests.test_delistings import _f25_raw, _row, _sec, _trading

CIK = 77001
OLD, NEW = "BBG_OLD", "BBG_NEW"
F25 = EdgarSubmission("f1", "25-NSE", "2018-08-28", "", "", "p.xml")


def _world(fake_edgar, *, rule="17 CFR 240.12d2-2(a)(3)", class_text="OldCo Inc. Common Stock", extra=(), rows=()):
    """GGP 2018 in miniature: the old line (CUSIP OLD000001) trades weekly to 2018-08-24 and stops; the new one
    (NEW000001) starts 2018-08-30 and trades on; the exchange's 25-NSE of 2018-08-28 names "Common Stock" only."""
    fake_edgar.submissions_by_cik[CIK] = [F25]
    fake_edgar.raws["f1"] = _f25_raw("New York Stock Exchange LLC", class_text=class_text, rule=rule,
                                     form_tag="25-NSE")
    old = _sec(OLD, CIK, "OLDC", "2018-03-23", "2018-08-24", "OLDCO INC")
    new = _sec(NEW, CIK, "NEWC", "2018-08-30", "2021-06-30", "NEWCO REIT INC CLASS")
    rows = [*_trading("OLDC", "2018-03-23", n=22, cusip="OLD000001"),
            *_trading("NEWC", "2018-08-30", n=30, cusip="NEW000001"), *rows]
    return old, new, rows, list(extra)


def _find(fake_edgar, sec_id, securities, cusips, rows):
    contexts = SecurityContexts.observed({s.sec_id: s for s in securities}, cusips, FtdIndex(rows))
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    return DelistingFinder(fake_edgar, clf).find(contexts(next(s for s in securities if s.sec_id == sec_id), False))


CUSIPS = {OLD: ["OLD000001"], NEW: ["NEW000001"]}


def test_a_tie_goes_to_the_sibling_that_stops_at_the_form25(fake_edgar):
    old, new, rows, _ = _world(fake_edgar)
    events, review = _find(fake_edgar, OLD, [old, new], CUSIPS, rows)
    assert [(e.sec_id, e.form25_sub.accession) for e in events] == [(OLD, "f1")]
    assert not any(r.flag == "form25_unmatched" for r in review)


def test_the_sibling_that_trades_on_is_not_the_one_removed_and_raises_no_review_row(fake_edgar):
    old, new, rows, _ = _world(fake_edgar)
    events, review = _find(fake_edgar, NEW, [old, new], CUSIPS, rows)
    assert all(e.form25_sub is None for e in events)
    assert not any(r.flag == "form25_unmatched" for r in review)


def test_the_otc_tail_after_a_removal_under_rule_b_is_not_the_listing_going_on(fake_edgar):
    """CIT, Oasis: the removed class trades on over the counter under its own CUSIP; the other line, under its own
    exchange ticker, is the one that goes on. The removed one still owns the Form 25."""
    old, new, rows, _ = _world(fake_edgar, rule="17 CFR 240.12d2-2(b)",
                               rows=_trading("OLDCQ", "2018-09-05", n=25, cusip="OLD000001"))
    events, review = _find(fake_edgar, OLD, [old, new], CUSIPS, rows)
    assert [(e.sec_id, e.form25_sub.accession) for e in events] == [(OLD, "f1")]
    assert not any(r.flag == "form25_unmatched" for r in review)


def test_a_tie_stays_when_no_sibling_trades_on(fake_edgar):
    """Nothing says which stopped: no evidence of a sibling that goes on, so the Form 25 stays ambiguous."""
    old, new, rows, _ = _world(fake_edgar)
    rows = [r for r in rows if r.cusip == "OLD000001"]
    events, review = _find(fake_edgar, OLD, [old, new], CUSIPS, rows)
    assert events == [] and "form25_unmatched" in [r.flag for r in review]


def test_a_tie_stays_when_two_siblings_stop_at_the_form25(fake_edgar):
    """IAC 2020: the old IAC and the old Match Group both stop on the day; the new Match Group goes on."""
    old, new, rows, _ = _world(fake_edgar)
    twin = _sec("BBG_TWIN", CIK, "TWNC", "2018-03-23", "2018-08-24", "TWINCO INC")
    rows = [*rows, *_trading("TWNC", "2018-03-23", n=22, cusip="TWN000001")]
    cusips = {**CUSIPS, "BBG_TWIN": ["TWN000001"]}
    for sid in (OLD, "BBG_TWIN"):
        events, review = _find(fake_edgar, sid, [old, twin, new], cusips, rows)
        assert events == [] and "form25_unmatched" in [r.flag for r in review]


def test_a_sibling_that_stopped_long_before_the_form25_does_not_own_it(fake_edgar):
    """The old line was last sighted 200 days before the filing: a Form 25 this late is not its ending, so the
    tie (the new line goes on) is not broken in its favour."""
    old, new, rows, _ = _world(fake_edgar)
    stale = _sec(OLD, CIK, "OLDC", "2017-03-23", "2018-02-09", "OLDCO INC")
    rows = [*_trading("OLDC", "2017-03-23", n=22, cusip="OLD000001"),
            *[r for r in rows if r.cusip == "NEW000001"]]
    events, review = _find(fake_edgar, OLD, [stale, new], CUSIPS, rows)
    assert events == [] and "form25_unmatched" in [r.flag for r in review]


def test_a_new_line_under_the_same_name_a_month_after_is_the_same_security_and_the_tie_stays(fake_edgar):
    """Linde 2023, Aptiv 2024, Labcorp 2024 (binding ruling of 2026-10-04: the old line takes no ending), Lions Gate
    2016: the line that goes on carries the stopper's name and was first sighted within a month of its last sighting."""
    old, new, rows, _ = _world(fake_edgar)
    new = _sec(NEW, CIK, "NEWC", "2018-08-30", "2021-06-30", "OLDCO INC")
    events, review = _find(fake_edgar, OLD, [old, new], CUSIPS, rows)
    assert events == [] and "form25_unmatched" in [r.flag for r in review]


def test_a_generic_text_beside_a_new_line_a_week_later_leaves_the_tie(fake_edgar):
    """Labcorp 2024: "Common Stock" names neither line, and the line that goes on starts within a month of the
    stopper's last sighting under a new name (Labcorp Holdings): the old line takes no ending."""
    old, new, rows, _ = _world(fake_edgar, class_text="Common Stock")
    events, review = _find(fake_edgar, OLD, [old, new], CUSIPS, rows)
    assert events == [] and "form25_unmatched" in [r.flag for r in review]


def test_a_text_naming_a_letter_no_sibling_carries_is_not_broken_by_trading(fake_edgar):
    old, new, rows, _ = _world(fake_edgar, class_text="Series B Common Stock")
    events, review = _find(fake_edgar, OLD, [old, new], CUSIPS, rows)
    assert events == []


# --- Moved to the OTC market (Freddie Mac, Fannie Mae 2010) ---

NO_EXCHANGE_COVER = ("FORM 10-K ... Securities registered pursuant to Section 12(b) of the Act: Title of each class "
                     "Name of each exchange on which registered None Securities registered pursuant to Section 12(g) "
                     "of the Act: Common Stock, without par value ...")
NASDAQ_COVER = ("FORM 10-K ... Title of each class Name of each exchange on which registered Common Stock "
                "The Nasdaq Stock Market LLC ...")
ISSUER_CIK = 88001


def _otc_world(fake_edgar, cover, *, eight_a=False, listing=(), acquired_8k=False):
    """One security, an issuer-filed Form 25 (12d2-2(c)) of 2010-06-28 and its own CUSIP trading on after it under
    the same symbol; the next 10-K's cover is `cover` ("" for one that is not in the cache)."""
    filings = [EdgarSubmission("o25", "25", "2010-06-28", "", "", "p.xml"),
               EdgarSubmission("ok", "10-K", "2011-02-24", "2010-12-31", "", "k.htm")]
    if eight_a:
        filings.append(EdgarSubmission("o8a", "8-A12B", "2010-06-30", "", "", "a.htm"))
    if acquired_8k:           # an Item 2.01 the end-of-era branch reads as a completed acquisition
        filings.append(EdgarSubmission("o201", "8-K", "2010-07-06", "2010-07-06", "2.01,9.01", "e.htm"))
    if listing:
        fake_edgar.listings[ISSUER_CIK] = list(listing)
    fake_edgar.submissions_by_cik[ISSUER_CIK] = filings
    fake_edgar.raws["o25"] = _f25_raw("New York Stock Exchange LLC", rule="17 CFR 240.12d2-2(c)", form_tag="25")
    if cover:
        fake_edgar.texts["ok"] = cover
    sec = _sec("BBG_OTC", ISSUER_CIK, "OTCX", "2009-01-02", "2026-09-25", "OTCX CORP")
    rows = _trading("OTCX", "2010-04-02", n=60, cusip="OTC000001", step=14)
    clf = DelistClassifier(fake_edgar, TickerResolver(fake_edgar))
    ctx = SecurityContexts.observed({sec.sec_id: sec}, {sec.sec_id: ["OTC000001"]}, FtdIndex(rows))(sec, False)
    assert ctx.record.trades_after("2010-07-03")
    return DelistingFinder(fake_edgar, clf).find(ctx)[0]


def test_a_security_that_traded_on_past_a_voluntary_form25_with_no_exchange_on_its_cover_moved_to_the_otc(fake_edgar):
    (d,) = _otc_world(fake_edgar, NO_EXCHANGE_COVER)
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (CrspBucket.COMPLIANCE_FAILURE, 520, None)
    assert [rw.rule for rw in d.rewrites] == [Rule.MOVED_OTC]
    assert "successor_unknown" not in d.flags and "2011-02-24" in d.record.reason


def test_an_exchange_on_the_cover_keeps_it_a_transfer_the_security_went_on_through(fake_edgar):
    (d,) = _otc_world(fake_edgar, NASDAQ_COVER)
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_OTC")


def test_a_cover_that_could_not_be_read_is_no_evidence_of_an_otc_move(fake_edgar):
    (d,) = _otc_world(fake_edgar, "")
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_OTC")


def test_the_issuers_8a12b_beside_its_form25_is_a_move_to_another_exchange_not_the_otc(fake_edgar):
    (d,) = _otc_world(fake_edgar, NO_EXCHANGE_COVER, eight_a=True)
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_OTC")


def test_edgars_otc_listing_today_is_the_evidence_when_no_cover_could_be_read(fake_edgar):
    """Light & Wonder 2025 (its 10-K's inline-XBRL cover has no column to read): EDGAR lists its tickers on the OTC
    market and on no exchange today, so the voluntary Form 25 it traded on past was a move to the OTC market."""
    (d,) = _otc_world(fake_edgar, "", listing=[("OTCX", "OTC")])
    assert (d.record.bucket, d.record.crsp_code, d.record.successor_sec_id) == (CrspBucket.COMPLIANCE_FAILURE, 520, None)
    assert [rw.rule for rw in d.rewrites] == [Rule.MOVED_OTC]
    assert "OTCX" in d.record.reason and "OTC market" in d.record.reason


def test_an_exchange_listing_of_its_ticker_is_no_otc_move(fake_edgar):
    (d,) = _otc_world(fake_edgar, "", listing=[("OTCX", "Nasdaq")])
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_OTC")


def test_an_8a12b_beside_the_form25_is_still_a_move_to_another_exchange_whatever_edgar_lists(fake_edgar):
    (d,) = _otc_world(fake_edgar, "", eight_a=True, listing=[("OTCX", "OTC")])
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_OTC")


def test_a_merger_the_continued_filings_rule_relabelled_is_no_merger_for_a_security_that_traded_on_otc(fake_edgar):
    """Retail Value Inc. 2022: an Item 2.01 (the last asset sales) and a 10-K after it made the voluntary Form 25 a
    'completed acquisition'; its shares traded over the counter for a year and its cover names no exchange."""
    (d,) = _otc_world(fake_edgar, NO_EXCHANGE_COVER, acquired_8k=True)
    assert (d.record.bucket, d.record.crsp_code) == (CrspBucket.COMPLIANCE_FAILURE, 520)
    assert [rw.rule for rw in d.rewrites] == [Rule.MOVED_OTC]


def test_with_an_exchange_on_the_cover_the_item_201_does_not_make_it_a_merger(fake_edgar):
    (d,) = _otc_world(fake_edgar, NASDAQ_COVER, acquired_8k=True)
    assert (d.record.bucket, d.record.successor_sec_id) == (CrspBucket.EXCHANGE_TRANSFER, "BBG_OTC")
