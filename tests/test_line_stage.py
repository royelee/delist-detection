"""Stage 4b at its interface, `line_follow.follow_lines`: the rounds, the holders, the folds (a placeholder's, a fold
of a fold, sub-plan 5h's today-holder fold), the 8-K text sources, the failures that must stop a run and the reads
that must not be cached. Each line's steps come from fails rows built here, its issuer's record from an EDGAR double
and its new CUSIPs' composites from an OpenFIGI double. tests/test_line_follow.py covers the rules one by one, and
tests/test_line_follow_cases.py runs real cases through both."""
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
import requests

from delist_detection.sources.edgar import EdgarBlocked, EdgarSubmission
from delist_detection.identity.figi_resolution import FigiCandidate
from delist_detection.sources.ftd import FtdIndex, FtdRow
from delist_detection.identity.identity import Identity
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.identity.line_follow import MAX_ROUNDS, MAX_TEXTS, follow_lines
from delist_detection.identity.observations import TickerEra
from delist_detection.sources.openfigi import OpenFigiUnavailable
from delist_detection.pipeline import Clients
from delist_detection.outputs.review_triage import ReviewItem
from delist_detection.sources.sec_stats import SEC_STATS
from delist_detection.identity.security_master import EraResolution, Issuer, build_securities

AS_OF = date(2026, 9, 25)
NAME = "REVERSE SPLIT CO"
WEEKS = 8                 # each CUSIP of a line fails weekly this many weeks
START = "2012-01-02"      # a Monday: the first CUSIP's first row
LATER_10Q = EdgarSubmission("q1", "10-Q", "2026-08-01", "2026-06-30", "", "q.htm")


def _monday(n: int) -> str:
    """The `n`-th Monday from START."""
    return (date.fromisoformat(START) + timedelta(weeks=n)).isoformat()


def _line(ticker, cusips, *, desc=NAME, weekday=0):
    """A line's fails rows: each of `cusips` fails weekly under `ticker` for WEEKS weeks at changing prices, the next
    from the week after the last (a switch the stage can follow); `weekday` days after each Monday."""
    rows, price = [], 10.0
    for i, cusip in enumerate(cusips):
        for w in range(WEEKS):
            day = date.fromisoformat(_monday(i * WEEKS + w)) + timedelta(days=weekday)
            rows.append(FtdRow(day.isoformat(), cusip, ticker, desc, round(price, 2)))
            price += 0.01
    return rows


def _firsts(rows):
    """Each CUSIP's first row date."""
    first = {}
    for r in sorted(rows, key=lambda r: r.date):
        first.setdefault(r.cusip, r.date)
    return first


@dataclass
class _Spec:
    """One security of the identity stage's answer: its era (ticker, span), resolution and CUSIPs."""
    sec_id: str
    cik: int
    ticker: str
    cusips: list
    source: str = ""
    candidate: FigiCandidate | None = None
    first: str = "2008-01-01"
    last: str = "2009-01-01"


def _identity(specs, rows):
    eras, res, issuers, cusips = {}, {}, {}, {}
    for sp in specs:
        era = TickerEra(sp.ticker, sp.first, sp.last)
        source = sp.source or ("placeholder" if sp.sec_id.startswith("CIK") else "cusip")
        eras[era.key] = era
        res[era.key] = EraResolution(era.key, sp.sec_id, source, sp.candidate, (), tuple(sp.cusips))
        issuers[era.key] = Issuer(sp.cik)
        cusips[sp.sec_id] = list(sp.cusips)
    return Identity(list(eras.values()), eras, FtdIndex(rows), issuers, res,
                    build_securities(res, eras, issuers), cusips)


class _Edgar:
    """Each issuer's record: its name, and its filings (by default, an 8-K item 5.03 on every CUSIP's first row
    date and a 10-Q for a period after every step, which `corroborate` takes as stating each switch). No full-text
    search (a test that wants one gives it `full_text_search`)."""

    full_text_search = None

    def __init__(self, filings=None, *, texts=None, name=NAME):
        self.filings, self.texts, self.name, self.read = filings, texts or {}, name, []

    def submissions(self, cik, fresh_after=None):
        return {"name": self.name, "formerNames": [], "tickers": [], "exchanges": []}

    def recent_filings(self, cik):
        return list(self.filings)

    def fetch_filing_text(self, cik, accession, primary_doc):
        self.read.append(accession)
        return self.texts.get(accession, "")


