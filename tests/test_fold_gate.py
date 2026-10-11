"""A fold of an unobserved CUSIP part is kept only when the era has no composite of its own and stage 4b's R1 test would
follow the step (`identity._check_folds`, `refine_eras(unfold=...)`).

The fold (`_split_era`, commit 56e3d42) joins a part of the fails rows that no observation names to the era before it, so
a seeds-only input finds the era's FIGI by the part's CUSIP (XRX 2017, ITT 2011, ALEX 2012). It also joined a new
security's CUSIP to the old one: HTZ 2016 (the spin-off took the name), Z 2015 (the new Zillow Group), NRF 2014 (the
era had its own composite). `identify` judges each fold after stage 3 and sends a refused one around again as a derived
era (verdict `FOLD_REFUSED`).

The world: ticker X, observed as "X CO" (issuer 101) on 2020-01-15 and 2020-06-30 on CUSIP 11111A101, then on
2021-12-31 on CUSIP 33333C303; CUSIP 22222B202 trades under X from 2020-09-01 and no caller observed it: the fold."""
from __future__ import annotations

from datetime import date

import requests

from delist_detection.identity.identity import FOLD_REFUSED, MAX_VERDICT_PASSES, identify, refine_eras
from delist_detection.identity.observations import Observation, ObservationIndex, split_eras
from delist_detection.identity.ticker_resolver import TickerResolution
from delist_detection.pipeline import Clients
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex, FtdRow

AS_OF = date(2026, 9, 25)
OLD, MIDDLE, NEW = "11111A101", "22222B202", "33333C303"
PAIR = ("X", MIDDLE)
FOLDED_KEY, DERIVED_KEY, LATER_KEY = "X@2020-01-15", "X@2020-09-01", "X@2021-12-31"
OBS = [Observation("X", d, "X CO") for d in ("2020-01-15", "2020-06-30", "2021-12-31")]

# the issuer's filings around the step (2020-09-01): an 8-K item 5.03, a 10-Q for a period after it
CARRIES_ON = [EdgarSubmission("0000101-20-000001", "8-K", "2020-08-31", "2020-08-31", "5.03,9.01", "a.htm"),
              EdgarSubmission("0000101-20-000002", "10-Q", "2020-11-10", "2020-09-30", "", "q.htm")]
SAME_NAME = {"name": "X CO", "formerNames": []}
RENAMED_BEFORE = {"name": "OTHER INC", "formerNames": [{"name": "X CO", "from": "1990-01-01", "to": "2020-06-30"}]}


class _Edgar:
    full_text_search = None        # stated absent: no other registrant is found

    def __init__(self, sub=SAME_NAME, filings=CARRIES_ON, fails=False):
        self.sub, self.filings, self.fails = sub, filings, fails

    def submissions(self, cik, fresh_after=None):
        return dict(self.sub) if int(cik) == 101 else {"__not_found__": True}

    def recent_filings(self, cik):
        if self.fails:
            raise requests.ConnectionError("down")
        return list(self.filings) if int(cik) == 101 else []

    def fetch_filing_text(self, cik, accession, primary_doc):
        return ""

    def fetch_filing_raw(self, cik, accession):
        return ""


