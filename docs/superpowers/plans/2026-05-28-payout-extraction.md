# Payout Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-extract the per-share cash merger consideration (`payout_per_share`) from SEC EDGAR filings for every MERGER-bucket ticker, eliminating the manual `data/payouts.csv` step.

**Architecture:** A new `PayoutExtractor` walks a tiered chain of EDGAR filings (closing 8-K Item 2.01 → announcement 8-K Item 1.01 → DEFM14A → PREM14A), fetches each filing's primary HTML via a new `EdgarClient.fetch_filing_text`, strips tags, and regex-matches the cash consideration. `classify_universe.py` runs it after classification and writes `output/payouts.csv` plus three new columns on `output/delist_classifications.csv`.

**Tech Stack:** Python 3.10+, `requests`, `pandas`, `pytest`. No new dependencies.

Design of record: `docs/superpowers/specs/2026-05-28-payout-extraction-design.md`.

---

## File Structure

- **Create** `src/delist_detection/payout_extractor.py` — `PayoutResult` dataclass + `PayoutExtractor` class. One responsibility: turn a `DelistRecord` into a payout value with evidence.
- **Modify** `src/delist_detection/edgar.py` — add `fetch_filing_text(cik, accession, primary_doc)`. Fits here: it's the EDGAR I/O + cache layer.
- **Modify** `src/delist_detection/__init__.py` — export `PayoutExtractor`, `PayoutResult`.
- **Modify** `scripts/classify_universe.py` — run extraction after classification; write the two output artifacts.
- **Create** `tests/test_payout_extractor.py` — unit tests on a fake EDGAR that serves canned filing text.
- **Create** `tests/test_payout_golden.py` — offline golden tests on committed real-filing fixtures.
- **Create** `tests/fixtures/altr_8k_201.txt`, `tests/fixtures/atvi_8k_201.txt` — stripped real 8-K text.
- **Create** `scripts/regen_payout_fixtures.py` — regenerates the golden fixtures from live SEC (committed, not run in CI).

---

## Task 1: `fetch_filing_text` on EdgarClient

**Files:**
- Modify: `src/delist_detection/edgar.py`
- Test: `tests/test_edgar_filing_text.py` (create)

The text cache lives under `cache/edgar/text/{accession_no_dashes}.txt`, separate from the JSON cache. `_strip_html` is a module-level pure function so it can be unit-tested without network or disk.

- [ ] **Step 1: Write the failing test for `_strip_html`**

Create `tests/test_edgar_filing_text.py`:

```python
from delist_detection.edgar import _strip_html


def test_strip_html_removes_tags_and_scripts():
    raw = (
        "<html><head><style>.x{color:red}</style>"
        "<script>var a=1;</script></head>"
        "<body><p>right to receive&nbsp;$113.00 in&#160;cash</p>"
        "<div>without   interest</div></body></html>"
    )
    out = _strip_html(raw)
    assert "var a" not in out
    assert "color:red" not in out
    assert "right to receive $113.00 in cash without interest" in out
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `pytest tests/test_edgar_filing_text.py::test_strip_html_removes_tags_and_scripts -v`
Expected: FAIL with `ImportError: cannot import name '_strip_html'`.

- [ ] **Step 3: Implement `_strip_html` and `fetch_filing_text`**

Add to `src/delist_detection/edgar.py`. Put `_strip_html` at module level (after the imports, before `EdgarClient`):

```python
import html as _html
import re as _re


def _strip_html(raw: str) -> str:
    """Strip <script>/<style>/tags, unescape entities, collapse whitespace."""
    t = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    t = _re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = _re.sub(r"\s+", " ", t)
    return t.strip()
```

Add this method to `EdgarClient` (after `submissions`):

```python
def fetch_filing_text(self, cik: int | str, accession: str, primary_doc: str) -> str:
    """Fetch a filing's primary document, return stripped plain text.

    Cached under cache/edgar/text/{accession_no_dashes}.txt. Returns '' on
    404 or network error so callers can fall through to the next tier.
    """
    acc_nodash = accession.replace("-", "")
    text_dir = self.cache_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    cp = text_dir / f"{acc_nodash}.txt"
    if cp.exists():
        return cp.read_text()
    url = (
        f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/"
        f"{acc_nodash}/{primary_doc}"
    )
    _throttle()
    try:
        resp = self.session.get(
            url,
            headers={**self.session.headers, "Host": "www.sec.gov", "Accept": "text/html,*/*"},
            timeout=30,
        )
    except requests.RequestException:
        return ""
    if resp.status_code != 200:
        cp.write_text("")
        return ""
    text = _strip_html(resp.text)
    cp.write_text(text)
    return text
