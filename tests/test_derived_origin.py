"""A derived era is checked against the step it came from (`identity.identify`, seeds-only parity Task 17): rule J (it
joins the line it was refused from only when the price carried over across the step), rule X (a derived era from a
`merged_out` step never takes the old line's issuer under a composite of its own), and the verdicts that carry the two
over the rounds (`derived_lines.identify_with_lines`).

The world: ticker X, observed by the caller through 2020 as "X CO" (issuer 101) on CUSIP 11111A101, then 22222B202; CUSIP 33333C303
trades under X from 2021-03-01 and no caller observed it: the step 22222B202 to 33333C303 was refused, and `derive` says CCC is
the line of the run."""
from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

import pytest

import delist_detection.identity.identity as identity_module
from delist_detection.identity.identity import (
    MAX_VERDICT_PASSES, EraIssuers, Identity, InferredIssuer, SecondPass, _check_derived, identify,
)
from delist_detection.identity.observations import DerivedFrom, Observation, ObservationIndex, TickerEra
from delist_detection.identity.ticker_resolver import TickerResolution
from delist_detection.sources.ftd import FtdRow
from delist_detection.pipeline import Clients

AS_OF = date(2026, 9, 25)
PAIR = ("X", "33333C303")
ORIGIN = DerivedFrom("BBGX", 101, "merged_out", "22222B202", "2021-03-01")
OBS = [Observation("X", d, "X CO") for d in ("2020-01-15", "2020-06-30", "2020-12-31")]
DERIVED_KEY = "X@2021-03-01"


class _Edgar:
    def __init__(self, names):
        self.names = names

    def submissions(self, cik, fresh_after=None):
        name = self.names.get(int(cik))
        return {"name": name, "formerNames": []} if name else {"__not_found__": True}

    def recent_filings(self, cik):
        return []


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
    """OpenFIGI: each CUSIP in `lines` is the US composite it names, the company named for it."""

    def __init__(self, lines):
        self.lines = lines

    def map(self, jobs, use_cache=True):
        out = []
        for j in jobs:
            line = self.lines.get(j["idValue"]) if j["idType"] == "ID_CUSIP" else None
            out.append({"warning": "No identifier found."} if line is None else {"data": [{
                "figi": line[0], "compositeFIGI": line[0], "exchCode": "US", "ticker": "X", "name": line[1],
                "securityType": "Common Stock", "securityType2": "Common Stock"}]})
        return out

    def filter(self, query, **fields):
        return []


class _Lookup:
    """The issuer lookup: a first answer per era (by its first sighting), and the answer when the old line's issuer is
    excluded (`excluded`, by era). Records every call."""

    issuers = None

    def __init__(self, answers, excluded=None):
        self.answers, self.excluded, self.calls, self.degraded_calls = answers, excluded or {}, [], []

    def resolve(self, ticker, observed_date=None, *, pin=None, name=None, since=None, exclude=()):
        self.calls.append((f"{ticker}@{since}", tuple(sorted(exclude))))
        table = self.excluded if exclude else self.answers
        cik, tier = table.get(f"{ticker}@{since}", (None, "none"))
        return TickerResolution(ticker, cik, None, tier if cik else "none")

    degraded_when_excluded = False       # a lookup with an exclusion rested on a failed request

    def is_degraded(self, ticker, observed_date=None, *, name=None, exclude=()):
        self.degraded_calls.append((observed_date, tuple(sorted(exclude))))
        return bool(exclude) and self.degraded_when_excluded

    def frequency_candidates(self, ticker, day):
        return [], False

    def shadow(self):
        return self

    def flush(self):
        pass


def _rows(symbol, cusip, dates, desc, price):
    return [FtdRow(d, cusip, symbol, desc, price + i * 0.01) for i, d in enumerate(dates)]


def _fails(old_last_price, new_first_price):
    """11111A101, then 22222B202 (its last row `old_last_price`), then 33333C303 from 2021-03-01 (its first row `new_first_price`)."""
    return (_rows("X", "11111A101", ["2020-01-02", "2020-02-03", "2020-03-02", "2020-04-01"], "X CO", 10.0)
            + _rows("X", "22222B202", ["2020-09-01", "2020-10-01", "2020-11-02"], "X CO NEW", 10.0)
            + [FtdRow("2021-01-04", "22222B202", "X", "X CO NEW", old_last_price)]
            + [FtdRow(d, "33333C303", "X", "X CO NEWER, INC (DE)", new_first_price)
               for d in ("2021-03-01", "2021-04-01", "2021-05-03")])


