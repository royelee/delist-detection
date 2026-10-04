# 5e: acquirer security and the gate (research and design)

Date 2026-10-04. Base 0de5d8f (5c accepted, D.mismatches 478), branch `5e-acquirer-gate`. Every finding comes from
cached data with network refused. Probes and replays are in `/tmp/claude/delist_detection/5e/` (`replay_5e.py`,
`dump_stage8.py` with `stage8.pkl`, `stage8_replay.py`, `proto.py`, `names.py`, `refused.py`) and the scratchpad
(`r5e/`).

Target set: the 36 case-map rows with sub_plan 5e and the 29 truth rows with fixed_by 5e (40 rows together, 61
mismatches at the base). 15 of those mismatches are `cash_currency` (5f's) and 9 are last-trade fields (5d's).
The rest are `price_sec_id` (23) and `price_ticker` (13), which are this sub-plan's.

## 1. What the code does (replayed)

**The roadmap's "unconfirmed" gate false fails (NYX, SCS, EV, SUN, THE).** The LLM labels each deal `election`.
`payout_gate.reconcile`'s election branch tests the cash leg alone and the stock leg alone against the last close.
The default package these deals pay is cash *and* stock, so both tests fail (`llm_gate_failed`, assumed par). Pass 2,
the cash+stock gate, skips elections. Neither a missing acquirer price nor a stale close is the cause. The package,
cash plus ratio times the acquirer's next-day close, is within 2% of the close in every case:

| Case | Package | Last close |
| --- | --- | --- |
| NYX | 11.27 + 0.1703 × 199.84 = 45.30 | 45.29 |
| SCS | 16.46 | 16.14 |
| EV | 73.09 | 72.21 (`ftd_close_prior:5`) |
| SUN | 46.83 | 46.75 |
| THE | 48.84 | 48.55 |

The same holds for FRX, URS, HTS, PPP, ABI, HEW and EP.

**Blank `price_sec_id`.**
- `_add_acquirers` ran only on terms that passed the gate.
- `acquirers.find_acquirer` accepts an OpenFIGI CUSIP answer by the terms' ticker. The answer is empty for renamed
  lines: LUK's 527288104 (JEF) and SIRI's 2008 CUSIP 82966U103 (XMSR).
- So 40 passed stock legs outside the truth set had no `price_sec_id` either. Each one's acquirer line held the
  ticker in the run's own ticker sightings.

**Stale ticker.** The gate priced the leg by the terms' ticker at the close of the last trade day. That gave one of
three results:
- no row: UAUA (CAL) and RRI (MIR) give `no_acq_price`;
- a placeholder: UAL and GEN at $0.01, AMCR and JHG at $1.00, INFO and NTCO at $0.01;
- a pre-closing close: UTX at 86.01 still included Carrier and Otis (RTX closed at 49.93 the next day); SPF traded
  before its 1-for-5 consolidation.

**Other causes.**
- No ticker in the terms (LEG, GXP, LSXMA, GCI, UNIT) gives `no_acq_ticker`.
- A class error: GLIBA names LBRDA, which has no rows, while the filing says Series C.
- AVB's `price_ticker` is the LLM's VMRK, but its line traded as EQR on the price date (VMRK began 08-19).
- TCF's last close (42.04) is the acquirer's. The target's CUSIP has no fails rows, so `ftd.close_of` fell back to
  the symbol TCF, which Chemical Financial took at the closing. This is 5d's tenure rule; JCI and WEN show the same.
- MRD's last close is a lagged row (09-19, 11.78). The close known on its last trade day is 14.69, so the gate is
  right to fail on the published close.

## 2. Rules (as built)

The work is a new pure module, `acquirer_line.py`, and a new pipeline stage, 8a (`_acquirer_lines`). It runs
before the payout gate, for every stock leg (a `--merger-terms` row with a ratio, or LLM terms with a ratio), passed
or not.

