from datetime import date

from delist_detection.edgar import EdgarSubmission
from delist_detection.listing_status import (
    cover_exchanges, exchanges_around, listed_today, withdrawal_kind,
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
        return {"exchanges": self.exchanges}


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