def _clients(lookup, rows, *, ccc=("BBGX", "X CO"), names=None):
    figi = _Figi({"11111A101": ("BBGX", "X CO"), "22222B202": ("BBGX", "X CO"), "33333C303": ccc})
    return Clients(edgar=_Edgar(names or {101: "X CO", 202: "X CO NEWER, INC"}), resolver=lookup, classifier=None,
                   figi=figi, ftd_client=_Fails(rows), as_of=AS_OF)


FIRST = {"X@2020-01-15": (101, "committed"), "X@2020-12-31": (101, "committed")}
OLD_ISSUER = {DERIVED_KEY: (101, "efts")}          # the lookup gives the derived era the old line's issuer
NEW_ISSUER = {DERIVED_KEY: (202, "efts")}


def _run(rows, derive, *, answers=None, excluded=None, ccc=("BBGX", "X CO"), verdicts=None, names=None):
    lookup = _Lookup({**FIRST, **(answers or {})}, excluded)
    clients = _clients(lookup, rows, ccc=ccc, names=names)
    kw = {} if verdicts is None else {"verdicts": verdicts}
    return identify(ObservationIndex(OBS), clients, as_of=AS_OF, derive=derive, **kw), lookup


def _same(a: Identity, b: Identity) -> None:
    """Everything the identity stage answers is equal, field by field (the fails index is each run's own)."""
    for f in dataclasses.fields(Identity):
        if f.name not in ("ftd", "verdicts"):
            assert getattr(a, f.name) == getattr(b, f.name), f.name


def _stages_with_no_derive(rows):
    return _run(rows, {})[0]


# --- 7: no derived era, no change -----------------------------------------------------------------------------------

def test_with_no_derive_identify_makes_the_same_calls_and_returns_the_same_result_as_with_an_empty_verdict_map():
    rows = _fails(10.0, 20.0)
    plain, lookup = _run(rows, {})
    assert [k for k, _ in lookup.calls] == ["X@2020-01-15", "X@2020-12-31"] and all(not ex for _, ex in lookup.calls)
    assert DERIVED_KEY not in plain.era_by_key and plain.verdicts == {}
    with_verdicts, other = _run(rows, {}, verdicts={})
    _same(plain, with_verdicts)
    assert lookup.calls == other.calls


# --- 3: rule J ------------------------------------------------------------------------------------------------------

def test_a_derived_era_on_its_origins_security_whose_price_did_not_carry_over_is_not_made():
    """Uniti 2025: 4.91 on the old CUSIP's last row, 8.09 on the new one's first (a ratio of 1.65). The step stays
    refused: no era, no security, the old security exactly as with no `derive` at all."""
    rows = _fails(4.91, 8.09)
    got, _ = _run(rows, {PAIR: ORIGIN}, answers=OLD_ISSUER)
    base = _stages_with_no_derive(rows)
    assert DERIVED_KEY not in got.era_by_key and set(got.securities) == {"BBGX"}
    _same(got, base)
    assert got.verdicts == {PAIR: "not_made"}


def test_a_derived_era_on_its_origins_security_whose_price_carried_over_is_made_and_joined():
    got, _ = _run(_fails(75.59, 75.26), {PAIR: ORIGIN}, answers=OLD_ISSUER)
    assert got.eras[-1].key == DERIVED_KEY and got.eras[-1].derived_from == ORIGIN
    assert got.resolutions[DERIVED_KEY].sec_id == "BBGX" and set(got.securities) == {"BBGX"}
    assert [e.key for e in got.securities["BBGX"].eras][-1] == DERIVED_KEY
    assert got.verdicts == {}


@pytest.mark.parametrize("old,new", [(None, 8.09), (4.91, None), (0.0, 8.09)])
def test_a_derived_era_with_no_price_on_one_side_is_made_and_joined(old, new):
    got, _ = _run(_fails(old, new), {PAIR: ORIGIN}, answers=OLD_ISSUER)
    assert got.resolutions[DERIVED_KEY].sec_id == "BBGX" and got.verdicts == {}