def _stating(rows):
    """The filings that state every switch of `rows` (see `_Edgar`)."""
    return [EdgarSubmission(f"k-{d}", "8-K", d, d, "5.03", "k.htm") for d in sorted(set(_firsts(rows).values()))] \
        + [LATER_10Q]


def _answer(composite, ticker="RS", name=NAME):
    return {"data": [{"figi": composite, "compositeFIGI": composite, "exchCode": "US", "ticker": ticker,
                      "name": name, "securityType": "Common Stock", "securityType2": "Common Stock"}]}


class _Figi:
    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.asked = answers or {}, error, []

    def map(self, jobs, use_cache=True):
        if self.error:
            raise self.error
        self.asked += [j["idValue"] for j in jobs]
        return [self.answers.get(j["idValue"], {"warning": "No identifier found."}) for j in jobs]


class _NoFiles:
    """The fails files: the index already holds every row (`FtdIndex.extend` scans no file)."""

    def urls_for(self, lo, hi):
        return []


def _follow(specs, rows, *, edgar=None, figi=None, review=()):
    identity = _identity(specs, rows)
    identity.review = list(review)
    edgar = edgar if edgar is not None else _Edgar(_stating(rows))
    clients = Clients(edgar=edgar, resolver=None, classifier=None, figi=figi or _Figi(), ftd_client=_NoFiles(),
                      issuers=IssuerRecord(edgar))
    return follow_lines(identity, clients, as_of=AS_OF)


def _flags(lines):
    return [(r.sec_id, r.flag) for r in lines.review]


# --- the rounds ----------------------------------------------------------------------------------------------------

def test_a_chain_of_switches_is_followed_up_to_max_rounds_and_no_further():
    """WIN: two reverse splits are two steps of one line; the follow takes MAX_ROUNDS steps at most."""
    lines = _follow([_Spec("BBGA", 1, "AA", ["C1"])], _line("AA", ["C1", "C2", "C3", "C4", "C5", "C6"]))
    assert MAX_ROUNDS == 3
    assert lines.cusips["BBGA"] == ["C1", "C2", "C3", "C4"]          # the C4 -> C5 step is a fourth
    short = _follow([_Spec("BBGA", 1, "AA", ["C1"])], _line("AA", ["C1", "C2", "C3"]))
    assert short.cusips["BBGA"] == ["C1", "C2", "C3"]
    assert [f for _, f in _flags(short)] == ["line_followed", "line_followed"]


def _fingerprint(lines):
    return ({k: (s.sec_id, s.issuer_cik, s.figi_source, tuple(e.key for e in s.eras), s.line_tickers)
             for k, s in lines.securities.items()},
            lines.cusips, lines.renames, {k: (v.composite, v.step.new_cusip) for k, v in lines.successors.items()},
            sorted(_flags(lines)))


def test_the_securities_in_any_order_give_the_same_lines():
    specs = [_Spec("BBGA", 1, "AA", ["A1"]), _Spec("CIK5-COMMON", 5, "PP", ["P1"]), _Spec("BBGF", 6, "FF", ["F1"])]
    rows = _line("AA", ["A1", "A2"]) + _line("PP", ["P1", "P2"]) + _line("FF", ["F1", "F2"])
    figi = lambda: _Figi({"P2": _answer("BBGX1"), "F2": _answer("BBGY1")})
    fwd = _follow(specs, rows, figi=figi())
    rev = _follow(list(reversed(specs)), rows, figi=figi())
    assert _fingerprint(fwd) == _fingerprint(rev)
    assert fwd.renames == {"CIK5-COMMON": "BBGX1"} and set(fwd.successors) == {"BBGF"}
    assert fwd.cusips == {"BBGA": ["A1", "A2"], "BBGX1": ["P1", "P2"], "BBGF": ["F1"]}


# --- the holders: a CUSIP or a composite held per round ------------------------------------------------------------