1. **Issuer.**
   - First, the run's security that held the terms' ticker on the last trade day (`LineIndex.holder`, from the
     run's ticker sightings). A ticker that begins only at the closing counts from the price date (JHG). A hold
     that ends before the price date, while another security takes the ticker by then, was handed over at the
     closing (WCRX: Actavis Inc's ACT went to Actavis plc).
   - The holder's issuer must have filed with EDGAR by the last trade day, and one of its EDGAR names must agree
     with the acquirer name (`issuer_fits`; this keeps ASD's 2007 IR line, Ingersoll Rand Inc, first filed 2017).
   - Else the resolver's issuer of the ticker on the last trade day, asked with the acquirer name
     (`issuer_by_ticker`), with names agreeing and never the target's CIK.
   - Else, with no ticker, the run's issuer that carried the acquirer name within [last trade − 400 d, price date
     + 30 d] and shares the most of its words, uniquely (`issuer_by_name`).
2. **Line** (`choose_line`), among the issuer's lines:
   - the one trading on the price date of the class the terms' quote names after "receive" or "into" (GLIBA:
     Series C);
   - else the one line whose CUSIP's first fails row falls in [last trade, price date + 3 trading days] (the
     closing CUSIP);
   - else the ticker's holder;
   - else the one line trading on the price date.
3. **Price and symbol.**
   - A closing CUSIP is priced at its close on the price date, from the next day's row, skipping placeholders
     (`is_placeholder_row`: ≤ $0.01, a non-trading symbol, or a $1.00 row whose next row is more than twice or
     less than half of it). The old CUSIP's stale repeats are never read.
   - Any other line is priced at its close on the last trade day, as before.
   - The symbol on the price date comes from the row dated that day (the closing CUSIP first: RTX over UTX), else
     the first row in the next 3 trading days.
   - For a merger before the run's fails window (PPP 2007), the candidate lines' rows are read into a private
     index. The run's index is not extended.
4. **Gate** (`payout_gate.gate_payouts(..., line_price=)`).
   - The terms' ticker price is tried first, unchanged. The line's price is tried when the ticker gives none or its
     price does not reconcile. `priced_by` records which price settled the leg.
   - An election whose two legs together reconcile is its default package (`llm_election_package`, cash and stock).
     A leg that fits alone still wins.
   - A received-close answer matches either ticker.
5. **Publish.**
   - `price_sec_id`, when the ticker settled the gate: today's fails-row acquirer, kept unchanged (it is also the
     only source of new `AddedAcquirer`s); else the holder.
   - When the line settled it: the line.
   - Otherwise (a failed or ungated leg): the line, else the holder.
   - `price_ticker` is the published security's symbol on the price date (`_Payouts.price_tickers` →
     `MergerInputs.price_ticker`). `price_requests.stock_legs` asks by it, and asks for a leg with no LLM ticker
     once the line is known.

## 3. Guards (named, tested in `tests/test_acquirer_gate_cases.py`)

- **RDC 2019.** ESV's pre-consolidation close reconciles 2.75. The leg is priced by the ticker, never on the
  post-split CUSIP.
