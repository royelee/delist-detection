# Reset-4f (first step): OTC Prints Requested and Valued — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ask the caller's price store for the first off-exchange print after each drop or distress ending
(`price_requests.csv`, kind `otc_print`), and value the ending from the answer: DLRET = print / last close − 1,
method `otc_print`, a measured value instead of a Shumway fill.

**Architecture:** `dlret.resolve_dlret` takes an `otc_print`; `reconstruction` carries an `otc_prints` map to it;
`price_requests.request_rows` writes the requests; `pipeline._apply_price_answers` turns `otc_print` answers into
`Overrides.otc_prints`; `exit_kind.MEASURED_METHODS` counts the method as a value. With no answers file the only
output change is the new request rows.

**Tech Stack:** Python ≥3.10, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md`, decision 11 ("A move to OTC is an ending with a
value. CRSP 520: the first off-exchange print within 10 trading days") and "What crosses the boundary"
(`price_requests.csv`: kind = last_close | received_close | otc_print; "OTC prints from the raw vendor files, volume
above zero, within 10 sessions, stopping before any emergence or new-CUSIP date"). Decision 3: harsh marks stay
for rows that still carry a fill. Roadmap: "reset-4f: Values of drops to OTC".

## Global Constraints

- Decisions 3 and 11 adopted (overnight rulings 2026-10-02).
- An `otc_print` request is written for every contract ending whose `exit_kind` is `dropped` or `liquidation`, that
  is not a continuation and has a published `last_trade_date`. Its `date` is the trading day after the last trade
  (the window's first session); `lookup_sec_id` is the ending's own `sec_id`, `lookup_ticker` its ticker. The 10
  sessions and the volume rule are the caller's (spec), not the library's.
- An `otc_print` answer values only the `liquidation` and `compliance_failure` buckets. A `--recoveries` ratio given
  for a liquidation wins over it (a caller's payment record beats a print).
- Without `--price-answers`, every table except `contract/price_requests.csv` stays byte-identical.
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Which endings ask.** Today's output has no CRSP-520 ending (the end-of-era resolver's OTC branch is not built),
   so the requests go to every drop and distress ending, as the spec's measurement did ("37 of 175 drops and
   distress endings with a usable print"). A distress ending that trades OTC after its delisting is valued by that
   price, which is what the Shumway mark approximates.
2. **Event-level API unchanged.** `handling.py` keeps its own recovery convention; this plan changes the
   firm-month DLRET (`delistings.csv` `dlret`) and the contract only.
3. **Permitted floor changes.** None expected: the acceptance runs without answers. Any scorecard change stops it.

## Review Focus

1. An `otc_print` answer for a merger ending changes nothing (Task 1 test).
2. A liquidation with both a `--recoveries` ratio and an OTC print takes the ratio (Task 1 test).
3. A continuation and an ending with no published date ask for no print (Task 2 test).

---

### Task 1: Value an ending from its OTC print

**Files:** Modify `src/delist_detection/dlret.py`, `src/delist_detection/reconstruction.py`,
`src/delist_detection/exit_kind.py`; Test `tests/test_dlret.py` (or the file that tests `resolve_dlret`; grep
`resolve_dlret(` in tests/), `tests/test_reconstruction.py`.

**Interfaces:** Produces `DlretMethod.OTC_PRINT = "otc_print"`; `resolve_dlret(..., otc_print: float | None = None)`;
`enrich(..., otc_print=None)`; `build_delistings_table(..., otc_prints: Mapping | None = None)`.

- [ ] **Step 1: Write the failing tests.**

```python
from delist_detection.crsp_codes import CrspBucket
from delist_detection.dlret import DlretMethod, resolve_dlret
from delist_detection.exchanges import Exchange


def test_an_otc_print_values_a_drop():
    r = resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.NASDAQ, 2.00, otc_print=0.50)
    assert (round(r.value, 6), r.method, r.terminal_value) == (-0.75, DlretMethod.OTC_PRINT, 0.50)
    r = resolve_dlret(CrspBucket.LIQUIDATION, Exchange.NYSE, 4.00, otc_print=1.00)
    assert (round(r.value, 6), r.method) == (-0.75, DlretMethod.OTC_PRINT)


