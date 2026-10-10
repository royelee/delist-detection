"""line_follow over real cases (sub-plan 5a): the cached fails rows, EDGAR answers and OpenFIGI answers of the
committed run's securities in tests/fixtures/lines/ (built once, offline, by scripts/build_line_fixtures.py). Each
case's first step is found, checked and decided by the rule functions, and, for a two-step case, the next; then every
case runs through the stage's interface, `follow_lines`, whose first answer for it must be the same."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from delist_detection.identity import line_follow as lf
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.sources.ftd import FtdIndex, FtdRow
from delist_detection.identity.identity import Identity
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.filings.listing_status import edgar_lists
from delist_detection.identity.observations import Observation, TickerEra
from delist_detection.pipeline import Clients
from delist_detection.identity.security_master import EraResolution, Issuer, Security, build_securities

FIX = Path(__file__).parent / "fixtures" / "lines"
DATA = json.loads((FIX / "cases.json").read_text())
EDGAR = json.loads((FIX / "edgar.json").read_text())
FIGI = json.loads((FIX / "openfigi.json").read_text())
SEARCHES = json.loads((FIX / "searches.json").read_text())
AS_OF = date.fromisoformat(DATA["as_of"])


def _fixture_rows() -> list[FtdRow]:
    with (FIX / "ftd_rows.csv").open(newline="") as fh:
        return [FtdRow(r["date"], r["cusip"], r["symbol"], r["description"],
                       float(r["price"]) if r["price"] else None) for r in csv.DictReader(fh)]


def _load_ftd() -> FtdIndex:
    return FtdIndex(_fixture_rows())


@pytest.fixture(scope="module")
def ftd():
    return _load_ftd()


class _Edgar:
    """The issuers' EDGAR answers as the fixture recorded them, read directly (`submissions`, `filings`) or through
    the stage's issuer record (`recent_filings`, `fetch_filing_text`); the full-text search answers the cached
    successor searches, and finds nothing for any other query."""

    def submissions(self, cik, fresh_after=None):
        d = EDGAR["issuers"].get(str(int(cik)), {})
        return {"name": d.get("name", ""), "formerNames": d.get("formerNames", []), "tickers": d.get("tickers", []),
                "exchanges": d.get("exchanges", [])}

    def filings(self, cik):
        return [EdgarSubmission(a, form, fd, rd, items, doc)
                for a, form, fd, rd, items, doc in EDGAR["issuers"].get(str(int(cik)), {}).get("filings", [])]

    def recent_filings(self, cik):
        return self.filings(cik)

    def fetch_filing_text(self, cik, accession, primary_doc):
        return EDGAR["texts"].get(accession, "")

    def full_text_search(self, q, forms, lo, hi):
        asked = [q, forms, lo.isoformat(), hi.isoformat()]
        return next((saved["hits"] for saved in SEARCHES.values() if saved["query"] == asked), [])


EDGAR_FIX = _Edgar()


def _security(sec_id):
    d = DATA["run"][sec_id]
    return Security(sec_id, d["issuer_cik"], d["share_class"], d["name"], "Common Stock", True, d["figi_source"],
                    eras=[TickerEra(t, "2008-01-16", "2008-01-16") for t in DATA["cases"].get(sec_id, {}).get("tickers", [])])


RUN = {k: _security(k) for k in DATA["run"]}


def _search(sec_id):
    """The case's cached successor search, answered only for the query the case asks."""
    saved = SEARCHES.get(sec_id)

    def search(q, forms, lo, hi):
        if saved and saved["query"] == [q, forms, lo.isoformat(), hi.isoformat()]:
            return saved["hits"]
        return []
    return search


def _held(sec_id):
    """Every security of the run that holds a CUSIP the fixture knows, and its CUSIPs."""
    held = {h: [c for c, hs in DATA["holders"].items() if h in hs] for hs in DATA["holders"].values() for h in hs}
    return {**held, **{sid: case["cusips"] for sid, case in DATA["cases"].items()}}


def _holders(sec_id, ftd):
    """The CUSIP holders `candidate_steps` reads for the case, as the stage gives them (`line_follow.holders_for`)."""
    return lf.holders_for(RUN[sec_id], RUN, _held(sec_id), DATA["holders"], ftd)


