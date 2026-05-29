from delist_detection.exchanges import Exchange, normalize_exchange


def test_normalize_nyse_variants():
    assert normalize_exchange("NYSE") is Exchange.NYSE
    assert normalize_exchange("New York Stock Exchange") is Exchange.NYSE
    assert normalize_exchange("nyse arca") is Exchange.NYSE  # ARCA -> NYSE family


def test_normalize_nasdaq_variants():
    assert normalize_exchange("NASDAQ") is Exchange.NASDAQ
    assert normalize_exchange("Nasdaq Global Select") is Exchange.NASDAQ
    assert normalize_exchange("NASDAQ-NMS") is Exchange.NASDAQ


def test_normalize_amex():
    # AMEX = NYSE American post-2017; both map to AMEX for Shumway purposes
    assert normalize_exchange("AMEX") is Exchange.AMEX
    assert normalize_exchange("NYSE American") is Exchange.AMEX
    assert normalize_exchange("NYSE MKT") is Exchange.AMEX


def test_normalize_unknown_or_missing():
    assert normalize_exchange("") is Exchange.OTHER
    assert normalize_exchange(None) is Exchange.OTHER
    assert normalize_exchange("OTC Markets") is Exchange.OTHER
    assert normalize_exchange("BATS") is Exchange.OTHER


import textwrap
import pytest
from delist_detection.av_listing import AvListingLoader


@pytest.fixture
def av_csv(tmp_path):
    p = tmp_path / "delisted.csv"
    p.write_text(textwrap.dedent("""\
        symbol,name,exchange,assetType,ipoDate,delistingDate
        ALTR,Altair,NASDAQ,Stock,2017-10-25,2025-03-26
        RSH,RadioShack,NYSE,Stock,1971-08-12,2015-02-09
    """))
    return p


def test_av_loader_exchange_lookup(av_csv):
    loader = AvListingLoader(av_csv)
    assert loader.exchange("ALTR") == "NASDAQ"
    assert loader.exchange("RSH") == "NYSE"
    assert loader.exchange("DOESNOTEXIST") is None
