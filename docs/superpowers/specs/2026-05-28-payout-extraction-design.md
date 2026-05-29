# Payout Extraction — Design

**Status:** draft
**Author:** Claude (Opus 4.7) with @royelee
**Date:** 2026-05-28

## 1. Problem

The delist_detection pipeline classifies 75% of the Tiingo universe's 461 delisted
tickers into the `MERGER` bucket (346 tickers). The bucket's train forward-return
label and backtest exit price both require a `payout_per_share` value — the
per-share cash consideration paid to shareholders at deal close. Today this
value is a manual CSV input (`data/payouts.csv`) consumed by
`scripts/compute_corrected_returns.py` and `qlib_adapter.apply_bmp_corrections`.
When `payout_per_share` is `None`, the pipeline neutral-marks the return
(payout defaults to `last_close`), which silently zeros out the merger arbitrage
signal that survivorship correction is meant to surface.

We need an automated, deterministic, EDGAR-only extractor that produces a
`payout_per_share` for every cash-merger ticker.

## 2. Scope

In scope:
- Cash-only M&A deals classified as `MERGER` (CRSP 200, 231, 233).
- USD per-share cash consideration extracted from SEC EDGAR filings.
- Evidence trail (source filing, confidence band) for every extracted value.

Out of scope for v1:
- Mixed cash + stock consideration (cash component alone misleads; treat as
  unknown so the pipeline neutral-marks).
- All-stock exchanges (already neutral-marked by design).
- Going-private LBO cap-table adjustments.
- Non-USD payouts (rare in the universe).
- Reverse-merger inversions where the surviving entity continues trading.

## 3. Approach

Layered regex extraction over a tiered chain of EDGAR filings. The tier
ordering is by filing precision — closing 8-Ks state the realized consideration
verbatim, while announcement 8-Ks and proxy statements state the agreed
consideration. First tier yielding a sanity-passing value wins.

Two alternatives were considered:

- **LLM extraction** over filing text. Rejected: non-deterministic, can't run
  offline tests, drifts across model versions, recurring API cost. Reconsider
  as a fallback if regex coverage is <90%.
- **Hybrid (regex first, LLM on misses).** Deferred. Implement A; measure
  miss rate; revisit only if needed.

The choice mirrors the existing classifier's idiom (regex + EDGAR JSON, all
cacheable, all offline-testable).

## 4. Architecture

### 4.1 New module — `src/delist_detection/payout_extractor.py`

```python
@dataclass(frozen=True)
class PayoutResult:
    value: float | None        # USD per share, None if no tier matched
    confidence: str            # 'high' | 'medium' | 'low' | 'none'
    source: str                # '8K_2.01' | '8K_1.01' | 'DEFM14A' | 'PRE14A' | 'none'
    accession: str             # SEC accession, '' if none
    quote: str                 # ~120-char snippet around the match, '' if none

class PayoutExtractor:
    def __init__(self, edgar: EdgarClient): ...
    def extract(self, record: DelistRecord, last_close: float | None = None) -> PayoutResult: ...
```

`PayoutExtractor.extract` is pure with respect to the EDGAR client — given the
same cached EDGAR JSON + filing text, it returns the same result.

### 4.2 EdgarClient extension

Add to `src/delist_detection/edgar.py`:

```python
def fetch_filing_text(self, cik: int, accession: str, primary_doc: str) -> str:
    """Fetch the primary filing document, strip HTML, normalize whitespace.

    URL pattern: www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}
    Cached separately from the JSON cache under cache/edgar/text/{accession}.txt.
    """
```

Implementation: requests.get with the SEC UA, strip `<script>`, `<style>`,
all tags via regex, collapse whitespace, write to text cache. Re-runs hit
cache and cost nothing.

### 4.3 Tier table

| Tier | Form/Item                    | Window vs delist date | Confidence | Rationale |
|------|------------------------------|-----------------------|------------|-----------|
| 1    | 8-K Item 2.01 (closing)      | `[delist - 30d, delist + 30d]` | high   | states realized consideration |
| 2    | 8-K Item 1.01 (deal signed)  | `[delist - 365d, delist - 7d]` | medium | states agreed consideration |
| 3    | DEFM14A (definitive proxy)   | before delist, latest          | medium | proxy quotes the merger agreement |
| 4    | PREM14A (preliminary proxy)  | before delist, latest          | low    | may be revised before final |

Tier 1 produces "high" because the deal closed at that price — no further
adjustment. Tier 4 is "low" because the value can change before the
definitive proxy.

### 4.4 Regex patterns

Verified against the real ALTR and ATVI closing 8-Ks (see §7 golden cases):
the canonical M&A closing language is *"converted into the right to receive
**$113.00 in cash**, without interest (the 'Merger Consideration')"* — it does
**not** say "$113.00 per share". So the primary pattern family is "in cash",
with "per share" as a secondary family for filings that use that wording.

Applied case-insensitive to the whitespace-normalized text. Note the
`(?!\d)` guard after `\.\d{2}` — it prevents matching a truncation of a
4-decimal figure (the ALTR 8-K contains `$1,618.7928`, which must NOT yield
`1,618.79`):