```

- [ ] **Step 4: Run the test, confirm it passes**

Run: `pytest tests/test_edgar_filing_text.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/edgar.py tests/test_edgar_filing_text.py
git commit -m "feat: EdgarClient.fetch_filing_text + _strip_html helper"
```

---

## Task 2: `PayoutResult` dataclass + non-merger short-circuit

**Files:**
- Create: `src/delist_detection/payout_extractor.py`
- Test: `tests/test_payout_extractor.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_payout_extractor.py`:

```python
from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.payout_extractor import PayoutExtractor, PayoutResult


class _StubEdgar:
    """Serves no filings and no text — used to test short-circuits."""
    def recent_filings(self, cik):
        return []
    def fetch_filing_text(self, cik, accession, primary_doc):
        return ""


def _rec(bucket, cik=111):
    return DelistRecord(
        ticker="X", cik=cik, observed_delist_date="2024-01-15",
        crsp_code=231, bucket=bucket, confidence="high", reason="", evidence={},
    )


def test_non_merger_returns_none():
    ext = PayoutExtractor(_StubEdgar())
    res = ext.extract(_rec(CrspBucket.COMPLIANCE_FAILURE))
    assert res == PayoutResult(None, "none", "none", "", "")


def test_merger_no_cik_returns_none():
    ext = PayoutExtractor(_StubEdgar())
    res = ext.extract(_rec(CrspBucket.MERGER, cik=None))
    assert res.value is None
    assert res.confidence == "none"
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `pytest tests/test_payout_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'delist_detection.payout_extractor'`.

- [ ] **Step 3: Create the module with the dataclass and short-circuits**

Create `src/delist_detection/payout_extractor.py`:

```python
"""Extract per-share cash merger consideration from EDGAR filings.

Tiered: closing 8-K (Item 2.01) → announcement 8-K (Item 1.01) →
DEFM14A → PREM14A. First tier yielding a sanity-passing value wins.
A miss returns PayoutResult(None, 'none', ...), which the BMP pipeline
treats as neutral-mark — i.e. a miss is zero-regression.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .edgar import EdgarSubmission


@dataclass(frozen=True)
class PayoutResult:
    value: float | None
    confidence: str            # 'high' | 'medium' | 'low' | 'none'
    source: str                # '8K_2.01' | '8K_1.01' | 'DEFM14A' | 'PRE14A' | 'none'
    accession: str
    quote: str

    @classmethod
    def none(cls) -> "PayoutResult":
        return cls(None, "none", "none", "", "")


_NONE = PayoutResult.none()


class PayoutExtractor:
    def __init__(self, edgar) -> None:
        self.edgar = edgar

    def extract(self, record: DelistRecord, last_close: float | None = None) -> PayoutResult:
        if record.bucket != CrspBucket.MERGER or record.cik is None:
            return _NONE
        return _NONE  # tiers added in Task 4
```

- [ ] **Step 4: Run the test, confirm it passes**

Run: `pytest tests/test_payout_extractor.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/payout_extractor.py tests/test_payout_extractor.py
git commit -m "feat: PayoutResult + PayoutExtractor non-merger short-circuit"
```

---

## Task 3: Regex matcher + sanity filter (pure functions)

**Files:**
- Modify: `src/delist_detection/payout_extractor.py`
- Test: `tests/test_payout_extractor.py`

These are the two pure functions the tiers depend on. `_match_payout` returns
`(value, quote)` for the modal sanity-passing match, or `(None, "")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_payout_extractor.py`:

