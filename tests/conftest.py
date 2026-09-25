"""Test fixtures: a fake EdgarClient that serves canned submissions."""

from __future__ import annotations

import errno
from dataclasses import dataclass, field
from typing import Any

import pytest

from delist_detection.edgar import EdgarSubmission


@dataclass
class _FakeEdgar:
    """Minimal stand-in for EdgarClient used by classifier unit tests."""

    submissions_by_cik: dict[int, list[EdgarSubmission]]
    company_map: dict[str, dict[str, Any]]
    texts: dict[str, str] = field(default_factory=dict)   # accession -> filing text
    raws: dict[str, str] = field(default_factory=dict)    # accession -> complete submission text
    listings: dict[int, list[tuple[str, str]]] = field(default_factory=dict)   # cik -> [(ticker, exchange)]
    former_names: dict[int, list[tuple[str, str, str]]] = field(default_factory=dict)  # cik -> [(name, from, to)]

    def company_tickers(self) -> dict[str, dict[str, Any]]:
        return self.company_map

    def recent_filings(self, cik: int | str) -> list[EdgarSubmission]:
        return list(self.submissions_by_cik.get(int(cik), []))

    def submissions(self, cik: int | str, fresh_after=None) -> dict[str, Any]:
        title = next((r["title"] for r in self.company_map.values()
                      if int(r["cik_str"]) == int(cik)), "")
        listed = self.listings.get(int(cik), [])
        former = [{"name": n, "from": lo, "to": hi} for n, lo, hi in self.former_names.get(int(cik), [])]
        return {"name": title, "formerNames": former, "sic": "",
                "tickers": [x for x, _ in listed], "exchanges": [y for _, y in listed]}

    def fetch_filing_text(self, cik: int | str, accession: str, primary_doc: str) -> str:
        return self.texts.get(accession, "")

    def fetch_filing_raw(self, cik: int | str, accession: str) -> str:
        return self.raws.get(accession, "")

    def company_search_atom(self, name: str, form_type: str = "25-NSE") -> list[dict]:
        return []


class _HalfWriter:
    """A file whose write stops halfway with a full disk, as when the process
    dies mid-write: the first half reaches the file, then OSError."""

    def __init__(self, fh):
        self.fh = fh

    def write(self, data):
        self.fh.write(data[: len(data) // 2])
        self.fh.flush()
        raise OSError(errno.ENOSPC, "No space left on device")

    def __getattr__(self, name):
        return getattr(self.fh, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fh.close()
        return False


@pytest.fixture
def writes_fail_midway(monkeypatch):
    """Arm a directory (call the returned function with it): every file opened
    for writing under it stops halfway through its first write (`_HalfWriter`).
    Patches the builtin `open` and `Path.open` (which `write_text` and
    `write_bytes` use)."""
    import builtins
    import pathlib

    real_open = builtins.open
    armed: list[str] = []

    def fake_open(file, mode="r", *args, **kwargs):
        fh = real_open(file, mode, *args, **kwargs)
        if any(ch in mode for ch in "wax") and any(str(file).startswith(d) for d in armed):
            return _HalfWriter(fh)
        return fh

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(pathlib.Path, "open", lambda self, mode="r", *a, **k: fake_open(self, mode, *a, **k))
    return lambda directory: armed.append(str(directory))


@pytest.fixture(autouse=True)
def _no_efts_network(monkeypatch):
    from delist_detection.ticker_resolver import TickerResolver
    monkeypatch.setattr(TickerResolver, "_efts_lookup", lambda self, t, d=None, **kw: (None, None, False))
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [])


@pytest.fixture
def fake_edgar() -> _FakeEdgar:
    """Three companies covering merger, compliance-failure, and liquidation."""

    altair = [
        EdgarSubmission(
            accession="0001354457-25-000243", form="25-NSE",
            filing_date="2025-03-26", report_date="",
            items="", primary_doc="primary_doc.xml",
        ),
        EdgarSubmission(
            accession="0001193125-25-066329", form="8-K",
            filing_date="2025-03-28", report_date="2025-03-26",
            items="1.01,1.02,2.01,2.04,3.01,3.03,5.01,5.02,5.03,9.01",
            primary_doc="d869190d8k.htm",
        ),
        EdgarSubmission(
            accession="0001193125-25-074144", form="15-12G",
            filing_date="2025-04-07", report_date="",
            items="", primary_doc="d924412d1512g.htm",
        ),
    ]

    # Compliance-failure fabrication: Form 25 + 3.01 only.
    compliance = [
        EdgarSubmission(
            accession="A001", form="25-NSE",
            filing_date="2023-05-10", report_date="",
            items="", primary_doc="p.xml",
        ),
        EdgarSubmission(
            accession="A002", form="8-K",
            filing_date="2023-05-08", report_date="2023-05-08",
            items="3.01,8.01", primary_doc="p.htm",
        ),
    ]

    # Liquidation: Form 25 + Form 15 with non-merger 8-K (regulation FD only).
    liquidation = [
        EdgarSubmission(
            accession="B001", form="25-NSE",
            filing_date="2019-11-06", report_date="",
            items="", primary_doc="p.xml",
        ),
        EdgarSubmission(
            accession="B002", form="8-K",
            filing_date="2019-11-04", report_date="2019-11-04",
            items="7.01,9.01", primary_doc="p.htm",
        ),
        EdgarSubmission(
            accession="B003", form="15-12G",
            filing_date="2019-12-15", report_date="",
            items="", primary_doc="p.htm",
        ),
    ]

    return _FakeEdgar(
        submissions_by_cik={1701732: altair, 999001: compliance, 999002: liquidation},
        company_map={
            "ALTR": {"cik_str": 1701732, "ticker": "ALTR", "title": "Altair Engineering Inc."},
            "BAD":  {"cik_str": 999001, "ticker": "BAD",  "title": "Bad Co."},
            "LIQ":  {"cik_str": 999002, "ticker": "LIQ",  "title": "Liquidating Trust"},
        },
        texts={"A002": "Item 3.01 Notice of Delisting ... has not regained compliance "
                       "with the minimum bid price requirement"},
    )


class _VirtualClock:
    """Time that passes only when the limiter sleeps on it. The limiter re-checks
    its pause after every sleep, so with the real clock and a no-op sleep it
    would busy-wait out every pause in real time."""

    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


@pytest.fixture(autouse=True)
def _fresh_sec_limiter(monkeypatch, tmp_path_factory):
    """Every test gets its own process-wide SEC limiter: in-process only, on a
    virtual clock that its own sleep advances (so it never waits in real time,
    and never busy-waits), and with no pause or request count left over from
    another test. DELIST_DETECTION_SEC_RATE_LOCK points at a per-test temporary
    file, outside the test's own tmp_path, so code that installs the
    machine-wide gate never touches the lock file under the home directory."""
    from delist_detection import edgar
    monkeypatch.setenv(edgar.SEC_RATE_LOCK_ENV, str(tmp_path_factory.mktemp("sec_rate") / "sec_rate.lock"))
    clock = _VirtualClock()
    monkeypatch.setattr(edgar, "SEC_LIMITER",
                        edgar.RateLimiter(edgar.SEC_MAX_RATE, clock=clock.now, sleep=clock.sleep))
