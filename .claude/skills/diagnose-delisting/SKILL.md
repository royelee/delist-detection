---
name: diagnose-delisting
description: Diagnose one uncertain delisting of the delist_detection library from SEC filings (cached, then live) and the web, and write a per-case report plus a summary record under data/diagnosis/. Use when asked to diagnose, classify or verify a delisting row, especially a contract ending with verdict=uncertain, a 0.0 or blank return, or a guessed reason.
---

# Diagnose one uncertain delisting

You get one case: a row of `data/diagnosis/source.csv` (one uncertain ending of
`output/contract/delistings.csv`, joined to its ticker history and to the library's internal row in
`output/delistings.csv`). Find out from evidence what really happened to the security, compare it with what the
library says, and write two files. **Write nothing else.** No library code, no file under `output/`, no other
`data/` file. The report is for a person who will later decide how to fix the library.

Read `reference.md` (same folder) before you start: the contract's vocabulary, the spec's decisions that define
the right answer, the decision table and the cause tags. `example-THI.md` is a finished report to copy the shape of.

## Steps

1. **The library's side.** From the source row: the contract fields (`exit_kind`, `drop_reason`, `continuation`,
   `successor_sec_id`, `last_trade_date`, `dlret`, `dlret_fill`, `terminal_value`), the payout the library
   publishes (`value_rule`, `cash_per_share`, `cash_currency`, `stock_ratio`, `price_ticker`, `price_sec_id`,
   `price_date`, `recovery_ratio`, `terms_source`, `terms_gate`, `value_formula`), the internal ending
   (`delist_date`, `bucket`, `crsp_code`, `reason`, `last_trade_date_source`, `review_flags`) and why it is
   uncertain (`uncertain_reasons`, `security_uncertain_reasons`). Look up the security's rows in
   `output/contract/security_history.csv` (its ticker ranges) and `output/cusip_history.csv` (its CUSIPs) and, if useful, its seeds in
   `output/observation_map.csv` (grep the sec_id). Read files with grep or small scripts; they are large.
2. **Evidence, in this order.** (a) the cache, (b) live SEC, (c) web search.
   - SEC, through the skill's helper (cached; a live fetch is cached for next time). Run from the repo root:
     `DELIST_DETECTION_SEC_RATE_LOCK=/tmp/claude/delist_detection/sec_rate.lock PYTHONPATH=src ~/miniconda3/envs/rdagent4qlib/bin/python .claude/skills/diagnose-delisting/sec.py <cmd>`
     with the Bash tool's `allowed_domains` set to `data.sec.gov, www.sec.gov, efts.sec.gov` (only for commands
     that may fetch: `filings`, `grep`, `text`, `search`; `fails` is offline). Commands: `filings CIK --from
     --to [--forms]`, `grep CIK ACCESSION REGEX [--all]`, `text CIK ACCESSION`, `search "PHRASE" [--forms]
     [--from --to] [--cik]`, `fails --cusip C | --symbol S | --name WORDS --from YYYYMM --to YYYYMM`.
     Never fetch SEC with curl or WebFetch (SEC refuses them, and they bypass the shared rate limit).
   - Where to look: the issuer's filings from about 180 days before the last trade to 400 days after (a Form 25
     can come a year late, CBL 2021). 8-K items 1.01, 1.03, 2.01, 3.01, 3.03, 5.01, 5.03, 8.01; Form 25 / 25-NSE
     (grep its EX-99.25 notice with `--all`); Form 15; DEFM14A, 424B3, S-4, SC TO-T, SC 14D9 for deal terms;
     the successor's or acquirer's 8-K12B / 8-K12G3 (`search`, or `filings` of its CIK). Fails rows of the
     security's CUSIPs after the end show what traded next: the same CUSIP under a new ticker (a rename), under a
     Q or OTC symbol (a drop), or a new CUSIP (new securities).
   - Web search (load the tool with ToolSearch `select:WebSearch`) only for facts SEC does not hold: a relisting,
     a press release, which symbol the stock traded under after it left the exchange. Never for a market price.
     Cite each by URL and mark it `web`.
3. **Decide** with `reference.md`'s decision table: what happened to the holder's shares (kept the same security,
   replaced by something, or lost), then the contract fields and the plan's extra fields.