def test_a_new_cusip_one_security_took_is_held_for_the_rest_of_the_round():
    """Two lines of the run both step to C9 (no US line for it): the first (sec_id order) takes it, the second is
    refused, in any input order."""
    specs = [_Spec("BBGA", 1, "AA", ["A1"]), _Spec("BBGB", 1, "BB", ["B1"])]
    rows = _line("AA", ["A1", "C9"]) + _line("BB", ["B1", "C9"], weekday=1)
    for order in (specs, list(reversed(specs))):
        lines = _follow(order, rows)
        assert lines.cusips == {"BBGA": ["A1", "C9"], "BBGB": ["B1"]}
        assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGB", "line_follow_refused:taken")]


def test_two_lines_of_one_round_cannot_take_the_same_successor_composite():
    """Two FIGI lines whose new CUSIPs both map to BBGX1: the first (sec_id order) is its successor, the second is
    refused `taken`, in any input order."""
    specs = [_Spec("BBGA", 1, "AA", ["A1"]), _Spec("BBGB", 2, "BB", ["B1"])]
    rows = _line("AA", ["A1", "A2"]) + _line("BB", ["B1", "B2"])
    for order in (specs, list(reversed(specs))):
        lines = _follow(order, rows, figi=_Figi({"A2": _answer("BBGX1"), "B2": _answer("BBGX1")}))
        assert set(lines.successors) == {"BBGA"}
        assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGB", "line_follow_refused:taken")]


def test_a_new_cusip_whose_composite_another_issuers_security_holds_is_refused():
    """The step is otherwise valid (corroborated, one composite): only R2's other_issuer refusal stops it."""
    specs = [_Spec("BBGA", 1, "AA", ["A1"]), _Spec("BBGO", 2, "OO", ["O1"])]
    rows = _line("AA", ["A1", "C9"]) + _line("OO", ["O1"])
    lines = _follow(specs, rows, figi=_Figi({"C9": _answer("BBGO")}))
    assert lines.cusips == {"BBGA": ["A1"], "BBGO": ["O1"]} and lines.successors == {}
    assert _flags(lines) == [("BBGA", "line_follow_refused:other_issuer")]


# --- the folds -----------------------------------------------------------------------------------------------------

def test_a_folded_placeholders_items_follow_it_to_its_figi_line():
    """A placeholder whose new CUSIP names a FIGI line becomes that line: its eras, CUSIPs and review items move
    (its `no_figi` item is dropped: it holds a FIGI after all), and the identity stage's items come first."""
    before = [ReviewItem("CIK5-COMMON", "PP", 5, "no_figi", "no FIGI"),
              ReviewItem("CIK5-COMMON", "PP", 5, "ticker_unconfirmed", "x"), ReviewItem("BBGA", "AA", 1, "x", "y")]
    lines = _follow([_Spec("BBGA", 1, "AA", []), _Spec("CIK5-COMMON", 5, "PP", ["P1"])], _line("PP", ["P1", "P2"]),
                    figi=_Figi({"P2": _answer("BBGX1")}), review=before)
    assert lines.renames == {"CIK5-COMMON": "BBGX1"} and set(lines.securities) == {"BBGA", "BBGX1"}
    assert {e.ticker for e in lines.securities["BBGX1"].eras} == {"PP"}
    assert lines.resolutions["PP@2008-01-01"].source == "handoff"
    assert _flags(lines) == [("BBGX1", "ticker_unconfirmed"), ("BBGA", "x"), ("BBGX1", "line_followed")]


def test_a_fold_chain_collapses_to_the_final_figi():
    """A placeholder folds into a ticker-tier FIGI line of its issuer (round 1), which the line's next CUSIP then
    folds into its own composite (round 2, the today-holder fold): both renames point at the last FIGI, which holds
    every CUSIP of the line."""
    cand = FigiCandidate("BBGF0", NAME, "FF", "Common Stock", ())
    specs = [_Spec("CIK7-COMMON", 7, "PP", ["P1"]),
             _Spec("BBGF0", 7, "FF", [], source="ticker", candidate=cand, first="2020-01-02", last="2020-12-31")]
    lines = _follow(specs, _line("PP", ["P1", "N1", "N2"]),
                    figi=_Figi({"N1": _answer("BBGF0", "FF"), "N2": _answer("BBGX9", "PPQ")}))
    assert lines.renames == {"CIK7-COMMON": "BBGX9", "BBGF0": "BBGX9"}
    assert lines.cusips == {"BBGX9": ["P1", "N1", "N2"]} and set(lines.securities) == {"BBGX9"}
    assert _flags(lines) == [("BBGX9", "line_followed"), ("BBGX9", "line_followed")]