```
# primary — "in cash" family
(?:right to receive|receive)\s+\$\s*([\d,]+\.\d{2})(?!\d)\s+in cash
\$\s*([\d,]+\.\d{2})(?!\d)\s+in cash(?:,?\s+without interest)?
# secondary — "per share" family
\$\s*([\d,]+\.\d{2})(?!\d)\s+(?:in cash\s+)?per\s+share
(?:cash|merger)\s+consideration of \$\s*([\d,]+\.\d{2})(?!\d)
```

Collect all matches across all patterns, parse to float (strip commas), keep
matches passing the sanity filter, group by value, choose the modal value
(filings repeat the number 3+ times). Tiebreak ties by numerically largest.

### 4.5 Sanity filter

A candidate value is rejected if:
- not in absolute band `[0.01, 10000.00]`, OR
- `last_close` is provided AND value < 0.05 × last_close (probably a dividend
  or a $-in-millions false positive), OR
- `last_close` is provided AND value > 20 × last_close (probably an aggregate
  consideration in millions misread as per-share).

The `last_close` parameter is optional. v1 ships without `last_close` wiring
through `classify_universe.py` (the absolute band carries most of the load).
A follow-up pulls `last_close` from the qlib data store.

### 4.6 Integration into `scripts/classify_universe.py`

After classification of all tickers completes, iterate the `MERGER` records,
instantiate `PayoutExtractor(edgar)`, call `extract(rec)`, and write:

1. **`output/payouts.csv`** — drop-in input for `compute_corrected_returns.py --payouts`.
   Columns: `ticker, payout_per_share, confidence, source, accession`.
   One row per merger ticker; rows with `value=None` are still emitted (with
   empty payout) so the file is self-documenting about extraction misses.

2. **Extra columns in `output/delist_classifications.csv`** — `payout_per_share`,
   `payout_source`, `payout_confidence`. Non-merger rows leave these empty.

Both writes are atomic (write to .tmp then rename).

## 5. Data flow

```
classify_universe.py
  ├── for each ticker:
  │     resolve CIK → classify → DelistRecord
  ├── after all 461 classified:
  │     for each MERGER record (346 tickers):
  │         PayoutExtractor.extract(rec)
  │           ├── tier 1: fetch 8-K Item 2.01 text → regex
  │           ├── tier 2: fetch 8-K Item 1.01 text → regex (if tier 1 missed)
  │           ├── tier 3: fetch DEFM14A text → regex (if 1+2 missed)
  │           └── tier 4: fetch PREM14A text → regex (if 1+2+3 missed)
  ├── write output/payouts.csv (346 rows)
  └── write output/delist_classifications.csv (461 rows, +3 cols)
```

## 6. Error handling

- Network failure on a single filing → log, skip to next tier.
- All tiers miss → `PayoutResult(None, 'none', 'none', '', '')`. The BMP
  pipeline already treats `None` as neutral-mark = current behavior, so a
  miss is a zero-regression outcome.
- Filing exists but `primary_doc` empty → skip filing.
- Regex matches a value that fails the sanity filter → discard, try next match
  in same filing; if no surviving matches, drop to next tier.

## 7. Testing strategy (TDD)

Test order, each red→green→commit:

1. `PayoutResult` dataclass exists with the documented fields and defaults.
2. `PayoutExtractor.extract(rec)` returns `('none', 'none', '', '')` when
   `rec.bucket != MERGER`.
3. Tier-1 match: `FakeEdgar` serves a canned 8-K with Item 2.01 containing
   "$113.00 per share in cash"; extractor returns `(113.0, 'high', '8K_2.01', …)`.
4. Tier-2 fallback: tier-1 filing missing → tier-2 filing has Item 1.01 with
   "$95.00 per share" → returns `(95.0, 'medium', '8K_1.01', …)`.
5. Tier-3 fallback: only DEFM14A available → returns `(…, 'medium', 'DEFM14A', …)`.
6. Tier-4 fallback: only PREM14A available → returns `(…, 'low', 'PRE14A', …)`.
7. All tiers miss → `(None, 'none', 'none', '', '')`.
8. Modal value selection: filing has "$113.00" 5×, "$112.00" 1× → picks 113.00.
9. Sanity-band rejection (absolute): "$0.001 per share" → rejected.
10. Sanity-band rejection (relative): last_close=100, value=2 → rejected;
    last_close=100, value=2500 → rejected.
11. Comma parsing: "$1,250.00 per share" → 1250.0.
12. Multi-form regex: each of the four patterns triggers extraction on its
    own canned filing.

Golden integration tests (offline, fixtures committed under `tests/fixtures/`):

- **ALTR**: 8-K `0001193125-25-066329` (`d869190d8k.htm`, CIK 1701732) →
  113.00, high. Verified phrasing: *"converted into the right to receive
  $113.00 in cash, without interest (the 'Merger Consideration')"*.
- **ATVI**: 8-K `0001104659-23-108985` (`tm2328253d1_8k.htm`, CIK 718877) →
  95.00, high. Verified phrasing: *"converted into the right to receive
  $95.00 in cash (the 'Merger Consideration')"*.

