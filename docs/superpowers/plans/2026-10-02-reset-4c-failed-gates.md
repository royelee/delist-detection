# Reset-4c (first step): Assumed Par After Any Failed Gate Is Uncertain — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decision 4 says assumed par is acceptable as a fill only when the payout gate passed, and a failed gate is
uncertain. Today the verdict reads only the regex payout's gate (`payout_gate_failed`); an ending whose LLM terms or
`--merger-terms` row failed the gate (`llm_gate_failed`, `terms_gate_failed`) and fell back to assumed par is still
confirmed. This plan makes every failed gate count.

**Architecture:** One rule in `verdict._ending_reasons`, a constant naming the three gate flags, tests, docs, and an
acceptance rebuild in which only `uncertain.csv`, the contract's `verdict` column and the scorecard's V lines move.

**Tech Stack:** Python ≥3.10, pytest (offline).

**Spec:** `docs/superpowers/specs/2026-10-02-delist-library-reset.md`, decision 4 ("Assumed par. Proposed: acceptable as
`dlret_fill` = 0.0 when the payout gate passed; a failed gate (JCI 2016) is uncertain."). Roadmap: "reset-4c: Values".

## Global Constraints

- Decision 4 adopted as proposed (reset-2); decision 2 adopted as proposed (overnight ruling 2026-10-02) — its
  hand-valued terms wait for reset-4e (see Rulings).
- The failed-gate flags are `payout_gate_failed`, `llm_gate_failed` and `terms_gate_failed` (flag names, before `:`).
- Only the verdict changes; today's nine tables other than `uncertain.csv` stay byte-identical.
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Scope.** The reset-4c research (2026-10-02, offline; 137 blank or assumed-par merger endings) found most blank
   values wait on a last trade date or close (33 of 55 blanks have a cash payout but no last close, 37 have no last
   trade date): reset-4e's work. Of the rest, 24 are not merger exits at all (reset-4a2) and only 8 have no
   consideration recorded. Hand-valued terms, a sanity filter for placeholder fails prices (0.01, 1.00) and the
   price answers' received closes come after reset-4e. This first step is decision 4's rule only.
2. **Permitted floor drops.** More endings become uncertain: `V.uncertain_endings`, `V.uncertain_endings_in_window`,
   `V.uncertain_input_tickers_share` and `V.uncertain_distress` may be lowered by hand with the reason "decision 4: assumed
   par after a failed LLM or terms gate is uncertain". Any other drop stops the acceptance.

## Review Focus

1. Assumed par with a gate that passed (no failed-gate flag, e.g. `merger_at_par`) stays confirmed (Task 1 test).
2. A failed gate on a merger valued by another source (not assumed par) is not this rule's business (Task 1 test).

---

### Task 1: The rule

**Files:**
- Modify: `src/delist_detection/verdict.py`
- Test: `tests/test_verdict.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_verdict.py`, add these rows to `test_each_ending_rule`'s
  parametrize list:

```python
    (dict(method="assumed_par", flags="llm_gate_failed:no_acq_price"), "assumed_par_after_failed_gate"),
    (dict(method="assumed_par", flags="terms_gate_failed:no_acq_price"), "assumed_par_after_failed_gate"),
```

  and add a test:

```python
def test_a_failed_gate_on_a_merger_valued_another_way_is_not_the_assumed_par_rule():
    row = ending("A", "2015-03-10", **{**GOOD, "method": "cash_only", "flags": "llm_gate_failed:no_acq_price"})
    assert "assumed_par_after_failed_gate" not in _one(row).endings[("A", "2015-03-10")].reasons
```

- [ ] **Step 2:** Run the file: the two new parametrized rows fail.
- [ ] **Step 3: Implement.** In `src/delist_detection/verdict.py`, add after `MEASURED_SOURCES`:

```python
GATE_FAILED = frozenset({"payout_gate_failed", "llm_gate_failed", "terms_gate_failed"})   # decision 4's failed gates
```

  and in `_ending_reasons` replace
  `if row["dlret_method"] == "assumed_par" and "payout_gate_failed" in flags:` with
  `if row["dlret_method"] == "assumed_par" and flags & GATE_FAILED:`. In the module docstring's ending paragraph,
  say "assumed par after a failed payout, LLM or terms gate (decision 4)".
- [ ] **Step 4:** Run `tests/test_verdict.py`, `tests/test_scorecard.py`, then the full suite (previous count + 3).
- [ ] **Step 5: Commit** — `git commit -m "verdict: assumed par after any failed gate is uncertain (reset-4c)"`

---

### Task 2: Docs

- [ ] In CLAUDE.md's `verdict.py` bullet and README.md's uncertain.csv section, wherever the assumed-par rule is
  described, name the three gates. Update CLAUDE.md's pytest count. Run the suite once; commit
  `docs: decision 4's failed gates (reset-4c)`.

---

### Task 3: Acceptance rebuild (network)

As in reset-4b's acceptance: check no SEC client runs; rebuild into `.superpowers/sdd/reset4c-acceptance` with
`--as-of 2026-09-25 --sec-workers 1 --extract-merger-terms-llm --id-baseline output/securities.csv`, the lock
variable and all seven hosts; stop on a sandbox denial, a non-zero exit or a refusal. The eight tables `securities`,
`ticker_history`, `cusip_history`, `delistings`, `payouts`, `review`, `review_summary`, `observation_map` must be
byte-identical to `output/` (stop otherwise); `uncertain.csv`, `contract/delistings.csv` (verdict column only) and the
scorecard change. Count the endings newly uncertain with `assumed_par_after_failed_gate`. Lower by hand only the
entries Ruling 2 permits, with its reason; publish; `scripts/scorecard.py --check`, `--raise-floor --write`; the full
suite; a "Done (first step)" bullet under reset-4c in the roadmap (the counts, the research's findings in Ruling 1,
and what is left). Commit `Acceptance: assumed par after any failed gate is uncertain (reset-4c)`.

## Self-review

- Spec coverage: decision 4's rule (Task 1); decision 2's hand values deferred with the reason (Ruling 1).
</content>
</invoke>