# rule F, CRC and BTU (sub-plan 5h): the ticker tier's composite is the line that took the ticker over later

CRC, CRC_OLD, CRC_NEW, CRC_SPLIT = "BBG00Y04KP80", "13057Q107", "13057Q206", "BBG0060B3M63"
CRC_NAME = "CALIFORNIA RESOURCES CORP"


def _crc(*, pick="CRC", source="ticker", today="CRCQQ"):
    """California Resources' 2014-2015 era, which the ticker tier gave BBG00Y04KP80 (the ticker `pick` today), its
    2016 reverse split's CUSIP mapping to BBG0060B3M63 (whose ticker is `today`)."""
    cand = FigiCandidate(CRC, CRC_NAME, pick, "Common Stock", ())
    spec = _Spec(CRC, 1609253, "CRC", [CRC_OLD], source=source, candidate=cand, first="2014-12-31", last="2015-12-31")
    rows = _line("CRC", [CRC_OLD, CRC_NEW], desc=CRC_NAME)
    return _follow([spec], rows, edgar=_Edgar(_stating(rows), name=CRC_NAME),
                   figi=_Figi({CRC_NEW: _answer(CRC_SPLIT, today, CRC_NAME)}))


def test_a_ticker_pick_today_holding_the_ticker_folds_into_the_lines_next_composite():
    """CRC 2014-2016: the ticker gave BBG00Y04KP80 (CRC today, the post-2020 line); the 2016 reverse split's CUSIP
    13057Q206 is BBG0060B3M63, whose ticker is now CRCQQ (it went bankrupt in 2020): one security, BBG0060B3M63."""
    lines = _crc()
    assert lines.renames == {CRC: CRC_SPLIT} and lines.successors == {}
    assert set(lines.securities) == {CRC_SPLIT} and lines.cusips == {CRC_SPLIT: [CRC_OLD, CRC_NEW]}
    assert [r.reason.rsplit(": ", 1)[1] for r in lines.review] == [f"folded into {CRC_SPLIT}"]


@pytest.mark.parametrize("why,kw", [("the new composite holds the ticker today", {"today": "CRC"}),
                                    ("the ticker pick names another ticker", {"pick": "CRCX"}),
                                    ("a line confirmed by its CUSIP", {"source": "cusip"})])
def test_a_line_successor_that_kept_the_ticker_or_a_cusip_line_stays_a_successor(why, kw):
    """Guards: the new composite holds the ticker today (a holding company's new line: the old one ended); the
    ticker pick names another ticker (an old line OpenFIGI still lists); a line confirmed by its CUSIP."""
    lines = _crc(**kw)
    assert lines.renames == {} and set(lines.securities) == {CRC}, why
    assert {k: v.composite for k, v in lines.successors.items()} == {CRC: CRC_SPLIT}, why


def test_the_follow_leaves_its_input_identity_as_it_was():
    """Final review M7: the securities the follow changes are copies in its answer; the identity's own securities,
    resolutions and CUSIPs are unchanged (BBGA takes the ticker FNP on its own CUSIP)."""
    rows = _line("AA", ["A1"]) + [r for r in _line("FNP", ["X", "A1"]) if r.cusip != "X"]
    identity = _identity([_Spec("BBGA", 1, "AA", ["A1"])], rows)
    before = (dict(identity.securities), {k: s.line_tickers for k, s in identity.securities.items()},
              dict(identity.resolutions), {k: list(v) for k, v in identity.cusips.items()})
    edgar = _Edgar(_stating(rows))
    lines = follow_lines(identity, Clients(edgar=edgar, resolver=None, classifier=None, figi=_Figi(),
                                           ftd_client=_NoFiles(), issuers=IssuerRecord(edgar)), as_of=AS_OF)
    assert lines.securities["BBGA"].line_tickers == {"FNP"}
    assert (dict(identity.securities), {k: s.line_tickers for k, s in identity.securities.items()},
            dict(identity.resolutions), {k: list(v) for k, v in identity.cusips.items()}) == before
    assert identity.securities["BBGA"].line_tickers == frozenset()