def follow(sec_id, ftd, *, cusips=None, tickers=None):
    """(step, evidence, refusal, decision) for the case's next step, as stage 4b reaches them; None, no step."""
    case = DATA["cases"][sec_id]
    cusips = cusips or case["cusips"]
    tickers = tickers or set(case["tickers"])
    steps = lf.candidate_steps(sec_id, cusips, tickers, ftd, holders=_holders(sec_id, ftd),
                               extra_symbols=case["extra_symbols"], extra_cusips=case["extra_cusips"])
    if not steps:
        return None
    step, cik = steps[0], case["issuer_cik"]
    first = date.fromisoformat(step.first)
    evidence, refused = lf.corroborate(
        step, filings=EDGAR_FIX.filings(cik), sub=EDGAR_FIX.submissions(cik), share_class=case["share_class"],
        text_of=lambda f: EDGAR["texts"].get(f.accession, ""), as_of=AS_OF,
        listed_now=lambda: edgar_lists(EDGAR_FIX, cik, [*tickers, step.symbol]),
        other_registrant=lambda: lf.other_registrant(
            _search(sec_id), EDGAR_FIX, name=lf.name_on(EDGAR_FIX.submissions(cik), first, case["name"]), day=first,
            cik=cik, own_tickers=tickers))
    decision = None
    if not refused and (step.kind == lf.NEW_SYMBOL or step.new_cusip in FIGI):
        cands = lf.composites(FIGI[step.new_cusip]) if step.kind == lf.SWITCH else None
        decision = lf.decide(step, RUN[sec_id], cands, RUN, described=lf.described_letter(cusips, ftd),
                             issuer_letters=lf.issuer_letters_of(case["issuer_cik"], RUN.values()))
    return step, evidence, refused, decision


# sec_id -> (kind, new CUSIP, symbol, first, refusal, decision kind, composite); decision None: OpenFIGI's answer
# for the new CUSIP is not cached, so the case stops at corroborate
EXPECTED = {
    "BBG000BN6349": (lf.SWITCH, "320771207", "FMD", "2013-12-03", "", lf.ATTACH, "BBG000BN6349"),
    "BBG000BLH3P8": (lf.NEW_SYMBOL, "415864107", "NVRI", "2023-06-21", "", lf.ATTACH, ""),
    "CIK1075415-COMMON": (lf.SWITCH, "25525P107", "DHC", "2020-01-03", "", None, None),
    "BBG001D9S707": (lf.SWITCH, "26817G300", "DYN", "2010-05-26", "", lf.SUCCESSOR, "BBG000BNLX91"),
    "BBG00JM9V731": (lf.SWITCH, "G39104107", "GTES", "2026-07-20", "", lf.SUCCESSOR, "BBG023G9VDF5"),
    "BBG009NGKQ45": (lf.SWITCH, "92918V208", "VRM", "2024-02-16", "", lf.ATTACH, "BBG009NGKQ45"),
    "BBG000BRWGG9": (lf.SWITCH, "767754872", "RAD", "2019-04-22", "", lf.ATTACH, "BBG000BRWGG9"),
    "BBG002B67HB2": (lf.SWITCH, "912932100", "UNIT", "2025-08-04", "merged_out", None, None),
    "BBG000BBG3P1": (lf.NEW_SYMBOL, "885218800", "THMR", "2008-12-11", "otc_move", None, None),
    "BBG000D9V7T4": (lf.SWITCH, "00258R109", "AAN", "2020-10-19", "merged_out", None, None),
    "BBG000FC9SM1": (lf.SWITCH, "05971J102", "BXS", "2017-11-01", "merged_out", None, None),
    "BBG00D30HGP6": (lf.SWITCH, "25401T108", "DBRG", "2021-06-22", "", lf.ATTACH, ""),
    "CIK1115836-COMMON": (lf.SWITCH, "G1154H107", "OEH", "2014-07-01", "", lf.FOLD, "BBG000BKZ5F6"),
    "CIK1066104-COMMON": (lf.NEW_SYMBOL, "21988R102", "CEB", "2012-08-14", "", lf.ATTACH, ""),
    # FB-003 (batch 3): the eight renames the follow refused. The OpenFIGI answers for DV's and YRCW's new CUSIPs are
    # not cached (decision None): a full run asks them live.
    "CIK1011006-COMMON": (lf.SWITCH, "021346101", "AABA", "2017-06-21", "", lf.ATTACH, ""),
    "CIK104889-COMMON": (lf.SWITCH, "384637104", "GHC", "2013-11-29", "", lf.FOLD, "BBG000C3FGH9"),
    "CIK730464-COMMON": (lf.SWITCH, "00737L103", "ATGE", "2017-05-24", "", None, None),
    "CIK716006-COMMON": (lf.SWITCH, "985510106", "YELL", "2021-02-09", "", None, None),
    "BBG000PCQQL6": (lf.NEW_SYMBOL, "74915M100", "QVCGA", "2025-02-25", "", lf.ATTACH, ""),
    "CIK891103-COMMON": (lf.SWITCH, "44919P508", "IACI", "2008-08-26", "", lf.FOLD, "BBG000BKQG80"),
}
NO_STEP = ("BBG00WYYC600", "CIK1507934-CLASS-A", "CIK1469372-CLASS-A")


