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
from delist_detection.identity.observations import Observation, TickerEra
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
    name: str = ""            # the name its era was observed under (blank: none, so no class letter)


def _identity(specs, rows, index=None):
    eras, res, issuers, cusips = {}, {}, {}, {}
    for sp in specs:
        era = TickerEra(sp.ticker, sp.first, sp.last, [Observation(sp.ticker, sp.first, sp.name)] if sp.name else [])
        source = sp.source or ("placeholder" if sp.sec_id.startswith("CIK") else "cusip")
        eras[era.key] = era
        res[era.key] = EraResolution(era.key, sp.sec_id, source, sp.candidate, (), tuple(sp.cusips))
        issuers[era.key] = Issuer(sp.cik)
        cusips[sp.sec_id] = list(sp.cusips)
    return Identity(list(eras.values()), eras, index if index is not None else FtdIndex(rows), issuers, res,
                    build_securities(res, eras, issuers), cusips)


class _Edgar:
    """Each issuer's record: its name, and its filings (by default, an 8-K item 5.03 on every CUSIP's first row
    date and a 10-Q for a period after every step, which `corroborate` takes as stating each switch). No full-text
    search (a test that wants one gives it `full_text_search`)."""

    full_text_search = None

    def __init__(self, filings=None, *, texts=None, name=NAME):
        self.filings, self.texts, self.name, self.read = filings, texts or {}, name, []
        self.former = []        # EDGAR's former names: {"name", "from", "to"}

    def submissions(self, cik, fresh_after=None):
        return {"name": self.name, "formerNames": self.former, "tickers": [], "exchanges": []}

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


def _follow(specs, rows, *, edgar=None, figi=None, review=(), log=None, index=None):
    identity = _identity(specs, rows, index)
    identity.review = list(review)
    edgar = edgar if edgar is not None else _Edgar(_stating(rows))
    clients = Clients(edgar=edgar, resolver=None, classifier=None, figi=figi or _Figi(), ftd_client=_NoFiles(),
                      issuers=IssuerRecord(edgar))
    return follow_lines(identity, clients, as_of=AS_OF, **({"log": log} if log else {}))


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


def test_a_line_whose_later_step_only_an_8k_names_reads_the_texts_in_that_round():
    """YRCW (batch 3 gate): the fails rows give the first step (a reverse split under the line's own ticker), and the
    second, Yellow's new ticker and CUSIP, is named only by the rename 8-K; the texts are read in the round the line
    first has no step, not only in the first round."""
    rows = _line("AA", ["C1", "C2"]) + [r for r in _line("YELL", ["X1", "X2", "985510106"]) if r.cusip == "985510106"]
    renamed = _firsts(rows)["985510106"]
    texts = {f"k-{renamed}": 'its common stock will trade under the ticker symbol "YELL", CUSIP number 985510106'}
    edgar = _Edgar(_stating(rows), texts=texts)
    lines = _follow([_Spec("BBGA", 1, "AA", ["C1"])], rows, edgar=edgar)
    assert lines.cusips == {"BBGA": ["C1", "C2", "985510106"]}
    assert "YELL" in lines.securities["BBGA"].line_tickers
    assert edgar.read.count(f"k-{renamed}") == 1        # each line end's texts are read once


def _moved_then_stopped(naming="the CUSIP number changed to 316645100", steps=1):
    """A line AA that takes `steps` steps from the fails rows (A1 -> A2 ...) and stops; the coded 8-K 19 days after
    its last CUSIP's settled last row names 316645100 in its text (`naming`), which trades under FNP from the week
    after. Returns the EDGAR double, the fails rows and the stage's answer."""
    chain = [f"A{i}" for i in range(1, steps + 2)]
    stop = _monday(WEEKS * len(chain) - 1)
    coded = EdgarSubmission("c1", "8-K", (date.fromisoformat(stop) + timedelta(days=19)).isoformat(), "", "5.03",
                            "d.htm")
    rows = _line("AA", chain) + [r for r in _line("FNP", ["X"] * len(chain) + ["316645100"]) if r.cusip != "X"]
    edgar = _Edgar([*_stating(rows), coded], texts={"c1": naming})
    return edgar, rows


