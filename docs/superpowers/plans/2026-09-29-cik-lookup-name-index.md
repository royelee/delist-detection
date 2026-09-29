# Plan: resolve issuer names from SEC's `cik-lookup-data.txt`, not the live company search

Branch `feat/handoff-successor-links` (on top of the handoff plan). Written 2026-09-29.

## Context

The ticker resolver's name-search tier (tier 5 of 6, `TickerResolver._name_search`) asks SEC's live company
search, `cgi-bin/browse-edgar?action=getcompany&company=<name>&type=<form>`, to turn an observed company name into
an issuer CIK. It runs for every era the pin, the manual overrides, `company_tickers.json` and the Form 25/15
full-text search leave unresolved. In a delisting universe that is most historical eras.

- It is expensive. Each era searches up to 6 spellings of its name (`_name_variants`) and up to 4 form filters
  per spelling (`25-NSE`, `25`, `15-12G`, none): more than 20 requests for one era. The answers are trusted for
  only 7 days (`COMPANY_SEARCH_FRESH_DAYS`), so a rerun a week later asks again.
- It is the endpoint SEC throttles. The project notes already measured it at 89% of cold issuer-resolution time,
  and it can slow to about 10 s per request.
- The 2026-09-28 full run was refused three times with HTTP 429 on this endpoint, at 8, 2 and 1 workers
  (`docs/2026-09-28-handoff-validation.md`).

SEC publishes the same name index as one file, `https://www.sec.gov/Archives/edgar/cik-lookup-data.txt`: about
38 MB, about 1.06 million `NAME:CIK:` lines. It is historically cumulative: a CIK appears under every name it
filed under (`MICHAEL KORS HOLDINGS LTD:0001530721:` and `CAPRI HOLDINGS LTD:0001530721:`; `JACOBS ENGINEERING
GROUP INC /DE/` and `JACOBS SOLUTIONS INC.` for 52988). It also lists funds, individuals and entities that no
longer file.

## Outcome

- One download of that file, cached and refreshed after 30 days, replaces the live company search in production.
- `_name_search` finds its candidates in a local index built from the file. Everything after it is unchanged:
  the ranking by EDGAR name fit, and the existed-by, Form 25 and observed-name checks, which read the cached
  submissions JSON from `data.sec.gov`.
- A resolver built without an index (the offline tests, the golden replay) keeps the live search, so the
  recorded golden answers still replay.
- A full cold run no longer sends `company_search` requests (`run_manifest.json`'s `sec_requests` shows none).

## What the file does not give, and how the design covers it

| The live search gives | The file does not | Covered by |
|---|---|---|
| Filing dates, used to rank candidates by closeness to the date | No dates at all | The submissions checks that already follow (`_existed_by`, `_fits_date`, `_validate_cik`, the observed-name check); the date penalty becomes the "unknown" 1000 the live path already uses for an undated hit |
| A form filter (`type=25-NSE` and so on) that hides most funds and individuals | Every filer | A local pre-rank by the words a name shares with the observed name, a cap of `NAME_SEARCH_CANDIDATES` (5) CIKs, and the same checks |
| One named company per query (a query matching several comes back unnamed and is dropped) | Every match | Exact name matches first, then prefix matches ranked by shared words; the existing rule keeps a candidate below the first only when its EDGAR names agree with the observed name |

## Design

### `cik_lookup.py` (new)

- `normalize_name(name)`:
  - uppercase;
  - `&` and punctuation (`. , ' ’ " ( )`) become spaces;
  - EDGAR's trailing state tag (`/DE/`, `/PA`) is dropped;
  - runs of whitespace collapse to one space.
- `CikNameIndex` over `(normalized name, CIK, name)` entries, sorted by normalized name.
  - `from_text(text)` parses `NAME:CIK:` lines (`rsplit(":", 2)`, so a colon inside a name survives) and skips
    blank or unparseable lines.
  - `search(query)`: the entries whose normalized name equals the query's, or starts with it followed by a space.
    This is EDGAR's prefix match on word boundaries: "MERRILL LYNCH" finds "MERRILL LYNCH & CO INC", "BARNES"
    does not find "BARNESANDNOBLE COM".
  - Answers come from a binary search over the sorted names.
- `CikLookupClient(cache_dir).index()` fetches the file through `sec_http.get_text`: the same throttle,
  User-Agent, retries and `EdgarBlocked`. The copy is cached as `cache_dir/cik-lookup-data.txt` and fetched again
  once it is `CIK_LOOKUP_MAX_AGE_DAYS` (30) old. A failed refetch serves the old copy as a degraded answer. The
  index is built once per client, on first use.

### Resolver (`ticker_resolver.py`)

- `TickerResolver(..., name_index=None)`: a `CikNameIndex`, or a callable returning one, loaded lazily.
- `_name_search` with an index:
  - For each spelling of the name (`_name_variants`, unchanged), take its exact matches, then its prefix
    matches.
  - Rank each group by the `name_tokens` words the entry's name shares with the whole observed name (most
    first), then by the shorter name, then by CIK.
  - Add CIKs in that order until `NAME_SEARCH_CANDIDATES` distinct CIKs are found. Each keeps the index name it
    was found under, and a date penalty of 1000.
  - Ranking by EDGAR name fit and the "agrees" rule for candidates below the first are unchanged.
