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

- **2026-10-04: 5d, 5e, 5g and 5h run in parallel.**
  - 5d runs in this worktree; 5e, 5g and 5h each run in their own git worktree. Their dependencies (5a, 5b, 5c) are
    done.
  - Then the controller merges them one at a time, runs one whole-branch review, one fix wave, one network run and
    one truth loop for the wave, and writes a report per sub-plan.
  - 5f follows 5e, and 5i comes last.
  - Alternative: one at a time, about 3 hours each on the new flow.
  - Cost if wrong:
    - merge conflicts in the shared files (pipeline.py, delistings.py, classifier.py);
    - interactions between the four sub-plans that only the combined loop sees;
    - attribution of a regression to one sub-plan takes a look at its kind.

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

## 5d (2026-10-04)

Design note: `docs/superpowers/plans/research/2026-10-04-5d-last-trade.md`.

- **R8 is published.** A bare "suspended (trading ...) on D" reads as the trading day before D, a confirmed 8-K
  print (`8k_suspended`, source `8k_301`), so the contract publishes it (MNK 2020-10-09, as the truth has it).
  "Suspended immediately on D" stays D, unconfirmed.
  - Alternative: keep the bare reading unconfirmed, so it never beats a notice.
  - Cost if wrong: a stock suspended after the close on D, stated without a timing word, is dated a day early.
- **An 8-K timing beats the notice's bare date when they disagree** (spec rule 2; TMHC 2026). On the 572 rows MIDAS
  dates, such disagreements side with the 8-K 4 times and the notice 3 times. HTS 2016 is re-ruled to 2016-07-12 by
  the same rule (its 8-K: "following the close of trading on July 12"; its report read only the notice).
  - Alternative: the notice keeps winning, and TMHC's truth moves instead.
  - Cost if wrong: about one day on a handful of rows, either way.
- **A halt the feed stamps at the open is the halt day unless the 8-K puts the halt at the open.** WM 2008 (09:30:06,
  the 8-K's "halt ... at the NYSE market open on September 26") gives 09-25; HET 2008 (09:30:05, its 8-K's "close of
  business on January 28") stays 01-28. A time threshold was tried first and broke HET.
  - Cost if wrong: a halt at the open with no 8-K wording keeps the halt day.
- **The ticker's tenure bounds MIDAS and halts only when a text day comes before them** (spec rule 3). Bounding
  every read gave wrong days where the successor's first fails rows lag its first trading day (Sinclair Inc 2023,
  the new TCF 2019) or are a $0.01 placeholder (APA Corp 2021).
  - Alternative: bound every read, which also dates continuations from MIDAS (SIRI 2024's 09-09 would publish).
  - Cost if wrong: a continuation's last trade stays a worked-out day where MIDAS could have given a print.
- **The spec's fails-row check of a MIDAS/text conflict is not built.** Rule 3 settles the conflicts the cases show,
  and the one conflict without a successor (DBD) has MIDAS confirmed by a halt and the fails rows.
- **DBD 2023 is re-ruled to MIDAS's 2023-05-26** (price date 05-30): no volume after it in a covered quarter, a
  Nasdaq code-D halt at 07:16 on 05-30, and the fails rows' one stale close. The truth had 06-01 worked out from
  "suspended on June 2".
- **GRUB 2021 is re-ruled to 2021-06-14** (R8 on the 8-K, the NYSE notice; MIDAS's 06-15 is JET's ADS). DTV 2009
  (the 8-K's "as of the close of trading on November 19") and PHLY 2008 (a code-D halt before the open on the Form
  25 day) get a published `last_trade_date` equal to the day their truth already worked out. GRUB and DTV were
  pass rows; they are known_wrong fixed_by 5d until a run of 5d's code matches them.
- **The closing day is the worked-out last trade (spec rule 4), never published.** The latest completion the 8-Ks
  state within ten days before the Form 25, else the Form 25 day; the day before when every clock time stated is
  before the open, or the day is no session. DADE 2007 and IFIN 2007 stay off it (the truth's day before the Form
  25 day has no source; residual unless the network run's halt feed answers). MLNM's published day is in its
  EX-99.1 press release, which 5d does not read (moved to 5f with its currency).
  - Cost if wrong: an unconfirmed day on about 20 rows, a day off where a merger closed before the open without a
    clock time.
- **The 5a carry (a rename's ticker boundary 1–3 days late) is deferred.** The run has 638 such boundaries, 223 of
  them outside the truth set, all unscored; a rule needs MIDAS's first day per boundary, measured on its own.
- **The golden case JCI-2010 conflicts with the truth.** It pins 2016-09-06; the 8-K, MIDAS bounded by Johnson
  Controls plc's start and the truth row (verified, upheld) give 2016-09-02. I may not edit the golden file, so
  `G.pass` drops by one on the network run; the golden row needs 2016-09-02.
- **Floors lowered by hand** in the rulings commit (D.mismatches 478 → 483, D.cases_matching 103 → 101, and three
  last-trade field floors): the rulings move truth cells on rows the committed, pre-5d output still holds. The
  offline replay of 5d's code gives D.mismatches 414.
- **Fixed_by relabels.** 26 rows whose last trade fields match the replay but keep other mismatches now name 5e, 5f
  or 5g; the 12 rows that match the replay stay known_wrong until the loop flips them.