def test_a_line_that_moved_and_then_stopped_reads_the_text_sources_for_its_second_step():
    """RRI 2009-2010: the step to RRI Energy comes from the fails rows in round 1, the later one to GenOn only from
    an 8-K's text, which is read for the line's new end in round 2."""
    edgar, rows = _moved_then_stopped()
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=edgar)
    assert lines.cusips == {"BBGA": ["A1", "A2", "316645100"]}
    assert lines.securities["BBGA"].line_tickers == {"FNP"}
    assert [f for _, f in _flags(lines)] == ["line_followed", "line_followed"]


def test_a_line_that_moved_and_then_stopped_with_no_text_source_behaves_as_before():
    edgar, rows = _moved_then_stopped(naming="nothing to see here")
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=edgar)
    assert lines.cusips == {"BBGA": ["A1", "A2"]} and lines.securities["BBGA"].line_tickers == frozenset()
    assert [f for _, f in _flags(lines)] == ["line_followed"]


def test_the_text_of_a_lines_end_is_read_once_however_many_rounds_follow(monkeypatch):
    """Two steps from the fails rows, then the text of the third round's end: read once, and not in the rounds in
    which the line still had a step."""
    from delist_detection.identity import line_follow
    reads, original = [], line_follow._Reads.text_sources

    def counting(self, s, end):
        reads.append((s.sec_id, end.settled))
        return original(self, s, end)

    monkeypatch.setattr(line_follow._Reads, "text_sources", counting)
    edgar, rows = _moved_then_stopped(steps=2)
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=edgar)
    assert lines.cusips == {"BBGA": ["A1", "A2", "A3", "316645100"]}
    assert reads == [("BBGA", _monday(WEEKS * 3 - 1))]


# --- a repeat call of the derived-line loop asks again only about the lines that changed ---------------------------

def _asked_ends(monkeypatch):
    """The (security, last CUSIP) of each line end whose 8-K texts `follow_lines` reads, and of each whose renamed-CUSIP
    pass it runs."""
    from delist_detection.identity import line_follow
    texts, passes = [], []
    text_sources, renamed = line_follow._Reads.text_sources, line_follow._Reads.renamed_cusips

    def counting_texts(self, s, end):
        texts.append((s.sec_id, end.cusip))
        return text_sources(self, s, end)

    def counting_pass(self, s, end, cusips, ftd):
        passes.append((s.sec_id, end.cusip))
        return renamed(self, s, end, cusips, ftd)

    monkeypatch.setattr(line_follow._Reads, "text_sources", counting_texts)
    monkeypatch.setattr(line_follow._Reads, "renamed_cusips", counting_pass)
    return texts, passes


STOPPED = [_Spec("BBGA", 1, "AA", ["A1"]), _Spec("BBGB", 2, "BB", ["B1"])]
STOPPED_ROWS = _line("AA", ["A1"]) + _line("BB", ["B1"])


def _follow_again(specs, rows, memo, edgar=None):
    """A round of the loop: the identity stage's answer built afresh, stage 4b given the loop's `memo`."""
    identity = _identity(specs, rows)
    edgar = edgar if edgar is not None else _Edgar(_stating(rows))
    clients = Clients(edgar=edgar, resolver=None, classifier=None, figi=_Figi(), ftd_client=_NoFiles(),
                      issuers=IssuerRecord(edgar))
    return follow_lines(identity, clients, as_of=AS_OF, memo=memo)


