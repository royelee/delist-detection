# Reset-3: The Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every run also writes the contract that qlib_practice will read: `security_history`, one-ending-per-security
`delistings`, the seed echo, `price_requests.csv` (with answers read back) and `id_changes.csv`, under
`output/contract/` beside today's nine tables, with `schema_version` in `run_manifest.json`.

**Architecture:** A leaf module (`exit_kind.py`) maps one of today's delistings rows to the contract's exit kind,
drop reason, continuation and value columns; the contract table, the golden judge and the scorecard all read
through it. A pure module (`contract.py`) builds the contract tables from the run's own tables and verdicts. Two
helpers feed it: `issuer_in_force.py` dates each security's issuer CIK from EDGAR's names (golden `MRK-2008`),
and `price_requests.py` writes the price requests and reads the caller's answers. Pipeline stage 10g writes the
contract; the scorecard moves to 10h and reads `contract/security_history.csv` for the issuer.

**Tech Stack:** Python ≥3.10, the standard library, pytest (offline). No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md` ("The contract": "What crosses the
boundary", "security_history", "delistings", "Invariants the library's build enforces"; decisions 6, 7, 9, 10
and 12). Roadmap: `docs/superpowers/plans/2026-10-02-delist-library-reset.md`, "reset-3: The contract".

## Global Constraints

- Decisions 6, 7, 9, 10 and 12 adopted as proposed on 2026-10-02.
- Side by side for one release (decision 6): the contract goes under `output/contract/`; today's nine tables keep
  their columns and contents. Only `uncertain.csv` changes (earlier endings, Task 2).
- `security_history` columns, in order: `sec_id, issuer_id, start_date, end_date, ticker, security_name,
  share_class`.
- `delistings` (contract) columns, in order: `sec_id, last_trade_date, exit_kind, drop_reason, continuation,
  successor_sec_id, ticker_successor_sec_id, dlret, dlret_fill, terminal_value, verdict`. Key `sec_id`, one ending
  per security, its last (decision 12).
- `exit_kind` ∈ merger, exchange, liquidation, dropped, lost_source, expiration (blank when no kind is asserted).
  `drop_reason` ∈ moved_otc, price, capital, went_private, bankruptcy, filings_fees, guidelines, sec_order, on
  dropped rows only.
- `last_trade_date` only from an exchange-print source (MIDAS, an exchange notice, 8-K item 3.01, a Nasdaq halt) and
  never after the Form 25 effective date (filing date + 10 days); otherwise blank.
- `continuation` true ⇒ `successor_sec_id` set and `dlret` blank; `successor_sec_id` is set on no other row.
  `dlret` and `dlret_fill` are never both set. Assumed par is a fill of 0.0, never `dlret`.
- `verdict` is `confirmed` or `uncertain`, from reset-2's `verdict.decide`.
- `price_requests.csv` kinds: `last_close`, `received_close`, `otc_print`. Answers are the same file plus a `price`
  column; a second run with answers changes value columns only.
- `sec_id` stays a FIGI or `CIK<cik>-<CLASS>` with CLASS from a class code (decision 7).
- `run_manifest.json` carries `schema_version` (1).
- Tests are offline; never add network to the test path. No lint tooling exists; do not invent one.
- Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Exit kind from today's bucket and code.** merger → `merger`; exchange_transfer → `exchange` (a continuation
   when its successor is another security); liquidation with code 470 (the classifier's bankruptcy code) →
   `dropped` for `bankruptcy`, other liquidations → `liquidation`; compliance_failure → `dropped` for the reason its
   code names (570 guidelines, 573 sec_order, 580 filings_fees, and CRSP's meaning for the other 5xx codes);
   expiration → `expiration`; unknown → blank (no kind asserted; its verdict is already uncertain). `lost_source`
   is not produced until reset-4a. This removes the audit's liquidation-vs-dropped difference (36 of its 49
   distress errors).
2. **Values.** cash_only, stock_only, cash_plus_stock, recovery_ratio and worthless are measured (`dlret`). Shumway
   marks, assumed par and an exchange transfer's 0.0 are fills (`dlret_fill`). A continuation has neither. The 124
   transfers with no successor keep today's 0.0 as a fill, so qlib_practice's labels do not move until reset-4a and
   reset-4f decide which are real drops.
3. **Last trade date.** Published only when an exchange print gave it and it is no later than the Form 25 effective
   date: 148 of the 875 contract endings are blank. An exchange-print date with a text conflict stays published:
   decision 12 blanks the date only when the date itself is uncertain.
4. **Earlier endings.** `verdict.decide` gives every real ending that is not its security's last the reason
   `earlier_ending:<last delist_date>`. `V.uncertain_endings` rises by those not already uncertain (at most 6); Task
   11 lowers that floor entry by hand with this reason.
5. **Issuer in force.** A sighting keeps its era's CIK when that CIK's EDGAR name on the sighting's date agrees with
   the observed name. Otherwise the one other CIK that SEC's name index lists under exactly the observed name and
   whose EDGAR name on that date agrees is the issuer in force; none or two keeps the era's CIK. The change date is
   the first day the new CIK carried an agreeing name, kept after the last sighting under the old CIK.
6. **What security_history publishes.** Every ticker_history range except those of the merger acquirers the run
   adds (no reader needs them, and a price answer can change which acquirers the gate keeps). Successors stay: a
   continuation's `successor_sec_id` must resolve.
7. **Placeholders.** `share_class_from_name` already yields a closed set (COMMON, CLASS X, SERIES X), so no
   placeholder ID changes. `placeholder_id` now refuses anything else. `id_changes.csv` lists the baseline run's
   placeholders that now hold a FIGI; the baseline is a `securities.csv` (default: the output folder's own, read
   before the run writes). It is not cumulative: git keeps earlier versions.
8. **Price requests.** One `last_close` per contract ending with a published date that is not a continuation; one
   `received_close` per LLM-read stock leg (a `--merger-terms` stock leg carries its own price); `otc_print` waits
   for reset-4f. An answer is matched on `(sec_id, last_trade_date, kind, lookup_ticker, date)`; `lookup_sec_id` is
   informational. `--last-trade-closes` stays for this release; a last close given by both stops the run.
9. **Readers.** The golden judge and the scorecard read the exit kind and the fill through `exit_kind.ending_fields`,
   the function that writes `contract/delistings.csv`, and the issuer from `contract/security_history.csv`.
   `lifecycle.EXIT_KIND_OF_BUCKET` and `lifecycle.DISTRESS` are deleted. Every scorecard number stays the same
   except the golden and audit lines the new readings fix.
10. **Layout.** `uncertain.csv` stays at `output/uncertain.csv`. The contract stage is 10g; the scorecard moves to
    10h.

## Measured on the committed output (2026-10-02, `2d5026a`)

- 881 real endings over 875 securities; 6 securities have two (APA, HNZ, IPHI, WFT, AOC/AON, GGP).
- Contract exit kinds: 618 merger, 193 exchange (69 continuations), 47 dropped/bankruptcy, 3 dropped/sec_order,
  3 dropped/filings_fees, 2 expiration, 9 blank.
- Values: 513 measured; 237 fills (61 assumed par, 52 Shumway, 124 transfer 0.0); 56 neither (34 wait for a
  last close, 17 abstain, 4 unknown, 1 expiration); 69 continuations with neither.
- Last trade dates: 148 blank in the contract (43 blank today, 38 from the last sighting, 69 with no source,
  none after the Form 25 effective date).
- MRK: both eras resolved to CIK 310158 (Schering-Plough until November 2009); golden `MRK-2008` expects 64978.

## Review Focus

1. A security whose only rows continue it (successor itself) gets no contract row, and one whose last real
   ending is a continuation gets `continuation=true` with both values blank (Task 4).
2. A price answer that answers no request, a non-numeric or non-positive price, and a last close given by both
   `--price-answers` and `--last-trade-closes` each stop the run before anything is written (Tasks 6 and 8).
3. An interval whose issuer changes inside it splits into two rows that neither overlap nor leave a gap, and a
   security with no sightings keeps its securities.csv CIK (Task 4).
4. A first run (no baseline `securities.csv`) writes an empty `id_changes.csv` without error (Task 7).
5. A resolver with no name index, or an issuer whose submissions read fails, keeps the era's CIK instead of
   stopping the run; a refusal (`EdgarBlocked`) still stops it (Tasks 5 and 7).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/delist_detection/exit_kind.py` (new) | One delistings row → exit kind, drop reason, continuation, dlret, dlret_fill; distress. Leaf module. |
| `src/delist_detection/contract.py` (new) | Pure builders of the five contract tables' rows (price requests via `price_requests`). |
| `src/delist_detection/issuer_in_force.py` (new) | Issuer CIK in force per sighting and each security's issuer timeline, through injected EDGAR callables. |
| `src/delist_detection/price_requests.py` (new) | Price request rows, stock legs, the answers file. |
| `src/delist_detection/verdict.py` | Published last trade date, Form 25 effective date, earlier endings, `Verdict.word`, `seed_key`. |
| `src/delist_detection/store.py` | `TableSpec.file`, the contract table specs, `CONTRACT_SCHEMA_VERSION`. |
| `src/delist_detection/lifecycle.py` | `Tables.security_history`; `issuer_of(sec_id, on)`; the walk reads exit kinds; delete `EXIT_KIND_OF_BUCKET`, `EXIT_KINDS`, `DISTRESS`. |
| `src/delist_detection/truth.py`, `scorecard.py`, `audit.py` | Read through `exit_kind`; the judge uses the issuer in force. |
| `src/delist_detection/manifest.py` | `schema_version`. |
| `src/delist_detection/figi_resolution.py` | `placeholder_id` takes a class code only. |
| `src/delist_detection/ticker_resolver.py` | `TickerResolver.name_index()`. |
| `src/delist_detection/pipeline.py` | 6b price answers, 10g contract, 10h scorecard, `run(id_baseline=)`. |
| `scripts/classify_universe.py` | `--price-answers`, `--id-baseline`, a contract summary line. |
| `scripts/seeds_from_observations.py` (new) | Observations → seeds, for the seeds-only measurement. |

---

### Task 1: `exit_kind` — one reading of an ending, used by the judge, the scorecard and the audit

**Files:**
- Create: `src/delist_detection/exit_kind.py`
- Modify: `src/delist_detection/lifecycle.py` (delete `EXIT_KIND_OF_BUCKET`, `EXIT_KINDS`, `DISTRESS`; `_walk`)
- Modify: `src/delist_detection/truth.py` (imports; `judge`)
- Modify: `src/delist_detection/scorecard.py` (imports; `_ending_lines`; `_verdict_lines`)
- Modify: `src/delist_detection/audit.py` (imports; `_census_group`)
- Modify: `src/delist_detection/verdict.py` (`_ending_reasons`: the unknown test)
- Test: `tests/test_exit_kind.py` (new), `tests/test_truth.py`

**Interfaces:**
- Consumes: delistings.csv rows as `store.read_table` returns them (string cells).
- Produces: `exit_kind.EXIT_KINDS`, `DROP_REASONS`, `EndingFields(exit_kind, drop_reason, continuation, dlret,
  dlret_fill)`, `ending_fields(row) -> EndingFields`, `is_continuation(row) -> bool`, `is_distress(row) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exit_kind.py`:

```python
import pytest

from delist_detection.crsp_codes import DLST_CODE_TO_BUCKET
from delist_detection.exit_kind import DROP_REASONS, EXIT_KINDS, ending_fields, is_distress
from lifecycle_tables import ending


def test_a_bankruptcy_is_dropped_for_bankruptcy_with_its_mark_as_a_fill():
    f = ending_fields(ending("S", "2020-05-11", "liquidation", dlret="-0.550000", method="shumway_nasdaq",
                             crsp_code="470"))
    assert (f.exit_kind, f.drop_reason, f.dlret, f.dlret_fill) == ("dropped", "bankruptcy", "", "-0.550000")


def test_a_liquidation_without_the_bankruptcy_code_stays_a_liquidation():
    f = ending_fields(ending("S", "2020-05-11", "liquidation", crsp_code="400"))
    assert (f.exit_kind, f.drop_reason) == ("liquidation", "")


@pytest.mark.parametrize("code,reason", [("573", "sec_order"), ("580", "filings_fees"), ("570", "guidelines"),
                                         ("520", "moved_otc"), ("500", "")])
def test_a_compliance_failure_is_dropped_for_the_reason_its_code_names(code, reason):
    f = ending_fields(ending("S", "2012-05-01", "compliance_failure", crsp_code=code))
    assert (f.exit_kind, f.drop_reason) == ("dropped", reason)


def test_a_measured_value_stays_dlret_and_assumed_par_is_a_fill():
    cash = ending_fields(ending("S", "2018-11-29", dlret="0.110000", method="cash_only", crsp_code="231"))
    par = ending_fields(ending("S", "2018-11-29", dlret="0.000000", method="assumed_par", crsp_code="231"))
    assert (cash.exit_kind, cash.dlret, cash.dlret_fill) == ("merger", "0.110000", "")
    assert (par.dlret, par.dlret_fill) == ("", "0.000000")


def test_a_continuation_has_no_value_and_a_transfer_keeps_its_zero_as_a_fill():
    cont = ending_fields(ending("S", "2015-10-02", "exchange_transfer", successor="T", dlret="0.000000",
                                method="exchange_transfer_zero", crsp_code="304"))
    xfer = ending_fields(ending("S", "2015-10-02", "exchange_transfer", dlret="0.000000",
                                method="exchange_transfer_zero", crsp_code="304"))
    assert (cont.exit_kind, cont.continuation, cont.dlret, cont.dlret_fill) == ("exchange", True, "", "")
    assert (xfer.exit_kind, xfer.continuation, xfer.dlret, xfer.dlret_fill) == ("exchange", False, "", "0.000000")


def test_a_successor_that_is_the_security_itself_is_not_a_continuation():
    assert not ending_fields(ending("S", "2019-03-20", "merger", successor="S")).continuation


def test_unknown_asserts_no_kind_and_a_blank_value_stays_blank():
    f = ending_fields(ending("S", "2009-03-08", "unknown", method="needs_last_trade"))
    assert (f.exit_kind, f.drop_reason, f.dlret, f.dlret_fill) == ("", "", "", "")


def test_distress_is_a_liquidation_or_a_drop_that_carries_a_harsh_mark():
    assert is_distress(ending("S", "2020-05-11", "liquidation", crsp_code="470"))
    assert is_distress(ending("S", "2020-05-11", "liquidation", crsp_code="400"))
    assert is_distress(ending("S", "2012-05-01", "compliance_failure", crsp_code="580"))
    assert is_distress(ending("S", "2012-05-01", "compliance_failure", crsp_code="500"))
    assert not is_distress(ending("S", "2012-05-01", "compliance_failure", crsp_code="520"))
    assert not is_distress(ending("S", "2018-11-29", "merger", crsp_code="231"))


def test_every_code_maps_into_the_contract_vocabulary():
    for code, bucket in DLST_CODE_TO_BUCKET.items():
        if bucket.value == "active":
            continue
        f = ending_fields(ending("S", "2010-01-04", bucket.value, crsp_code=str(code)))
        assert f.exit_kind in EXIT_KINDS
        assert f.drop_reason == "" or (f.exit_kind == "dropped" and f.drop_reason in DROP_REASONS)
```