4. **Payout, not prices.** Find what one share turned into and write it as a payout rule with its terms
   (`reference.md`, "The payout rule"): `value_rule`, `cash_per_share` and `cash_currency`, `stock_ratio`, the
   security whose price the rule needs (`price_ticker`, and `price_sec_id` when the run has it), `price_date`,
   `recovery_ratio`, and a `value_formula` line. Take the terms from the filings (the merger agreement's
   consideration, the default package of an election deal, a plan's distributions). **Do not look up or compute
   market prices** (the last close, an acquirer's price, an OTC print): qlib_practice supplies them and computes
   the return. Compare your rule and terms with the library's published ones, term by term — a wrong ratio, a
   missing cash leg or a missing currency is a `wrong` or `missing` terms status even when the rule agrees.
5. **Write the two files** (below). Keep the report short: facts and citations, no padding.

## Files

`data/diagnosis/reports/<case_id>.md` — the report, in this order:

1. **Verdict.** One or two sentences: what happened, and whether the library's row is right.
2. **Library vs evidence.** A table, one row per field: `exit_kind`, `drop_reason`, `continuation`, `successor`,
   `last_trade_date`, `value_rule`, `terms` (cash and currency, ratio, price security, price date), `issuer`,
   `ticker_history` — columns *library says*, *evidence says*, *status* (`agree` / `wrong` / `missing` /
   `unknown`).
3. **Corrected classification.** A code block with the contract fields (`exit_kind`, `drop_reason`,
   `continuation`, `successor`, `last_trade_date`), the payout (`value_rule`, `cash_per_share`, `cash_currency`,
   `stock_ratio`, `price_ticker`, `price_sec_id`, `price_date`, `recovery_ratio`, `value_formula`) and the extras
   (`event_type`, `consideration`, `holder_value`, `effective_date`, `successor_ticker`, `confidence`).
4. **Why this confidence.** The confidence, then one line for each of the five key fields — exit kind,
   successor, last trade date, payout rule, terms — saying what it rests on: `filing` (name it), `fails rows`,
   `web`, or `worked out` (say from what). For `inferred` or `unresolved`, end with what is not backed and what
   evidence would make it `verified` (for example "an exchange print or a filing that states the last day").
   A `verified` report needs only the five lines.
5. **What happened.** Bullets, each a fact with its citation: `[SEC 8-K 2020-11-04](url)` or `[web](url)`.
6. **Decision-tree bucket.** Kept the same security / replaced / lost, and why.
7. **Why the library got it wrong.** Point at the library's reason, flags or rule; the cause tag.
8. **Fix and open checks.** What the corrected row needs; facts still to confirm (never a market price — those
   are qlib_practice's); whether this should become a golden case (a well-sourced case a rule fix should flip).

`data/diagnosis/records/<case_id>.json` — one JSON object, the summary line:

```json
{"case_id": "...", "sec_id": "...", "ticker": "...", "report": "reports/<case_id>.md",
 "event_type": "...", "consideration": "...", "confidence": "verified|inferred|unresolved",
 "exit_kind": "...", "drop_reason": "...", "continuation": true, "successor_ticker": "...",
 "last_trade_date": "YYYY-MM-DD",
 "value_rule": "cash|stock|cash_plus_stock|otc_print|recovery|worthless|transfer|continuation|expiration|unknown",
 "cash_per_share": null, "cash_currency": "", "stock_ratio": null, "price_ticker": "", "price_date": "",
 "value_formula": "...",
 "status": {"exit_kind": "agree|wrong|missing|unknown", "last_trade_date": "...", "successor": "...",
            "value_rule": "...", "terms": "...", "issuer": "...", "ticker_history": "..."},
 "confidence_reasons": ["for inferred/unresolved: each field not backed by a filing, what it rests on instead"],
 "library_wrong": true, "cause": "one tag from reference.md, or other:<short note>",
 "golden_worthy": true, "sec_evidence": 3, "web_evidence": 0, "open_checks": ["..."], "verdict": "one sentence"}
```

`library_wrong` is true when any of `exit_kind`, `last_trade_date`, `successor`, `value_rule` or `terms` is
`wrong`.

## Modes (the diagnosis truth loop)

Besides the uncertain rows of `source.csv` (mode `uncertain`, steps 1–5 above), the truth loop (spec
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md`, 1.5) sends two other kinds of case. Its case
row is in `data/diagnosis/loop/<label>/round-<N>/cases.csv`: `mode`, `sec_id`, `ticker`,
`truth_case_id`, and three JSON lists of the same length: `fields`, `side_a`, `side_b`, plus the context columns of
`source.csv`.

- `regression`: a contract field changed for a security outside the truth set; `side_a` is the old value (the
  sub-plan's base run), `side_b` the new one. Decide, field by field, which one the filings support. A field named
  `delistings.added` / `delistings.removed` means the whole contract row appeared or disappeared;
  `security_history.ranges` compares the ticker ranges.
- `mismatch`: the library disagrees with the truth file; `side_a` is the truth, `side_b` the library. The truth came
  from an earlier report (`truth_case_id`'s report under `data/diagnosis/reports/`): read it first.
  Decide, field by field, which value the filings support. If the library is right, name the filing the earlier
  report missed or misread (its accession number) in `missed_filing`; without one, the truth will not change.

Write the report and the record under the round's folder (`reports/<case_id>.md`, `records/<case_id>.json`), not
under `data/diagnosis/reports/`. Section 2 of the report shows both values and the evidence for
each field. The record has every key of the uncertain-mode record, plus:

```json
"mode": "regression | mismatch",
"field_verdicts": [{"field": "<as in fields>", "right": "old | new | truth | library | neither",
                    "value": "<the right value>", "missed_filing": "<accession, mismatch mode only, or empty>"}]
```

`confidence` follows the same rule as in uncertain mode. Every loop record gets a skeptic pass, whatever it decides.

## Rules

- Every fact in the report has a citation; a fact you could not source is written as unknown, never guessed.
- `confidence`: `verified` when the exit kind, successor, last trade date, payout rule and terms each rest on a
  cited SEC filing — a date the filing states counts ("ceased trading at the close on D", "suspended before the
  open on D" → the trading day before D, the Form 25 notice's suspension date); `inferred` when one of them rests
  on the web, on fails rows, or on a date you worked out rather than read; `unresolved` when the evidence does not
  settle the case (say what is missing). Market prices never count: the payout rule needs none.
- The right answer follows the spec's decisions in `reference.md`, not the library's current behaviour and not
  common usage: a 1:1 holding-company reorganization is a continuation; post-bankruptcy equity is a new
  security; a move to OTC is an ending valued at the first OTC print.
- Write only the two files. Return the JSON record as your final answer as well.
</content>