def test_a_derived_era_on_another_security_is_not_judged_by_rule_j_whatever_the_prices():
    """Seadrill's 185: the new CUSIP is a composite of its own; the price decides nothing for an era that is not on the
    line it came from."""
    got, _ = _run(_fails(0.10, 18.50), {PAIR: ORIGIN}, answers=NEW_ISSUER, ccc=("BBGY", "X CO NEWER, INC"))
    assert got.resolutions[DERIVED_KEY].sec_id == "BBGY" and got.verdicts == {}
    assert set(got.securities) == {"BBGX", "BBGY"}


# --- 6: the verdicts ------------------------------------------------------------------------------------------------

def test_given_a_not_made_verdict_identify_equals_identify_without_that_pair_in_derive():
    rows = _fails(10.0, 10.0)          # the price carried over: only the verdict removes the era
    got, lookup = _run(rows, {PAIR: ORIGIN}, answers=OLD_ISSUER, verdicts={PAIR: "not_made"})
    _same(got, _stages_with_no_derive(rows))
    assert got.verdicts == {PAIR: "not_made"} and DERIVED_KEY not in got.era_by_key


# --- 4: rule X ------------------------------------------------------------------------------------------------------

OWN_COMPOSITE = ("BBGY", "X CO NEWER, INC")        # the new CUSIP's composite is its own, not the old line's
SECOND = {DERIVED_KEY: (202, "efts")}              # what the lookup answers when the old line's issuer is excluded


def test_a_derived_era_from_a_merged_out_step_that_took_the_old_issuer_is_asked_again_without_it():
    """Coca-Cola Enterprises 2016: the name search ranks the old registrant first; by stage 4b's own finding it cannot
    be the issuer of the line after a `merged_out` step. The second lookup excludes it and its answer stands."""
    logs = []
    lookup = _Lookup({**FIRST, **OLD_ISSUER}, SECOND)
    got = identify(ObservationIndex(OBS), _clients(lookup, _fails(10.0, 10.0), ccc=OWN_COMPOSITE), as_of=AS_OF,
                   derive={PAIR: ORIGIN}, log=logs.append)
    assert got.issuers[DERIVED_KEY].cik == 202 and got.tier(DERIVED_KEY) == "efts"
    assert got.resolutions[DERIVED_KEY].sec_id == "BBGY" and got.securities["BBGY"].issuer_cik == 202
    assert got.verdicts == {PAIR: "without_old_issuer"}
    derived_calls = [c for c in lookup.calls if c[0] == DERIVED_KEY]
    assert derived_calls == [(DERIVED_KEY, ()), (DERIVED_KEY, (101,))]     # first pass without, the pass with the verdict
    assert "derived eras asked without the old line's issuer: 1 (X@2021-03-01)" in logs


def test_when_the_second_lookup_finds_nothing_the_era_has_no_issuer_and_its_security_is_still_made():
    got, _ = _run(_fails(10.0, 10.0), {PAIR: ORIGIN}, answers=OLD_ISSUER, ccc=OWN_COMPOSITE)
    assert DERIVED_KEY not in got.issuers and got.tier(DERIVED_KEY) == "none"
    assert got.resolutions[DERIVED_KEY].sec_id == "BBGY" and "BBGY" in got.securities
    assert got.securities["BBGY"].issuer_cik is None and got.verdicts == {PAIR: "without_old_issuer"}


@pytest.mark.parametrize("why", ["other_registrant", "name"])
def test_a_derived_era_from_an_other_registrant_or_name_step_keeps_the_origins_issuer(why):
    """CHTR 2016 keeps its issuer on both sides: the step was refused for another registrant, not because the old
    issuer filed nothing after it."""
    origin = DerivedFrom("BBGX", 101, why, "22222B202", "2021-03-01")
    got, lookup = _run(_fails(10.0, 10.0), {PAIR: origin}, answers=OLD_ISSUER, excluded=SECOND, ccc=OWN_COMPOSITE)
    assert got.issuers[DERIVED_KEY].cik == 101 and got.verdicts == {}
    assert all(not ex for _, ex in lookup.calls)