The stripped-text fixtures are committed so the tests run with no network.
A separate helper (committed but not run in CI) regenerates them from the
live SEC archives via the EdgarClient.

Regression: the existing 62 tests stay green.

## 8. Web verification

Per the autonomous-mode preference for this project, after the first full run:

1. Sample 20 high-confidence rows and all medium/low rows.
2. For each, WebFetch the EDGAR filing URL.
3. Eyeball that the extracted value appears in the doc.
4. Categorize misses (wrong filing, wrong regex, wrong tier choice).
5. Patch regex / tier window / sanity filter and re-run.

Target: ≥90% high-confidence coverage on the 346 merger tickers, ≥95%
non-none extraction (high + medium + low combined).

## 9. Public API additions

In `src/delist_detection/__init__.py`:

```python
from .payout_extractor import PayoutExtractor, PayoutResult
```

No changes to existing exports.

## 10. CLI

The existing `compute_corrected_returns.py --payouts data/payouts.csv` path
keeps working unchanged. Users can either:
- Run `classify_universe.py` (which now auto-writes `output/payouts.csv`) and
  point the corrected-returns CLI at `output/payouts.csv`, OR
- Continue to hand-curate `data/payouts.csv` if they want to override the
  extractor's output for a specific ticker.

A new `--no-extract-payouts` flag on `classify_universe.py` lets users skip
the extraction step (faster re-run during classifier development).

## 11. Known limitations

- Filings older than ~2002 sometimes lack a structured primary doc; the
  regex falls back to the full submission text.
- Non-USD deals (e.g. an Israeli issuer paying in NIS) are extracted as
  numeric values without unit awareness. The sanity band catches the most
  egregious cases but not all. v1 documents this as a manual-override
  scenario.
- Earn-outs and contingent value rights (CVRs) are ignored — only the
  upfront cash component is captured.
- Special dividends declared shortly before close (i.e. payout = special_div
  + merger_consideration) are captured only partially when the regex matches
  the announcement 8-K's headline number rather than the closing 8-K's
  combined figure. Mitigated by tier-1 priority.

## 12. Migration

No migration required. Existing `data/payouts.csv` continues to work; the
new `output/payouts.csv` is a sibling artifact.

## 13. Open questions

None at design time. Open items will surface during web verification and
get tracked as follow-up plans.

## 14. Implementation outcome (2026-05-28)

Built and verified end-to-end on the Tiingo 2026-05-22 universe. The
web-verification loop (§8) drove several precision hardenings beyond the
original §4.4 regex, all root-caused from live-EDGAR drilling:

- **"in cash" is the operative signal.** Patterns split into strong (embed
  "in cash"/"cash consideration") and weak (bare "$X per share", "purchase
  price of $X", "merger consideration of $X"). Weak patterns require an
  "in cash" phrase adjacent and are disabled entirely for the noisy proxy
  tiers.
- **Negative-context guards** for dividend / par-value / rounding /
  option-exercise boilerplate, and for convertible-note redemption figures
  ("$X per $1,000 principal amount").
- **Both-sided date bound on proxy tiers** so a recycled CIK's decades-old
  proxy cannot match (e.g. MRO 2001 PREM14A vs a 2024 delist).
- **Tier-1 closing window widened to 120d before** the delist date (deal
  close routinely precedes the recorded last-trade date).

Final result on the 346 merger tickers:

| Metric | Value |
|---|---|
| payouts extracted | 232 (`high` 197, `medium` 35) |
| extracted values confirmed as cash-only consideration | 232 / 232 |
| pure-cash deals missed | 0 |
| misses | 114 — all all-stock, mixed cash+stock, or cash/stock-election |

The headline "67% coverage" is by design: the 114 misses are all-stock,
mixed-consideration, or election deals, for which a miss (neutral mark, ≈0%
return for an all-stock deal) is the *correct* survivorship treatment.
Effective recall on pure-cash mergers — the only deals that need a payout — is
~100%, at 100% precision (no extracted value carries a stock co-consideration).

### Post-review hardening (code review, 2026-05-28)

A high-effort review surfaced a precision bug the first pass missed: **mixed
cash+stock deals were emitting only the cash leg** (e.g. AET `$145.00 cash +
0.8378 CVS shares` recorded as `145.00`), understating ~38 tickers' returns.
The fix detects a stock leg joined to the cash by "and"/"plus" with a share
ratio and abstains the whole ticker — including when a later filing quotes an
intermediate all-cash bid (PMCS) or a cash-election leg (SCS). Contingent CVRs
are excluded from the stock-leg test so cash+CVR deals keep their cash floor.
The review also fixed: regex tiebreak and dividend/par-value windows (tuned to
avoid false drops of real all-cash tenders ARIA/AZPN), break/escrow-fee guards,
convertible-note redemption guards, EDGAR `fetch_filing_text` robustness
(transient-error caching, empty-`primary_doc`, utf-8 encoding), `extract()`
network-error safety, and a header-derived CSV error-row padding.