class _Fails:
    def __init__(self, rows):
        self.rows_ = list(rows)

    def urls_for(self, lo, hi):
        return ["mem"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.rows_:
            if (symbols and r.symbol in symbols) or (cusips and r.cusip in cusips):
                yield r


class _Figi:
    """Each CUSIP in `lines` is the US composite it names; a call is recorded."""

    def __init__(self, lines):
        self.lines, self.asked = lines, []

    def map(self, jobs, use_cache=True):
        out = []
        for j in jobs:
            self.asked.append(j["idValue"])
            line = self.lines.get(j["idValue"])
            out.append({"warning": "No identifier found."} if line is None else {"data": [{
                "figi": line[0], "compositeFIGI": line[0], "exchCode": "US", "ticker": "X", "name": line[1],
                "securityType": "Common Stock", "securityType2": "Common Stock"}]})
        return out

    def filter(self, query, **fields):
        return []


class _Lookup:
    issuers = None

    def __init__(self, answers):
        self.answers = answers

    def resolve(self, ticker, observed_date=None, *, pin=None, name=None, since=None, exclude=()):
        cik, tier = self.answers.get(f"{ticker}@{since}", (None, "none"))
        return TickerResolution(ticker, cik, None, tier if cik else "none")

    def is_degraded(self, ticker, observed_date=None, *, name=None, exclude=()):
        return False

    def frequency_candidates(self, ticker, day):
        return [], False

    def shadow(self):
        return self

    def flush(self):
        pass


def _rows(cusip, dates, desc="X CO"):
    return [FtdRow(d, cusip, "X", desc, 10.0) for d in dates]


ROWS = (_rows(OLD, ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"])
        + _rows(MIDDLE, ["2020-09-01", "2020-10-01", "2020-11-02", "2021-01-04"])
        + _rows(NEW, ["2021-03-01", "2021-04-01", "2021-05-03"]))
ANSWERS = {f"X@{d}": (101, "committed") for d in ("2020-01-15", "2020-09-01", "2021-12-31")}
NEW_LINE = ("BBGX", "X CO")


def _run(*, figi=None, edgar=None, rows=ROWS, obs=OBS, verdicts=None, logs=None):
    figi = _Figi({MIDDLE: NEW_LINE, NEW: NEW_LINE, **(figi or {})})
    clients = Clients(edgar=edgar or _Edgar(), resolver=_Lookup(ANSWERS), classifier=None, figi=figi,
                      ftd_client=_Fails(rows), as_of=AS_OF)
    kw = {} if verdicts is None else {"verdicts": verdicts}
    return identify(ObservationIndex(obs), clients, as_of=AS_OF, log=(logs.append if logs is not None else (lambda *_: None)),
                    **kw), figi


# --- the fold, and the pair it is judged under ----------------------------------------------------------------------

def test_refine_eras_records_the_fold_and_unfold_makes_the_part_a_derived_era_instead():
    era = split_eras(OBS)[0]
    folded = refine_eras([era], FtdIndex(ROWS))
    assert [(e.key, e.ftd_cusips) for e in folded] == [(FOLDED_KEY, (OLD, MIDDLE)), (LATER_KEY, (NEW,))]
    (fold,) = folded[0].folds
    assert (fold.cusip, fold.old_cusip, fold.earlier, fold.first) == (MIDDLE, OLD, (OLD,), "2020-09-01")
    assert fold.descriptions == ("X CO",) and folded[1].folds == ()
    unfolded = refine_eras([era], FtdIndex(ROWS), unfold=[PAIR])
    assert [(e.key, e.ftd_cusips, e.derived) for e in unfolded] == [
        (FOLDED_KEY, (OLD,), False), (DERIVED_KEY, (MIDDLE,), True), (LATER_KEY, (NEW,), False)]
    assert unfolded[0].folds == ()
    other_ticker = refine_eras([era], FtdIndex(ROWS), unfold=[("Y", MIDDLE)])
    assert [e.ftd_cusips for e in other_ticker] == [(OLD, MIDDLE), (NEW,)]


# --- a fold that passes both gates stays folded (XRX 2017, ITT 2011, ALEX 2012) ----------------------------------------

def test_a_fold_of_an_era_with_no_composite_that_stage_4b_would_follow_stays_folded():
    logs = []
    got, figi = _run(logs=logs)
    assert [(e.key, e.ftd_cusips) for e in got.eras] == [(FOLDED_KEY, (OLD, MIDDLE)), (LATER_KEY, (NEW,))]
    assert got.verdicts == {} and got.resolutions[FOLDED_KEY].sec_id == "BBGX"
    assert OLD in figi.asked                                  # gate (a) asked OpenFIGI for the era's own CUSIP
    assert not any("fold" in line for line in logs)


# --- gate (a): the era has a composite of its own (NRF 2014) ----------------------------------------------------------

def test_a_fold_of_an_era_that_has_a_composite_of_its_own_is_not_kept_and_the_part_is_a_derived_era():
    logs = []
    got, _ = _run(figi={OLD: ("BBGO", "X CO")}, logs=logs)
    assert got.verdicts == {PAIR: FOLD_REFUSED}
    assert [(e.key, e.ftd_cusips) for e in got.eras] == [
        (FOLDED_KEY, (OLD,)), (DERIVED_KEY, (MIDDLE,)), (LATER_KEY, (NEW,))]
    assert got.resolutions[FOLDED_KEY].sec_id == "BBGO" and got.resolutions[DERIVED_KEY].sec_id == "BBGX"
    assert set(got.securities) == {"BBGO", "BBGX"}
    assert any("folds not kept: 1 (X@2020-01-15)" in line for line in logs)


# --- gate (b): stage 4b's R1 test refuses the step ---------------------------------------------------------------------

def test_a_fold_whose_step_r1_refuses_as_name_is_not_kept():
    """HTZ 2016: the spin-off took the name; the issuer's EDGAR name from the step on is another one."""
    got, _ = _run(edgar=_Edgar(sub=RENAMED_BEFORE))
    assert got.verdicts == {PAIR: FOLD_REFUSED}
    assert [e.key for e in got.eras] == [FOLDED_KEY, DERIVED_KEY, LATER_KEY]


def test_a_fold_whose_step_r1_refuses_as_merged_out_is_not_kept():
    """Z 2015: the old registrant files no periodic report after the step and no 8-K12B of its own."""
    got, _ = _run(edgar=_Edgar(filings=[]))
    assert got.verdicts == {PAIR: FOLD_REFUSED}
    assert [(e.key, e.ftd_cusips) for e in got.eras] == [
        (FOLDED_KEY, (OLD,)), (DERIVED_KEY, (MIDDLE,)), (LATER_KEY, (NEW,))]


def test_a_fold_whose_era_has_no_issuer_is_not_kept():
    """Stage 4b follows no security without an issuer, so R1 could not follow the step."""
    figi = _Figi({MIDDLE: NEW_LINE, NEW: NEW_LINE})
    clients = Clients(edgar=_Edgar(), resolver=_Lookup({}), classifier=None, figi=figi, ftd_client=_Fails(ROWS),
                      as_of=AS_OF)
    got = identify(ObservationIndex(OBS), clients, as_of=AS_OF)
    assert got.verdicts == {PAIR: FOLD_REFUSED}


def test_a_read_that_failed_leaves_the_fold_and_says_so():
    """A refusal rested on a failed request is no finding: the fold stays and the era gets a resolution_degraded item."""
    got, _ = _run(edgar=_Edgar(fails=True))
    assert got.verdicts == {} and [e.key for e in got.eras] == [FOLDED_KEY, LATER_KEY]
    degraded = [r for r in got.review if r.flag == "resolution_degraded" and "fold" in r.reason]
    assert [r.ticker for r in degraded] == ["X"] and MIDDLE in degraded[0].reason


# --- the verdict, and the run that is not a seeds run ------------------------------------------------------------------

def test_given_a_fold_refused_verdict_identify_makes_the_derived_era_at_once():
    got, _ = _run(verdicts={PAIR: FOLD_REFUSED})
    assert [e.key for e in got.eras] == [FOLDED_KEY, DERIVED_KEY, LATER_KEY]
    assert got.verdicts == {PAIR: FOLD_REFUSED}


def test_the_verdict_rounds_stay_within_the_bound_when_every_pass_refuses_a_fold():
    got, _ = _run(edgar=_Edgar(filings=[]))
    assert len(got.verdicts) <= MAX_VERDICT_PASSES


def test_a_part_with_an_observation_is_an_era_and_nothing_is_judged():
    """The full run: the caller observed the middle CUSIP, so there is no fold, and no verdict whatever the filings."""
    obs = [*OBS, Observation("X", "2020-10-15", "X CO")]
    got, figi = _run(obs=obs, edgar=_Edgar(filings=[]), figi={OLD: ("BBGO", "X CO")})
    assert got.verdicts == {} and all(e.folds == () for e in got.eras)
    assert [e.ftd_cusips for e in got.eras] == [(OLD,), (MIDDLE,), (NEW,)]