@pytest.mark.parametrize("source", ["manual", "cik_map"])
def test_a_derived_era_whose_answer_is_given_keeps_it(source):
    got, lookup = _run(_fails(10.0, 10.0), {PAIR: ORIGIN}, answers={DERIVED_KEY: (101, source)}, excluded=SECOND,
                       ccc=OWN_COMPOSITE)
    assert got.issuers[DERIVED_KEY].cik == 101 and got.verdicts == {}


def test_a_derived_era_with_a_pin_keeps_the_issuer_it_is_pinned_to():
    """No refine builds a derived era with a pin, but the rule says so: the check leaves it alone."""
    pinned = TickerEra("X", "2021-03-01", "2021-03-01", [Observation("X", "2021-03-01", "X CO NEW", cik=101, derived=True)],
                       ftd_cusips=("33333C303",), derived_from=ORIGIN)
    by_sec_id = TickerEra("X", "2021-03-01", "2021-03-01",
                          [Observation("X", "2021-03-01", "X CO NEW", sec_id="BBGY", derived=True)],
                          ftd_cusips=("33333C303",), derived_from=ORIGIN)
    unpinned = TickerEra("X", "2021-03-01", "2021-03-01", [Observation("X", "2021-03-01", "X CO NEW", derived=True)],
                         ftd_cusips=("33333C303",), derived_from=ORIGIN)
    resolutions = {unpinned.key: SimpleNamespace(sec_id="BBGY")}
    found = SimpleNamespace(issuers={unpinned.key: SimpleNamespace(cik=101)},
                            answers={unpinned.key: SimpleNamespace(source="efts")})
    assert _check_derived([pinned], {PAIR: ORIGIN}, {}, None, resolutions, found) == {}
    assert _check_derived([by_sec_id], {PAIR: ORIGIN}, {}, None, resolutions, found) == {}
    assert _check_derived([unpinned], {PAIR: ORIGIN}, {}, None, resolutions, found) == {
        PAIR: ("without_old_issuer", unpinned.key)}


def test_a_derived_era_joined_to_its_origin_keeps_the_origins_issuer():
    got, lookup = _run(_fails(75.59, 75.26), {PAIR: ORIGIN}, answers=OLD_ISSUER, excluded=SECOND)
    assert got.issuers[DERIVED_KEY].cik == 101 and got.resolutions[DERIVED_KEY].sec_id == "BBGX"
    assert got.verdicts == {} and all(not ex for _, ex in lookup.calls)


def test_an_answer_the_second_pass_gives_is_dropped_when_it_is_the_excluded_issuer(monkeypatch):
    monkeypatch.setattr(EraIssuers, "infer", lambda self, eras, ftd, dates, ciks, handoffs=None: SecondPass(
        {DERIVED_KEY: InferredIssuer(101, "rule_b", "8-K")}, {}))
    got, _ = _run(_fails(10.0, 10.0), {PAIR: ORIGIN}, ccc=OWN_COMPOSITE)      # the lookup itself finds nothing
    assert got.verdicts == {PAIR: "without_old_issuer"} and DERIVED_KEY not in got.issuers


def test_an_answer_the_name_check_gives_is_dropped_when_it_is_the_excluded_issuer(monkeypatch):
    monkeypatch.setattr(EraIssuers, "check_names", lambda self, eras, ftd, last_seen, answers: {
        DERIVED_KEY: InferredIssuer(101, "name_in_force", "SEC's name index")})
    got, _ = _run(_fails(10.0, 10.0), {PAIR: ORIGIN}, answers={DERIVED_KEY: (303, "name_search")},
                  excluded={DERIVED_KEY: (303, "name_search")}, ccc=OWN_COMPOSITE)
    # the first pass takes the name check's answer (101: the old issuer); asked without it, the check's answer is
    # dropped and the lookup's own (303) stands
    assert got.verdicts == {PAIR: "without_old_issuer"} and got.issuers[DERIVED_KEY].cik == 303


# --- 6: the verdicts, the other half --------------------------------------------------------------------------------

