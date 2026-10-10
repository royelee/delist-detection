import json
from datetime import date
from pathlib import Path

import pytest

from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.filings.listing_status import (
    cover_exchanges, exchanges_around, listed_today, listing_answers, unlisted_cover, withdrawal_kind,
)

COVER_2019 = ("UNITED STATES SECURITIES AND EXCHANGE COMMISSION FORM 10-K ... Securities registered pursuant "
              "to Section 12(b) of the Act: Title of each class Trading Symbol(s) Name of each exchange on which "
              "registered Common Stock, $0.625 par value APA New York Stock Exchange Chicago Stock Exchange ...")
COVER_2021 = ("FORM 10-K ... Name of each exchange on which registered Common Stock APA "
              "Nasdaq Global Select Market ...")


def test_cover_exchanges():
    assert cover_exchanges(COVER_2019) == {"NYSE", "CHICAGO"}
    assert cover_exchanges(COVER_2021) == {"NASDAQ"}
    assert cover_exchanges("") == set()


def test_withdrawal_kind():
    assert withdrawal_kind("CHICAGO", {"NYSE", "CHICAGO"}, {"NYSE"}) == "secondary"        # Apache 2020
    assert withdrawal_kind("NYSE ARCA", {"NYSE", "NYSE ARCA"}, {"NYSE"}) == "secondary"    # IRF 2007
    assert withdrawal_kind("NASDAQ", {"NASDAQ"}, {"NYSE"}) == "delisting"                  # moved: transfer
    assert withdrawal_kind("NYSE", {"NYSE"}, None) == "delisting"                          # stopped filing
    assert withdrawal_kind("NYSE", {"NYSE"}, set()) == "delisting"                         # OTC afterwards
    assert withdrawal_kind("", None, None) == "delisting"


class _Edgar:
    def __init__(self, texts):
        self.texts = texts

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.texts.get(accession, "")


def test_exchanges_around():
    filings = [
        EdgarSubmission("k19", "10-K", "2020-02-21", "", "", "a.htm"),
        EdgarSubmission("k21", "10-K", "2021-02-25", "", "", "b.htm"),
        EdgarSubmission("q", "10-Q", "2020-08-01", "", "", "c.htm"),
    ]
    before, after = exchanges_around(_Edgar({"k19": COVER_2019, "k21": COVER_2021}), 6769, filings,
                                     date(2020, 6, 8))
    assert before == {"NYSE", "CHICAGO"} and after == {"NASDAQ"}
    assert exchanges_around(_Edgar({}), 1, [], date(2020, 6, 8)) == (None, None)


COVER_NONE = ("FORM 10-K ... Securities registered pursuant to Section 12(b) of the Act: Title of each class Name of "
              "each exchange on which registered None Securities registered pursuant to Section 12(g): Common Stock")


def test_unlisted_cover_is_the_first_annual_report_after_the_day_whose_cover_names_no_exchange():
    """Freddie Mac, Fannie Mae 2010: the next 10-K's "Name of each exchange on which registered" column holds none.
    An unread report, one with an exchange, one without the column, and a report outside the window are no cover
    that names none."""
    filings = [EdgarSubmission("k10", "10-K", "2010-02-24", "", "", "a.htm"),
               EdgarSubmission("k11", "10-K", "2011-02-24", "", "", "b.htm"),
               EdgarSubmission("k12", "10-K", "2012-02-24", "", "", "c.htm")]
    day = date(2010, 6, 28)
    assert unlisted_cover(_Edgar({"k11": COVER_NONE}), 1, filings, day) == "2011-02-24"
    assert unlisted_cover(_Edgar({}), 1, filings, day) is None                          # not in the cache
    assert unlisted_cover(_Edgar({"k11": COVER_2021}), 1, filings, day) is None         # an exchange
    assert unlisted_cover(_Edgar({"k11": "FORM 10-K ... no such column ..."}), 1, filings, day) is None
    assert unlisted_cover(_Edgar({"k12": COVER_NONE}), 1, filings[:1] + filings[2:], day) is None   # past the window
    assert unlisted_cover(_Edgar({"k11": COVER_NONE}), 1, [], day) is None


class _Figi:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def map(self, jobs, use_cache=True):
        self.calls.append((jobs, use_cache))
        return [self.answer]


class _Sub:
    def __init__(self, exchanges):
        self.exchanges = exchanges

    def submissions(self, cik, fresh_after=None):
        # EDGAR's parallel arrays: a ticker per exchange entry
        return {"tickers": [f"T{i}" for i in range(len(self.exchanges))], "exchanges": self.exchanges}


