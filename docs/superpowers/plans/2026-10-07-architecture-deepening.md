# Architecture deepening of src/delist_detection: program plan and decision log

Branch `arch-deepening`, from f5b3c0d (PR #7's head). The architecture review (2026-10-06) found 11 candidates and 6
smaller ones. The operator asked for all of them, one by one, without rulings mid-run. This file holds the order, the
gate and every choice made along the way.

The vocabulary (module, interface, depth, seam, adapter, leverage, locality) is the codebase-design glossary. The
domain terms are CONTEXT.md's.

## The gate (every step)

A deepening moves behaviour behind a smaller interface. It changes nothing the library publishes.

- **The full suite passes.**
- **The offline whole-run replay is byte-identical** to the reference made at f5b3c0d
  (`/tmp/claude/delist_detection/arch/ref_out`, checked with `same_output.py`).
- **A declared defect fix may change rows.** Each changed row must be explained in the commit. Four defects were
  found by the review:
  - a failed EDGAR read in the handoff stage can crash the run;
  - AZPN 2022's stale payout flags on a continuation;
  - CNB, IMB and SPNV publish a last trade date flagged unconfirmed;
  - `plan_stock` gets "low" confidence.
- **Tests move to the deepened module's interface.** Tests that reached past it are deleted once covered.

## Order

| # | Candidate | Defect fixed | Status |
|---|---|---|---|
| 1 | Stage 8 as one merger value module, with the price request round trip (review 1, 2) | | |
| 2 | One issuer record over EDGAR with the failed-read policy (review 4) | the handoff stage's uncaught read | |
| 3 | One owner for rewriting an ending (review 3) | AZPN's stale flags | |
| 4 | The last trade date as one module (review 5) | CNB, IMB, SPNV | |
| 5 | history owns where a security's history ends (review 6) | | |
| 6 | A security's identity behind security_master (review 7) | | |
| 7 | The line follow owns its rounds; one R1 reading per ending (review 8) | | |
| 8 | One run snapshot; one reading of a delistings row (review 9) | | |
| 9 | The truth set and the loop round as two modules (review 10) | | |
| 10 | dlret decides the value rule once (small) | plan_stock's confidence | |
| 11 | The Clients seam declares capabilities (small) | | |
| 12 | The fails index owns its loading (small) | | |
| 13 | One leaf module for ticker and share-class spelling (small) | | |
| 14 | The finder builds its own trading record (small) | | |
| 15 | One truth-case type (speculative) | | |
| 16 | Package layout: concept subpackages and a lazy package root (review 11) | | |

The issuer record (2) comes early because stages 8, 9 and 9b read issuers through closures that it replaces. The
layout (16) comes last, once steps 8 and 13 have made the pure leaf modules.

## Decision log

- **2026-10-07:** the work goes on its own branch, so PR #7 (the diagnosis-truth roadmap) stays reviewable as it is.
  This branch stacks on it.