Add to `tests/test_truth.py` (after `test_judge_passes_when_every_checked_field_agrees`):

```python
def test_judge_reads_a_bankruptcy_as_dropped():
    t = tables([sec("S", cik="100")], [iv("S", "AAA", "2010-01-04", "2020-05-01")],
               [ending("S", "2020-05-11", "liquidation", ltd="2020-05-01", dlret="-0.550000",
                       method="shumway_nasdaq", crsp_code="470")],
               [obs("AAA", "2012-06-29", "S")])
    assert judge(_case(exit_kind="dropped"), LifecycleView(t)).mismatches == ()
    assert judge(_case(exit_kind="liquidation"), LifecycleView(t)).mismatches == (
        "exit_kind dropped != liquidation",)
```

(`tables`, `sec`, `iv`, `ending`, `obs` and `LifecycleView` are already imported by `tests/test_truth.py`; add any
that is missing to its imports.)

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_exit_kind.py tests/test_truth.py -q -o addopts=""`
Expected: `tests/test_exit_kind.py` fails to import (`No module named 'delist_detection.exit_kind'`), and
`test_judge_reads_a_bankruptcy_as_dropped` fails with `exit_kind liquidation != dropped`.

- [ ] **Step 3: Write `exit_kind.py`**

Create `src/delist_detection/exit_kind.py`:

```python
"""The contract's view of one delistings.csv row (spec: Delist Library Reset,
"delistings · one row per ended security"; decisions 9 and 12): its exit kind,
drop reason, whether it is a continuation, and its value split into a measured
`dlret` and a `dlret_fill`.

Today's bucket and CRSP code map to `exit_kind` and `drop_reason`: a bankruptcy
delisting (the classifier's code 470, today's `liquidation` bucket) is `dropped`
for `bankruptcy`; a compliance failure is `dropped` for the reason its code
names; `unknown` asserts no kind. A successor other than the security itself is
a continuation (decision 9). A cash or stock consideration or a recovery is
measured; a Shumway mark, assumed par and a transfer's 0.0 are fills; a
continuation has neither. contract/delistings.csv, the golden judge and the
scorecard all read a row through `ending_fields`, so they see the same values.
Pure, on string rows as store.read_table returns them."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

EXIT_KINDS = frozenset({"merger", "exchange", "liquidation", "dropped", "lost_source", "expiration"})
DROP_REASONS = frozenset({"moved_otc", "price", "capital", "went_private", "bankruptcy", "filings_fees",
                          "guidelines", "sec_order"})
NOT_DISTRESS = frozenset({"moved_otc", "went_private"})        # drop reasons that carry no harsh mark

# The drop reason of each code a dropped security can carry: the codes this
# library gives (classifier.py: 470 a bankruptcy, 570 a listing deficiency, 573
# an SEC revocation, 580 a delinquent filer), and the other 5xx codes of
# crsp_codes.DLST_CODE_TO_BUCKET by CRSP's meaning.
DROP_REASON_OF_CODE = {
    "470": "bankruptcy", "574": "bankruptcy", "520": "moved_otc", "550": "price", "552": "price",
    "560": "capital", "570": "guidelines", "584": "guidelines", "573": "sec_order", "585": "sec_order",
    "580": "filings_fees",
}
MEASURED_METHODS = frozenset({"cash_only", "stock_only", "cash_plus_stock", "recovery_ratio", "worthless"})
FILL_METHODS = frozenset({"assumed_par", "shumway_nyse_amex", "shumway_nasdaq", "exchange_transfer_zero"})


@dataclass(frozen=True)
class EndingFields:
    exit_kind: str           # one of EXIT_KINDS, or "" when the row asserts none (today's `unknown`)
    drop_reason: str         # one of DROP_REASONS on a `dropped` row whose code names one, else ""
    continuation: bool
    dlret: str               # the measured value as delistings.csv writes it, or ""
    dlret_fill: str          # the fill as delistings.csv writes it, or ""


def is_continuation(row: Mapping[str, str]) -> bool:
    """A successor other than the security itself: the same holders own it now."""
    return bool(row["successor_sec_id"]) and row["successor_sec_id"] != row["sec_id"]


def _kind(row: Mapping[str, str]) -> tuple[str, str]:
    bucket, reason = row["bucket"], DROP_REASON_OF_CODE.get(row["crsp_code"], "")
    if bucket == "merger":
        return "merger", ""
    if bucket == "exchange_transfer":
        return "exchange", ""
    if bucket == "liquidation":
        return ("dropped", reason) if reason == "bankruptcy" else ("liquidation", "")
    if bucket == "compliance_failure":
        return "dropped", reason
    if bucket == "expiration":
        return "expiration", ""
    return "", ""


def ending_fields(row: Mapping[str, str]) -> EndingFields:
    """The contract's columns for one delistings.csv row."""
    kind, reason = _kind(row)
    cont = is_continuation(row)
    method, value = row["dlret_method"], row["dlret"]
    return EndingFields(kind, reason, cont,
                        value if method in MEASURED_METHODS and not cont else "",
                        value if method in FILL_METHODS and not cont else "")


def is_distress(row: Mapping[str, str]) -> bool:
    """A liquidation, or a drop for a reason that carries a harsh mark: every
    drop reason but a move to OTC or going private. A drop whose code names no
    reason counts, as today's compliance_failure bucket always did."""
    f = ending_fields(row)
    return f.exit_kind == "liquidation" or (f.exit_kind == "dropped" and f.drop_reason not in NOT_DISTRESS)
```

- [ ] **Step 4: Switch the readers**

In `src/delist_detection/lifecycle.py`:

1. Delete these lines (and nothing else around them):

```python
EXIT_KIND_OF_BUCKET = {"merger": "merger", "exchange_transfer": "exchange", "liquidation": "liquidation",
                       "compliance_failure": "dropped", "expiration": "expiration"}
EXIT_KINDS = frozenset({"merger", "exchange", "liquidation", "dropped", "lost_source", "expiration"})
DISTRESS = ("liquidation", "compliance_failure")                         # today's distress buckets
```

   If the module docstring mentions `EXIT_KIND_OF_BUCKET`, replace that sentence with: "An ending's exit kind is
   read through `exit_kind.ending_fields`, the function that writes contract/delistings.csv."
2. Add `from .exit_kind import ending_fields` after `from . import store`.
3. In `_walk`, replace

```python
        if e["bucket"] == "exchange_transfer":
            return LEFT_VIEW, chain, [e]
        complete = e["bucket"] != "unknown" and e["last_trade_date"] and e["dlret"]
```

   with

```python
        kind = ending_fields(e).exit_kind
        if kind == "exchange":
            return LEFT_VIEW, chain, [e]
        complete = kind != "" and e["last_trade_date"] and e["dlret"]
```

In `src/delist_detection/truth.py`:

1. Replace `from .lifecycle import ACTIVE, ENDED, EXIT_KIND_OF_BUCKET, EXIT_KINDS, LifecycleView` with

```python
from .exit_kind import EXIT_KINDS, ending_fields
from .lifecycle import ACTIVE, ENDED, LifecycleView
```

2. In `judge`, replace `kind = EXIT_KIND_OF_BUCKET.get(final["bucket"], "")` with
   `kind = ending_fields(final).exit_kind`.

In `src/delist_detection/scorecard.py`:

1. Remove `DISTRESS, ` from the `from .lifecycle import (...)` list and add `from .exit_kind import ending_fields,
   is_distress` after it.
2. In `_ending_lines`, replace

```python
    xfer = [r for r in real if r["bucket"] == "exchange_transfer" and not r["successor_sec_id"]]
    missing_ltd = [r for r in real if not r["last_trade_date"]]
    blank = [r for r in real if not r["dlret"]]
    distress = [r for r in real if r["bucket"] in DISTRESS]
```

   with

```python
    fields = {id(r): ending_fields(r) for r in real}
    xfer = [r for r in real if fields[id(r)].exit_kind == "exchange" and not fields[id(r)].continuation]
    missing_ltd = [r for r in real if not r["last_trade_date"]]
    blank = [r for r in real if not r["dlret"]]
    distress = [r for r in real if is_distress(r)]
    assumed_par = [r for r in real if fields[id(r)].exit_kind == "merger" and fields[id(r)].dlret_fill]
```

   then replace `"R2.2.unknown_reason": sum(r["bucket"] == "unknown" for r in real),` with
   `"R2.2.unknown_reason": sum(not fields[id(r)].exit_kind for r in real),`, replace
   `"R2.4.assumed_par": sum(r["dlret_method"] == "assumed_par" for r in real),` with
   `"R2.4.assumed_par": len(assumed_par),`, and replace
   `"R2.4.assumed_par_in_window": sum(r["dlret_method"] == "assumed_par" and inw(r) for r in real),` with
   `"R2.4.assumed_par_in_window": sum(inw(r) for r in assumed_par),`.
3. In `_verdict_lines`, replace
   `distress = {(r["sec_id"], r["delist_date"]) for r in tables.delistings if r["bucket"] in DISTRESS}` with
   `distress = {(r["sec_id"], r["delist_date"]) for r in tables.delistings if is_distress(r)}`.

In `src/delist_detection/audit.py`:

1. Replace `from .scorecard import CENSUS_GROUPS, DISTRESS, Window` with

```python
from .exit_kind import is_distress
from .scorecard import CENSUS_GROUPS, Window
```

2. In `_census_group`, replace `"distress": row["bucket"] in DISTRESS,` with `"distress": is_distress(row),`.

In `src/delist_detection/verdict.py`, add `from .exit_kind import ending_fields` after the `from .lifecycle import`
line, and in `_ending_reasons` replace `if row["bucket"] == "unknown":` with `if not ending_fields(row).exit_kind:`.

Then search for leftovers: `grep -rn "EXIT_KIND_OF_BUCKET\|lifecycle import.*DISTRESS\|scorecard import.*DISTRESS" src tests scripts`
must print nothing.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_exit_kind.py tests/test_truth.py tests/test_lifecycle.py tests/test_scorecard.py tests/test_audit.py tests/test_verdict.py -q -o addopts=""`
Expected: all pass.

Then the full suite: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q -o addopts=""`.
Expected: `1603 passed, 25 xfailed` (1589 + 13 exit-kind tests + 1 truth test). The committed-output floor test
still passes: on the committed tables `A.census.distress.errors` falls (the bankruptcies now read `dropped`), every
other number is unchanged. Confirm with `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py`
and record in the report each metric that differs from `output/scorecard.json`; only `A.*` lines may differ, each
in its good direction.

- [ ] **Step 6: Commit**

```bash
git add src/delist_detection/exit_kind.py src/delist_detection/lifecycle.py src/delist_detection/truth.py \
        src/delist_detection/scorecard.py src/delist_detection/audit.py src/delist_detection/verdict.py \
        tests/test_exit_kind.py tests/test_truth.py
git commit -m "exit_kind: the contract's reading of an ending, for the judge and the scorecard (reset-3)"
```

---

### Task 2: Verdict — published last trade date, earlier endings, verdict words

**Files:**
- Modify: `src/delist_detection/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: `exit_kind.ending_fields` (Task 1).
- Produces: `verdict.CONFIRMED`, `UNCERTAIN`, `Verdict.word -> str`, `form25_effective(row) -> date | None`,
  `published_last_trade_date(row) -> str`, `seed_key(row)` (the renamed `_seed_key`), and the
  `earlier_ending:<delist_date>` reason in `decide`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_verdict.py`, change the import line's `_seed_key` to `seed_key` (and the one use of `_seed_key` in the
file to `seed_key`), add `published_last_trade_date` to that import, and add:

```python
def test_an_earlier_ending_is_uncertain_and_names_the_last_one():
    t = tables([sec("S")], [iv("S", "AAA", "2008-01-02", "2012-03-30")],
               [ending("S", "2009-12-01", "exchange_transfer", ltd="2009-11-20", dlret="0.000000",
                       method="exchange_transfer_zero"),
                ending("S", "2012-03-31", ltd="2012-03-30", dlret="0.100000")],
               [obs("AAA", "2008-01-02", "S")])
    v = decide(t, {})
    assert "earlier_ending:2012-03-31" in v.endings[("S", "2009-12-01")].reasons
    assert v.endings[("S", "2012-03-31")].confirmed