```python
from delist_detection.payout_extractor import _match_payout, _passes_sanity


def test_match_in_cash_family_altr():
    text = ("each share ... were converted into the right to receive "
            "$113.00 in cash, without interest (the Merger Consideration). "
            "amount in cash equal to $1,618.7928 ($113.00 multiplied by ...)")
    val, quote = _match_payout(text)
    assert val == 113.00
    assert "113.00" in quote


def test_match_in_cash_family_atvi():
    text = "was cancelled and automatically converted into the right to receive $95.00 in cash (the Merger Consideration)"
    val, _ = _match_payout(text)
    assert val == 95.00


def test_match_per_share_family():
    text = "holders received $42.50 per share in cash at closing"
    val, _ = _match_payout(text)
    assert val == 42.50


def test_match_four_decimal_trap_not_truncated():
    # $1,618.7928 must NOT be read as 1618.79; the only real per-share is 12.00
    text = "$1,618.7928 was the note payoff; shares received $12.00 in cash"
    val, _ = _match_payout(text)
    assert val == 12.00


def test_match_modal_value_wins():
    text = ("$113.00 in cash ... $113.00 in cash ... $113.00 in cash ... "
            "an alternate $112.00 in cash")
    val, _ = _match_payout(text)
    assert val == 113.00


def test_match_comma_thousands():
    text = "right to receive $1,250.00 in cash per share"
    val, _ = _match_payout(text)
    assert val == 1250.00


def test_no_match_returns_none():
    val, quote = _match_payout("this filing mentions no cash consideration")
    assert val is None and quote == ""


def test_sanity_absolute_band():
    assert not _passes_sanity(0.001, None)
    assert not _passes_sanity(20000.0, None)
    assert _passes_sanity(113.0, None)


def test_sanity_relative_band():
    assert not _passes_sanity(2.0, last_close=100.0)      # < 5% of last close
    assert not _passes_sanity(2500.0, last_close=100.0)   # > 20x last close
    assert _passes_sanity(113.0, last_close=111.85)
```

- [ ] **Step 2: Run them, confirm they fail**

Run: `pytest tests/test_payout_extractor.py -v`
Expected: FAIL with `ImportError: cannot import name '_match_payout'`.

- [ ] **Step 3: Implement the two functions**

Add to `src/delist_detection/payout_extractor.py` (module level, after the imports):

```python
_ABS_MIN, _ABS_MAX = 0.01, 10000.00

# Ordered patterns; group 1 is the dollar value. The (?!\d) guard prevents
# matching a 2-decimal truncation of a 4-decimal figure (e.g. $1,618.7928).
_PATTERNS = [
    re.compile(r"(?:right to receive|receive)\s+\$\s*([\d,]+\.\d{2})(?!\d)\s+in\s+cash", re.I),
    re.compile(r"\$\s*([\d,]+\.\d{2})(?!\d)\s+in\s+cash(?:,?\s+without\s+interest)?", re.I),
    re.compile(r"\$\s*([\d,]+\.\d{2})(?!\d)\s+(?:in\s+cash\s+)?per\s+share", re.I),
    re.compile(r"(?:cash|merger)\s+consideration\s+of\s+\$\s*([\d,]+\.\d{2})(?!\d)", re.I),
]


def _passes_sanity(value: float, last_close: float | None) -> bool:
    if not (_ABS_MIN <= value <= _ABS_MAX):
        return False
    if last_close is not None and last_close > 0:
        if value < 0.05 * last_close or value > 20.0 * last_close:
            return False
    return True


def _match_payout(text: str, last_close: float | None = None) -> tuple[float | None, str]:
    """Return (modal sanity-passing value, ~120-char quote) or (None, '')."""
    counts: dict[float, int] = {}
    quotes: dict[float, str] = {}
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            try:
                val = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if not _passes_sanity(val, last_close):
                continue
            counts[val] = counts.get(val, 0) + 1
            if val not in quotes:
                lo = max(0, m.start() - 40)
                quotes[val] = text[lo:m.end() + 40].strip()
    if not counts:
        return None, ""
    # modal value; tiebreak by numerically largest
    best = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return best, quotes[best]
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `pytest tests/test_payout_extractor.py -v`
Expected: PASS (all tests, including the 2 from Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/payout_extractor.py tests/test_payout_extractor.py
git commit -m "feat: payout regex matcher + sanity filter"
```

---

## Task 4: Tiered filing walk in `extract`