@pytest.mark.parametrize("sec_id", sorted(EXPECTED), ids=lambda s: DATA["cases"][s]["note"].split(":")[0])
def test_a_real_lines_next_step(sec_id, ftd):
    step, evidence, refused, decision = follow(sec_id, ftd)
    kind, new_cusip, symbol, first, why, decided, composite = EXPECTED[sec_id]
    assert (step.kind, step.new_cusip, step.symbol, step.first, refused) == (kind, new_cusip, symbol, first, why)
    assert bool(evidence) != bool(refused)
    if decided is None:
        assert decision is None
    else:
        assert (decision.kind, decision.composite) == (decided, composite)


NEW_CUSIP_OF = {"BBG00WYYC600": ("966387409", "BBG000PX3XC0"), "CIK1507934-CLASS-A": ("531229102", "BBG003P9ZSL3"),
                "CIK1469372-CLASS-A": ("55825T103", "BBG007FG0C23")}


@pytest.mark.parametrize("sec_id", NO_STEP, ids=lambda s: DATA["cases"][s]["note"].split(":")[0])
def test_a_line_whose_next_cusip_is_another_securitys_takes_no_step(sec_id, ftd):
    """Must not change: WLL 2017 (its new CUSIP is BBG000PX3XC0's), new LMCA 2013 and new MSG 2015 (the ticker
    passed to another issuer, whose line of the run holds the new CUSIP)."""
    assert follow(sec_id, ftd) is None
    # positive control: the fixture holds the rows a step would be built from, so the guard is what refuses
    new_cusip, other = NEW_CUSIP_OF[sec_id]
    case = DATA["cases"][sec_id]
    rows = ftd.by_cusip(new_cusip)
    spellings = {t + s for t in case["tickers"] for s in ("", "D", "ZZZZ")}
    assert len(rows) >= lf.MIN_NEW_ROWS and {r.symbol for r in rows} & spellings
    assert DATA["holders"][new_cusip] == [other] and sec_id not in DATA["holders"][new_cusip]
    assert new_cusip not in case["cusips"]


def test_sbgis_new_holding_company_is_never_its_line(ftd):
    """Must not change (SBGI 2023): the new holding company, another CIK, replaces the registrant. The real run
    adds the holdco (BBG01GJ3NY88, which this fixture's RUN holds) only in stage 8, so the guard stage 4b has is the 8-K12B search: an 8-K12B
    filed by another CIK naming Sinclair refuses the step in `corroborate`."""
    case = DATA["cases"]["BBG000F2XXP2"]
    step, evidence, refused, decision = follow("BBG000F2XXP2", ftd)
    assert (step.new_cusip, refused) == ("829242106", "")           # without the search, nothing refuses it
    hit = {"_source": {"ciks": ["0001971213"], "display_names": ["Sinclair, Inc. (SBGI) (CIK 0001971213)"],
                       "form": "8-K12B", "file_date": step.first}}
    first, cik = date.fromisoformat(step.first), case["issuer_cik"]
    evidence, refused = lf.corroborate(
        step, filings=EDGAR_FIX.filings(cik), sub=EDGAR_FIX.submissions(cik), share_class=case["share_class"],
        text_of=lambda f: EDGAR["texts"].get(f.accession, ""), as_of=AS_OF,
        listed_now=lambda: edgar_lists(EDGAR_FIX, cik, [*case["tickers"], step.symbol]),
        other_registrant=lambda: lf.other_registrant(
            lambda q, forms, lo, hi: [hit], EDGAR_FIX, name=lf.name_on(EDGAR_FIX.submissions(cik), first, case["name"]),
            day=first, cik=cik, own_tickers=case["tickers"]))
    assert (evidence, refused) == ("", "other_registrant")