# --- the 8-K text sources -------------------------------------------------------------------------------------------

def test_the_text_sources_filter_the_8ks_before_the_cap():
    """A busy issuer's coded 8-K among more than MAX_TEXTS uncoded ones nearer the line's stop is still read, and
    the CUSIP it names is the line's next step (Liz Claiborne's "316645100" under FNP)."""
    stop = _monday(WEEKS - 1)                     # A1's settled last row
    uncoded = [EdgarSubmission(f"u{i}", "8-K", stop, "", "8.01", "d.htm") for i in range(MAX_TEXTS + 2)]
    coded = EdgarSubmission("c1", "8-K", (date.fromisoformat(stop) + timedelta(days=19)).isoformat(), "", "5.03",
                            "d.htm")
    edgar = _Edgar([*uncoded, coded, LATER_10Q], texts={"c1": "the CUSIP number changed to 316645100"})
    rows = _line("AA", ["A1"]) + [r for r in _line("FNP", ["X", "316645100"]) if r.cusip != "X"]
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=edgar)
    assert edgar.read == ["c1"]
    assert lines.cusips == {"BBGA": ["A1", "316645100"]} and lines.securities["BBGA"].line_tickers == {"FNP"}


# --- failures: the ones that stop the run, and the reads that are reported, never cached ---------------------------

def test_openfigi_unavailable_inside_the_stage_stops_the_run():
    with pytest.raises(OpenFigiUnavailable):
        _follow([_Spec("BBGA", 1, "AA", ["A1"])], _line("AA", ["A1", "A2"]), figi=_Figi(error=OpenFigiUnavailable("x")))


class _Down(_Edgar):
    """The submissions read fails with `exc`, or (`stale`) answers from a stale copy."""

    def __init__(self, filings, exc=None, *, stale=False):
        super().__init__(filings)
        self.exc, self.stale, self.calls = exc, stale, 0

    def submissions(self, cik, fresh_after=None):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        if self.stale:
            SEC_STATS.degraded("submissions")
        return super().submissions(cik)


def test_a_refused_submissions_read_inside_the_stage_stops_the_run():
    rows = _line("AA", ["A1", "A2"])
    with pytest.raises(EdgarBlocked):
        _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=_Down(_stating(rows), EdgarBlocked("403")))


def test_a_degraded_submissions_read_gives_the_security_a_resolution_degraded_row():
    rows = _line("AA", ["A1", "A2"])
    edgar = _Down(_stating(rows), stale=True)
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=edgar)
    assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGA", "resolution_degraded")]
    assert edgar.calls > 1                         # a stale copy is never remembered: each ask reads again


def test_a_failed_read_inside_the_stage_gives_a_resolution_degraded_row():
    rows = _line("AA", ["A1", "A2"])
    edgar = _Down(_stating(rows), requests.ConnectionError("down"))
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=edgar)
    assert ("BBGA", "resolution_degraded") in _flags(lines)
    assert edgar.calls > 1                         # a failed read is never remembered


def test_a_failed_read_that_leaves_no_step_still_gives_a_resolution_degraded_row():
    rows = _line("AA", ["A1"])
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows,
                    edgar=_Down(_stating(rows), requests.ConnectionError("down")))
    assert _flags(lines) == [("BBGA", "resolution_degraded")]


def _renamed_lately():
    """A line renamed AA -> BB on its own CUSIP within `RECENT_DAYS` of the run date (BB from 2026-06-29), with no
    periodic report after it yet: R1 then rests on whether BB is listed today (UNIT 2025)."""
    rows, price = [], 10.0
    for w in range(2 * WEEKS):
        day = (date(2026, 5, 4) + timedelta(weeks=w)).isoformat()
        rows.append(FtdRow(day, "A1", "AA" if w < WEEKS else "BB", NAME, round(price, 2)))
        price += 0.01
    return [_Spec("BBGA", 1, "AA", ["A1"], first="2026-05-04", last="2026-06-22")], rows