**Files:**
- Modify: `src/delist_detection/payout_extractor.py`
- Test: `tests/test_payout_extractor.py`

Now wire the tiers. The extractor selects candidate filings from
`edgar.recent_filings(cik)` by form + item + date window, fetches each one's
text, and returns the first tier that matches.

- [ ] **Step 1: Write the failing tests with a fake EDGAR that serves text**

Append to `tests/test_payout_extractor.py`:

```python
from delist_detection.edgar import EdgarSubmission


class _FakeEdgarText:
    """recent_filings + fetch_filing_text keyed by accession."""
    def __init__(self, filings, texts):
        self._filings = filings
        self._texts = texts
    def recent_filings(self, cik):
        return list(self._filings)
    def fetch_filing_text(self, cik, accession, primary_doc):
        return self._texts.get(accession, "")


def _merger_rec():
    return DelistRecord(
        ticker="ALTR", cik=1701732, observed_delist_date="2025-03-26",
        crsp_code=231, bucket=CrspBucket.MERGER, confidence="high",
        reason="", evidence={},
    )


def test_tier1_closing_8k_high():
    filings = [EdgarSubmission(
        accession="C1", form="8-K", filing_date="2025-03-28",
        report_date="2025-03-26", items="2.01,5.01,3.01", primary_doc="d.htm")]
    texts = {"C1": "converted into the right to receive $113.00 in cash, without interest"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 113.00
    assert res.confidence == "high"
    assert res.source == "8K_2.01"
    assert res.accession == "C1"


def test_tier2_announcement_8k_medium():
    # No 2.01 filing; a 1.01 filing ~60d before delist carries the number.
    filings = [EdgarSubmission(
        accession="A1", form="8-K", filing_date="2025-01-26",
        report_date="2025-01-26", items="1.01,9.01", primary_doc="d.htm")]
    texts = {"A1": "agreed to acquire each share for $95.00 in cash"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 95.00
    assert res.confidence == "medium"
    assert res.source == "8K_1.01"


def test_tier3_defm14a_medium():
    filings = [EdgarSubmission(
        accession="D1", form="DEFM14A", filing_date="2025-02-01",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"D1": "right to receive $80.00 in cash for each share"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 80.00
    assert res.source == "DEFM14A"
    assert res.confidence == "medium"


def test_tier4_prem14a_low():
    filings = [EdgarSubmission(
        accession="P1", form="PREM14A", filing_date="2025-01-10",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"P1": "right to receive $80.00 in cash for each share"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.source == "PRE14A"
    assert res.confidence == "low"


def test_tier1_preferred_over_tier2():
    filings = [
        EdgarSubmission(accession="C1", form="8-K", filing_date="2025-03-28",
            report_date="2025-03-26", items="2.01,5.01", primary_doc="d.htm"),
        EdgarSubmission(accession="A1", form="8-K", filing_date="2025-01-26",
            report_date="2025-01-26", items="1.01", primary_doc="d.htm"),
    ]
    texts = {"C1": "right to receive $113.00 in cash",
             "A1": "for $999.00 in cash"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 113.00 and res.source == "8K_2.01"


def test_all_tiers_miss_returns_none():
    filings = [EdgarSubmission(
        accession="C1", form="8-K", filing_date="2025-03-28",
        report_date="2025-03-26", items="2.01", primary_doc="d.htm")]
    texts = {"C1": "the deal closed with no dollar figure stated here"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res == PayoutResult.none()
```

- [ ] **Step 2: Run them, confirm they fail**

Run: `pytest tests/test_payout_extractor.py -v`
Expected: tier tests FAIL (extract still returns `_NONE`).

- [ ] **Step 3: Implement the tier walk**

Replace the body of `extract` and add the helpers in
`src/delist_detection/payout_extractor.py`:

```python
_CLOSING_WINDOW = (timedelta(days=30), timedelta(days=30))     # (before, after) delist
_ANNOUNCE_WINDOW = (timedelta(days=365), timedelta(days=7))    # before delist


def _parse(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# (source label, confidence, form predicate, date-window predicate)
class PayoutExtractor:
    def __init__(self, edgar) -> None:
        self.edgar = edgar

    def extract(self, record: DelistRecord, last_close: float | None = None) -> PayoutResult:
        if record.bucket != CrspBucket.MERGER or record.cik is None:
            return _NONE
        filings = self.edgar.recent_filings(record.cik)
        if not filings:
            return _NONE
        delist = _parse(record.observed_delist_date or "")

        tiers = [
            ("8K_2.01", "high", self._tier1_closing(filings, delist)),
            ("8K_1.01", "medium", self._tier2_announcement(filings, delist)),
            ("DEFM14A", "medium", self._tier_form(filings, "DEFM14A", delist)),
            ("PRE14A", "low", self._tier_form(filings, "PREM14A", delist)),
        ]
        for source, conf, candidates in tiers:
            for f in candidates:
                text = self.edgar.fetch_filing_text(record.cik, f.accession, f.primary_doc)
                if not text:
                    continue
                val, quote = _match_payout(text, last_close)
                if val is not None:
                    return PayoutResult(val, conf, source, f.accession, quote[:160])
        return _NONE

    @staticmethod
    def _in_window(f: EdgarSubmission, delist: date | None,
                   before: timedelta, after: timedelta) -> bool:
        if delist is None:
            return True
        fd = _parse(f.report_date) or _parse(f.filing_date)
        if fd is None:
            return False
        return (delist - before) <= fd <= (delist + after)

    def _tier1_closing(self, filings, delist):
        before, after = _CLOSING_WINDOW
        out = [f for f in filings
               if f.form == "8-K" and "2.01" in f.item_set
               and self._in_window(f, delist, before, after)]
        out.sort(key=lambda f: abs(((_parse(f.report_date) or _parse(f.filing_date) or delist or date.min) - (delist or date.min)).days))
        return out

    def _tier2_announcement(self, filings, delist):
        before, after = _ANNOUNCE_WINDOW
        out = [f for f in filings
               if f.form == "8-K" and "1.01" in f.item_set
               and self._in_window(f, delist, before, after)]
        out.sort(key=lambda f: (_parse(f.report_date) or _parse(f.filing_date) or date.min), reverse=True)
        return out

    def _tier_form(self, filings, form, delist):
        out = [f for f in filings if f.form == form]
        if delist is not None:
            out = [f for f in out if (_parse(f.filing_date) or date.max) <= delist + timedelta(days=30)]
        out.sort(key=lambda f: (_parse(f.filing_date) or date.min), reverse=True)
        return out
```

Delete the old stub `__init__`/`extract` (the ones from Task 2/3) so only this
class definition remains — there must be exactly one `class PayoutExtractor`.

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `pytest tests/test_payout_extractor.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/payout_extractor.py tests/test_payout_extractor.py
git commit -m "feat: tiered EDGAR filing walk in PayoutExtractor.extract"
```

---

## Task 5: Export from package + golden fixtures

**Files:**
- Modify: `src/delist_detection/__init__.py`
- Create: `scripts/regen_payout_fixtures.py`
- Create: `tests/fixtures/altr_8k_201.txt`, `tests/fixtures/atvi_8k_201.txt`
- Create: `tests/test_payout_golden.py`

- [ ] **Step 1: Add exports**

In `src/delist_detection/__init__.py`, add after the `handling` import block:

```python
from .payout_extractor import PayoutExtractor, PayoutResult
```

And add `"PayoutExtractor"` and `"PayoutResult"` to `__all__`.

- [ ] **Step 2: Write the fixture regenerator**

Create `scripts/regen_payout_fixtures.py`:

