"""Small output tables for the lifecycle, truth, scorecard and audit tests. Each
helper returns one row with its table's full column set (blank where a test
does not care), as store.read_table would."""
from __future__ import annotations

from delist_detection.lifecycle import Tables
from delist_detection.store import TABLES


def _row(table: str, **cells) -> dict[str, str]:
    row = dict.fromkeys(TABLES[table].columns, "")
    unknown = set(cells) - set(row)
    assert not unknown, f"{table}: no column(s) {sorted(unknown)}"
    row.update({k: str(v) for k, v in cells.items()})
    return row


def sec(sec_id, cik="100", figi_source="cusip", observed=True):
    return _row("securities", sec_id=sec_id, issuer_cik=cik, share_class="COMMON", name=sec_id,
                observed="true" if observed else "false", figi_source=figi_source)


def iv(sec_id, ticker, start, end=""):
    return _row("ticker_history", sec_id=sec_id, ticker=ticker, valid_from=start, valid_to=end, source="observation")


def ending(sec_id, delist_date, bucket="merger", *, ltd="", dlret="", method="cash_only", successor="",
           confidence="high", dlret_confidence="high", flags="", reason="", source="midas", **cells):
    return _row("delistings", sec_id=sec_id, delist_date=delist_date, bucket=bucket, last_trade_date=ltd,
                dlret=dlret, dlret_method=method, successor_sec_id=successor, confidence=confidence,
                dlret_confidence=dlret_confidence, review_flags=flags, reason=reason,
                last_trade_date_source=source if ltd else "", **cells)


def obs(ticker, as_of, sec_id="", status="mapped", *, era=None, name=""):
    """An observation_map row; its era starts on its own date unless `era` says otherwise."""
    return _row("observation_map", ticker=ticker, as_of=as_of, sec_id=sec_id, status=status,
                era=era or f"{ticker}@{as_of}", name=name)


def review(sec_id, flags="no_form25"):
    return _row("review", severity="check", sec_id=sec_id, review_flags=flags)


def hist(sec_id, issuer, start, end="", ticker="AAA"):
    """A contract/security_history.csv row."""
    return _row("security_history", sec_id=sec_id, issuer_id=issuer, start_date=start, end_date=end, ticker=ticker,
                security_name=sec_id, share_class="COMMON")


def tables(securities=(), history=(), delistings=(), observations=(), reviews=(), *, uncertain=None,
           security_history=None, contract_delistings=None) -> Tables:
    return Tables(list(securities), list(history), list(delistings), list(observations), list(reviews),
                  uncertain, security_history, contract_delistings)


def cend(sec_id, value_rule):
    """A contract/delistings.csv row."""
    return _row("contract_delistings", sec_id=sec_id, value_rule=value_rule)


def contract_row(sec_id, **cells):
    """A contract/delistings.csv row with any of its columns set."""
    return _row("contract_delistings", sec_id=sec_id, **cells)