def test_the_published_last_trade_date_needs_an_exchange_print_before_the_form25_takes_effect():
    ok = ending("S", "2018-12-10", ltd="2018-11-28", delist_filing_form="25-NSE", delist_filing_date="2018-11-29")
    late = ending("S", "2018-12-10", ltd="2018-12-20", delist_filing_form="25-NSE", delist_filing_date="2018-11-29")
    seen = ending("S", "2018-12-10", ltd="2018-11-28", source="last_sighting")
    assert published_last_trade_date(ok) == "2018-11-28"
    assert published_last_trade_date(late) == ""
    assert published_last_trade_date(seen) == ""
    assert published_last_trade_date(ending("S", "2018-12-10")) == ""


def test_a_verdict_reads_confirmed_or_uncertain():
    assert Verdict().word == "confirmed"
    assert Verdict(("no_last_trade_date",)).word == "uncertain"
```

(`tables`, `sec`, `iv`, `ending`, `obs` come from `lifecycle_tables`, as the file's other tests use them.)

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_verdict.py -q -o addopts=""`
Expected: an ImportError on `seed_key` / `published_last_trade_date`.

- [ ] **Step 3: Implement**

In `src/delist_detection/verdict.py`:

1. Below `SECURITY_UNCERTAIN = "security_uncertain"` add `CONFIRMED, UNCERTAIN = "confirmed", "uncertain"`.
2. In `class Verdict`, after the `confirmed` property, add:

```python
    @property
    def word(self) -> str:
        """The contract's verdict column."""
        return CONFIRMED if self.confirmed else UNCERTAIN
```

3. After `_covered`, add:

```python
def form25_effective(row: Mapping[str, str]) -> date | None:
    """The day a row's Form 25 takes effect (FORM25_EFFECTIVE_DAYS after it was
    filed), or None when the row cites no Form 25."""
    if row["delist_filing_date"] and row["delist_filing_form"].startswith("25"):
        return date.fromisoformat(row["delist_filing_date"]) + timedelta(days=FORM25_EFFECTIVE_DAYS)
    return None


def published_last_trade_date(row: Mapping[str, str]) -> str:
    """contract/delistings.csv's last_trade_date (decision 12): the row's date when
    an exchange print gave it and it is no later than the Form 25's effective
    date, else blank."""
    ltd = row["last_trade_date"]
    if not ltd or row["last_trade_date_source"] not in EXCHANGE_PRINT_SOURCES:
        return ""
    effective = form25_effective(row)
    return "" if effective is not None and date.fromisoformat(ltd) > effective else ltd
```

4. In `_ending_reasons`, replace

```python
    if row["delist_filing_date"] and row["delist_filing_form"].startswith("25"):
        effective = date.fromisoformat(row["delist_filing_date"]) + timedelta(days=FORM25_EFFECTIVE_DAYS)
        if date.fromisoformat(ltd) > effective:
            reasons.append(f"last_trade_after_form25_effective:{effective.isoformat()}")
```

   with

```python
    effective = form25_effective(row)
    if effective is not None and date.fromisoformat(ltd) > effective:
        reasons.append(f"last_trade_after_form25_effective:{effective.isoformat()}")
```

5. Rename `_seed_key` to `seed_key` (its definition and its two uses).
6. In `decide`, replace

```python
    endings = {(r["sec_id"], r["delist_date"]): Verdict(tuple(_ending_reasons(r, securities.get(r["sec_id"]))))
               for r in tables.delistings if r["successor_sec_id"] != r["sec_id"]}
```

   with

```python
    real = [r for r in tables.delistings if r["successor_sec_id"] != r["sec_id"]]
    last_of: dict[str, str] = {}
    for r in real:
        last_of[r["sec_id"]] = max(last_of.get(r["sec_id"], ""), r["delist_date"])
    endings = {}
    for r in real:
        reasons = _ending_reasons(r, securities.get(r["sec_id"]))
        if r["delist_date"] != last_of[r["sec_id"]]:
            reasons.append(f"earlier_ending:{last_of[r['sec_id']]}")
        endings[(r["sec_id"], r["delist_date"])] = Verdict(tuple(reasons))
```

7. In the module docstring, after the paragraph on endings, add: "An ending that is not its security's last (one that
   ended, returned and ended again) is uncertain, `earlier_ending:<the last one's delist_date>`: the contract keeps
   one ending per security (decision 12)."

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_verdict.py -q -o addopts=""` — all pass.
Full suite: expected `1606 passed, 25 xfailed`. The floor test reads the committed uncertain.csv as written, so
the V lines do not move until Task 11 rebuilds it.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/verdict.py tests/test_verdict.py
git commit -m "Verdict: published last trade date, earlier endings, verdict words (reset-3)"
```

---

### Task 3: Store, lifecycle and manifest — contract tables, the issuer in force, schema version

**Files:**
- Modify: `src/delist_detection/store.py`
- Modify: `src/delist_detection/lifecycle.py` (`Tables`, `LifecycleView`)
- Modify: `src/delist_detection/truth.py` (`judge`)
- Modify: `src/delist_detection/manifest.py`
- Modify: `tests/lifecycle_tables.py`
- Test: `tests/test_store.py`, `tests/test_lifecycle.py`, `tests/test_truth.py`, `tests/test_run_provenance.py`

**Interfaces:**
- Produces: `store.TableSpec.file`; `store.CONTRACT_SCHEMA_VERSION = 1`; table specs `security_history`,
  `contract_delistings`, `seeds`, `price_requests`, `id_changes` (files under `contract/`); `store.CONTRACT_TABLES`;
  `store.PRICE_REQUEST_COLUMNS`; `lifecycle.Tables.security_history`; `LifecycleView.issuer_of(sec_id, on="")`;
  the manifest's `schema_version`; `lifecycle_tables.hist(...)` and `tables(..., uncertain=, security_history=)`.

- [ ] **Step 1: Write the failing tests**

In `tests/lifecycle_tables.py`, add after `review`:

```python
def hist(sec_id, issuer, start, end="", ticker="AAA"):
    """A contract/security_history.csv row."""
    return _row("security_history", sec_id=sec_id, issuer_id=issuer, start_date=start, end_date=end, ticker=ticker,
                security_name=sec_id, share_class="COMMON")
```

and replace `tables` with:

```python
def tables(securities=(), history=(), delistings=(), observations=(), reviews=(), *, uncertain=None,
           security_history=None) -> Tables:
    return Tables(list(securities), list(history), list(delistings), list(observations), list(reviews),
                  uncertain, security_history)
```

Add to `tests/test_store.py`:

```python
def test_contract_tables_are_written_under_contract_and_read_back(tmp_path):
    from delist_detection.store import CONTRACT_TABLES, TABLES, read_table, table_path, write_tables
    row = {"sec_id": "S", "issuer_id": "100", "start_date": "2010-01-04", "end_date": "", "ticker": "AAA",
           "security_name": "S", "share_class": "COMMON"}
    write_tables(tmp_path, {"security_history": [row]})
    path = table_path(tmp_path, "security_history")
    assert path == tmp_path / "contract" / "security_history.csv"
    assert read_table("security_history", path) == [row]
    assert {TABLES[t].file for t in CONTRACT_TABLES} == {
        "contract/security_history.csv", "contract/delistings.csv", "contract/seeds.csv",
        "contract/price_requests.csv", "contract/id_changes.csv"}
    assert table_path(tmp_path, "delistings") == tmp_path / "delistings.csv"
```

Add to `tests/test_lifecycle.py`:

```python
def test_tables_read_takes_security_history_when_the_run_wrote_one(tmp_path):
    from delist_detection.store import write_tables
    write_tables(tmp_path, {"securities": [], "ticker_history": [], "delistings": [], "observation_map": []})
    assert Tables.read(tmp_path).security_history is None
    write_tables(tmp_path, {"security_history": [hist("S", "100", "2010-01-04")]})
    assert Tables.read(tmp_path).security_history == [hist("S", "100", "2010-01-04")]


def test_issuer_of_reads_the_issuer_in_force_on_the_day():
    t = tables([sec("S", cik="310158")], [iv("S", "MRK", "2008-01-02")], [], [obs("MRK", "2008-06-30", "S")],
               security_history=[hist("S", "64978", "2008-01-02", "2009-11-03", "MRK"),
                                 hist("S", "310158", "2009-11-04", "", "MRK")])
    view = LifecycleView(t)
    assert view.issuer_of("S", "2008-06-30") == "64978"
    assert view.issuer_of("S", "2012-06-29") == "310158"
    assert view.issuer_of("S") == "310158"
    assert LifecycleView(tables([sec("S", cik="310158")])).issuer_of("S", "2008-06-30") == "310158"
```

(import `hist` and `Tables` alongside the file's other helpers if they are not imported yet.)

Add to `tests/test_truth.py`:

```python
def test_judge_checks_the_issuer_in_force_on_the_case_date():
    t = tables([sec("S", cik="310158")], [iv("S", "AAA", "2008-01-02")], [], [obs("AAA", "2008-06-30", "S")],
               security_history=[hist("S", "64978", "2008-01-02", "2009-11-03"),
                                 hist("S", "310158", "2009-11-04")])
    assert judge(_case(on="2008-06-30", issuer_cik="64978"), LifecycleView(t)).mismatches == ()
```

In `tests/test_run_provenance.py`, add `"schema_version"` to the expected manifest key set (the set that holds
`"latency_ms", "stages", "resolution_degraded", "review", "handoffs"`).

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_store.py tests/test_lifecycle.py tests/test_truth.py tests/test_run_provenance.py -q -o addopts=""`
Expected: failures on the unknown `security_history` table, the `Tables` argument count, and the manifest keys.

- [ ] **Step 3: Implement**

In `src/delist_detection/store.py`:

1. Add `file: str = ""` to `TableSpec` after `sort`, with the comment `# the path under the output folder; "" means
   "<name>.csv"`.
2. After `UNCERTAIN_COLUMNS`, add:

```python
# The contract (spec: Delist Library Reset, "The contract"; contract.py), written
# under contract/ beside the tables above for one release (decision 6).
CONTRACT_SCHEMA_VERSION = 1
SECURITY_HISTORY_COLUMNS: tuple[str, ...] = (
    "sec_id", "issuer_id", "start_date", "end_date", "ticker", "security_name", "share_class")
CONTRACT_DELISTINGS_COLUMNS: tuple[str, ...] = (
    "sec_id", "last_trade_date", "exit_kind", "drop_reason", "continuation", "successor_sec_id",
    "ticker_successor_sec_id", "dlret", "dlret_fill", "terminal_value", "verdict")
SEEDS_COLUMNS: tuple[str, ...] = ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "sec_id", "verdict")
PRICE_REQUEST_COLUMNS: tuple[str, ...] = ("sec_id", "last_trade_date", "kind", "lookup_sec_id", "lookup_ticker", "date")
ID_CHANGES_COLUMNS: tuple[str, ...] = ("old_sec_id", "new_sec_id", "changed_on", "issuer_cik", "share_class")
CONTRACT_TABLES = ("security_history", "contract_delistings", "seeds", "price_requests", "id_changes")
```

3. Add these specs to the end of the `TABLES` tuple (after the `uncertain` spec):

```python
    TableSpec("security_history", SECURITY_HISTORY_COLUMNS, ("sec_id", "start_date", "ticker"),
              file="contract/security_history.csv"),
    TableSpec("contract_delistings", CONTRACT_DELISTINGS_COLUMNS, ("sec_id",), file="contract/delistings.csv"),
    TableSpec("seeds", SEEDS_COLUMNS, ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id"),
              file="contract/seeds.csv"),
    TableSpec("price_requests", PRICE_REQUEST_COLUMNS, ("sec_id", "kind", "date", "lookup_ticker"),
              file="contract/price_requests.csv"),
    TableSpec("id_changes", ID_CHANGES_COLUMNS, ("old_sec_id",), file="contract/id_changes.csv"),
```

4. Replace `table_path` with:

```python
def table_path(out_dir: str | Path, name: str) -> Path:
    """Where table `name` lives under `out_dir`: its spec's `file`, else `<name>.csv`."""
    spec = TABLES.get(name)
    return Path(out_dir) / (spec.file if spec is not None and spec.file else f"{name}.csv")
```

(`atomic_io.replace_all_on_success` already creates a missing parent folder.)

In `src/delist_detection/lifecycle.py`:

1. Add the field `security_history: Sequence[Mapping[str, str]] | None = None     # None: no contract (a run
   before reset-3)` to `Tables` after `uncertain`, and in `Tables.read` return
   `cls(rd("securities"), rd("ticker_history"), rd("delistings"), rd("observation_map"), optional("review") or [],
   optional("uncertain"), optional("security_history"))`; extend its docstring with "contract/security_history.csv
   may be missing (None)."
2. In `LifecycleView`, add the field `_history: dict[str, list[Mapping[str, str]]] = field(init=False)`; in
   `__post_init__` add

```python
        self._history = defaultdict(list)
        for r in self.tables.security_history or ():
            self._history[r["sec_id"]].append(r)
```

3. Replace `issuer_of` with:

```python
    def issuer_of(self, sec_id: str, on: str = "") -> str:
        """The security's issuer CIK: the contract's issuer in force on `on`
        (security_history.csv) when an interval of it covers that day, else
        securities.csv's."""
        for r in self._history.get(sec_id, ()) if on else ():
            if r["start_date"] <= on and (not r["end_date"] or on <= r["end_date"]):
                return r["issuer_id"]
        return self._securities.get(sec_id, {}).get("issuer_cik", "")