```python
"""Regenerate golden payout fixtures from live SEC EDGAR. Not run in CI.

Run manually:  python scripts/regen_payout_fixtures.py
"""
from pathlib import Path

from delist_detection import EdgarClient

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"

CASES = [
    # (out_name, cik, accession, primary_doc)
    ("altr_8k_201.txt", 1701732, "0001193125-25-066329", "d869190d8k.htm"),
    ("atvi_8k_201.txt", 718877, "0001104659-23-108985", "tm2328253d1_8k.htm"),
]


def main() -> int:
    FIX.mkdir(parents=True, exist_ok=True)
    edgar = EdgarClient(cache_dir=ROOT / "cache" / "edgar")
    for name, cik, acc, doc in CASES:
        text = edgar.fetch_filing_text(cik, acc, doc)
        assert text, f"empty fetch for {name}"
        (FIX / name).write_text(text)
        print(f"wrote {name} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Generate the fixtures (network)**

Run: `python scripts/regen_payout_fixtures.py`
Expected output: `wrote altr_8k_201.txt (...)` and `wrote atvi_8k_201.txt (...)`.
Verify each contains the value:

Run: `grep -o '\$113.00 in cash' tests/fixtures/altr_8k_201.txt | head -1`
Expected: `$113.00 in cash`.
Run: `grep -o '\$95.00 in cash' tests/fixtures/atvi_8k_201.txt | head -1`
Expected: `$95.00 in cash`.

If the fetch fails (network/SEC), the golden test in Step 4 is the gate; do
not fabricate fixture content.

- [ ] **Step 4: Write the golden test**

Create `tests/test_payout_golden.py`:

```python
from pathlib import Path

import pytest

from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.edgar import EdgarSubmission
from delist_detection.payout_extractor import PayoutExtractor

FIX = Path(__file__).parent / "fixtures"


class _FixtureEdgar:
    def __init__(self, filing, text):
        self._filing = filing
        self._text = text
    def recent_filings(self, cik):
        return [self._filing]
    def fetch_filing_text(self, cik, accession, primary_doc):
        return self._text


def _golden(name, cik, accession, doc, observed):
    path = FIX / name
    if not path.exists():
        pytest.skip(f"fixture {name} not generated; run scripts/regen_payout_fixtures.py")
    filing = EdgarSubmission(
        accession=accession, form="8-K", filing_date=observed,
        report_date=observed, items="2.01,5.01,3.01", primary_doc=doc)
    rec = DelistRecord(ticker="T", cik=cik, observed_delist_date=observed,
                       crsp_code=231, bucket=CrspBucket.MERGER,
                       confidence="high", reason="", evidence={})
    ext = PayoutExtractor(_FixtureEdgar(filing, path.read_text()))
    return ext.extract(rec)


def test_golden_altr():
    res = _golden("altr_8k_201.txt", 1701732, "0001193125-25-066329",
                  "d869190d8k.htm", "2025-03-26")
    assert res.value == 113.00
    assert res.confidence == "high"
    assert res.source == "8K_2.01"


def test_golden_atvi():
    res = _golden("atvi_8k_201.txt", 718877, "0001104659-23-108985",
                  "tm2328253d1_8k.htm", "2023-10-13")
    assert res.value == 95.00
    assert res.confidence == "high"
```

- [ ] **Step 5: Run golden + full suite**

Run: `pytest tests/test_payout_golden.py -v`
Expected: PASS (both). If fixtures absent, they SKIP — regenerate first.
Run: `pytest -q`
Expected: all existing 62 tests + new tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/__init__.py scripts/regen_payout_fixtures.py \
        tests/fixtures/altr_8k_201.txt tests/fixtures/atvi_8k_201.txt \
        tests/test_payout_golden.py
git commit -m "feat: export PayoutExtractor + golden ALTR/ATVI fixtures"
```

---

## Task 6: Integrate into `classify_universe.py`

**Files:**
- Modify: `scripts/classify_universe.py`

Run extraction after classification, write `output/payouts.csv`, and add three
columns to the classifications CSV. Add a `--no-extract-payouts` flag.

- [ ] **Step 1: Add the CLI flag**

In `main()`, after the existing `p.add_argument("--quiet", ...)` line, add:

```python
    p.add_argument("--no-extract-payouts", action="store_true",
                   help="Skip per-share payout extraction (faster dev re-run)")
    p.add_argument("--payouts-output",
                   default=str(ROOT / "output" / "payouts.csv"))
```

- [ ] **Step 2: Import the extractor**

Add to the imports near the top (with the other `delist_detection` imports):

```python
from delist_detection.payout_extractor import PayoutExtractor
```

- [ ] **Step 3: Collect records during the write loop**

The current loop writes rows but discards `rec`. Add a list to retain merger
records. Just before `with out_path.open("w", newline="") as fh:` add:

```python
    extractor = None if args.no_extract_payouts else PayoutExtractor(edgar)
    payout_by_ticker: dict[str, "PayoutResult"] = {}
```