def test_a_round_that_touches_no_line_asks_stage_4b_about_none_and_gives_the_same_lines(monkeypatch):
    from delist_detection.identity.line_follow import LineMemo
    texts, passes = _asked_ends(monkeypatch)
    memo = LineMemo()
    first = _follow_again(STOPPED, STOPPED_ROWS, memo)
    assert texts == passes == [("BBGA", "A1"), ("BBGB", "B1")]
    again = _follow_again(STOPPED, STOPPED_ROWS, memo)
    assert texts == passes == [("BBGA", "A1"), ("BBGB", "B1")]            # no line asked again
    assert _fingerprint(again) == _fingerprint(first) == _fingerprint(_follow(STOPPED, STOPPED_ROWS))


def test_a_line_a_derived_era_joined_or_whose_cusips_changed_is_asked_again_and_no_other(monkeypatch):
    from delist_detection.identity.line_follow import LineMemo
    texts, passes = _asked_ends(monkeypatch)
    memo = LineMemo()
    _follow_again(STOPPED, STOPPED_ROWS, memo)
    del texts[:], passes[:]
    joined = [*STOPPED, _Spec("BBGA", 1, "AA2", ["A1"], first="2010-01-01", last="2011-01-01")]     # a new era of AA's
    again = _follow_again(joined, STOPPED_ROWS, memo)
    assert texts == passes == [("BBGA", "A1")]
    assert _fingerprint(again) == _fingerprint(_follow(joined, STOPPED_ROWS))
    del texts[:], passes[:]
    cusips = [STOPPED[0], _Spec("BBGB", 2, "BB", ["B1", "B0"])]                                 # a CUSIP added to BB's
    again = _follow_again(cusips, STOPPED_ROWS, memo)
    assert texts == passes == [("BBGA", "A1"), ("BBGB", "B1")]          # AA's stamp is the joined one's no more
    assert _fingerprint(again) == _fingerprint(_follow(cusips, STOPPED_ROWS))


def test_a_line_end_the_fails_index_now_shows_otherwise_is_asked_again(monkeypatch):
    from delist_detection.identity.line_follow import LineMemo
    texts, passes = _asked_ends(monkeypatch)
    memo = LineMemo()
    _follow_again(STOPPED, STOPPED_ROWS, memo)
    del texts[:], passes[:]
    longer = _line("AA", ["A1"]) + [FtdRow(_monday(WEEKS + 1), "A1", "AA", NAME, 12.0)] + _line("BB", ["B1"])
    _follow_again(STOPPED, longer, memo)
    assert texts == passes == [("BBGA", "A1")]


def test_a_read_that_rested_on_a_stale_copy_is_not_kept(monkeypatch):
    from delist_detection.identity.line_follow import LineMemo
    texts, passes = _asked_ends(monkeypatch)
    memo = LineMemo()
    _follow_again(STOPPED, STOPPED_ROWS, memo, edgar=_Down(_stating(STOPPED_ROWS), stale=True))
    del texts[:], passes[:]
    _follow_again(STOPPED, STOPPED_ROWS, memo)
    assert texts == passes == [("BBGA", "A1"), ("BBGB", "B1")]


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


# --- FB-003: the run log names each refused step ---------------------------------------------------------------

def test_the_run_log_names_each_refused_step_with_its_security_cusips_day_and_reason():
    """A full run's log lists every step the follow refused: the security, old CUSIP -> new CUSIP under the symbol
    from the first new row's day, and the reason (the review row, `line_follow_refused:<why>`, is unchanged)."""
    specs = [_Spec("BBGA", 1, "AA", ["A1"]), _Spec("BBGB", 1, "BB", ["B1"])]
    rows = _line("AA", ["A1", "C9"]) + _line("BB", ["B1", "C9"], weekday=1)
    logged = []
    lines = _follow(specs, rows, log=logged.append)
    assert sorted(_flags(lines)) == [("BBGA", "line_followed"), ("BBGB", "line_follow_refused:taken")]
    # C9's rows come first under AA's symbol (the same CUSIP fails weekly under both), so the step names AA
    first = _firsts(rows)["C9"]
    assert [m for m in logged if m.startswith("line follow refused:")] == [
        f"line follow refused: BBGB B1 -> C9 under AA from {first} (taken)"]


