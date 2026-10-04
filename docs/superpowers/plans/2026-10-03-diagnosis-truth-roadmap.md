# Diagnosis truth fixes: roadmap

Spec: `docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md` (approved 2026-10-03). Case map:
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv`. Reader notes: the same folder.

One implementation plan per sub-plan, written when the previous one is accepted, in this order. Each plan names the
cases it targets (from the case map), the rules it adds (from spec section 3), and the "must not change" cases its
tests pin. Each ends with the truth loop (spec 1.7) and is accepted only when:

- `D.mismatches` fell and the floor was raised (`scripts/scorecard.py --raise-floor`);
- `scripts/scorecard.py --check --base <the sub-plan's base commit>` passes: no floored drop, no failing golden or
  diagnosis `pass` case, and `D.unexplained_regressions` 0 (without `--base` the regression check does not run);
- the golden replay set, the golden lifecycles and the floor test are green (`pytest`);
- the operator has the sub-plan's report (mismatches per field before and after, regressions and how the loop
  settled them, truth changes, uncertain endings and L1 coverage before and after).

Work stays on the worktree branch; merging or pushing is the operator's call.

| Sub-plan | Plan file | Depends on | Target | Status |
| --- | --- | --- | --- | --- |
| 5-0 Truth set and loop | `2026-10-03-reset-5-0-truth-set.md` | none | the truth file, judge, regression report, diagnose modes, truth updates, loop workflow | done (282 cases: 19 pass, 263 known_wrong; D.mismatches 756) |
| 5a One line across a CUSIP or ticker change | `2026-10-03-reset-5a-line-continuity.md` | 5-0 | 43 cases (F1) | done (D.mismatches 755 -> 649; 28 of 43 cases pass); accepted by the controller, operator review of `output/diagnose_unknown_report/loop/5a/report.md` section 8 pending |
| 5b Form 25 reach, matching and ownership | `2026-10-04-reset-5b-form25-reach.md` | 5a | 50 cases (F4, F5) | done (D.mismatches 646 -> 596; 58 -> 78 cases match); accepted by the controller, operator review of `output/diagnose_unknown_report/loop/5b/report.md` section 8 pending |
| 5c Issuer role and successor links | `2026-10-04-reset-5c-issuer-successors.md` | 5a, 5b | 26 cases (F2, F3) | written |
| 5d Last trade date | to write | 5a, 5b | 33 cases (F6) | |
| 5e Acquirer security and the gate | to write | 5a, 5c | 35 cases (F7) | |
| 5f Terms extraction (LLM schema, legs, schema 3) | to write | 5e | 33 cases (F8) | |
| 5g Distress | to write | 5a, 5b | 13 cases (F9) plus endings 5a brings out | |
| 5h Identity | to write | 5a | 6 cases (F11) | |
| 5i Verdict and evidence | to write | all | 40 cases (F10 and the verdict-only rulings) | |

Carried from 5a:
- 5d: a same-CUSIP rename's ticker boundary is 1–3 days late against the 8-K (the ranges come from fails rows): PRDO,
  PGEN, LC, DSW, RLGY. Date it from the 8-K's effective date or MIDAS.
- Every sub-plan's full run passes `--id-baseline <the base commit's output/securities.csv>` whenever `output/`
  already holds a run of the sub-plan. The default baseline, the previous `output/`, misses the sub-plan's own folds.
- The loop's agents sometimes label a verdict against their own text (HON) or return no skeptic. Settle such rows
  from the record's text and the cited filings.

Carried from 5-0's final review into 5a's plan, as its first task: a placeholder outside the truth set that 5a folds
into a FIGI line must not become a truth row of its own (the regression path adds no truth row for a sec_id that is
not in the run or is a renamed placeholder, and the regression report folds the placeholder's removed row into its
FIGI's added row as one rename). Also carried, for the sub-plan that first needs it:
- update_truth's status flips must read payout legs before 5f;
- a malformed record JSON should be retried, not abort the update;
- a prepared `casesPath` must sit at `loop/<label>/round-<N>/cases.csv`.
- for 5h: UAG 2009 (CIK1019849-COMMON, United Auto Group seen as UAG while it traded as PAG). 5a's U4 (a fails row
  confirms a ticker only when its description can name the issuer) would place it on PAG's line, but it changed 13
  other eras' guard (more than 10), so 5a dropped it.

Before writing each plan: replay the cases the reader notes call "unconfirmed mechanism" (5b: XMSR, SOV, TXU, RHDC,
IDARQ, LKSD; 5e: the gate false-fails NYX, SCS, EV, SUN, THE) on cached data and record what the code actually does.
