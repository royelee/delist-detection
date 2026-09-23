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