# --- FB-003: a placeholder's new CUSIP held by a security of its own issuer ---------------------------------------------

def _held(holder_kw=None, holder_cik=1, placeholder="CIK1-COMMON", others=(), figi_for="BBGH", described=None):
    """A placeholder AA (CUSIP A1) whose next CUSIP C9 another security of the run, BBGH (ticker HH, issuer
    `holder_cik`), holds; `others` are further securities of the run."""
    kw = {"name": "REVERSE SPLIT CO CLASS B", **(holder_kw or {})}
    specs = [_Spec(placeholder, 1, "AA", ["A1"]), _Spec("BBGH", holder_cik, "HH", ["C9"], **kw), *others]
    desc = described or NAME
    rows = _line("AA", ["A1", "C9"], desc=desc)
    return _follow(specs, rows, figi=_Figi({"C9": _answer(figi_for)}))


def test_a_placeholder_folds_into_the_line_of_its_issuer_that_holds_its_next_cusip():
    """IAC 2008 and WPO 2013: the placeholder's old CUSIP ended as a FIGI line of the same issuer began on the new
    one, which that line holds; the "another security holds it" guard is for another issuer's line (WLL, LMCA, MSG)."""
    lines = _held({"name": ""})
    assert lines.renames == {"CIK1-COMMON": "BBGH"} and set(lines.securities) == {"BBGH"}
    assert set(lines.cusips["BBGH"]) == {"A1", "C9"}
    assert [(r.flag, r.reason.rsplit(": ", 1)[1]) for r in lines.review] == [("line_followed", "folded into BBGH")]


def test_a_plain_placeholder_folds_into_the_lettered_line_its_cusips_descriptions_name():
    """WPO 2013 through the stage: COMMON placeholder, the holder's class B, the old CUSIP's descriptions say CLB."""
    lines = _held(described=NAME + " CLB", holder_kw={"name": NAME + " CLASS B"})
    assert lines.renames == {"CIK1-COMMON": "BBGH"}


def test_a_plain_placeholder_does_not_fold_when_its_issuer_has_lines_of_two_letters():
    others = [_Spec("BBGOTHER", 1, "OO", ["O1"], name="REVERSE SPLIT CO CLASS A")]
    lines = _held(described=NAME + " CLB", holder_kw={"name": NAME + " CLASS B"}, others=others)
    assert lines.renames == {} and set(lines.securities) >= {"CIK1-COMMON", "BBGH"}
    assert [f for _, f in _flags(lines)] == []


def test_a_figi_line_never_steps_to_a_cusip_another_security_of_its_issuer_holds():
    """WLL 2017 must not change: only a placeholder is the same line as the holder (a fold); two FIGI lines are
    two securities of the run, and their link is stage 9's."""
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"]), _Spec("BBGH", 1, "HH", ["C9"])], _line("AA", ["A1", "C9"]),
                    figi=_Figi({"C9": _answer("BBGH")}))
    assert lines.renames == {} and lines.successors == {} and _flags(lines) == []


def test_a_placeholder_never_steps_to_a_cusip_another_issuers_security_holds():
    """New LMCA 2013 and new MSG 2015 must not change."""
    lines = _held(holder_cik=2)
    assert lines.renames == {} and _flags(lines) == []