def test_a_failed_listed_today_read_refuses_a_recent_step_and_never_stops_the_run():
    """Architecture step 7a: the listed-today read of a recent step goes through the issuer record. When it fails
    the step is refused `merged_out` (nothing says the old registrant carries on) and degraded; the run goes on (it
    used to stop). With the read answered (BB on NYSE) the same step is followed."""
    class Listed(_Edgar):
        def submissions(self, cik, fresh_after=None):
            return {"name": NAME, "formerNames": [], "tickers": ["BB"], "exchanges": ["NYSE"]}

    specs, rows = _renamed_lately()
    followed = _follow(specs, rows, edgar=Listed([]))
    assert _flags(followed) == [("BBGA", "line_followed")] and followed.securities["BBGA"].line_tickers == {"BB"}
    specs, rows = _renamed_lately()
    edgar = _Down([], requests.ConnectionError("down"))
    lines = _follow(specs, rows, edgar=edgar)
    assert sorted(_flags(lines)) == [("BBGA", "line_follow_refused:merged_out"), ("BBGA", "resolution_degraded")]
    assert lines.securities["BBGA"].line_tickers == frozenset() and edgar.calls > 0


def test_a_failed_8k_text_read_that_leaves_no_step_gives_one_resolution_degraded_row():
    class TextDown(_Edgar):
        def fetch_filing_text(self, cik, accession, primary_doc):
            raise requests.ConnectionError("down")

    near = (date.fromisoformat(_monday(WEEKS - 1)) + timedelta(days=3)).isoformat()
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], _line("AA", ["A1"]),
                    edgar=TextDown([EdgarSubmission("a1", "8-K", near, "", "5.03", "d.htm")]))
    assert _flags(lines) == [("BBGA", "resolution_degraded")]


def test_a_failed_other_registrant_search_refuses_the_step_and_degrades_it():
    """The other-registrant search (R1) failing reads as `read_failed`, never as no other registrant. The double is
    production's shape (`EdgarClient.full_text_search`): a failed read counts itself degraded and answers no hits."""
    class SearchDown(_Edgar):
        def full_text_search(self, q, forms, lo, hi):
            SEC_STATS.degraded("failed_request")
            return []

    rows = _line("AA", ["A1", "A2"])
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=SearchDown(_stating(rows)))
    assert sorted(_flags(lines)) == [("BBGA", "line_follow_refused:read_failed"), ("BBGA", "resolution_degraded")]
    assert lines.cusips == {"BBGA": ["A1"]}


def _other_filer(listing):
    """An issuer's record whose other-registrant search names another filer (OTHER CO, OTH, CIK 999): `listing` is
    that filer's submissions read."""
    class Edgar(_Edgar):
        def full_text_search(self, q, forms, lo, hi):
            return [{"_source": {"ciks": ["0000000999"], "display_names": ["OTHER CO (OTH) (CIK 0000000999)"],
                                 "form": "8-K12B", "file_date": "2012-03-01"}}]

        def submissions(self, cik, fresh_after=None):
            return listing() if int(cik) == 999 else super().submissions(cik)
    return Edgar


def test_a_failed_read_of_the_other_filers_listing_refuses_the_step_and_degrades_it():
    """The filer the search names may be another issuer's own listed stock (skipped) or the old registrant's
    successor: with its listing unread nothing is known, so the step is refused `read_failed`."""
    def down():
        SEC_STATS.degraded("failed_request")
        raise requests.ConnectionError("down")

    rows = _line("AA", ["A1", "A2"])
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=_other_filer(down)(_stating(rows)))
    assert sorted(_flags(lines)) == [("BBGA", "line_follow_refused:read_failed"), ("BBGA", "resolution_degraded")]
    assert lines.cusips == {"BBGA": ["A1"]}


def test_a_step_whose_other_filers_listing_answered_from_a_stale_copy_is_followed_and_degraded():
    """A read answered from a stale copy is an answer (production's submissions read serves its cached copy, counted
    degraded): the filer's stale listing says OTH is its own NYSE stock, so it is no successor of the issuer and the
    step is followed; the step's answer rested on the stale copy, so it is degraded too."""
    def stale():
        SEC_STATS.degraded("stale_copy")
        return {"name": "OTHER CO", "tickers": ["OTH"], "exchanges": ["NYSE"]}

    rows = _line("AA", ["A1", "A2"])
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=_other_filer(stale)(_stating(rows)))
    assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGA", "resolution_degraded")]
    assert lines.cusips == {"BBGA": ["A1", "A2"]}