Inside the loop, immediately after the successful `rec = classifier.classify_ticker(...)`
block computes `rec` (i.e. after the `ev = rec.evidence or {}` line, before the
`writer.writerow([...])` call), add:

```python
            if extractor is not None and rec.bucket == CrspBucket.MERGER:
                try:
                    payout_by_ticker[rec.ticker] = extractor.extract(rec)
                except Exception as e:  # extraction must never abort the run
                    if not args.quiet:
                        print(f"[{i:4d}/{len(rows)}] {ticker}: payout ERROR {e}",
                              file=sys.stderr)
```

- [ ] **Step 4: Add the three payout columns to the classifications CSV**

Change the header `writer.writerow([...])` to append three columns at the end:

```python
        writer.writerow([
            "ticker", "cik", "observed_delist_date", "crsp_code", "bucket",
            "confidence", "reason", "delist_filing_form", "delist_filing_date",
            "anchor_8k_items", "dereg_form", "resolved_name", "resolution_source",
            "payout_per_share", "payout_source", "payout_confidence",
        ])
```

And change the per-row `writer.writerow([...])` (the success path) to append:

```python
                ev.get("name", ""),
                ev.get("resolution_source", ""),
                (lambda pr: "" if pr is None or pr.value is None else f"{pr.value:.2f}")(payout_by_ticker.get(rec.ticker)),
                (lambda pr: "" if pr is None else pr.source)(payout_by_ticker.get(rec.ticker)),
                (lambda pr: "" if pr is None else pr.confidence)(payout_by_ticker.get(rec.ticker)),
            ])
```

Also extend the ERROR-path `writer.writerow([...])` (in the `except` block) with
three trailing empty strings so column counts match:

```python
                writer.writerow([ticker, "", observed, "", "unknown", "none",
                                 err, "", "", "", "", "", "", "", "", ""])
```

- [ ] **Step 5: Write `output/payouts.csv` after the loop**

After the classification `with` block closes (after the `elapsed = time.time() - t0`
summary print, before `return 0`), add:

```python
    if extractor is not None:
        payouts_path = Path(args.payouts_output)
        payouts_path.parent.mkdir(parents=True, exist_ok=True)
        with payouts_path.open("w", newline="") as pf:
            pw = csv.writer(pf)
            pw.writerow(["ticker", "payout_per_share", "confidence", "source", "accession"])
            for tkr, pr in sorted(payout_by_ticker.items()):
                pw.writerow([
                    tkr,
                    "" if pr.value is None else f"{pr.value:.2f}",
                    pr.confidence, pr.source, pr.accession,
                ])
        n_hit = sum(1 for pr in payout_by_ticker.values() if pr.value is not None)
        print(f"Wrote {payouts_path}: {n_hit}/{len(payout_by_ticker)} merger payouts extracted")
```

- [ ] **Step 6: Smoke-test on a tiny limit (network)**

Run: `python scripts/classify_universe.py --limit 5 --output /tmp/cls_smoke.csv --payouts-output /tmp/payouts_smoke.csv`
Expected: completes; prints a "Wrote .../payouts_smoke.csv: N/M merger payouts extracted" line; both files exist and have the new columns. (N may be 0 if none of the first 5 are mergers — that's fine; the point is no crash and correct headers.)

Run: `head -1 /tmp/cls_smoke.csv`
Expected: header ends with `...,payout_per_share,payout_source,payout_confidence`.

- [ ] **Step 7: Commit**

```bash
git add scripts/classify_universe.py
git commit -m "feat: extract payouts in classify_universe; write payouts.csv + cols"
```

---

## Task 7: Full run + web verification

**Files:**
- Create: `output/payouts.csv` (generated artifact)
- Modify: `output/delist_classifications.csv` (regenerated with new columns)

This task realizes the spec's §8 verification loop (per the autonomous-mode
preference for this project). It is run-and-verify, not code; track findings as
follow-up tasks.

- [ ] **Step 1: Full run over the universe**

Run: `python scripts/classify_universe.py`
Expected: completes with cached EDGAR JSON (text fetches are new, so this will
do up to ~4 network fetches per merger ticker on the first run; subsequent runs
are free). Prints "Wrote output/payouts.csv: N/346 merger payouts extracted".