```

In `src/delist_detection/truth.py`, in `judge`, replace both `view.issuer_of(sec)` with `view.issuer_of(sec, case.on)`.

In `src/delist_detection/manifest.py`, add `from .store import CONTRACT_SCHEMA_VERSION` with the other imports, add
`"schema_version": CONTRACT_SCHEMA_VERSION,` to the dict `build` returns (after `"code_version"`), and add to its
docstring: "`schema_version` is the contract's (store.CONTRACT_SCHEMA_VERSION), asserted by the consumer's reader."

- [ ] **Step 4: Run the tests**

Run the four files from Step 2 — all pass. Full suite: expected `1610 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/store.py src/delist_detection/lifecycle.py src/delist_detection/truth.py \
        src/delist_detection/manifest.py tests/lifecycle_tables.py tests/test_store.py tests/test_lifecycle.py \
        tests/test_truth.py tests/test_run_provenance.py
git commit -m "Contract table specs, issuer in force for the judge, schema_version (reset-3)"
```

---

### Task 4: `contract.py` — the contract's rows, and placeholders from a class code

**Files:**
- Create: `src/delist_detection/contract.py`
- Modify: `src/delist_detection/figi_resolution.py` (`placeholder_id`)
- Test: `tests/test_contract.py` (new), `tests/test_figi_resolution.py`

**Interfaces:**
- Consumes: `exit_kind.ending_fields`; `verdict.Verdicts`, `published_last_trade_date`, `seed_key`, `decide`;
  `lifecycle.Tables`.
- Produces: `contract.last_endings(delistings) -> dict[str, row]`, `delisting_rows(tables, verdicts) -> list[dict]`,
  `seed_rows(tables, verdicts) -> list[dict]`, `security_history_rows(tables, issuers, leave_out=()) -> list[dict]`
  (`issuers`: sec_id → [(from ISO date, CIK str)]), `id_change_rows(baseline, securities, changed_on) -> list[dict]`;
  `figi_resolution.SHARE_CLASS_CODE`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contract.py`:

```python
from delist_detection.contract import (delisting_rows, id_change_rows, last_endings, security_history_rows,
                                       seed_rows)
from delist_detection.verdict import decide
from lifecycle_tables import ending, iv, obs, sec, tables


def _run_tables():
    return tables(
        [sec("A"), sec("B"), sec("C"), sec("D")],
        [iv("A", "AAA", "2010-01-04", "2015-03-02"), iv("B", "BBB", "2015-03-03"), iv("C", "CCC", "2010-01-04"),
         iv("D", "DDD", "2010-01-04", "2018-06-29")],
        [ending("A", "2015-03-10", "exchange_transfer", ltd="2015-03-02", dlret="0.000000",
                method="exchange_transfer_zero", successor="B", terminal_value="12.000000"),
         ending("C", "2019-03-20", "merger", ltd="2019-03-19", successor="C"),
         ending("D", "2009-12-01", "exchange_transfer", ltd="2009-11-20", dlret="0.000000",
                method="exchange_transfer_zero"),
         ending("D", "2018-07-09", ltd="2018-06-29", dlret="0.012000", source="last_sighting",
                terminal_value="20.000000")],
        [obs("AAA", "2012-06-29", "A"), obs("CCC", "2012-06-29", "C"), obs("DDD", "2012-06-29", "D")])


def test_one_row_per_ended_security_its_last_and_none_for_a_security_that_continues_itself():
    t = _run_tables()
    rows = {r["sec_id"]: r for r in delisting_rows(t, decide(t, {}))}
    assert set(rows) == {"A", "D"}
    assert set(last_endings(t.delistings)) == {"A", "D"}
    assert rows["D"]["dlret"] == "0.012000" and rows["D"]["last_trade_date"] == ""     # not an exchange print
    assert rows["D"]["verdict"] == "uncertain" and rows["D"]["terminal_value"] == "20.000000"


def test_a_continuation_names_its_successor_and_carries_no_value():
    t = _run_tables()
    a = {r["sec_id"]: r for r in delisting_rows(t, decide(t, {}))}["A"]
    assert (a["exit_kind"], a["continuation"], a["successor_sec_id"]) == ("exchange", True, "B")
    assert (a["dlret"], a["dlret_fill"], a["terminal_value"]) == ("", "", "")
    assert a["last_trade_date"] == "2015-03-02"


def test_the_seed_echo_keeps_every_observation_with_its_sec_id_and_verdict():
    t = _run_tables()
    rows = seed_rows(t, decide(t, {}))
    assert [(r["ticker"], r["sec_id"]) for r in rows] == [("AAA", "A"), ("CCC", "C"), ("DDD", "D")]
    assert {r["verdict"] for r in rows} <= {"confirmed", "uncertain"}
    assert set(rows[0]) == {"ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "sec_id", "verdict"}


def test_security_history_splits_an_interval_where_the_issuer_changes():
    t = tables([sec("S", cik="310158"), sec("Q", cik="5")],
               [iv("S", "MRK", "2008-01-02"), iv("Q", "QQQ", "2010-01-04", "2012-01-03")])
    rows = security_history_rows(t, {"S": [("2008-01-16", "64978"), ("2009-11-04", "310158")]})
    s = [(r["issuer_id"], r["start_date"], r["end_date"]) for r in rows if r["sec_id"] == "S"]
    assert s == [("64978", "2008-01-02", "2009-11-03"), ("310158", "2009-11-04", "")]
    q = [r for r in rows if r["sec_id"] == "Q"]
    assert [(r["issuer_id"], r["start_date"], r["end_date"]) for r in q] == [("5", "2010-01-04", "2012-01-03")]
    assert q[0]["security_name"] == "Q" and q[0]["share_class"] == "COMMON"


def test_security_history_leaves_out_what_it_is_told_to():
    t = tables([sec("S"), sec("X", observed=False)], [iv("S", "AAA", "2010-01-04"), iv("X", "XXX", "2015-01-02")])
    assert {r["sec_id"] for r in security_history_rows(t, {}, leave_out={"X"})} == {"S"}


def _sec_row(sec_id, cik, source, share_class="COMMON"):
    return {"sec_id": sec_id, "issuer_cik": cik, "share_class": share_class, "name": sec_id, "security_type": "",
            "observed": "true", "figi_source": source}


def test_id_changes_name_the_figi_that_now_holds_a_placeholders_issuer_and_class():
    baseline = [_sec_row("CIK100-COMMON", "100", "placeholder"), _sec_row("CIK200-COMMON", "200", "placeholder"),
                _sec_row("CIK300-COMMON", "300", "placeholder"), _sec_row("BBG000OLD001", "400", "cusip")]
    now = [_sec_row("BBG000NEW100", "100", "cusip"), _sec_row("BBG000AAA200", "200", "cusip"),
           _sec_row("BBG000BBB200", "200", "ticker"), _sec_row("CIK300-COMMON", "300", "placeholder")]
    assert id_change_rows(baseline, now, "2026-09-25") == [
        {"old_sec_id": "CIK100-COMMON", "new_sec_id": "BBG000NEW100", "changed_on": "2026-09-25",
         "issuer_cik": "100", "share_class": "COMMON"}]
    assert id_change_rows([], now, "2026-09-25") == []
```

In `tests/test_figi_resolution.py`, after the two `placeholder_id` asserts, add:

```python
def test_a_placeholder_is_built_from_a_class_code_only():
    assert placeholder_id(1, "SERIES A") == "CIK1-SERIES-A"
    with pytest.raises(ValueError):
        placeholder_id(1, "Class A Common Stock")
```