- **WBS 2026.** The acquirer the run adds (BBG000BTJS47) is unchanged.
- **IPHI 2021.** New Marvell from the fails rows, not old Marvell's holder.
- **PGN 2012.** DUK is unchanged.
- **SOV 2009.** SAN was Santander Chile's ticker then. No line is found; the gate still fails.
- **MRD and BLD.** The line is found, but the gate still fails: it is doing its job.
- **TCF.** The line is found; the gate fails on the target's own close (5d).
- **Dated lookups.** The resolver is asked only on the last trade day (GEN, reused by Gen Digital in 2022).
- **Either-or elections.** They are never summed (BLD's 505 or 20.2 QXO).

## 4. Blast radius (offline replay of 0de5d8f against HEAD over the whole run)

See the replay record (section 7). Outside the truth set, the only reported-column change is a blank
`price_sec_id` filled on 42 merger endings. On VIA and VIA-B, `price_ticker` also changes, from CBS to VIAC, CBS's
ticker on the price date. On SNI it changes from DISCA to DISCK (the filing's Series C). The two rules added after the
first replay (D-holder handover, issuer check) moved exactly WCRX (old Actavis to Actavis plc) and ASD (the wrong
2017 Ingersoll Rand line to none), measured by rerunning stage 8 alone on the pickled stage-8 inputs.

`security_history`, `terms_gate` and `dlret` outside the truth set do not change: the gate repairs reach truth rows
only. No securities are added. R1 and handoff outcomes are unchanged.

## 5. Expected changed list

**Fixed: every scored field now matches.**
- CAL, RTN, RYL, TCF, MIR, JNS, IHS, GLIBA, GXP, LSXMA, JEF, XMSR, AVB, MRD and TERP. These are 15 of the 29
  fixed_by-5e rows.
- TERP matches because the resolver's issuer of BEP holds BEPC, which is the default package (R4, 5f).

**Fixed apart from other sub-plans' fields.** The `price_sec_id` mismatch is gone; what remains belongs elsewhere:
- `cash_currency` only (5f): NYX, FRX, EV, URS, HTS, PPP, BLD and EP.
- 5d's last-trade fields: LEG; ABI keeps both those and `cash_currency`.

**Bonus outside 5e's own rows.** RKT (WRK), WEN, ANN, SGP, THI and JCI each lose one or two mismatches.

**Left open.**
- GCI and UNIT: the acquirer is named only by a post-closing name shared with the target, or by "Windstream", and
  its line is not in the run (rule 2's "add the acquirer" is deferred, D3). Recommend 5f, reading the ticker or
  new name from the filing, else residual.
- SOV: the LLM's anachronistic SAN; the ADS traded as STD in 2009. Recommend 5f.
- SCS, THE, LEG, ABI: last trade and price date (5d). UNIT: the internal last trade date (5d).
- `cash_currency`, 15 rows: 5f.
- MEL (5i) gains one mismatch: a `price_sec_id` on its published merger row, where the truth is a continuation. It
  goes away when MEL's exit kind is fixed.

## 6. Decisions

- **D1. Ticker price first, line price second.**
  - Alternative: always price on the line at the price date.
  - Why: every row that passes today keeps its price (RDC: the post-consolidation CUSIP would fail 2.75).
  - Cost if wrong: a ticker price that reconciles by accident keeps a wrong price. The line is still published.
- **D2. A passing row's fails-row acquirer is never overridden; only blanks are filled.**
  - Alternative: the line always wins.
  - Why: IPHI's new Marvell sits under another CIK than old Marvell's holder.
  - Cost: a wrong `find_acquirer` composite stays.
- **D3. No new `AddedAcquirer`.** Spec rule 2's "add the acquirer when it has no line" is deferred.
  - Why: added securities feed stage 8b's and stage 9's successor searches and stage 9b's handoffs. Every scored
    truth `price_sec_id` is already a line of the run.
  - Cost: GCI's New Gannett and ETP/HERO-like acquirers stay without a `price_sec_id`.
- **D4. Name route only among the run's issuers, scored by shared words, unique best.**
  - Alternative: EDGAR's whole name index.
  - Why: a CIK with no line in the run yields nothing under D3. `names_agree` alone lets 'SM Energy Co' match
    'Monarch Energy Holding'.
  - Cost: an acquirer that is in the run under another CIK and is named only by its name; none was found.
- **D5. Election package.**
  - Alternative: leave elections to 5f.
  - Why: the LLM's two legs are the default package R4 publishes. An either-or election's legs together are about
    twice the close, so they fail.
  - Cost: two either-or legs that happen to sum near the close; none found.
- **D6. Spec rule 5's stale-close relaxation is not built.**
  - Why: MRD is the only remaining case. Passing it on the fresh close would publish +25% against its published
    lagged close. The real fix is the last close itself (5d's fails-close rule).
  - Cost: MRD stays assumed par and uncertain.
- **D7. Non-USD cash leg (R5) is left to 5f.** It needs the LLM's currency, a schema change.
- **D8. The price ticker comes from the security's own fails rows on the price date; ticker_history's line start
  is not moved** (rule 4's second half).
  - Why: moving RTX's start from 04-09 to 04-03 changes `security_history` outside the truth set.
  - Cost: ticker_history lags the price ticker by a few days for re-CUSIPed acquirers.
- **D9. The resolver is asked with the acquirer name**, as the agreed CAL/UAUA approach says.
  - Live cost: about 125 submissions and 150 full-text searches not in today's cache, about 280 requests once.
- **D10. Truth file: no change.** No truth row contradicts a correct fix. The 16 rows that now match flip to `pass`
  in the loop (`update_truth.flip_statuses`) after the full run, not here. The 14 fixed_by-5e rows left are
  re-routed in the reply, not in the file, to keep the parallel merge clean.
- **D11. A hold ending before the price date, the ticker taken by then, is handed to the new holder** (WCRX).
  - Alternative: the last-trade-day holder always.
  - Cost: a ticker reused within three trading days by an unrelated security; the issuer check (D12) still applies.
- **D12. A holder's issuer must have filed by the last trade day and carry an agreeing name** (ASD).
  - Alternative: trust the run's security master.
  - Cost: an acquirer whose EDGAR names never agree with the LLM's name (BRCM's "Holdco") gets no
    `price_sec_id` from its holder.
- **D13. An early merger's line rows go in a private index**, not into the run's index.
  - Why: later stages build ticker and CUSIP history from the shared index, so extending it before the fails
    window would move security_history.
  - Cost: one extra scan of the early fails files.

## 7. Replay record

The replay: `/tmp/claude/delist_detection/5e/replay_5e.py`, offline over the whole run. The base is 0de5d8f's src
(`base_out`) and the new run is HEAD (`final_out`). Both use `--id-baseline` = 0de5d8f's securities.csv.

- **Changed securities: 82.** 40 are in the truth set and 42 outside it.
  - Outside, every change is a `price_sec_id` filled on a merger ending. VIA, VIA-B and SNI also change their
    `price_ticker`.
  - No `delistings.csv` bucket, code, last trade or successor changes.
  - No `security_history` row changes.
- **D.mismatches 478 → 439.** By field: `price_sec_id` 40 → 12 and `price_ticker` 58 → 47.
- **D.cases_matching 103 → 119.** 16 known_wrong rows now match: AVB, CAL, GLIBA, GXP, IHS, JEF, JNS, LSXMA, MIR,
  MRD, RTN, RYL, TCF, TERP, XMSR and WEN (WEN is 5d's).
- **Other scorecard lines.**
  - R2.4.assumed_par 60 → 33.
  - V.uncertain_endings 252 → 232.
  - L2.low 187 → 163.
  - R1.4.review_rows 635 → 648, of which 36 `resolution_degraded` rows are offline-only (D9's uncached lookups).
  - V.audit.confirmed_but_wrong 31 → 32: JCI's gate now passes, so its wrong last trade (5d: 09-06 for 09-02) is
    no longer hidden behind assumed par.
- **What the loop will see.** About 42 regression rows, all filled `price_sec_id`s, until the loop settles them.
  Spot-checked as right: CBI→MDR, TW→WLTW, BDK→SWK, CB→Chubb, AGN→Actavis plc, COL→UTC, SNI→DISCK (Series C) and
  WCRX→Actavis plc. Unverified: VIA (Viacom class A) priced on CBS class B as the terms read; STRZA on the old LGF
  placeholder line.

## Docs (for CLAUDE.md, module level)

- `acquirer_line.py` — a merger's acquirer as a line of the run (sub-plan 5e). The terms' ticker and acquirer name
  are only evidence of the issuer. The issuer is:
  - the security that held the ticker on the last trade day (`LineIndex.holder`; a ticker beginning at the closing
    counts from the price date, and a hold that ends before the price date was handed over to the new holder);
  - its issuer only when it filed by then and carries an agreeing name (`issuer_fits`);
  - else the resolver's issuer of the ticker on that day, asked with the name (`issuer_by_ticker`);
  - else the run's issuer that carried the name around the closing, best by shared words (`issuer_by_name`).

  `choose_line` picks the issuer's line: the class the quote names, else the CUSIP that began at the closing, else
  the holder. `LineIndex.price` prices a closing CUSIP at its close on the price date, past the $0.01 and $1.00
  placeholder rows (`is_placeholder_row`), and any other line at the last trade day's close. `symbol_on` gives the
  line's symbol on the price date.
- `pipeline` stage 8a (`_acquirer_lines`) runs before the gate for every stock leg, passed or not. A merger before
  the run's fails window reads its lines' rows into a private index. `_gate` tries the terms' ticker price, then the
  line's (`gate_payouts(line_price=)`, `GatedPayouts.priced_by`). `_add_acquirers` keeps the fails-row acquirer for
  ticker-settled terms (the only source of `AddedAcquirer`s) and else publishes the line or holder.
  `_Payouts.price_tickers` carries the published security's symbol on the price date to `payout_rule`
  (`MergerInputs.price_ticker`) and `price_requests.stock_legs`.
- `payout_gate`: an election whose cash and stock legs together reconcile, when neither does alone, is its default
  package (`llm_election_package`).