def test_a_recovery_ratio_beats_an_otc_print_and_a_merger_ignores_it():
    r = resolve_dlret(CrspBucket.LIQUIDATION, Exchange.NYSE, 4.00, recovery_ratio=0.5, otc_print=1.00)
    assert r.method is DlretMethod.RECOVERY_RATIO
    m = resolve_dlret(CrspBucket.MERGER, Exchange.NYSE, 10.0, payout_per_share=12.0, otc_print=1.00)
    assert m.method is DlretMethod.CASH_ONLY


def test_without_a_print_a_drop_keeps_its_mark():
    r = resolve_dlret(CrspBucket.COMPLIANCE_FAILURE, Exchange.NASDAQ, 2.00)
    assert r.method is DlretMethod.SHUMWAY_NASDAQ
```

  (Use the `Exchange` member names `exchanges.py` defines; grep them.) In the reconstruction test file add one test
  that `build_delistings_table([rec], last_trade_closes={key: 2.0}, otc_prints={key: 0.5})` for a
  compliance-failure `DelistRecord` gives `dlret_method` `otc_print` and `dlret` −0.75, built like that file's other
  `build_delistings_table` tests. In the exit_kind test file (grep `ending_fields` in tests/) add one case: a row with
  `dlret_method` `otc_print` puts its value in `dlret`, not `dlret_fill`.
- [ ] **Step 2:** Run them: they fail.
- [ ] **Step 3: Implement.**
  - `dlret.py`: add `OTC_PRINT = "otc_print"` to `DlretMethod` (after `RECOVERY_RATIO`); add the keyword
    `otc_print: float | None = None` to `resolve_dlret` (last parameter). In the LIQUIDATION branch, after the
    `recovery_ratio` block and before `_shumway_result`, and in the COMPLIANCE_FAILURE branch before
    `_shumway_result`, add:

```python
        if otc_print is not None and otc_print > 0:
            return DlretResult(otc_print / last_trade_close - 1.0, DlretMethod.OTC_PRINT, otc_print)