- [ ] **Step 2: Coverage report**

Run:
```bash
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("output/payouts.csv")))
n = len(rows)
hit = [r for r in rows if r["payout_per_share"]]
from collections import Counter
print(f"merger tickers: {n}")
print(f"payout extracted: {len(hit)} ({len(hit)/n:.1%})")
print("by confidence:", Counter(r["confidence"] for r in hit))
print("by source:", Counter(r["source"] for r in hit))
PY
```
Expected: target ≥95% non-none, ≥90% high-confidence. Record actuals.

- [ ] **Step 2b: If below target, drill and fix**

For misses, inspect the candidate filings. Common causes and fixes:
- Wrong phrasing not covered by `_PATTERNS` → add a pattern (re-run Task 3 tests first).
- Tier-1 closing 8-K outside the ±30d window → widen `_CLOSING_WINDOW`.
- Mixed/stock deal → correctly a miss (neutral-mark); leave as-is.
Re-run from Step 1 after each fix. Keep `_match_payout` unit tests green.

- [ ] **Step 3: Independent web verification of a sample**

Pick 15 high-confidence + all medium/low rows. For each, fetch the cited
accession and confirm the value appears, using the project UA (WebFetch is
403'd by SEC):

```bash
curl -s -A "delist_detection/0.1 (royelee@users.noreply.github.com)" \
  "https://www.sec.gov/Archives/edgar/data/<CIK>/<ACC_NODASH>/<DOC>" \
  | grep -o '\$[0-9,]*\.[0-9][0-9] in cash' | head
```

Cross-check the grepped value against `payouts.csv`. Categorize any mismatch
and fix root cause (regex / tier / sanity band), then re-run.

- [ ] **Step 4: Commit the regenerated artifacts**

```bash
git add output/payouts.csv output/delist_classifications.csv
git commit -m "data: regenerate classifications with auto-extracted payouts"
```

- [ ] **Step 5: Update README**

In `README.md`, update the M&A/payout sections to note payouts are now
auto-extracted by `classify_universe.py` into `output/payouts.csv`, and that
`compute_corrected_returns.py --payouts output/payouts.csv` consumes it. Add a
row to the project-layout listing for `payout_extractor.py`. Commit:

```bash
git add README.md
git commit -m "docs: document auto payout extraction in README"
```

---

## Self-Review

**Spec coverage:**
- §4.1 PayoutResult/PayoutExtractor → Tasks 2, 4. ✓
- §4.2 fetch_filing_text → Task 1. ✓
- §4.3 tier table (8K_2.01/8K_1.01/DEFM14A/PRE14A + confidences + windows) → Task 4. ✓
- §4.4 regex (in-cash + per-share families, `(?!\d)` guard, modal selection) → Task 3. ✓
- §4.5 sanity filter (absolute + relative bands) → Task 3 `_passes_sanity`. ✓
- §4.6 integration (payouts.csv + 3 cols + atomic-ish writes + --no-extract flag) → Task 6. ✓
- §7 testing (12 unit + 2 golden) → Tasks 2/3/4 (unit), Task 5 (golden). ✓
- §8 web verification → Task 7. ✓
- §9 exports → Task 5. ✓
- §10 CLI `--no-extract-payouts` → Task 6. ✓

**Placeholder scan:** No TBD/TODO; all code shown in full. ✓

**Type consistency:** `PayoutResult(value, confidence, source, accession, quote)` used identically across Tasks 2/4/5/6. `_match_payout(text, last_close) -> (float|None, str)` and `_passes_sanity(value, last_close) -> bool` consistent across Tasks 3/4. `fetch_filing_text(cik, accession, primary_doc) -> str` consistent across Tasks 1/4/5. Source label `"PRE14A"` (not `"PREM14A"`) used for the PREM14A form in both spec §4.1 and Task 4. ✓

**Note on §4.6 "atomic writes":** the spec mentions write-to-tmp-then-rename. The plan writes directly (matching the existing script's pattern, which already writes `output/delist_classifications.csv` directly with `fh.flush()`). Atomic-rename is deferred as a non-blocking nicety to avoid diverging from the established script idiom; documented here rather than silently dropped.