def test_listed_today():
    listed = _Figi({"data": [{"exchCode": "US"}, {"exchCode": "UW"}]})
    assert listed_today(listed, "BBG000MM2P62") is True
    assert listed.calls[0] == ([{"idType": "COMPOSITE_ID_BB_GLOBAL", "idValue": "BBG000MM2P62"}], False)
    assert listed_today(_Figi({"warning": "No identifier found."}), "BBG000FJLFX8") is False
    assert listed_today(_Figi({"data": [{"exchCode": "US"}, {"exchCode": "UV"}]}), "BBG1") is False   # OTC only
    assert listed_today(_Figi({"error": "x"}), "BBG1") is None
    assert listed_today(_Figi({}), "CIK1-COMMON", edgar=_Sub(["NYSE"]), cik=1) is True
    assert listed_today(_Figi({}), "CIK1-COMMON", edgar=_Sub(["OTC"]), cik=1) is False
    assert listed_today(_Figi({}), "CIK1-COMMON") is None


LISTING_FIX = Path(__file__).parent / "fixtures" / "listing_status"


class _FixEdgar:
    def __init__(self, sub):
        self.sub = sub

    def submissions(self, cik, fresh_after=None):
        return self.sub


def _fix(name):
    return json.loads((LISTING_FIX / f"{name}.json").read_text())


@pytest.mark.parametrize("name,listed", [
    ("celgene", False), ("tss", False), ("slack", False), ("mylan", False), ("alexion", False),
    ("apache_old", False), ("apple", True), ("berkshire_b", True), ("alphabet_a", True),
])
def test_a_dead_figi_with_a_venue_row_is_not_listed(name, listed):
    """OpenFIGI's map by composite FIGI still returns an exchange venue row for a
    delisted security (Celgene: UW; TSS: UN; old Apache: UW — live answers of
    2026-09-23). With the issuer's CIK known, the security is listed today only
    when the issuer's EDGAR submissions also list one of its tickers on a major
    exchange; the fixtures hold the live OpenFIGI answer and the issuer's
    cached submissions tickers/exchanges."""
    f = _fix(name)
    got = listed_today(_Figi(f["openfigi"]), f["sec_id"], edgar=_FixEdgar(f["submissions"]), cik=f["cik"],
                       tickers=f["observed_tickers"])
    assert got is listed


def test_the_openfigi_ticker_also_counts_and_no_cik_keeps_the_openfigi_rule():
    figi = _Figi({"data": [{"exchCode": "UN", "ticker": "NEWT"}]})
    sub = _FixEdgar({"tickers": ["NEWT"], "exchanges": ["NYSE"]})
    assert listed_today(figi, "BBG1", edgar=sub, cik=5, tickers=["OLDT"]) is True     # renamed since observed
    assert listed_today(figi, "BBG1", edgar=_FixEdgar({"tickers": ["NEWT"], "exchanges": ["OTC"]}), cik=5,
                        tickers=["OLDT"]) is False
    assert listed_today(figi, "BBG1", tickers=["OLDT"]) is True                        # no CIK: OpenFIGI alone
    # a placeholder: one of its own tickers must be on a major exchange
    assert listed_today(_Figi({}), "CIK5-COMMON", edgar=sub, cik=5, tickers=["OTHER"]) is False
    assert listed_today(_Figi({}), "CIK5-COMMON", edgar=sub, cik=5, tickers=["NEWT"]) is True


def test_a_security_trading_at_the_data_edge_and_delisted_after_the_run_date_was_listed_on_it():
    """An --as-of run reads today's OpenFIGI and EDGAR listing, which a later delisting has already changed (WBD,
    LESL and QRVO in a run as of 2026-09-25 read on 2026-10-10). A Form 25 the issuer filed after the run date (the
    EDGAR client's copy names the forms it left out, `FILED_AFTER_RUN_DATE`) shows that a security still trading at
    the fails data's end was listed on the run date; the issuer's lines that ended long before (DISCA, DISCK 2022)
    stay as today's answer says."""
    from delist_detection.filings.listing_status import listed_on_run_date
    from delist_detection.sources.edgar import FILED_AFTER_RUN_DATE
    later = {"tickers": ["WBD"], "exchanges": [""], FILED_AFTER_RUN_DATE: ["25-NSE", "8-K"]}
    edge, end = date(2026, 9, 14), date(2026, 9, 14)
    assert listed_on_run_date(False, later, edge, end) is True
    assert listed_on_run_date(None, later, date(2026, 8, 20), end) is True
    assert listed_on_run_date(False, later, date(2022, 4, 8), end) is False          # DISCA's line
    assert listed_on_run_date(False, {**later, FILED_AFTER_RUN_DATE: ["8-K"]}, edge, end) is False
    assert listed_on_run_date(False, {"tickers": ["WBD"]}, edge, end) is False        # nothing filed after
    assert listed_on_run_date(True, {}, None, None) is True
    gone = _Figi({"warning": "No identifier found."})
    assert listed_today(gone, "BBG011386VF4", edgar=_FixEdgar(later), cik=1437107, tickers=["WBD"]) is False