def test_a_placeholder_does_not_fold_into_a_line_that_trades_on_under_another_cusip():
    """The holder has another CUSIP still failing past the new one's first row: a second live line of the issuer,
    not the placeholder's next CUSIP."""
    specs = [_Spec("CIK1-COMMON", 1, "AA", ["A1"]), _Spec("BBGH", 1, "HH", ["H0", "C9"])]
    rows = _line("AA", ["A1", "C9"]) + [FtdRow(_monday(2 * WEEKS + 3 + i), "H0", "HH", NAME, 20.0 + i)
                                         for i in range(5)]
    lines = _follow(specs, rows, figi=_Figi({"C9": _answer("BBGH")}))
    assert lines.renames == {} and _flags(lines) == []


# --- FB-003: the tickers a round attached are loaded before the next round ---------------------------------------------

class _FailsFiles:
    """A fails source over rows: the index holds only what it was asked for, as with SEC's files."""

    def __init__(self, rows):
        self.rows_ = list(rows)

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.rows_:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


def test_a_new_ticker_a_round_attached_is_loaded_for_the_next_round():
    """EXBD 2012-2015: CEB is the same CUSIP under a new ticker (round 1); the 2015 switch to 125134106 is found
    under CEB, whose rows the index must then hold (it held the old CUSIP's rows and the old ticker's only)."""
    old = _line("AA", ["A1"])
    renamed = [FtdRow(_monday(WEEKS + w), "A1", "BB", NAME, 20.0 + w * 0.01) for w in range(WEEKS)]
    new = [FtdRow(_monday(2 * WEEKS + w), "C9", "BB", NAME, 30.0 + w * 0.01) for w in range(WEEKS)]
    everything = old + renamed + new
    held = [r for r in everything if r.symbol == "AA" or r.cusip == "A1"]       # what stage 1 opened it with
    index = FtdIndex(held, source=_FailsFiles(everything), window=(date(2008, 1, 1), AS_OF))
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], everything, index=index, figi=_Figi({"C9": _answer("BBGA")}))
    assert lines.cusips == {"BBGA": ["A1", "C9"]} and lines.securities["BBGA"].line_tickers == {"BB"}
    assert [f for _, f in _flags(lines)] == ["line_followed", "line_followed"]


# --- FB-003: a rename EDGAR dates, whose new ticker neither EDGAR nor the 8-K names (DV to ATGE) ------------------------

class _EveryFile(_FailsFiles):
    """`_FailsFiles` that also reads a whole file when asked for no key (`FtdIndex.every_row`), counting such reads."""

    def __init__(self, rows):
        super().__init__(rows)
        self.whole = 0

    def rows(self, url, *, symbols=None, cusips=None):
        if symbols is None and cusips is None:
            self.whole += 1
            yield from self.rows_
        else:
            yield from super().rows(url, symbols=symbols, cusips=cusips)


def _renamed(*, rename_at="stop", new_desc=NAME):
    """AA (OLD NAME CO) fails for WEEKS weeks on A1; REVERSE SPLIT CO's C9 then fails under ZZ, a ticker nobody
    names. EDGAR dates the issuer's rename from OLD NAME CO (`rename_at`: the stop, or years before)."""
    old, new = _line("AA", ["A1"], desc="OLD NAME CO"), _line("ZZ", ["X", "C9"], desc=new_desc)
    new = [r for r in new if r.cusip == "C9"]
    everything = old + new
    stop = date.fromisoformat(_monday(WEEKS - 1))
    day = stop if rename_at == "stop" else date(2009, 1, 5)
    former = [{"name": "OLD NAME CO", "from": "2000-01-01T00:00:00.000Z", "to": f"{day.isoformat()}T04:00:00.000Z"}]
    files = _EveryFile(everything)
    index = FtdIndex([r for r in everything if r.symbol == "AA" or r.cusip == "A1"], source=files,
                     window=(date(2008, 1, 1), AS_OF))
    edgar = _Edgar(_stating(everything), name=NAME)
    edgar.former = former
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], everything, edgar=edgar, index=index)
    return lines, files


