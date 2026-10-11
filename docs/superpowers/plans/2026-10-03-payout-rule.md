# Payout Rule Published in the Contract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `contract/delistings.csv` publishes, for every ending, the rule that turns one share into its terminal
payout and the terms of that rule (`value_rule`, `cash_per_share`, `stock_ratio`, `price_sec_id`, `price_ticker`,
`price_date`, ...), so qlib_practice computes `dlret = payout / last close − 1` with its own prices. Terms the library
read from filings are published even when its own sanity gate failed (`terms_gate=failed`).

**Architecture:** A new pure module `payout_rule.py` turns one `delistings.csv` row, its `exit_kind.EndingFields`, the
contract's published last-trade date and the merger's pre-gate inputs (`MergerInputs`: the `--merger-terms` row, the
LLM terms, the regex read, the acquirer's sec_id) into the ten new columns. `contract.delisting_rows` takes an
optional `inputs` map and appends them. `pipeline._contract` builds the inputs from `_Payouts` and `Overrides`.
`Tables` gains `contract_delistings` (optional) and `scorecard._ending_lines` counts by rule.

**Tech Stack:** Python ≥3.10, pytest (offline).

**Spec:** operator decision 2026-10-03 (`.superpowers/sdd/payout-rule/brief.md`): the library publishes the payout
rule, the market prices stay with the caller. Roadmap: values of drops and mergers without library prices.

## Global Constraints

- Additive: today's columns, `dlret`, `dlret_fill`, `terminal_value`, `price_requests.csv` and the nine tables do not
  change. New columns come after `verdict`. `CONTRACT_SCHEMA_VERSION` 1 → 2.
- `value_rule` is one of `cash, stock, cash_plus_stock, otc_print, recovery, worthless, transfer, continuation,
  expiration, unknown`.
- `price_date` is the trading day after the published last trade (as `price_requests` dates `received_close` and
  `otc_print`); blank when the contract has no last-trade date.
- Tests are offline. Python: `PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python`; pytest with `-o addopts=""`.

## Rulings this plan makes

1. **Terms source order.** A `--merger-terms` row wins (`terms_source=--merger-terms`, `terms_gate` blank: no gate ran).
   Else the terms the row carries (gated, kept): `terms_source` is the row's `payout_source`, or `llm` for a stock leg
   the LLM read. Else the pre-gate read: the LLM terms (`llm`), else the regex value (its source) — `terms_gate=failed`.
2. **`terms_gate`.** `passed` when the row carries gated terms and a last close existed to check them; blank for an
   override, for a row with no last close (the gate could not run) and for rules with no terms; `failed` for pre-gate
   terms published after the gate dropped them (including a gate that could not check for want of a close, when the
   row carries no terms at all). Cost if wrong: qlib_practice treats a `failed` row's terms as unverified.
3. **Election deals that fail the gate publish both legs as read** (`terms_gate=failed`). First drafted as
   `unknown` (the legs can be alternatives), reversed on the acceptance run: THI, which the brief names, is labelled
   `election` by the LLM yet pays C$65.50 cash and 0.8025 QSR shares. Cost if wrong: a true either/or election is
   overstated as cash plus stock; `failed` tells the caller to re-check. A passed election is on the row and
   publishes normally.
4. **`cash_currency` is always blank**: no library source records a currency, and the brief forbids guessing USD.
5. **A stock leg with no acquirer ticker** publishes `stock_ratio` with a blank `price_ticker`; qlib_practice cannot
   price it and uses the fill.
6. **Order of rules.** continuation, then bucket: merger (terms), transfer, liquidation (recovery, worthless, else
   `otc_print`, a bankruptcy drop included, since its bucket is liquidation), `dropped` exit kinds (`otc_print`),
   expiration; any other bucket `unknown`. `recovery_ratio` is the row's value; `value_formula` shows
   `ratio × last_close / last_close − 1` as `recovery_ratio − 1`.
7. **Scorecard names.** `R2.7.value_rule.<rule>` (count of contract endings) and `R2.7.payout_rule_known`
   (endings whose rule is not `unknown`, floored UP). Counted over `contract/delistings.csv` (one row per ended
   security), not over every delistings.csv row; present only when the contract file is.
8. **Permitted floor changes.** The new `R2.7.payout_rule_known` enters the floor. No existing number moves.

## Review Focus

1. A merger the gate dropped (THI, RAI, AVP) publishes its LLM/regex terms with `terms_gate=failed` (Task 2).
2. A `--merger-terms` row wins and carries no gate state (Task 2).
3. A continuation has `value_rule=continuation` and no terms; an exchange transfer that is not a continuation is `transfer` (Task 1).
4. The nine tables and the old contract columns are byte-identical (acceptance).

---

### Task 1: The rule of each ending (pure)

**Files:** Create `src/delist_detection/payout_rule.py`; Test `tests/test_payout_rule.py`.

- [ ] Write failing tests: cash row, stock row, cash_plus_stock row with price_ticker/price_date and formula, otc_print
  for a drop and a liquidation, recovery, worthless, transfer, continuation, expiration, unknown bucket, a merger
  with no terms is `unknown`.
- [ ] Implement `MergerInputs`, `value_fields(row, fields, last_trade_date, inputs)`; run to green.

### Task 2: Pre-gate terms and overrides

**Files:** Modify `src/delist_detection/payout_rule.py`; Test `tests/test_payout_rule.py`.

- [ ] Failing tests: LLM terms with no row terms → `terms_gate=failed`, `terms_source=llm`; regex-only → failed with
  the regex source; override wins, gate blank; election failed → `unknown`; row terms + no last close → gate blank.
- [ ] Implement; green.

### Task 3: Contract columns, schema version, pipeline wiring

**Files:** Modify `store.py`, `contract.py`, `pipeline.py`; Test `tests/test_contract.py`, `tests/test_pipeline.py`.

- [ ] Failing tests: `delisting_rows` carries the new columns; `run_manifest.json` `schema_version == 2`; a pipeline
  run's contract file has the columns.
- [ ] Add `payout_rule.merger_inputs(...)`, wire `_contract`; green.

### Task 4: Scorecard lines and docs

**Files:** Modify `lifecycle.py` (`Tables.contract_delistings`), `scorecard.py`, `pipeline._as_read`, CLAUDE.md,
README.md, docs/data-flow.md; Test `tests/test_scorecard.py`.

- [ ] Failing tests: `R2.7.value_rule.*` and `R2.7.payout_rule_known` from a table with contract rows; absent without.
- [ ] Implement; docs; full suite.

### Task 5: Acceptance

- [ ] Rebuild into `.superpowers/sdd/payout-rule/acceptance`; compare the nine tables and old contract columns with
  `output/`; the existing scorecard numbers; stop on a difference. Else publish, `scorecard.py --check`,
  `--raise-floor --write`, full suite, commit.