def test_given_a_without_old_issuer_verdict_identify_asks_with_the_exclusion_at_once():
    lookup = _Lookup({**FIRST, **OLD_ISSUER}, SECOND)
    got = identify(ObservationIndex(OBS), _clients(lookup, _fails(10.0, 10.0), ccc=OWN_COMPOSITE), as_of=AS_OF,
                   derive={PAIR: ORIGIN}, verdicts={PAIR: "without_old_issuer"})
    assert [c for c in lookup.calls if c[0] == DERIVED_KEY] == [(DERIVED_KEY, (101,))]    # no lookup without it
    assert got.issuers[DERIVED_KEY].cik == 202 and got.verdicts == {PAIR: "without_old_issuer"}


def test_the_passes_stop_at_the_bound_and_say_so(monkeypatch):
    """A check that never settles (each pass finds a new verdict) goes around `MAX_VERDICT_PASSES` times, then goes on
    with what it has."""
    logs, seen = [], []

    def always(eras, derive, verdicts, *args):
        seen.append(dict(verdicts))
        return {("X", f"C{len(seen)}"): ("not_made", DERIVED_KEY)}

    monkeypatch.setattr(identity_module, "_check_derived", always)
    got = identify(ObservationIndex(OBS), _clients(_Lookup(FIRST), _fails(10.0, 10.0)), as_of=AS_OF, log=logs.append)
    assert len(seen) == MAX_VERDICT_PASSES + 1 and len(got.verdicts) == MAX_VERDICT_PASSES
    assert any("not applied" in line for line in logs)


def test_the_degraded_check_of_an_excluded_lookup_asks_for_the_key_of_that_lookup():
    """A lookup made without the old issuer that rested on a failed request is reported degraded: `is_degraded` is
    asked with the same exclusion as `resolve`, or it would read the other lookup's key."""
    lookup = _Lookup({**FIRST, **OLD_ISSUER}, SECOND)
    lookup.degraded_when_excluded = True
    got = identify(ObservationIndex(OBS), _clients(lookup, _fails(10.0, 10.0), ccc=OWN_COMPOSITE), as_of=AS_OF,
                   derive={PAIR: ORIGIN})
    assert {ex for _, ex in lookup.degraded_calls} == {(), (101,)}
    flagged = [r for r in got.review if r.flag == "resolution_degraded" and "issuer resolution" in r.reason]
    assert [r.reason.split(":")[0] for r in flagged] == ["X@2021-03-01 X CO NEWER, INC"]


def test_a_second_pass_answer_is_filtered_before_the_two_passes_are_merged(monkeypatch):
    """The capped pass infers the excluded issuer for the era and the followed pass another one: the merge would take
    the capped answer and the filter then drop it, losing the valid one. Each pass is filtered first."""
    calls = []

    def infer(self, eras, ftd, dates, ciks, handoffs=None):
        calls.append(1)
        cik = 101 if len(calls) % 2 == 1 else 303          # the capped pass first, then the followed one
        return SecondPass({DERIVED_KEY: InferredIssuer(cik, "rule_b", "8-K")},
                          {DERIVED_KEY: InferredIssuer(cik, "rule_c", "CUSIP")})

    monkeypatch.setattr(EraIssuers, "infer", infer)
    got, _ = _run(_fails(10.0, 10.0), {PAIR: ORIGIN}, ccc=OWN_COMPOSITE)
    assert got.verdicts == {PAIR: "without_old_issuer"} and got.issuers[DERIVED_KEY].cik == 303


def test_an_origin_with_no_issuer_gives_no_rule_x_verdict():
    """There is no old issuer to leave out: the guard on `issuer_cik is None`."""
    origin = DerivedFrom("BBGX", None, "merged_out", "22222B202", "2021-03-01")
    era = TickerEra("X", "2021-03-01", "2021-03-01", [Observation("X", "2021-03-01", "X CO NEW", derived=True)],
                    ftd_cusips=("33333C303",), derived_from=origin)
    found = SimpleNamespace(issuers={}, answers={era.key: SimpleNamespace(source="efts")})
    assert _check_derived([era], {PAIR: origin}, {}, None, {era.key: SimpleNamespace(sec_id="BBGY")}, found) == {}
    # cik_of(issuers, key) is None for an era with no issuer answer: without the guard None == None gives a verdict
