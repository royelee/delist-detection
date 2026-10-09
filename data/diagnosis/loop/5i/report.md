# Sub-plan 5i: verdict and evidence (operator report)

Base ca58ee1. Design note `docs/superpowers/plans/research/2026-10-04-5i-verdicts.md`. Run and accepted with 5f in
wave 2; the shared steps, floors and open items are in `../wave2/report.md`.

## Result

**Accepted by the controller, with wave 2.** As the spec requires, 5i changes only verdicts (`uncertain.csv` and the
V lines) and no contract row. Uncertain endings fell from 206 to 98, and uncertain securities rose from 42 to 48 under
the closed_no_event rule.

Every scored mismatch on 5i's 11 truth rows is a contract field, so none could pass by 5i's code.
- DJ and AGE took R8 from their NYSE notices, and their remaining field went to 5f.
- The four Liberty 2023 rows went to 5f (baskets) and are residual now.
- MEL, FNF, TEAM, QRTEA and CSAL are residual. MEL's block is stage 8b's successor link: its own 25-NSE states the
  one-for-one exchange.

## What 5i changed

- **`verdict_rules.py` settles five doubts:**
  - a merger relabel backed by the security's own Form 25 (25-NSE only);
  - a continuation that names its 8-K12B or 8-K12G3, unless the registrant's own ratio is neither one nor a plain
    split (CHTR's 0.9042 stays uncertain; SIRI's 0.1 reverse split does not);
  - today's ticker map, when the issuer's own Form 25 and an observed name agree;
  - assumed par after a gate that failed only on price, within the gate's tolerance widened by the close's age (a
    NULL-like acquirer ticker counts as missing: GRUB stays uncertain);
  - a stale seed within 365 days after a settled, non-continuation ending. A doubt on the ending's own row (a
    last-trade conflict, a one-for-one merger) keeps the seed uncertain (MEL, FRK).
- **Stage 9g** (`continuation_evidence.py`, metered as "continuation readings"): an 8-K item 3.03 or 8-K12B confirms
  a continuation only when 5c's R1 reader finds a one-for-one exchange whose target names the registrant or the
  successor. Each confirmation is recorded in `run_manifest.json` (`continuation_filings`).
- **The closed_no_event gap:** an observed security with every range closed and no ending is uncertain
  (`closed_no_event:<day>`).
- **verdict.GATE_FAILED is the one gate-failed set,** including 5f's `terms_gate_skipped`.

## Review

0 Critical, 4 Important, 9 Minor, all fixed in 5i's fourth patch. Of 17 sampled endings 5i now confirms, 14 were right.
MEL and FRK were wrong, and GRUB was unclear; all three stay uncertain now.

## Carried

Reader note A's theme 6(b) and 6(c) are not built: LVNTA's overlap is a real placeholder identity fault.