(add `import pytest` to that file if it lacks it).

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_contract.py tests/test_figi_resolution.py -q -o addopts=""`
Expected: `No module named 'delist_detection.contract'`, and `DID NOT RAISE` for the class text.

- [ ] **Step 3: Write `contract.py`**

Create `src/delist_detection/contract.py`:

```python
"""The contract (spec: Delist Library Reset, "The contract"; decisions 6, 7, 9,
10 and 12): the tables qlib_practice will read, built from the run's own tables
and verdicts and written under output/contract/ beside today's tables for one
release.

- security_history.csv (`security_history_rows`): one row per security per
  interval in which its ticker and its issuer CIK hold;
- delistings.csv (`delisting_rows`): one row per ended security, its last real
  ending; an earlier one is uncertain (`verdict`, `earlier_ending`);
- seeds.csv (`seed_rows`): every input observation with its sec_id and verdict;
- price_requests.csv: `price_requests.request_rows`;
- id_changes.csv (`id_change_rows`): the baseline run's placeholders that now
  hold a FIGI.

run_manifest.json carries store.CONTRACT_SCHEMA_VERSION. Pure."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from datetime import date, timedelta

from .exit_kind import ending_fields
from .lifecycle import Tables
from .verdict import Verdicts, published_last_trade_date, seed_key

ECHOED = ("ticker", "as_of", "name", "cusip", "pin_cik", "pin_sec_id", "sec_id")


def last_endings(delistings: Sequence[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    """Each security's last real ending (its successor is not itself), by delist
    date: the one contract/delistings.csv keeps (decision 12)."""
    out: dict[str, Mapping[str, str]] = {}
    for r in sorted((r for r in delistings if r["successor_sec_id"] != r["sec_id"]), key=lambda r: r["delist_date"]):
        out[r["sec_id"]] = r
    return out


def delisting_rows(tables: Tables, verdicts: Verdicts) -> list[dict[str, object]]:
    """contract/delistings.csv: one row per ended security (`exit_kind.ending_fields`,
    `verdict.published_last_trade_date`, its ending's verdict). A continuation
    carries no terminal value."""
    rows: list[dict[str, object]] = []
    for sid, r in last_endings(tables.delistings).items():
        f = ending_fields(r)
        rows.append({
            "sec_id": sid, "last_trade_date": published_last_trade_date(r), "exit_kind": f.exit_kind,
            "drop_reason": f.drop_reason, "continuation": f.continuation,
            "successor_sec_id": r["successor_sec_id"] if f.continuation else "",
            "ticker_successor_sec_id": r["ticker_successor_sec_id"], "dlret": f.dlret, "dlret_fill": f.dlret_fill,
            "terminal_value": "" if f.continuation else r["terminal_value"],
            "verdict": verdicts.endings[(sid, r["delist_date"])].word,
        })
    return rows


def seed_rows(tables: Tables, verdicts: Verdicts) -> list[dict[str, str]]:
    """contract/seeds.csv: every input observation (observation_map's input
    columns), its sec_id (blank when unplaced) and its verdict."""
    return [{**{c: r[c] for c in ECHOED}, "verdict": verdicts.seeds[seed_key(r)].word}
            for r in tables.observation_map]


def _issuer_on(timeline: Sequence[tuple[str, str]], day: str, default: str) -> str:
    if not timeline:
        return default
    cik = timeline[0][1]
    for since, c in timeline:
        if since <= day:
            cik = c
    return cik


def _day_before(iso: str) -> str:
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


def security_history_rows(tables: Tables, issuers: Mapping[str, Sequence[tuple[str, str]]],
                          leave_out: Collection[str] = ()) -> list[dict[str, str]]:
    """contract/security_history.csv: each ticker_history range, split where the
    issuer CIK in force changes. `issuers` is each security's issuer timeline
    (`issuer_in_force.issuer_changes`: [(from ISO date, CIK)], earliest first); a
    day before its first entry takes that entry's CIK, and a security with no
    timeline takes its securities.csv CIK. `leave_out` names securities not
    published (the merger acquirers the run adds)."""
    secs = {s["sec_id"]: s for s in tables.securities}
    out: list[dict[str, str]] = []
    for r in tables.ticker_history:
        sid = r["sec_id"]
        if sid in leave_out:
            continue
        s, timeline = secs.get(sid, {}), issuers.get(sid, ())
        start, end = r["valid_from"], r["valid_to"]
        bounds = [start, *(d for d, _ in timeline[1:] if start < d and (not end or d <= end))]
        for i, lo in enumerate(bounds):
            hi = _day_before(bounds[i + 1]) if i + 1 < len(bounds) else end
            out.append({"sec_id": sid, "issuer_id": _issuer_on(timeline, lo, s.get("issuer_cik", "")),
                        "start_date": lo, "end_date": hi, "ticker": r["ticker"],
                        "security_name": s.get("name", ""), "share_class": s.get("share_class", "")})
    return out


def id_change_rows(baseline: Sequence[Mapping[str, str]], securities: Sequence[Mapping[str, str]],
                   changed_on: str) -> list[dict[str, str]]:
    """contract/id_changes.csv (decision 7): each placeholder of the baseline run
    (its securities.csv rows) that this run no longer has and whose issuer and
    class exactly one FIGI security of this run holds. Not cumulative: git keeps
    the earlier files."""
    now = {s["sec_id"] for s in securities}
    figis: dict[tuple[str, str], set[str]] = defaultdict(set)
    for s in securities:
        if s["figi_source"] != "placeholder" and s["issuer_cik"]:
            figis[(s["issuer_cik"], s["share_class"])].add(s["sec_id"])
    rows = []
    for b in baseline:
        if b["figi_source"] != "placeholder" or b["sec_id"] in now:
            continue
        found = figis.get((b["issuer_cik"], b["share_class"]), set())
        if len(found) == 1:
            rows.append({"old_sec_id": b["sec_id"], "new_sec_id": next(iter(found)), "changed_on": changed_on,
                         "issuer_cik": b["issuer_cik"], "share_class": b["share_class"]})
    return rows
```

In `src/delist_detection/figi_resolution.py`, replace `placeholder_id` with:

```python
SHARE_CLASS_CODE = re.compile(r"COMMON|CLASS [A-Z]|SERIES [A-Z0-9]")     # share_class_from_name's values


def placeholder_id(cik: int, share_class: str | None) -> str:
    """`CIK<cik>-<CLASS>` from a class code (decision 7): COMMON, CLASS X or
    SERIES X, as `share_class_from_name` gives it. Free class text could give one
    class two IDs, so anything else raises ValueError."""
    code = (share_class or "COMMON").upper().strip()
    if not SHARE_CLASS_CODE.fullmatch(code):
        raise ValueError(f"placeholder_id: {share_class!r} is not a class code")
    return f"CIK{int(cik)}-{code.replace(' ', '-')}"
```

- [ ] **Step 4: Run the tests**

Run the two files from Step 2 — all pass. Full suite: expected `1617 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/contract.py src/delist_detection/figi_resolution.py tests/test_contract.py \
        tests/test_figi_resolution.py
git commit -m "contract: security_history, delistings, seed echo and id_changes rows (reset-3)"
```

---

### Task 5: `issuer_in_force` — the issuer CIK on each sighting's date

**Files:**
- Create: `src/delist_detection/issuer_in_force.py`
- Modify: `src/delist_detection/ticker_resolver.py` (`TickerResolver.name_index`)
- Test: `tests/test_issuer_in_force.py` (new)

**Interfaces:**
- Consumes: `evidence.name_at`, `evidence.parse_day`, `names.names_agree`, `cik_lookup.CikNameIndex`.
- Produces: `issuer_in_force.Sighting(sec_id, day, name, cik)`, `in_force(s, submissions, exact_names) -> str`,
  `agreeing_since(sub, name, on) -> date | None`, `issuer_changes(sightings, submissions, exact_names) ->
  dict[str, list[tuple[str, str]]]`; `TickerResolver.name_index() -> CikNameIndex | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_issuer_in_force.py`:

```python
from datetime import date

from delist_detection.cik_lookup import CikNameIndex
from delist_detection.issuer_in_force import Sighting, agreeing_since, in_force, issuer_changes
from delist_detection.ticker_resolver import TickerResolver

OLD_MERCK = {"name": "MERCK SHARP & DOHME CORP",
             "formerNames": [{"name": "MERCK & CO INC", "from": "1994-01-01T00:00:00.000Z",
                              "to": "2009-11-03T00:00:00.000Z"}]}
NEW_MERCK = {"name": "Merck & Co., Inc.",
             "formerNames": [{"name": "SCHERING PLOUGH CORP", "from": "1994-01-01T00:00:00.000Z",
                              "to": "2009-11-03T00:00:00.000Z"}]}
SUBS = {64978: OLD_MERCK, 310158: NEW_MERCK}


def submissions(cik):
    return SUBS.get(cik)


def exact_names(name):
    return [64978, 310158] if name == "MERCK & CO INC" else []


def test_a_sighting_takes_the_one_cik_that_carried_its_name_that_day():
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "310158"), submissions, exact_names) == "64978"
    assert in_force(Sighting("S", "2012-06-29", "MERCK & CO INC", "310158"), submissions, exact_names) == "310158"


def test_without_one_agreeing_alternative_the_era_cik_stays():
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "310158"), submissions, lambda n: []) == "310158"
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", "999"), lambda c: None, exact_names) == "999"
    assert in_force(Sighting("S", "2008-06-30", "MERCK & CO INC", ""), submissions, exact_names) == ""


def test_agreeing_since_is_the_first_day_of_the_agreeing_name():
    assert agreeing_since(NEW_MERCK, "MERCK & CO INC", date(2012, 6, 29)) == date(2009, 11, 4)
    assert agreeing_since(OLD_MERCK, "MERCK & CO INC", date(2008, 6, 30)) == date(1994, 1, 1)
    assert agreeing_since(NEW_MERCK, "MERCK & CO INC", date(2008, 6, 30)) is None


def test_the_timeline_changes_on_the_day_the_new_issuer_took_the_name():
    rows = [Sighting("S", d, "MERCK & CO INC", "310158") for d in ("2008-01-16", "2009-06-30", "2010-06-30")]
    assert issuer_changes(rows, submissions, exact_names) == {"S": [("2008-01-16", "64978"),
                                                                    ("2009-11-04", "310158")]}


def test_a_change_date_never_falls_on_or_before_the_last_sighting_under_the_old_issuer():
    rows = [Sighting("S", "2009-12-31", "MERCK & CO INC", "64978"), Sighting("S", "2010-06-30", "MERCK & CO INC", "310158")]
    subs = {64978: {"name": "MERCK & CO INC", "formerNames": []}, 310158: NEW_MERCK}
    out = issuer_changes(rows, subs.get, lambda n: [])
    assert out == {"S": [("2009-12-31", "64978"), ("2010-01-01", "310158")]}


def test_the_resolver_hands_out_its_name_index(fake_edgar):
    index = CikNameIndex.from_text("MERCK & CO INC:0000064978:\n")
    assert TickerResolver(fake_edgar, name_index=index).name_index() is index
    assert TickerResolver(fake_edgar).name_index() is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_issuer_in_force.py -q -o addopts=""`
Expected: `No module named 'delist_detection.issuer_in_force'`.

- [ ] **Step 3: Implement**

Create `src/delist_detection/issuer_in_force.py`:

```python
"""The issuer CIK in force on each sighting of a security (spec: security_history's
`issuer_id`, "the CIK in force on the interval"; golden MRK-2008).

A sighting keeps its era's CIK when that CIK's EDGAR name on the sighting's date
(`evidence.name_at`) agrees with the observed name (`names.names_agree`). When it
does not, the one other CIK that SEC's name index lists under exactly the
observed name, and whose EDGAR name on that date agrees, is the issuer in force:
Merck's 2008 sightings resolved to CIK 310158, which was Schering-Plough until
November 2009, while old Merck & Co (CIK 64978) carried the name then. No such
CIK, or two, keeps the era's.

`issuer_changes` turns the sightings into each security's issuer timeline. A
change is dated on the first day the new CIK carried an agreeing name
(`agreeing_since`), kept after the last sighting under the old CIK and no later
than the first sighting under the new one. EDGAR is reached only through the
injected `submissions` and `exact_names` callables."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .evidence import name_at, parse_day
from .names import names_agree

Submissions = Callable[[int], "dict | None"]      # a CIK's submissions JSON, None when it cannot be read
ExactNames = Callable[[str], Sequence[int]]       # the CIKs the name index lists under exactly this name


@dataclass(frozen=True)
class Sighting:
    sec_id: str
    day: str          # ISO date
    name: str         # the observed name
    cik: str          # the era's CIK, "" when unknown


def in_force(s: Sighting, submissions: Submissions, exact_names: ExactNames) -> str:
    """The issuer CIK in force on the sighting's date (see the module docstring)."""
    if not s.cik or not s.name:
        return s.cik
    on = date.fromisoformat(s.day)
    sub = submissions(int(s.cik))
    if not isinstance(sub, dict) or names_agree(name_at(sub, on), s.name):
        return s.cik
    agreeing = []
    for cik in sorted(set(exact_names(s.name)) - {int(s.cik)}):
        other = submissions(cik)
        if isinstance(other, dict) and names_agree(name_at(other, on), s.name):
            agreeing.append(cik)
    return str(agreeing[0]) if len(agreeing) == 1 else s.cik


def _spans(sub: dict) -> list[tuple[date | None, date | None, str]]:
    """Each EDGAR name with the days it was in force, earliest first; the current
    name runs from the day after the last former name ended."""
    former = []
    for fn in sub.get("formerNames") or []:
        if isinstance(fn, dict):
            lo, hi = parse_day(fn.get("from")), parse_day(fn.get("to"))
            if lo and hi:
                former.append((lo, hi, fn.get("name") or ""))
    former.sort()
    start = former[-1][1] + timedelta(days=1) if former else None
    return [*former, (start, None, sub.get("name") or "")]


def agreeing_since(sub: dict, name: str, on: date) -> date | None:
    """The first day of the unbroken run of EDGAR names, ending with the one in
    force on `on`, that agree with `name`; None when the name in force on `on`
    does not agree, or the run reaches back past every dated name."""
    spans = _spans(sub)
    i = next((k for k, (lo, hi, _) in enumerate(spans)
              if (lo is None or lo <= on) and (hi is None or on <= hi)), None)
    if i is None or not names_agree(spans[i][2], name):
        return None
    while i > 0 and names_agree(spans[i - 1][2], name):
        i -= 1
    return spans[i][0]


def issuer_changes(sightings: Iterable[Sighting], submissions: Submissions,
                   exact_names: ExactNames) -> dict[str, list[tuple[str, str]]]:
    """sec_id -> [(from ISO date, CIK)], earliest first: the CIK in force on the
    security's first sighting with one, then each change. A sighting with no CIK
    changes nothing."""
    by_sec: dict[str, list[Sighting]] = defaultdict(list)
    for s in sightings:
        by_sec[s.sec_id].append(s)
    out: dict[str, list[tuple[str, str]]] = {}
    for sid, rows in by_sec.items():
        rows.sort(key=lambda s: s.day)
        timeline: list[tuple[str, str]] = []
        last_day = ""
        for s in rows:
            cik = in_force(s, submissions, exact_names)
            if not cik:
                continue
            if not timeline:
                timeline.append((s.day, cik))
            elif cik != timeline[-1][1]:
                sub = submissions(int(cik))
                since = agreeing_since(sub, s.name, date.fromisoformat(s.day)) if isinstance(sub, dict) else None
                after = (date.fromisoformat(last_day) + timedelta(days=1)).isoformat()
                timeline.append((min(max(since.isoformat() if since else s.day, after), s.day), cik))
            last_day = s.day
        if timeline:
            out[sid] = timeline
    return out
```

In `src/delist_detection/ticker_resolver.py`, add after the `_index` method:

```python
    def name_index(self) -> CikNameIndex | None:
        """SEC's name index (cik-lookup-data.txt), loaded on first use; None without
        one or when it cannot be loaded. A refusal (`fatal.FATAL`) stops the run."""
        return self._index()
```

- [ ] **Step 4: Run the tests**

Run the test file — all pass. Full suite: expected `1623 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/issuer_in_force.py src/delist_detection/ticker_resolver.py tests/test_issuer_in_force.py
git commit -m "issuer_in_force: the issuer CIK on each sighting's date (reset-3)"
```

---

### Task 6: `price_requests` — the requests and the caller's answers

**Files:**
- Create: `src/delist_detection/price_requests.py`
- Test: `tests/test_price_requests.py` (new)

**Interfaces:**
- Consumes: `store.DelistingKey`, `store.PRICE_REQUEST_COLUMNS`, `reconstruction.OverrideFileError`,
  `reconstruction.for_delisting`, `observations.normalize_ticker`, `trading_calendar.next_trading_day`.
- Produces: `LAST_CLOSE`, `RECEIVED_CLOSE`, `OTC_PRINT`, `KINDS`, `PriceKey(sec_id, last_trade_date, kind,
  lookup_ticker, date)`, `key_of(row) -> PriceKey`, `stock_legs(endings, llm_terms, merger_terms, acquirer_ids) ->
  dict[DelistingKey, tuple[str, str]]`, `request_rows(contract_rows, endings, legs) -> list[dict]`,
  `load_answers(path) -> dict[PriceKey, float]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_price_requests.py`:

```python
from types import SimpleNamespace

import pytest

from delist_detection.price_requests import (LAST_CLOSE, RECEIVED_CLOSE, PriceKey, key_of, load_answers,
                                             request_rows, stock_legs)
from delist_detection.reconstruction import OverrideFileError
from delist_detection.store import DelistingKey
from lifecycle_tables import ending


def test_requests_ask_the_last_close_and_a_stock_legs_received_close():
    endings = {"A": ending("A", "2018-12-10", ltd="2018-11-28", ticker="AET"),
               "B": ending("B", "2019-01-10", ltd="2019-01-03", ticker="BBB"),
               "C": ending("C", "2015-03-10", "exchange_transfer", successor="Z", ltd="2015-03-02", ticker="CCC")}
    contract = [{"sec_id": "A", "last_trade_date": "2018-11-28", "continuation": False},
                {"sec_id": "B", "last_trade_date": "", "continuation": False},
                {"sec_id": "C", "last_trade_date": "2015-03-02", "continuation": True}]
    legs = {DelistingKey("A", "2018-12-10"): ("CVS", "BBG000BGRY34")}
    assert request_rows(contract, endings, legs) == [
        {"sec_id": "A", "last_trade_date": "2018-11-28", "kind": LAST_CLOSE, "lookup_sec_id": "A",
         "lookup_ticker": "AET", "date": "2018-11-28"},
        {"sec_id": "A", "last_trade_date": "2018-11-28", "kind": RECEIVED_CLOSE, "lookup_sec_id": "BBG000BGRY34",
         "lookup_ticker": "CVS", "date": "2018-11-29"}]


def test_a_stock_leg_comes_from_the_llm_terms_unless_the_caller_gave_terms():
    a, b = ending("A", "2018-12-10"), ending("B", "2019-01-10")
    llm = {DelistingKey("A", "2018-12-10"): SimpleNamespace(stock_ratio=0.8378, acquirer_ticker="cvs"),
           DelistingKey("B", "2019-01-10"): SimpleNamespace(stock_ratio=0.5, acquirer_ticker="XYZ")}
    given = {"B": {"cash_per_share": 10.0, "stock_ratio": 0.5, "acquirer_price": 20.0, "acquirer_ticker": "XYZ"}}
    assert stock_legs([a, b], llm, given, {DelistingKey("A", "2018-12-10"): "BBG000BGRY34"}) == {
        DelistingKey("A", "2018-12-10"): ("CVS", "BBG000BGRY34")}


def _answers(tmp_path, *rows, header="sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date,price"):
    p = tmp_path / "answers.csv"
    p.write_text("\n".join([header, *rows]) + "\n")
    return p


def test_answers_are_read_by_request_and_a_blank_price_is_unanswered(tmp_path):
    p = _answers(tmp_path, "A,2018-11-28,last_close,A,AET,2018-11-28,191.32",
                 "A,2018-11-28,received_close,BBG000BGRY34,CVS,2018-11-29,")
    assert load_answers(p) == {PriceKey("A", "2018-11-28", LAST_CLOSE, "AET", "2018-11-28"): 191.32}
    assert key_of({"sec_id": "A", "last_trade_date": "2018-11-28", "kind": LAST_CLOSE, "lookup_sec_id": "A",
                   "lookup_ticker": "AET", "date": "2018-11-28"}) in load_answers(p)


@pytest.mark.parametrize("row,message", [
    ("A,2018-11-28,last_close,A,AET,2018-11-28,abc", "not a number"),
    ("A,2018-11-28,last_close,A,AET,2018-11-28,-1", "not positive"),
    ("A,2018-11-28,closing,A,AET,2018-11-28,191", "kind"),
])
def test_a_bad_answer_names_its_file_and_line(tmp_path, row, message):
    with pytest.raises(OverrideFileError, match=rf"answers.csv:2: .*{message}"):
        load_answers(_answers(tmp_path, row))


def test_an_answers_file_without_the_price_column_is_refused(tmp_path):
    with pytest.raises(OverrideFileError, match="price"):
        load_answers(_answers(tmp_path, "A,2018-11-28,last_close,A,AET,2018-11-28",
                              header="sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date"))
```

(`ending(..., ticker="AET")` passes `ticker` through its `**cells`.)

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_price_requests.py -q -o addopts=""`
Expected: `No module named 'delist_detection.price_requests'`.

- [ ] **Step 3: Implement**

Create `src/delist_detection/price_requests.py`:

```python
"""price_requests.csv (spec: "What crosses the boundary", Out then In): the
prices the library asks the caller's store for, and the caller's answers read
back.

One `last_close` per contract ending with a last trade date that is not a
continuation (the security's own close on that day), and one `received_close`
per stock leg the library read from a filing (the acquirer's close on the
ex-date, the trading day after the last trade). `otc_print` requests start with
reset-4f. The answers file is this file plus a `price` column (raw as-traded
closes). An answered last close replaces the library's fails-to-deliver close
and an answered received close the acquirer price, so a second run with the
answers changes values only. An answer is matched on `PriceKey`;
`lookup_sec_id` is informational."""
from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

from .observations import normalize_ticker
from .reconstruction import OverrideFileError, for_delisting
from .store import PRICE_REQUEST_COLUMNS, DelistingKey
from .trading_calendar import next_trading_day

LAST_CLOSE, RECEIVED_CLOSE, OTC_PRINT = "last_close", "received_close", "otc_print"
KINDS = (LAST_CLOSE, RECEIVED_CLOSE, OTC_PRINT)


class PriceKey(NamedTuple):
    sec_id: str
    last_trade_date: str
    kind: str
    lookup_ticker: str
    date: str


def key_of(row: Mapping[str, Any]) -> PriceKey:
    return PriceKey(row["sec_id"], row["last_trade_date"], row["kind"], row["lookup_ticker"], row["date"])


def stock_legs(endings: Sequence[Mapping[str, str]], llm_terms: Mapping[DelistingKey, Any],
               merger_terms: Mapping, acquirer_ids: Mapping[DelistingKey, str]
               ) -> dict[DelistingKey, tuple[str, str]]:
    """The acquirer (ticker, sec_id) of each ending whose LLM terms read a stock
    ratio and an acquirer ticker. A --merger-terms row for the ending wins and
    carries its own acquirer price, so it asks nothing. Read before the payout
    gate's verdict, so an answer that changes the gate does not change the
    requests; the acquirer sec_id is "" when the run found none."""
    out: dict[DelistingKey, tuple[str, str]] = {}
    for r in endings:
        key = DelistingKey(r["sec_id"], r["delist_date"])
        if for_delisting(merger_terms, key):
            continue
        t = llm_terms.get(key)
        if t is not None and t.stock_ratio and t.acquirer_ticker:
            out[key] = (normalize_ticker(t.acquirer_ticker), acquirer_ids.get(key, ""))
    return out


def request_rows(contract_rows: Sequence[Mapping[str, Any]], endings: Mapping[str, Mapping[str, str]],
                 legs: Mapping[DelistingKey, tuple[str, str]]) -> list[dict[str, str]]:
    """price_requests.csv: per contract ending (`endings`: each sec_id's last real
    delistings.csv row, contract.last_endings) with a last trade date and no
    continuation, its last close, and the received close of its stock leg."""
    out: list[dict[str, str]] = []
    for c in contract_rows:
        ltd = c["last_trade_date"]
        if not ltd or c["continuation"] is True:
            continue
        r = endings[c["sec_id"]]
        out.append({"sec_id": c["sec_id"], "last_trade_date": ltd, "kind": LAST_CLOSE,
                    "lookup_sec_id": c["sec_id"], "lookup_ticker": r["ticker"], "date": ltd})
        leg = legs.get(DelistingKey(r["sec_id"], r["delist_date"]))
        if leg is not None:
            out.append({"sec_id": c["sec_id"], "last_trade_date": ltd, "kind": RECEIVED_CLOSE,
                        "lookup_sec_id": leg[1], "lookup_ticker": leg[0],
                        "date": next_trading_day(date.fromisoformat(ltd)).isoformat()})
    return out


def load_answers(path: str | Path) -> dict[PriceKey, float]:
    """The answers file (--price-answers): price_requests.csv's columns plus
    `price`. A blank price is unanswered and skipped. A missing column, a kind
    not in KINDS, or a price that is not a positive number raises
    OverrideFileError naming the file and line."""
    p = Path(path)
    out: dict[PriceKey, float] = {}
    with p.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in (*PRICE_REQUEST_COLUMNS, "price") if c not in (reader.fieldnames or [])]
        if missing:
            raise OverrideFileError(f"{p}: missing column(s) {', '.join(missing)}")
        for line, row in enumerate(reader, start=2):
            where = f"{p}:{line}"
            if row["kind"] not in KINDS:
                raise OverrideFileError(f"{where}: kind {row['kind']!r} is not one of {', '.join(KINDS)}")
            cell = (row["price"] or "").strip()
            if not cell:
                continue
            try:
                price = float(cell)
            except ValueError:
                raise OverrideFileError(f"{where}: price {cell!r} is not a number") from None
            if math.isnan(price) or price <= 0:
                raise OverrideFileError(f"{where}: price {cell!r} is not positive")
            out[key_of(row)] = price
    return out
```

(If importing `reconstruction` here creates an import cycle, move nothing: report it as NEEDS_CONTEXT.)

- [ ] **Step 4: Run the tests**

Run the test file — all pass. Full suite: expected `1630 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/price_requests.py tests/test_price_requests.py
git commit -m "price_requests: the requests and the caller's answers (reset-3)"
```

---

### Task 7: Pipeline stage 10g and the CLI — every run writes the contract

**Files:**
- Modify: `src/delist_detection/pipeline.py`
- Modify: `scripts/classify_universe.py`
- Test: `tests/test_pipeline.py`, `tests/test_pipeline_prefetch.py`, `tests/test_run_provenance.py`,
  `tests/test_classify_universe_cli.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces: `pipeline.run(..., id_baseline=())`; stage 10g `_contract` (with `_issuers_in_force`), the scorecard as
  10h; the manifest stage `"issuers in force"`; CLI `--id-baseline` and the line
  `Contract (contract/): N security intervals, E endings, R price requests, I id changes`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
def test_every_run_writes_the_contract_beside_todays_tables(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    summary = run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None)
    for name in ("security_history", "contract_delistings", "seeds", "price_requests", "id_changes"):
        assert table_path(tmp_path, name).exists() and name in summary.counts
    ended = {r["sec_id"]: r for r in read_table("contract_delistings", table_path(tmp_path, "contract_delistings"))}
    assert ended["BBG000FJLFX8"]["exit_kind"] == "merger"
    assert ended["BBG000FJLFX8"]["verdict"] in ("confirmed", "uncertain")
    seeds = read_table("seeds", table_path(tmp_path, "seeds"))
    assert len(seeds) == len(read_table("observation_map", table_path(tmp_path, "observation_map")))
    hist = read_table("security_history", table_path(tmp_path, "security_history"))
    assert {r["sec_id"] for r in hist} >= {"BBG000FJLFX8", "BBG000LIVE01"}
    assert {r["issuer_id"] for r in hist if r["sec_id"] == "BBG000FJLFX8"} == {"1122304"}
    assert json.loads((tmp_path / "run_manifest.json").read_text())["schema_version"] == 1


def test_id_changes_compare_the_run_with_a_baseline(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    baseline = [{"sec_id": "CIK1122304-COMMON", "issuer_cik": "1122304", "share_class": "COMMON",
                 "name": "AETNA INC", "security_type": "", "observed": "true", "figi_source": "placeholder"}]
    run(index, clients, Overrides(), out_dir=tmp_path, log=lambda *_: None, id_baseline=baseline)
    rows = read_table("id_changes", table_path(tmp_path, "id_changes"))
    assert [(r["old_sec_id"], r["new_sec_id"]) for r in rows] == [("CIK1122304-COMMON", "BBG000FJLFX8")]
```

(Add `import json` to the file's imports if it is missing.) In `test_run_is_deterministic`, add the five contract
table names to the names it compares. In `tests/test_pipeline_prefetch.py`, the byte-identity test at the bottom
(`csv1`/`csvn`) must compare the contract files too: replace its two `glob("*.csv")` comprehensions with
`{str(p.relative_to(tmp_path / "out1")): p.read_bytes() for p in (tmp_path / "out1").rglob("*.csv")}` (and `outn`
likewise) and change `len(csv1) == 9` to `len(csv1) == 14`, updating the comment to name the contract's five
files. In `tests/test_run_provenance.py`, add `"issuers in force"` to the expected stage set. In
`tests/test_classify_universe_cli.py`, give `_FakeSummary.counts` the five contract names (0 each) if it does not
read `.get`, and add:

```python
def test_a_bad_id_baseline_exits_2(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "securities.csv"
    bad.write_text("sec_id,oops\nX,1\n")
    rc = _main_with(monkeypatch, tmp_path, "--id-baseline", str(bad))
    assert rc == 2 and "securities.csv" in capsys.readouterr().err
```

using the file's existing helper that runs `main()` with an argument list (`_main_with` is the name used here; if
the file's helper has another name or signature, use it and say so in the report).

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_pipeline_prefetch.py tests/test_run_provenance.py tests/test_classify_universe_cli.py -q -o addopts="" -x`
Expected: the new pipeline test fails (no contract files), then the others as each is reached.

- [ ] **Step 3: Wire the pipeline**

In `src/delist_detection/pipeline.py`:

1. Imports: add

```python
from .contract import delisting_rows as contract_delisting_rows
from .contract import id_change_rows, last_endings, security_history_rows, seed_rows
from .issuer_in_force import Sighting as IssuerSighting
from .issuer_in_force import issuer_changes
from .price_requests import key_of, request_rows, stock_legs
from .verdict import Verdicts
```

   and add `Mapping` to the `from collections.abc import ...` line.
2. After `_as_read`'s `rows` helper, return the contract's security_history too:

```python
    return Tables(rows("securities"), rows("ticker_history"), rows("delistings"), rows("observation_map"),
                  rows("review"), rows("uncertain") if "uncertain" in tables else None,
                  rows("security_history") if "security_history" in tables else None)
```

3. Add, after `_ticker_evidence`:

```python
def _issuers_in_force(ctx: _RunContext, observation_map: Sequence[Mapping[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Each security's issuer timeline (issuer_in_force.issuer_changes) from its
    sightings: every observation_map row with a sec_id, except a conflict (two
    names that day). A submissions read that fails keeps the era's CIK; a refusal
    (`fatal.FATAL`) stops the run. Without a name index (a test double's
    resolver), every sighting keeps its era's CIK."""
    edgar, memo = ctx.clients.edgar, {}

    def submissions(cik: int):
        if cik not in memo:
            try:
                memo[cik] = edgar.submissions(cik)
            except FATAL:
                raise
            except requests.RequestException:
                memo[cik] = None
        return memo[cik]

    index_of = getattr(ctx.clients.resolver, "name_index", None)
    index = index_of() if callable(index_of) else None

    def exact_names(name: str) -> list[int]:
        return [h.cik for h in index.split_search(name)[0]] if index is not None else []

    mark = ctx.meter.start()
    out = issuer_changes((IssuerSighting(r["sec_id"], r["as_of"], r["name"], r["issuer_cik"])
                          for r in observation_map if r["sec_id"] and r["status"] != "conflict"),
                         submissions, exact_names)
    ctx.meter.done("issuers in force", mark)
    return out


def _contract(ctx: _RunContext, read: Tables, verdicts: Verdicts, payouts: _Payouts, successor_ids: set[str],
              overrides: Overrides, id_baseline: Sequence[Mapping[str, str]]) -> dict[str, list[dict]]:
    """10g. The contract (contract.py), written under contract/ beside today's
    tables (decision 6): security_history with each interval's issuer in force
    (`_issuers_in_force`), leaving out the merger acquirers the run adds;
    delistings, one row per ended security; the seed echo; the price requests;
    and the placeholders of `id_baseline` (a securities.csv) that now hold a FIGI."""
    issuers = _issuers_in_force(ctx, read.observation_map)
    ended = contract_delisting_rows(read, verdicts)
    endings = last_endings(read.delistings)
    legs = stock_legs(list(endings.values()), payouts.llm_terms, overrides.merger_terms, payouts.acquirer_ids)
    return {
        "security_history": security_history_rows(read, issuers, leave_out=set(payouts.added) - successor_ids),
        "contract_delistings": ended,
        "seeds": seed_rows(read, verdicts),
        "price_requests": request_rows(ended, endings, legs),
        "id_changes": id_change_rows(id_baseline, read.securities, ctx.as_of.isoformat()),
    }
```

4. In `_scorecard`'s docstring, change `10g.` to `10h.`.
5. In `_run`, add the parameter `id_baseline: Sequence[Mapping[str, str]] = ()` after `scorecard`, and replace

```python
    tables["uncertain"] = verdicts.uncertain_rows()
    card = _scorecard(ctx, _as_read(tables), scorecard, limit)                                     # 10g
```

   with

```python
    tables["uncertain"] = verdicts.uncertain_rows()
    tables.update(_contract(ctx, _as_read(tables), verdicts, payouts, set(successors.added), overrides,
                            id_baseline))                                                          # 10g
    card = _scorecard(ctx, _as_read(tables), scorecard, limit)                                     # 10h
```

6. In `run`, add the parameter `id_baseline: Sequence[Mapping[str, str]] = ()` (after `scorecard`) and pass
   `id_baseline=id_baseline` to `_run`. In its docstring, change "Observations -> the eight tables under `out_dir`"
   to "Observations -> the nine tables under `out_dir` and the contract under `out_dir`/contract/ (contract.py;
   `id_baseline`: the securities.csv rows id_changes.csv compares with)".

In `scripts/classify_universe.py`:

1. Add `from delist_detection.store import read_table` to the imports.
2. In `build_parser`, after `--recoveries`, add:

```python
    p.add_argument("--id-baseline", default=None,
                   help="securities.csv to list placeholder->FIGI changes against in contract/id_changes.csv "
                        "(default: OUTPUT_DIR/securities.csv when it exists)")
```

3. Add, after `read_inputs`:

```python
def read_id_baseline(args: argparse.Namespace) -> list[dict[str, str]]:
    """The securities.csv rows contract/id_changes.csv compares with: --id-baseline,
    else the output folder's own when it exists (read before the run replaces it),
    else none. A file that is not a securities.csv raises OverrideFileError."""
    path = Path(args.id_baseline) if args.id_baseline else Path(args.output_dir) / "securities.csv"
    if args.id_baseline is None and not path.exists():
        return []
    try:
        return read_table("securities", path)
    except ValueError as exc:
        raise OverrideFileError(str(exc)) from None
```

4. In `main`, inside the `try` that calls `read_inputs`, add `id_baseline = read_id_baseline(args)` after it, pass
   `id_baseline=id_baseline` to `run(...)`, and after the `Uncertain (uncertain.csv): ...` print add:

```python
    c = summary.counts
    print(f"Contract (contract/): {c.get('security_history', 0)} security intervals, "
          f"{c.get('contract_delistings', 0)} endings, {c.get('price_requests', 0)} price requests, "
          f"{c.get('id_changes', 0)} id changes")
```

5. In the module docstring's list of written files, add `contract/{security_history,delistings,seeds,
   price_requests,id_changes}.csv`.

- [ ] **Step 4: Run the tests**

Run the four files from Step 2 — all pass. Full suite: expected `1633 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_pipeline.py \
        tests/test_pipeline_prefetch.py tests/test_run_provenance.py tests/test_classify_universe_cli.py
git commit -m "Every run writes the contract under contract/ (stage 10g); scorecard is 10h (reset-3)"
```

---

### Task 8: Price answers — a second run changes values only

**Files:**
- Modify: `src/delist_detection/pipeline.py` (`Overrides`, stage 6b, `_gate`, `_contract`)
- Modify: `scripts/classify_universe.py` (`--price-answers`)
- Test: `tests/test_pipeline.py`, `tests/test_classify_universe_cli.py`

**Interfaces:**
- Consumes: `price_requests.load_answers`, `key_of`, `LAST_CLOSE`, `RECEIVED_CLOSE`, `PriceKey`.
- Produces: `Overrides.price_answers` (`PriceKey -> float`), `Overrides.acquirer_prices`
  (`DelistingKey -> (ticker, price)`), `pipeline._apply_price_answers`, CLI `--price-answers PATH`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
def test_price_answers_change_value_columns_only(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    first = tmp_path / "first"
    run(index, clients, Overrides(), out_dir=first, log=lambda *_: None)
    requests = read_table("price_requests", table_path(first, "price_requests"))
    ask = next(r for r in requests if r["sec_id"] == "BBG000FJLFX8" and r["kind"] == "last_close")
    answered = {key_of(ask): 191.32}
    index, clients = _clients(fake_edgar)
    second = tmp_path / "second"
    run(index, clients, Overrides(price_answers=answered), out_dir=second, log=lambda *_: None)
    aet = next(r for r in read_table("delistings", table_path(second, "delistings")) if r["sec_id"] == "BBG000FJLFX8")
    assert aet["last_trade_close"] == "191.320000"
    for name in ("securities", "ticker_history", "observation_map", "security_history", "seeds", "price_requests"):
        assert table_path(first, name).read_bytes() == table_path(second, name).read_bytes(), name


def test_an_answer_to_no_request_stops_the_run_before_anything_is_written(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    stray = {PriceKey("BBG000FJLFX8", "2001-01-02", "last_close", "AET", "2001-01-02"): 10.0}
    with pytest.raises(OverrideFileError, match="answer no request"):
        run(index, clients, Overrides(price_answers=stray), out_dir=tmp_path, log=lambda *_: None)
    assert not list(tmp_path.rglob("*.csv"))


def test_a_last_close_given_twice_stops_the_run(fake_edgar, tmp_path):
    index, clients = _clients(fake_edgar)
    first = tmp_path / "first"
    run(index, clients, Overrides(), out_dir=first, log=lambda *_: None)
    ask = next(r for r in read_table("price_requests", table_path(first, "price_requests"))
               if r["sec_id"] == "BBG000FJLFX8" and r["kind"] == "last_close")
    index, clients = _clients(fake_edgar)
    with pytest.raises(OverrideFileError, match="both give the last close"):
        run(index, clients, Overrides(last_trade_closes={"BBG000FJLFX8": 190.0}, price_answers={key_of(ask): 191.32}),
            out_dir=tmp_path / "second", log=lambda *_: None)
```

(import `key_of`, `PriceKey` from `delist_detection.price_requests` and `OverrideFileError` from
`delist_detection.reconstruction` if the file does not already). If AET's ending has no published last trade date
in this fixture (so no `last_close` request exists), say so in the report as NEEDS_CONTEXT instead of changing the
fixture.

Add to `tests/test_classify_universe_cli.py`:

```python
def test_a_bad_price_answers_file_exits_2(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "answers.csv"
    bad.write_text("sec_id,last_trade_date,kind,lookup_sec_id,lookup_ticker,date,price\nA,2018-11-28,last_close,A,AET,2018-11-28,abc\n")
    rc = _main_with(monkeypatch, tmp_path, "--price-answers", str(bad))
    assert rc == 2 and "answers.csv:2" in capsys.readouterr().err
```

(same helper note as Task 7.)

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_pipeline.py tests/test_classify_universe_cli.py -q -o addopts=""`
Expected: `Overrides` has no `price_answers`; the CLI does not know `--price-answers`.

- [ ] **Step 3: Implement**

In `src/delist_detection/pipeline.py`:

1. Add to `Overrides`:

```python
    price_answers: dict = field(default_factory=dict)      # price_requests.PriceKey -> price (--price-answers)
    acquirer_prices: dict = field(default_factory=dict)    # DelistingKey -> (acquirer ticker, price), from price_answers
```

2. Imports: add `replace` to `from dataclasses import ...`; extend the `price_requests` import with
   `LAST_CLOSE, RECEIVED_CLOSE`.
3. After `_check_overrides`, add:

```python
def _apply_price_answers(overrides: Overrides, delistings: list[Delisting]) -> Overrides:
    """6b. The caller's price answers (--price-answers) as this run's overrides: a
    last_close answer is the last-trade close of the delisting of its sec_id
    whose last trade day it names, a received_close answer that delisting's
    acquirer price. A last close --last-trade-closes also gives stops the run
    (OverrideFileError). An answer whose delisting this run does not have is
    refused at stage 10g with every other answer to no request."""
    if not overrides.price_answers:
        return overrides
    by_day = {(e.sec_id, e.last_trade.day.isoformat()): e for e in delistings if e.last_trade.day is not None}
    closes, prices, twice = dict(overrides.last_trade_closes), {}, []
    for k, price in overrides.price_answers.items():
        e = by_day.get((k.sec_id, k.last_trade_date))
        if e is None:
            continue
        if k.kind == LAST_CLOSE:
            if for_delisting(overrides.last_trade_closes, e.key) is not None:
                twice.append(f"{k.sec_id} {k.last_trade_date}")
            closes[e.key] = price
        elif k.kind == RECEIVED_CLOSE:
            prices[e.key] = (k.lookup_ticker, price)
    if twice:
        raise OverrideFileError("--price-answers and --last-trade-closes both give the last close of: "
                                + "; ".join(twice))
    return replace(overrides, last_trade_closes=closes, acquirer_prices=prices)
```

4. In `_gate`, make `acquirer_price` take an answer first:

```python
    def acquirer_price(ticker: str, key: DelistingKey) -> float | None:
        answered = overrides.acquirer_prices.get(key)
        if answered is not None and answered[0] == normalize_ticker(ticker or ""):
            return answered[1]
        # Priced on THAT merger's own last-trade day: many mergers can share a
```

   (the rest of the function unchanged).
5. In `_contract`, after `ended = ...` and the `legs`/`requests` computation, refuse unrequested answers. Replace
   `"price_requests": request_rows(ended, endings, legs),` by computing `requests = request_rows(ended, endings,
   legs)` before the `return`, then:

```python
    unrequested = sorted(set(overrides.price_answers) - {key_of(r) for r in requests})
    if unrequested:
        raise OverrideFileError("--price-answers rows that answer no request of this run: "
                                + "; ".join(" ".join(k) for k in unrequested[:5])
                                + (f" (and {len(unrequested) - 5} more)" if len(unrequested) > 5 else ""))
```

   and use `"price_requests": requests,` in the returned dict.
6. In `_run`, after `_check_overrides(overrides, delistings)  # 6`, add
   `overrides = _apply_price_answers(overrides, delistings)                                         # 6b`.

In `scripts/classify_universe.py`:

1. Import `load_answers` from `delist_detection.price_requests`.
2. Add after `--recoveries`:

```python
    p.add_argument("--price-answers",
                   help="contract/price_requests.csv answered: its columns plus price (raw as-traded closes)")
```

3. In `read_inputs`, add `price_answers=load_answers(args.price_answers) if args.price_answers else {},` to the
   `Overrides(...)` call.

- [ ] **Step 4: Run the tests**

Run the two files — all pass. Full suite: expected `1637 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add src/delist_detection/pipeline.py scripts/classify_universe.py tests/test_pipeline.py \
        tests/test_classify_universe_cli.py
git commit -m "Price answers: --price-answers, a second run changes values only (reset-3)"
```

---

### Task 9: Seeds from observations — the seeds-only input

**Files:**
- Create: `scripts/seeds_from_observations.py`
- Test: `tests/test_seeds_from_observations.py` (new)

**Interfaces:**
- Produces: `seeds(rows) -> list[dict]` in the script (importable as a module under `scripts/`, the way other
  script tests import theirs; if no test imports a script yet, load it with `importlib.util.spec_from_file_location`
  as below).

- [ ] **Step 1: Write the failing test**

Create `tests/test_seeds_from_observations.py`:

```python
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "seeds_from_observations", Path(__file__).resolve().parents[1] / "scripts" / "seeds_from_observations.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _o(ticker, as_of, name):
    return {"ticker": ticker, "as_of": as_of, "name": name, "cusip": "", "cik": "", "sec_id": ""}


def test_a_seed_is_a_first_sighting_a_return_or_a_new_name():
    rows = [_o("AAA", "2010-06-30", "ALPHA CORP"), _o("AAA", "2010-12-31", "ALPHA CORP"),
            _o("BBB", "2010-06-30", "BETA INC"), _o("BBB", "2011-06-30", "BETA INC"),
            _o("AAA", "2011-06-30", "ZETA HOLDINGS"), _o("CCC", "2010-12-31", "")]
    assert [(r["ticker"], r["as_of"]) for r in mod.seeds(rows)] == [
        ("AAA", "2010-06-30"), ("AAA", "2011-06-30"), ("BBB", "2010-06-30"), ("BBB", "2011-06-30"),
        ("CCC", "2010-12-31")]
```

(BBB is missing from the 2010-12-31 snapshot, so 2011-06-30 is a return; AAA's 2011 name shares no word with
ALPHA CORP.)

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_seeds_from_observations.py -q -o addopts=""`
Expected: FileNotFoundError for the script.

- [ ] **Step 3: Write the script**

Create `scripts/seeds_from_observations.py`:

```python
"""Reduce an observations CSV to seeds (spec: "What crosses the boundary", In:
seeds.csv): one row per introduction of a ticker -- its first snapshot, a return
after a snapshot it was missing from, or a new name (names.names_agree fails
against the name it had in its previous snapshot). The snapshot calendar is the
set of as_of dates in the file. Reset-3 runs classify_universe.py on this file to
measure what passing seeds only would cost (roadmap: "Risk to measure first").

    PYTHONPATH=src python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict

from delist_detection.names import names_agree


def seeds(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    days = sorted({r["as_of"] for r in rows})
    before = {d: days[i - 1] for i, d in enumerate(days) if i}
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r)
    out = []
    for ticker in sorted(by_ticker):
        rs = sorted(by_ticker[ticker], key=lambda r: r["as_of"])
        seen = {r["as_of"] for r in rs}
        prev = None
        for r in rs:
            renamed = prev is not None and r["name"] and prev["name"] and not names_agree(r["name"], prev["name"])
            if prev is None or before.get(r["as_of"]) not in seen or renamed:
                out.append(r)
            prev = r
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observations", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    with open(args.observations, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames or [], list(reader)
    out = seeds(rows)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {args.out}: {len(out)} seeds from {len(rows)} observations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test**

Run the test file — it passes. Full suite: expected `1638 passed, 25 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/seeds_from_observations.py tests/test_seeds_from_observations.py
git commit -m "seeds_from_observations: the seeds-only input for the reset-3 measurement"
```

---

### Task 10: Docs

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `CONTEXT.md`, `docs/data-flow.md`

Docs only. Before writing a claim about the code, grep that it exists. Keep each file's style and wrapping.

- [ ] **Step 1: CLAUDE.md**

1. Commands: change the pytest count to the suite's actual numbers after Task 9 (expected `1638 tests + 25
   known-wrong golden xfails`). After the `classify_universe.py --as-of` line add:

```bash
python scripts/classify_universe.py --observations obs.csv --price-answers answered.csv   # contract/price_requests.csv plus a price column: a second run changes values only; a row that answers no request exits 2
python scripts/classify_universe.py --observations obs.csv --id-baseline output/securities.csv   # compare placeholders with this securities.csv for contract/id_changes.csv (default: OUTPUT_DIR/securities.csv)
python scripts/seeds_from_observations.py --observations data/observations.csv --out seeds.csv   # one row per introduction: the seeds-only input
```

   In every output list `{...,uncertain}.csv + scorecard.json`, add `+ contract/{security_history,delistings,seeds,
   price_requests,id_changes}.csv`.
2. Measurement section: after the `ticker_evidence.py` bullet, add:

```markdown
- `exit_kind.py` — one delistings.csv row in the contract's terms: `ending_fields` (exit kind, drop reason,
  continuation, `dlret` and `dlret_fill`) and `is_distress`. Today's bucket and CRSP code map to the exit kind
  (a code-470 bankruptcy is `dropped` for `bankruptcy`; `unknown` asserts none). The contract, the golden judge
  and the scorecard all read through it.
- `contract.py` — the contract's rows (spec "The contract", decisions 6, 7, 9, 10, 12), written under
  `output/contract/` beside today's tables for one release: `security_history_rows` (ticker ranges split where
  the issuer in force changes), `delisting_rows` (one per ended security, its last), `seed_rows` (the seed
  echo), `id_change_rows` (baseline placeholders that now hold a FIGI). `run_manifest.json` carries
  `schema_version` (`store.CONTRACT_SCHEMA_VERSION`).
- `issuer_in_force.py` — the issuer CIK on each sighting's date: the era's CIK when its EDGAR name that day agrees
  with the observed name, else the one other CIK SEC's name index lists under that name whose name agreed then
  (MRK 2008: old Merck & Co, CIK 64978). `issuer_changes` dates each change.
- `price_requests.py` — `contract/price_requests.csv` (`last_close` per ending with a published date,
  `received_close` per LLM-read stock leg; `otc_print` from reset-4f) and `load_answers` for `--price-answers`.
```

3. Non-obvious invariants: after the uncertain.csv bullet, add:

```markdown
- **The contract is written beside today's tables for one release (decision 6).** Stage 10g writes
  `output/contract/{security_history,delistings,seeds,price_requests,id_changes}.csv` from the tables about to be
  written and the verdicts; the scorecard (10h) reads the issuer from `contract/security_history.csv`. Contract
  delistings hold one row per ended security, its last real ending; `last_trade_date` is published only from an
  exchange print no later than the Form 25 effective date; a continuation has no value; assumed par, Shumway marks
  and a transfer's 0.0 are `dlret_fill`. `--price-answers` (the requests plus a `price` column) feeds the closes and
  acquirer prices, so a second run changes values only; an answer to no request, or a last close also given by
  `--last-trade-closes`, exits 2 before anything is written. Today's nine tables keep their columns.
```

4. In the scorecard invariant, change "stage 10g" to "stage 10h". In the reset-2 verdict invariant, change "10g
   (scorecard)" to "10h (scorecard)", add "10g (the contract)", and add that an earlier ending is uncertain
   (`earlier_ending`). In the "Every output is written only after the whole run succeeds" bullet and the
   "Configurable input paths" bullet, state that the contract files are written in the same group.

- [ ] **Step 2: README.md**

After the `uncertain.csv` section, add a section `### contract/ — the tables qlib_practice will read` with: the
five files and their columns (from `store.py`), the exit-kind mapping (Ruling 1 of this plan, as a table: today's
bucket and code → exit_kind, drop_reason), the value split (Ruling 2), the published last trade date rule
(Ruling 3), `--price-answers` (Ruling 8) and `schema_version`. In the intro, say the run also writes the contract
under `contract/`. In the scripts tree, add `seeds_from_observations.py`.

- [ ] **Step 3: CONTEXT.md**

After the **Verdict** entry, add:

```markdown
**Contract** — the tables the consumer reads (`output/contract/`): security_history, one-ending-per-security
delistings, the seed echo, price requests, id changes, and `schema_version` in the manifest. Built from today's
tables by `contract.py`; written beside them for one release.

**Exit kind** — the contract's kind of ending: merger, exchange, liquidation, dropped (with a drop reason),
lost_source, expiration. A continuation is an exchange whose successor is held by the same holders one for one.

**Fill** (`dlret_fill`) — a value the library assumes rather than measures: a Shumway mark, assumed par, a
transfer's 0.0. Never in `dlret`.

**Issuer in force** — the CIK that carried a security's name on a given day; it can change while the security
continues (a reverse merger, a holding-company reorganization).
```

- [ ] **Step 4: docs/data-flow.md**

After the stage paragraph reset-2 added (ticker evidence, verdicts, scorecard), add a paragraph: "10g, the contract
(`pipeline._contract`): `_issuers_in_force` (one cached submissions read per issuer CIK, and SEC's name index for a
sighting whose era CIK did not carry its name that day), then `contract.py`'s rows and `price_requests.request_rows`.
A price answer to no request stops the run here. 10h, the scorecard." Renumber the scorecard to 10h wherever this
file says 10g. In the Outputs list, add the five contract files.

- [ ] **Step 5: Check and commit**

Run the full suite once (docs only: expect the Task 9 count). Then:

```bash
git add CLAUDE.md README.md CONTEXT.md docs/data-flow.md
git commit -m "docs: the contract under contract/ (reset-3)"
```

---

### Task 11: Acceptance rebuild (network) and the seeds-only measurement

**Files:**
- Create: `output/contract/*.csv`
- Modify: `output/uncertain.csv`, `output/scorecard.json`, `output/run_manifest.json`, `output/run.log`,
  `data/scorecard.json`, `data/golden_lifecycles.csv`, `docs/superpowers/plans/2026-10-02-delist-library-reset.md`

- [ ] **Step 1: Make sure no other SEC client is running**

Run `ls -la ~/.cache/delist_detection/sec_rate.lock /tmp/claude/delist_detection/sec_rate.lock`; neither may have
been modified in the last few minutes. The worktree's `cache/` already holds reset-2's acceptance caches.

- [ ] **Step 2: Rebuild into a scratch folder**

```bash
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src \
  ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations data/observations.csv \
  --output-dir .superpowers/sdd/reset3-acceptance --as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm \
  --id-baseline output/securities.csv
```

Allow the hosts `data.sec.gov`, `www.sec.gov`, `efts.sec.gov`, `api.openfigi.com`, `api.nasdaq.com` and
`www.nasdaqtrader.com` (the halt feed). Expected: exit 0; the `Contract (contract/): ...` line; an "issuers in
force" stage in the log.

- [ ] **Step 3: Check today's tables did not change**

For each of `securities`, `ticker_history`, `cusip_history`, `delistings`, `payouts`, `review`, `review_summary` and
`observation_map`: `cmp output/<name>.csv .superpowers/sdd/reset3-acceptance/<name>.csv` prints nothing. For
`uncertain.csv`, every difference is an `earlier_ending:` reason or a row that carries one (`git diff --no-index`).
If anything else differs, stop: copy nothing, commit nothing, report which tables differ.

- [ ] **Step 4: Check the contract against the measured numbers**

In `.superpowers/sdd/reset3-acceptance/contract/`: `delistings.csv` has 875 rows; exit kinds 618 merger, 193
exchange (69 continuations), 53 dropped (47 bankruptcy, 3 sec_order, 3 filings_fees), 2 expiration, 9 blank; 148
blank `last_trade_date`; no row with both `dlret` and `dlret_fill`; every continuation row has a `successor_sec_id`
and blank values. `seeds.csv` has as many rows as `observation_map.csv`. `id_changes.csv` exists. Every
`security_history` interval of `BBG000BPD168` (MRK) dated before 2009-11-04 has `issuer_id` 64978. Report each
number; a difference from this list is a concern to report, not a stop, except a row with both values set or a
continuation with a value, which is a stop.

- [ ] **Step 5: Publish**

```bash
mkdir -p output/contract
cp .superpowers/sdd/reset3-acceptance/contract/*.csv output/contract/
cp .superpowers/sdd/reset3-acceptance/uncertain.csv .superpowers/sdd/reset3-acceptance/scorecard.json \
   .superpowers/sdd/reset3-acceptance/run_manifest.json output/
```

and copy the run's stderr to `output/run.log` (check it holds no key, User-Agent or e-mail address first).

- [ ] **Step 6: Golden flips and the floor**

Run `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python -m pytest tests/test_golden_lifecycles.py -q -o addopts=""`.
`MRK-2008` now passes, so its strict xfail fails: in `data/golden_lifecycles.csv` set its `status` to `pass` and
clear `fixed_by` and `library_says`. Do the same for any other `known_wrong` row that now passes, and list them.
Then `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/scorecard.py --check`. The expected drops are
the V lines the earlier endings raise (`V.uncertain_endings`, and `V.uncertain_endings_in_window`,
`V.uncertain_input_tickers_share` or `V.audit.confirmed_but_wrong` if they move). Lower exactly those floor
entries by hand to today's values in `data/scorecard.json`, with the reason "reset-3: an earlier ending is
uncertain (one ending per security, decision 12)" in the commit. Any other drop is a stop: report it. Then
`scripts/scorecard.py --raise-floor --write`, and the full suite (expected: the Task 10 count, with one fewer
xfail and one more pass per flipped golden row).

- [ ] **Step 7: The seeds-only measurement**

```bash
PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python scripts/seeds_from_observations.py \
  --observations data/observations.csv --out .superpowers/sdd/reset3-seeds.csv
DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src \
  ~/miniconda3/envs/rdagent4qlib/bin/python scripts/classify_universe.py --observations .superpowers/sdd/reset3-seeds.csv \
  --output-dir .superpowers/sdd/reset3-seeds-only --as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm
```

(same hosts; it may need SEC requests the full run did not). Record from its `scorecard.json`, beside the
acceptance run's: `L1.coverage_tickers`, `L1.coverage_securities`, `L1.left_view`, `L1.closed_no_event`,
`R1.1.mapped_share`, `V.uncertain_seeds`, and the number of seeds.

- [ ] **Step 8: Record and commit**

In `docs/superpowers/plans/2026-10-02-delist-library-reset.md`, under "reset-3", add a "Done 2026-10-02" bullet:
the plan file, decisions 6, 7, 9, 10 and 12 adopted as proposed, the contract's row counts from Step 4, the
golden rows flipped, the floor entries lowered and why, and the seeds-only numbers with one sentence on the
roadmap's rule ("If coverage falls, keep every sighting until reset-4a lands"). Then:

```bash
git add output/contract output/uncertain.csv output/scorecard.json output/run_manifest.json output/run.log \
        data/scorecard.json data/golden_lifecycles.csv docs/superpowers/plans/2026-10-02-delist-library-reset.md
git commit -m "Acceptance: the contract under output/contract/, golden MRK-2008 passes (reset-3)"
```

---

## Self-review

- **Spec coverage.** security_history with the issuer in force (Tasks 3–5, 7); delistings v2 with every listed
  column, one ending per security, earlier endings uncertain (Tasks 1, 2, 4); the seed echo (4, 7); price requests
  and answers replacing `--last-trade-closes` over the release (6, 8); `id_changes.csv` and class-code placeholders
  (4, 7); `schema_version` (3); side by side under `contract/` (3, 7); the judge and scorecard read exit kind and
  fill from the contract's reading and `EXIT_KIND_OF_BUCKET` is deleted (1, 3); golden `MRK-2008` (5, 11); the
  seeds-only risk measured (9, 11). Not here, by the roadmap: `review.csv`'s removal (cleanup after this release),
  `otc_print` values (reset-4f), the resolver's `lost_source` (reset-4a), qlib_practice's switch (reset-3q).
- **Types.** `ending_fields`/`EndingFields` (1) feed `contract.delisting_rows` (4) and the readers (1);
  `published_last_trade_date`, `seed_key`, `Verdict.word` (2) feed `contract` (4); `issuer_changes` returns
  `{sec_id: [(ISO date, CIK str)]}` (5), the shape `security_history_rows` takes (4); `PriceKey`/`key_of` (6) key
  `Overrides.price_answers` (8); `request_rows` takes `contract.delisting_rows` output and `last_endings` (4, 6, 7).
- **Counts.** The suite counts in each task assume the test counts listed; a task whose count differs reports the
  real number and why.
</content>
</invoke>
