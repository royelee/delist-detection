# Diagnosis truth fixes: roadmap

Spec: `docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md` (approved 2026-10-03). Case map:
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes/case_map.csv`. Reader notes: the same folder.

One implementation plan per sub-plan, written when the previous one is accepted, in this order. Each plan names the
cases it targets (from the case map), the rules it adds (from spec section 3), and the "must not change" cases its
tests pin. Each ends with the truth loop (spec 1.7) and is accepted only when:

- `D.mismatches` fell and the floor was raised (`scripts/scorecard.py --raise-floor`);
- `D.unexplained_regressions` is 0 and `scripts/scorecard.py --check` passes;
- the golden replay set, the golden lifecycles and the floor test are green (`pytest`);
- the operator has the sub-plan's report (mismatches per field before and after, regressions and how the loop
  settled them, truth changes, uncertain endings and L1 coverage before and after).

Work stays on the worktree branch; merging or pushing is the operator's call.

| Sub-plan | Plan file | Depends on | Target | Status |
| --- | --- | --- | --- | --- |
| 5-0 Truth set and loop | `2026-10-03-reset-5-0-truth-set.md` | none | the truth file, judge, regression report, diagnose modes, truth updates, loop workflow | written |
| 5a One line across a CUSIP or ticker change | to write | 5-0 | 43 cases (F1) | |
| 5b Form 25 reach, matching and ownership | to write | 5a | 50 cases (F4, F5) | |
| 5c Issuer role and successor links | to write | 5a, 5b | 26 cases (F2, F3) | |
| 5d Last trade date | to write | 5a, 5b | 33 cases (F6) | |
| 5e Acquirer security and the gate | to write | 5a, 5c | 35 cases (F7) | |
| 5f Terms extraction (LLM schema, legs, schema 3) | to write | 5e | 33 cases (F8) | |
| 5g Distress | to write | 5a, 5b | 13 cases (F9) plus endings 5a brings out | |
| 5h Identity | to write | 5a | 6 cases (F11) | |
| 5i Verdict and evidence | to write | all | 40 cases (F10 and the verdict-only rulings) | |

Before writing each plan: replay the cases the reader notes call "unconfirmed mechanism" (5b: XMSR, SOV, TXU, RHDC,
IDARQ, LKSD; 5e: the gate false-fails NYX, SCS, EV, SUN, THE) on cached data and record what the code actually does.