@pytest.mark.parametrize("sec_id,otc", [("BBG009NGKQ45", "VRMMQ"), ("BBG000BRWGG9", "RADCQ")])
def test_after_a_reverse_split_the_bankrupt_lines_otc_tail_and_relist_are_no_step(sec_id, otc, ftd):
    """Must not change (VRM 2025, RAD 2023): once the reverse split is followed, the line's next rows are its
    OTC symbol after the bankruptcy (and, for VRM, the reorganized company's 2025 CUSIP under VRM): no step."""
    step, *_ = follow(sec_id, ftd)
    case = DATA["cases"][sec_id]
    assert follow(sec_id, ftd, cusips=[*case["cusips"], step.new_cusip], tickers={*case["tickers"]}) is None
    assert otc in {r.symbol for r in ftd.by_cusip(step.new_cusip)}


# --- the same cases through the stage's interface, `follow_lines` ------------------------------------------------

class _Figi:
    """The fixture's OpenFIGI answers; a CUSIP it does not hold reads as an error answer (nothing settled)."""

    def map(self, jobs, use_cache=True):
        return [FIGI.get(j["idValue"], {"error": "not in the fixture"}) for j in jobs]


class _NoFiles:
    """The fails files: the fixture's index already holds every row the cases read."""

    def urls_for(self, lo, hi):
        return []


class _FixtureFiles:
    """The fixture's rows as one fails file, for the stage's reads of whole windows (`FtdIndex.every_row`: DV)."""

    def __init__(self):
        self.rows_ = _fixture_rows()

    def urls_for(self, lo, hi):
        return ["fixture"]

    def rows(self, url, *, symbols=None, cusips=None):
        for r in self.rows_:
            if (symbols is None and cusips is None) or (symbols and r.symbol in symbols) or \
                    (cusips and r.cusip in cusips):
                yield r


# the run's other securities that hold a CUSIP the cases meet (WLL's, LMCA's and MSG's next ones); with no issuer
# known here they are not followed themselves
HOLDERS = sorted({h for held in DATA["holders"].values() for h in held} - set(DATA["cases"]))


def _identity() -> Identity:
    """The identity stage's answer over the cases: one era per ticker, under the case's observed name."""
    eras, res, issuers, cusips = {}, {}, {}, {}
    for sid, case in DATA["cases"].items():
        for t in case["tickers"]:
            era = TickerEra(t, "2008-01-16", "2008-01-16", [Observation(t, "2008-01-16", case["name"])])
            eras[era.key] = era
            res[era.key] = EraResolution(era.key, sid, case["figi_source"], None, (), tuple(case["cusips"]))
            issuers[era.key] = Issuer(case["issuer_cik"])
        cusips[sid] = list(case["cusips"])
    for i, sid in enumerate(HOLDERS):
        era = TickerEra(f"HOLD{i}", "2008-01-16", "2008-01-16", [Observation(f"HOLD{i}", "2008-01-16", RUN[sid].name)])
        eras[era.key] = era
        cusips[sid] = sorted(c for c, held in DATA["holders"].items() if sid in held)
        res[era.key] = EraResolution(era.key, sid, "cusip", None, (), tuple(cusips[sid]))
        if RUN[sid].issuer_cik in {c["issuer_cik"] for c in DATA["cases"].values()}:
            issuers[era.key] = Issuer(RUN[sid].issuer_cik)       # the line of a case's issuer (GHC, IAC) is known
    index = FtdIndex(_fixture_rows(), source=_FixtureFiles(), window=(date(2007, 12, 17), AS_OF))
    return Identity(list(eras.values()), eras, index, issuers, res,
                    build_securities(res, eras, issuers), cusips)


