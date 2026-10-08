"""Delist Detection: a FIGI-keyed security master and Form-25-driven delistings, from SEC EDGAR.

The package is laid out by concept, and imports run one way between its subpackages (tests/test_import_closure.py
reads them from the real import graph):

    vocabulary   the leaves every part reads: identifier spelling, name agreement, the trading calendar, CRSP
                 codes, exchanges, the row vocabulary; imports nothing of the package
    sources      the SEC, OpenFIGI, Nasdaq and LLM clients and their plumbing; imports the vocabulary
    filings      what SEC filings say, read by several stages; imports sources
    outputs      what a run publishes, as rows; imports the sources' plumbing, no client and no stage
    identity     a security's identity (stages 1 to 4c); imports filings and outputs
    endings      every delisting, found, dated and classified (stages 5 to 9g); imports identity
    terms        what one share of a merger ending became (stage 8); imports endings
    measurement  how far a published run is from the truth; imports outputs
    handling     delistings.csv for training and backtests; imports outputs
    pipeline     the run, every stage in order (`run`, `default_clients`); nothing imports it

Importing the package loads none of its modules. The names below, the ones the README and the scripts import from
here, load their module on first use.
"""

_LAZY = {                                   # name: the module that defines it
    "EdgarClient": "sources.edgar",
    "TickerResolver": "identity.ticker_resolver",
    "DelistClassifier": "endings.classifier",
    "PayoutExtractor": "terms.payout_extractor",
    "Exchange": "vocabulary.exchanges",
    "build_train_label_adjustment": "handling.handling",
    "build_backtest_exit": "handling.handling",
    "build_firm_month_correction": "handling.handling",
}
__all__ = list(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY})
