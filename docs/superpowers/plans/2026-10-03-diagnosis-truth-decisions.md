# Diagnosis truth fixes: decisions made for the operator

From 2026-10-04 the operator asked me to stop asking. I apply my own recommendation on every ruling and note it here
for later review. Each entry gives what I chose, the alternative, and what it costs if wrong. Rulings the operator
made themselves are recorded in each sub-plan's report and in `data/diagnosis_truth_changes.csv`. This file lists the
ones I made alone.

## Process

- **2026-10-04, from 5d on:** each sub-plan drops the separate plan document and the task-by-task re-implementation.
  - The new flow: one Opus agent researches, designs (in a short design note under `docs/superpowers/plans/research/`)
    and implements test-first, committed on the branch.
  - Kept, because they caught every real defect so far: the Opus whole-branch review with the offline replay over
    real caches, one fix wave, the network run with round 1 read by kind, and the truth loop with acceptance.
  - Alternative: the roadmap's one-plan-per-sub-plan flow. That ran about 5–6 hours per sub-plan.
  - Cost if wrong: less step-by-step review of each unit.

## 5c (2026-10-04)

- **WWE 2023 → TKO is a continuation.** One TKO share per WWE share, no cash, into a new holdco, even though Endeavor
  contributed UFC for 51%. This is consistent with DOW (DowDuPont) and WR (Evergy), which you ruled continuations.
  - Alternative: a merger, because the holders' claim changed (decision 9, as the skeptic argued).
  - Cost if wrong: mergers of equals into a new holdco read as continuations, with DLRET 0 instead of a value.
- **CSC 2017 → DXC stays a merger.** The required 8-K12B name tie finds no tie between DXC and Computer Sciences.
  - Alternative: drop the name tie for this path. It wrongly linked AABA, MSG and HUB-B.
  - Cost if wrong: one R1 continuation outside the truth set is missed, with no regression.
- **NSAM and FTI stay mergers.** Their own-share reading is ambiguous: NSAM's 8-Ks state two different terms, and FTI's
  defined term attributes Technip's ratio to it.
  - Cost if wrong: two new-holdco continuations are missed.
- **Spec rule 6 is deferred to 5f.** As written, it would turn SIRI 2024, a passing continuation, into a merger.
  - Cost if wrong: CHTR's 5f field waits.
- **One-for-one means only one security comes back (I5).** Any further shares, rights, warrants, units or CVRs break
  it, so FNF 2014, GGP 2010 and LSXMA 2023 stay mergers or baskets.
  - Cost if wrong: a few one-for-one-plus-CVR deals stay mergers.
- **OKE and ROVI are routed to 5h.** OKE needs OpenFIGI's own composite for its new CUSIP. ROVI needs TiVo's former
  name, Titan Technologies, for the name tie.
- **NCRA, NWS-A and SXCI are residual.** Their lines have no source for the new ticker.
- **Floors lowered by hand,** each traced in the 5c acceptance commit.