def test_behind_the_clock_edgar_listing_stands_for_a_security_trading_at_the_data_edge():
    """QRVO and LESL in a run as of 2026-09-25 read on 2026-10-10: OpenFIGI answers "No identifier found" and
    LESLQ on OTC, EDGAR still lists QRVO and LESL on Nasdaq, no Form 25 yet. A run behind the clock takes EDGAR's
    listing for a security that traded to the fails data's end; a run on today's date keeps today's answer."""
    from delist_detection.filings.listing_status import listed_on_run_date
    from delist_detection.sources.edgar import FILED_AFTER_RUN_DATE
    qrvo = {"tickers": ["QRVO"], "exchanges": ["Nasdaq"]}
    end = date(2026, 9, 14)
    assert listed_on_run_date(False, qrvo, date(2026, 8, 18), end, tickers=["QRVO"], behind_clock=True) is True
    assert listed_on_run_date(False, qrvo, date(2026, 8, 18), end, tickers=["QRVO"]) is False
    assert listed_on_run_date(False, qrvo, date(2026, 6, 1), end, tickers=["QRVO"], behind_clock=True) is False
    otc = {"tickers": ["FMCC"], "exchanges": ["OTC"]}
    assert listed_on_run_date(False, otc, end, end, tickers=["FMCC"], behind_clock=True) is False
    assert listed_on_run_date(False, qrvo, end, end, tickers=["XXX"], behind_clock=True) is False
    # OKE 2026: its Form 25, filed before the run date, schedules the transfer after it: the finder reads it
    oke = {"tickers": ["OKE"], "exchanges": ["NYSE"],
           "filings": {"recent": {"form": ["8-K", "25"], "filingDate": ["2026-09-24", "2026-09-17"]}}}
    assert listed_on_run_date(False, oke, end, end, tickers=["OKE"], behind_clock=True) is False
    # TWO 2026: its own Form 25 by the run date (the merger) wins over a later Form 25 of its preferred
    two = {"tickers": ["TWO-PA", "TWOD"], "exchanges": ["NYSE", "NYSE"], FILED_AFTER_RUN_DATE: ["25", "4"],
           "filings": {"recent": {"form": ["25", "8-K"], "filingDate": ["2026-09-24", "2026-09-10"]}}}
    assert listed_on_run_date(False, two, end, end, tickers=["TWO"], behind_clock=True) is False


def test_a_security_edgar_lists_on_cboe_is_listed_today():
    figi = _Figi({"data": [{"exchCode": "UF", "ticker": "CBOE"}]})
    sub = _FixEdgar({"tickers": ["CBOE"], "exchanges": ["CBOE"]})
    assert listed_today(figi, "BBG000QH56C1", edgar=sub, cik=1374310, tickers=["CBOE"]) is True


from delist_detection.sources.openfigi import OpenFigiBlocked


class _BatchFigi:
    def __init__(self, answers, fail=None):
        self.answers, self.fail, self.calls = answers, fail, []

    def map(self, jobs, use_cache=True):
        self.calls.append(([j["idValue"] for j in jobs], use_cache))
        if self.fail is not None:
            raise self.fail
        return [self.answers.get(j["idValue"], {"warning": "No identifier found."}) for j in jobs]


def test_listing_answers_asks_openfigi_once_for_every_figi():
    figi = _BatchFigi({"BBG1": {"data": [{"exchCode": "UN"}]}})
    got = listing_answers(figi, ["BBG1", "CIK7-COMMON", "BBG2", "BBG1"])
    assert figi.calls == [(["BBG1", "BBG2"], False)]     # one call; no placeholder, no duplicate, no cache
    assert got == {"BBG1": {"data": [{"exchCode": "UN"}]}, "BBG2": {"warning": "No identifier found."}}


def test_a_prefetched_answer_needs_no_openfigi_call():
    assert listed_today(None, "BBG1", answer={"data": [{"exchCode": "UN"}]}) is True
    assert listed_today(None, "BBG1", answer={"error": "x"}) is None
    assert listed_today(None, "BBG1", answer={"warning": "No identifier found."}) is False


def test_a_failed_batch_leaves_each_security_to_ask_alone():
    assert listing_answers(_BatchFigi({}, fail=RuntimeError("figi down")), ["BBG1"]) == {}


def test_a_refused_batch_aborts():
    with pytest.raises(OpenFigiBlocked):
        listing_answers(_BatchFigi({}, fail=OpenFigiBlocked("401")), ["BBG1"])


def test_no_figi_client_or_only_placeholders_asks_nothing():
    figi = _BatchFigi({})
    assert listing_answers(figi, ["CIK1-COMMON"]) == {} and figi.calls == []
    assert listing_answers(None, ["BBG1"]) == {}