- Without an index, the live search runs exactly as today.
- The shadow resolvers of the warm pass share the index read-only.
- An index that cannot be loaded (`requests.RequestException`, with no cached copy) is logged, and the run falls
  back to the live search. A refusal (`EdgarBlocked`) still stops the run.

### Wiring

- `pipeline.default_clients` gives the resolver a lazy `CikLookupClient(cache_dir / "sec_data" / "cik_lookup")`.
- The download goes through `sec_http.get_text`, so `run_manifest.json` counts it under `sec_data` like the other
  SEC data files. (Planned as its own `cik_lookup` endpoint; dropped as unneeded, since a run sends at most one.)

## Tasks

Test first; keep the offline suite green; one commit per task.

- **Task 1 — `normalize_name` and `CikNameIndex`.** Tests on a small committed excerpt of the real file
  (`tests/fixtures/cik_lookup/excerpt.txt`), covering:
  - exact beats prefix;
  - prefix only on a word boundary;
  - state tags and punctuation are ignored;
  - a former name finds the current CIK (Michael Kors, Capri);
  - a line with a colon in the name;
  - blank lines.
- **Task 2 — `CikLookupClient`.** Tests with a fake session:
  - the first call downloads and caches;
  - a later call within 30 days reads the cache and sends no request;
  - an older copy is fetched again;
  - a failed refetch serves the old copy, counted as degraded;
  - a 429 raises `EdgarBlocked`.
- **Task 3 — the resolver's index path.** Tests:
  - the name tier resolves through the index and sends no company search;
  - the candidate order and the cap of 5;
  - a fund sharing a name prefix loses to the company whose Form 25 fits;
  - without an index, the live search is used unchanged;
  - an index that cannot load falls back to the live search.
- **Task 4 — wiring.** `default_clients`, CLAUDE.md, the
  `docs/data-flow.md` resolver section, and the measured-speed note.
- **Task 5 — live check.** Resolve the case-ticker eras and a sample of the full universe's eras twice, with the
  live search and with the index. Compare the CIKs and explain every difference. Then rerun
  `classify_universe.py` on `data/observations.csv` (as_of 2026-09-25) with the index. If it completes, finish the
  handoff plan's Task 8 checks on the full output and record them in the validation note.

## Rules found by the full runs (2026-09-29)

The first index version answered differently from the live search in ways only the full universe showed. Each fix
was checked by replaying the 698 cached name-tier answers offline, then by a full run with the LLM merger terms
(`docs/2026-09-28-handoff-validation.md`).

| Case | Wrong answer | Rule now |
|---|---|---|
| WEATHERFORD INTL, NIELSEN N.V. | a fund or an individual (WEATHERFORD YVONNE); a missed match | the live search's form filter emulated from submissions JSON; periods dropped |
| NORTHEAST UTILITIES (NU) | Northeast Bancorp, through the spelling NORTHEAST | a spelling matching more than 10 CIKs reads nothing unless it keeps every word of the name |
| MEDCO HEALTH SOLUTIONS (MHS) | none: 17 matches, most of them its subsidiaries | such a spelling reads the top 10 entries carrying every word |
| WACHOVIA CORP (WB) | 104019, the pre-2001 Wachovia, which holds the exact name | the exact name wins before the form filter only while its holder still files (within a year) |
| FIRST REPUBLIC BANK (FRC) | Republic First Bancorp, FIRST REPUBLIC BANCORP in 1996-97, the shortened spelling's only Form 25 filer | the exact-name holder that still files wins; a lone filer counts only with a name carried in the 5 years before the date |
| TCF FINANCIAL CORP, GANNETT CO INC (2012-14) | none: two or three CIKs took the name at different times | the one that carried the name by the date |
| DIVERSIFIED HEALTHCARE TRUST (2014) | none: a 2020 name carried back by a snapshot | a lone active exact-name holder is not vetoed by the date |
| ANHEUSER BUSCH COS INC (BUD) | the brewery subsidiary; then none | hyphens read as spaces, COMPANIES a filler like COS; of several filers, the one with exactly the name's words |
| MOTOROLA INC, AMB PROPERTY CORP | Motorola Mobility; the operating partnership | of several filers, the exact name; an exact-name answer's date gap counts from its nearest filing, not 1000 |
| ALBERTO CULVER CO (ACV, 2010) | 3327, the old company renamed in 2006 | of several named filers, the one carrying the name on the date (the 2006 spin-off) |
| CHICAGO MERCANTILE HLDGS (CME) | the exchange subsidiary | a name carried a few years before counts: the snapshot lags CME Group's 2007 rename |
| APTIV PLC (2012-13) | Aptiv Solutions, another company | the date decides only among filers the query names |
| S&P GLOBAL INC (MHFI) | an S&P fund trust, through the spelling S P | as NORTHEAST |