@pytest.fixture(scope="module")
def staged():
    edgar = _Edgar()
    clients = Clients(edgar=edgar, resolver=None, classifier=None, figi=_Figi(), ftd_client=_NoFiles(),
                      issuers=IssuerRecord(edgar))
    return lf.follow_lines(_identity(), clients, as_of=AS_OF)


def _first_item(lines, sec_id):
    """The stage's first line follow item for the case (under the FIGI line a fold moved it to); None for none."""
    holder = lines.renames.get(sec_id, sec_id)
    return next((r for r in lines.review if r.sec_id == holder and r.flag.startswith("line_follow")), None)


@pytest.mark.parametrize("sec_id", sorted(EXPECTED), ids=lambda s: DATA["cases"][s]["note"].split(":")[0])
def test_a_real_lines_first_step_through_the_stage(sec_id, staged):
    """The stage takes each case's first step as the rules do: the same step, refusal and decision. A new CUSIP whose
    OpenFIGI answer the fixture lacks (DHC) is an error answer there, so the stage refuses it `unsettled`."""
    kind, new_cusip, symbol, first, why, decided, composite = EXPECTED[sec_id]
    item = _first_item(staged, sec_id)
    assert f" -> {new_cusip} under {symbol} from {first}" in item.reason
    if why or decided is None:
        assert item.flag == f"{lf.LINE_REFUSED}:{why or 'unsettled'}"
    elif decided == lf.ATTACH:
        assert item.flag == lf.LINE_FOLLOWED and item.reason.endswith(": the same security")
        assert kind == lf.NEW_SYMBOL or new_cusip in staged.cusips[sec_id]
    elif decided == lf.FOLD:
        assert item.reason.endswith(f": folded into {composite}") and staged.renames[sec_id] == composite
        assert new_cusip in staged.cusips[composite]
    else:
        assert item.reason.endswith(f": continued by {composite}") and staged.successors[sec_id].composite == composite


@pytest.mark.parametrize("sec_id", NO_STEP, ids=lambda s: DATA["cases"][s]["note"].split(":")[0])
def test_a_line_whose_next_cusip_is_another_securitys_takes_no_step_in_the_stage(sec_id, staged):
    assert _first_item(staged, sec_id) is None
    assert NEW_CUSIP_OF[sec_id][0] not in staged.cusips[sec_id]


# --- FB-003: the eight renames the follow refused, each with the step that decides it ------------------------------------

def test_the_yhoo_step_to_altaba_passes_r1_on_the_funds_reports_and_attaches(ftd):
    """YHOO 2017: Altaba filed N-CSR and N-Q for periods after the step and no 10-K or 10-Q (merged_out before).
    OpenFIGI's answer for 021346101 is a closed-end fund typed Mutual Fund, which R2 leaves out of the US lines, so the
    placeholder takes the CUSIP and the ticker AABA (the same security): stage 5 then finds Altaba's 2019 25-NSE."""
    step, evidence, refused, decision = follow("CIK1011006-COMMON", ftd)
    assert (refused, decision.kind) == ("", lf.ATTACH) and evidence.startswith("renamed from YAHOO INC")
    filings = EDGAR_FIX.filings(DATA["cases"]["CIK1011006-COMMON"]["issuer_cik"])
    assert {f.form for f in filings if f.report_date > step.first} & lf.INVESTMENT_COMPANY_FORMS
    assert not {f.form for f in filings if f.report_date > step.first} & lf.PERIODIC_FORMS


def test_the_wpo_step_was_kept_out_only_by_ghcs_line_holding_its_cusip(ftd):
    """WPO 2013: GHC's line BBG000C3FGH9 holds the new CUSIP 384637104, which kept the step out of candidate_steps; a
    COMMON placeholder is not kept from the CUSIP of its own issuer's line it folds into (`holders_for`), the fails
    descriptions say CLB, and the issuer's lines name class B only."""
    case = DATA["cases"]["CIK104889-COMMON"]
    assert lf.candidate_steps("CIK104889-COMMON", case["cusips"], case["tickers"], ftd, holders=DATA["holders"],
                              extra_symbols=case["extra_symbols"]) == []
    assert lf.described_letter(case["cusips"], ftd) == "B"
    step, _, refused, decision = follow("CIK104889-COMMON", ftd)
    assert (step.new_cusip, refused, decision.kind, decision.composite) == ("384637104", "", lf.FOLD, "BBG000C3FGH9")