```

    Leave `compute_dlret` as it is.
  - `reconstruction.py`: `enrich(..., otc_print: float | None = None)` passes `otc_print=otc_print` to
    `resolve_dlret`; `_dlret_confidence` grades `OTC_PRINT` `medium` (add it to the tuple with `RECOVERY_RATIO`);
    `build_delistings_table(..., otc_prints: Mapping | None = None)` passes `otc_print=for_delisting(otc_prints, key)`.
  - `exit_kind.py`: add `"otc_print"` to `MEASURED_METHODS`.
- [ ] **Step 4:** Run the three test files, then the full suite.
- [ ] **Step 5: Commit** — `git commit -m "dlret: an OTC print values a drop or distress ending (reset-4f)"`

---

### Task 2: Request the prints and read the answers

**Files:** Modify `src/delist_detection/price_requests.py`, `src/delist_detection/pipeline.py`; Test
`tests/test_price_requests.py` (grep `request_rows(` in tests/), `tests/test_pipeline.py`.

**Interfaces:** Consumes Task 1's `build_delistings_table(..., otc_prints=)`. Produces `Overrides.otc_prints:
dict` (DelistingKey -> price).

- [ ] **Step 1: Write the failing tests.**
  - In the `request_rows` test file: a contract row with `exit_kind` `dropped`, `continuation` False and
    `last_trade_date` `2015-03-06` (a Friday) gives, besides its `last_close` row, one row
    `{"kind": "otc_print", "lookup_sec_id": <its sec_id>, "lookup_ticker": <its ticker>, "date": "2015-03-09"}`;
    a `liquidation` row also asks; a `merger` row, a continuation (`continuation` True) and a row with a blank
    `last_trade_date` ask for no `otc_print`. Build the inputs the way that file's existing `request_rows` tests do.
  - In tests/test_pipeline.py, next to the existing `_apply_price_answers` test (grep it): an `otc_print` answer
    keyed on a delisting's `(sec_id, last_trade_date)` lands in `Overrides.otc_prints[delisting.key]`, and the
    last-close and received-close maps are unchanged by it.
- [ ] **Step 2:** Run them: they fail.
- [ ] **Step 3: Implement.**
  - `price_requests.py` `request_rows`: after the `last_close` row, add

```python
        if c["exit_kind"] in OTC_EXIT_KINDS:
            out.append({"sec_id": c["sec_id"], "last_trade_date": ltd, "kind": OTC_PRINT,
                        "lookup_sec_id": c["sec_id"], "lookup_ticker": r["ticker"],
                        "date": next_trading_day(date.fromisoformat(ltd)).isoformat()})
```

    with `OTC_EXIT_KINDS = frozenset({"dropped", "liquidation"})   # decision 11: a drop or distress ending's first
    off-exchange print` next to `KINDS`. Update the module docstring ("`otc_print` requests start with reset-4f"
    becomes what they are: one per drop or distress ending, dated the session after the last trade; the caller
    answers with the first off-exchange print within 10 sessions). Keep the row order: last_close, otc_print,
    received_close. If `contract_rows` cells are typed differently (grep how `c["continuation"]` is compared), match it.
  - `pipeline.py`: `Overrides` gains `otc_prints: dict = field(default_factory=dict)   # DelistingKey -> OTC print,
    from price_answers`; `_apply_price_answers` adds `elif k.kind == OTC_PRINT: otc[e.key] = price` (import
    `OTC_PRINT`) and returns `replace(..., otc_prints=otc)`; its docstring names the third kind; `_delisting_rows`
    passes `otc_prints=overrides.otc_prints` to `build_delistings_table`.
- [ ] **Step 4:** Run the two test files, `tests/test_contract.py` (if it checks price_requests rows, update its
  expectation and say so), then the full suite.
- [ ] **Step 5: Commit** — `git commit -m "price_requests: ask for the first OTC print after a drop and value it from the answer (reset-4f)"`

---

### Task 3: Docs

- [ ] CLAUDE.md (`price_requests.py` bullet: the `otc_print` rows; the contract invariant: an OTC print answer is a
  value, not a fill; `dlret.py`/`exit_kind.py` mentions), README.md (the price_requests and DLRET method sections:
  grep `received_close` and `recovery_ratio`), docs/data-flow.md (where price_requests is described). Update the
  pytest count. Commit `docs: OTC prints (reset-4f)`.

---

### Task 4: Acceptance rebuild (network)

As in the earlier acceptance tasks (lock check, `.superpowers/sdd/reset4f-acceptance`, the usual flags and seven
hosts, no `--price-answers`; stop on a denial or a non-zero exit). Every table except
`contract/price_requests.csv` must be byte-identical to `output/`, and the scorecard must not move (stop otherwise).
Count the new `otc_print` rows and check each names a `dropped` or `liquidation` contract ending. Then run a second,
offline pass to prove the answers path: copy the new `price_requests.csv` to
`.superpowers/sdd/2026-10-02-reset-4f-otc-prints/answers.csv` with a `price` column holding, for three `otc_print`
rows only, half of that ending's `last_trade_close` from `delistings.csv` (other prices blank), rebuild into
`.superpowers/sdd/reset4f-answers` with `--price-answers` that file (warm caches, so no requests), and check those
three rows read `dlret_method` `otc_print` and `dlret` −0.5 and nothing else changed except their contract
`dlret`/`dlret_fill` cells and the scorecard's value lines. Publish the first rebuild only;
`scripts/scorecard.py --check`; the full suite; a "Done (first step)" bullet under reset-4f in the roadmap (the
request count and what is left: the OTC branch of the end-of-era resolver, CRSP 520 labels, and the caller's
answers from qlib_practice). Commit `Acceptance: OTC prints requested (reset-4f)`.

## Self-review

- Spec coverage: decision 11's value path and the `otc_print` request; the resolver's OTC branch (CRSP 520 labels) is
  not in this step (Ruling 1).
- Types: `otc_prints` is a DelistingKey map like `recovery_ratios`; `for_delisting` reads both.
</content>