def test_a_rename_edgar_dates_finds_the_new_cusip_by_the_name_its_fails_rows_carry():
    """DV 2017: DeVry renamed itself Adtalem on 2017-05-24 and the new CUSIP 00737L103 failed from that day under
    ATGE, which EDGAR no longer lists (it lists CVSA today) and the 8-K 5.03 does not name. The rows near the stop
    that carry the name EDGAR dates the issuer's rename to are the line's next CUSIP."""
    lines, files = _renamed()
    assert lines.cusips == {"BBGA": ["A1", "C9"]} and lines.securities["BBGA"].line_tickers == {"ZZ"}
    assert [f for _, f in _flags(lines)] == ["line_followed"] and files.whole == 1


def test_no_rename_near_the_stop_reads_no_whole_file():
    lines, files = _renamed(rename_at="long ago")
    assert lines.cusips == {"BBGA": ["A1"]} and _flags(lines) == [] and files.whole == 0


@pytest.mark.parametrize("new_desc", ["ANOTHER WIDGET CORP",
                                      "SPLIT REVERSE CO"])      # both words, another first word: Global X beside Adtalem Global
def test_rows_that_do_not_carry_the_new_name_are_no_next_cusip(new_desc):
    lines, files = _renamed(new_desc=new_desc)
    assert lines.cusips == {"BBGA": ["A1"]} and _flags(lines) == [] and files.whole == 1


def test_a_placeholder_folds_into_the_holder_of_its_next_cusip_whatever_openfigi_answers():
    """SVC 2019 and UNIT 2017: OpenFIGI names no US composite for the new CUSIP (decide alone would attach), but the
    placeholder's issuer's FIGI line holds it: the placeholder folds into that line, never takes a held CUSIP."""
    specs = [_Spec("CIK1-COMMON", 1, "AA", ["A1"]), _Spec("BBGH", 1, "HH", ["C9"])]
    rows = _line("AA", ["A1", "C9"])
    for figi in (_Figi({}), _Figi({"C9": _answer("BBGOTHER")})):
        lines = _follow(specs, rows, figi=figi)
        assert lines.renames == {"CIK1-COMMON": "BBGH"} and set(lines.securities) == {"BBGH"}
        assert [c for c, hs in _holders_of(lines).items() if len(hs) > 1] == []


def _holders_of(lines):
    held = {}
    for sid, cusips in lines.cusips.items():
        for c in cusips:
            held.setdefault(c, set()).add(sid)
    return held


def test_a_refused_step_is_returned_with_its_security_and_why():
    """A registrant that merged out (no periodic report after the step) refuses the step; the stage hands it back."""
    rows = _line("AA", ["A1", "A2"])
    lines = _follow([_Spec("BBGA", 1, "AA", ["A1"])], rows, edgar=_Edgar([f for f in _stating(rows) if f is not LATER_10Q]))
    [r] = lines.refused
    assert (r.sec_id, r.why, r.step.old_cusip, r.step.new_cusip, r.step.symbol) == ("BBGA", "merged_out", "A1", "A2", "AA")
    assert _flags(lines) == [("BBGA", "line_follow_refused:merged_out")]


def test_a_refused_step_of_a_folded_placeholder_carries_its_figi_line():
    """A placeholder folds into a FIGI line at its first switch; the next switch has no filing and is refused: the
    refused step names the FIGI line, as the review items do."""
    rows = _line("PP", ["P1", "N1", "N2"])
    stated = [f for f in _stating(rows) if f.filing_date != _firsts(rows)["N2"]]
    lines = _follow([_Spec("CIK5-COMMON", 5, "PP", ["P1"])], rows, edgar=_Edgar(stated),
                    figi=_Figi({"N1": _answer("BBGX1")}))
    assert lines.renames == {"CIK5-COMMON": "BBGX1"}
    [r] = lines.refused
    assert (r.sec_id, r.why, r.step.new_cusip) == ("BBGX1", "no_filing", "N2")
    assert ("BBGX1", "line_follow_refused:no_filing") in _flags(lines)