def test_the_iaci_step_was_kept_out_only_by_its_issuers_line_holding_its_cusip(ftd):
    """IACI 2008: BBG000BKQG80 holds 44919P508, the CUSIP the placeholder's 44919P300 ended as; the follow folds the
    placeholder into it. That line's own next step, 44919P508 -> 44891N109 (2020-07-02), is refused `name`: the new
    IAC is a different issuer, the old one became Match Group, and the follow is right to stop there."""
    case = DATA["cases"]["CIK891103-COMMON"]
    assert lf.candidate_steps("CIK891103-COMMON", case["cusips"], case["tickers"], ftd, holders=DATA["holders"],
                              extra_symbols=case["extra_symbols"]) == []
    step, _, refused, decision = follow("CIK891103-COMMON", ftd)
    assert (step.new_cusip, refused, decision.composite) == ("44919P508", "", "BBG000BKQG80")


def _second(sec_id, ftd, cusips, tickers):
    """The case's step after the first one was followed (`cusips` and `tickers` as an attach left them)."""
    return follow(sec_id, ftd, cusips=cusips, tickers=tickers)


def test_exbds_second_step_to_ceb_inc_is_found_and_corroborated_but_needs_an_openfigi_answer(ftd):
    """EXBD/CEB: after the 2012 rename (CEB on 21988R102) the line goes on as CEB INC on 125134106 from 2015-05-15 (the
    ticker CEB is loaded for the round; the Gartner merger closed 2017-04-05). R1 passes (10-Qs, the 8-K 5.03); the
    new CUSIP's OpenFIGI answer is not cached, so R2 waits for a full run, which asks it."""
    step, evidence, refused, decision = _second("CIK1066104-COMMON", ftd, ["21988R102"], {"EXBD", "CEB"})
    assert (step.kind, step.new_cusip, step.symbol, step.first) == (lf.SWITCH, "125134106", "CEB", "2015-05-15")
    assert refused == "" and decision is None and bool(evidence)


def test_qrteas_second_step_to_the_reverse_split_cusip_is_found_but_needs_an_openfigi_answer(ftd):
    """QRTEA: the same CUSIP 74915M100 went on as QVCGA (the first step, found 14 trading days past the settled row),
    then the 1-for-50 reverse split made 74915M605 from 2025-05-23. R1 passes; OpenFIGI's answer is not cached."""
    step, evidence, refused, decision = _second("BBG000PCQQL6", ftd, ["74915M100"], {"QRTEA", "QVCGA"})
    assert (step.kind, step.new_cusip, step.symbol, step.first) == (lf.SWITCH, "74915M605", "QVCGA", "2025-05-23")
    assert refused == "" and decision is None and bool(evidence)


def test_iacs_2020_step_is_refused_because_the_new_iac_is_another_issuer(ftd):
    """The old IAC became Match Group on 2020-07-01; the CUSIP 44891N109 under IAC is the new IAC's. The description
    names no name the issuer carried from then (Match Group, Inc.), so the follow stops: right."""
    case = DATA["cases"]["CIK891103-COMMON"]
    rows = ftd.by_cusip("44891N109")
    assert rows and rows[0].date == "2020-07-02"
    steps = lf.candidate_steps("BBG000BKQG80", ["44919P508"], {"IAC", "IACI"}, ftd, holders={},
                               extra_symbols=case["extra_symbols"])
    assert [(st.new_cusip, st.symbol) for st in steps] == [("44891N109", "IAC")]
    _, refused = lf.corroborate(
        steps[0], filings=EDGAR_FIX.filings(case["issuer_cik"]), sub=EDGAR_FIX.submissions(case["issuer_cik"]),
        share_class="COMMON", text_of=lambda f: EDGAR["texts"].get(f.accession, ""), as_of=AS_OF,
        listed_now=lambda: False)
    assert refused == "name"


def test_the_dv_step_is_found_by_the_name_its_rows_carry():
    """DV 2017: the case's named CUSIP is 00737L103, found by `renamed_cusips` (EDGAR dates the rename to Adtalem on
    2017-05-24; ATGE is neither listed by EDGAR today nor named by the 8-K 5.03)."""
    assert DATA["cases"]["CIK730464-COMMON"]["extra_cusips"] == ["00737L103"]
