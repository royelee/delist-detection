# Sub-plan 5e: acquirer security and the payout gate (operator report)

Base 0de5d8f. Design note `docs/superpowers/plans/research/2026-10-04-5e-acquirer-gate.md`. Run and accepted with
the rest of wave 1; the shared steps, floors and open items are in `../wave1/report.md`.

## Result

**Accepted by the controller, with wave 1.** Of the 29 truth cases 5e owned at the base, 14 pass: AVB, CAL, GLIBA,
GXP, IHS, JEF, JNS, LSXMA, MIR, MRD, RTN, RYL, TCF and XMSR.
- 11 of the other 15 now name 5f, mostly `cash_currency`: ABI, BLD, EV, FRX, GCI, HTS, NYX, PPP, SCS, THE and URS.
- LEG, SOV, UNIT and TERP are residual. TERP matched in 5e's offline replay, but its acquirer fields still mismatch
  in the live run.

## What 5e changed

- **Stage 8a** finds every stock leg's acquirer line before the payout gate (`acquirer_line`). The gate prices the
  package on that line.
- **A ticker handed over at the closing**, with the holder's issuer checked.
- **Fix wave (784da27):**
  - **Critical:** answering a `received_close` request flipped the acquirer and the request key, so the second run
    exited 2 (CAL, GLIBA). Now the published acquirer and the request come from a first gate pass that reads no
    answer, and each answer is used only on its own request's path. A round-trip test covers every case.
  - The price-date symbol comes from the fails row that carries that day's close: JCI is JCI, CB is CB, ABI is LIFE,
    FTO is HFC and PLD is PLD.
  - A gate settled on the terms' ticker keeps stage 8a's line of the same issuer: TWC is New Charter, VIA is
    ViacomCBS class A and STRZA is LGFB. VIA's dlret moves from −6.03% to +2.56%, and TWC's from −2.83% to +3.19%.
  - A `--merger-terms` acquirer ticker is published as the caller gave it.

## Rulings

ABI's price ticker is LIFE: Invitrogen was renamed Life Technologies on 2008-11-21, as the loop's diagnosis cited.
The ABI unit test expects LIFE.

## Changes outside the truth set

36 stock legs gained an acquirer FIGI, or a corrected one, settled `new_right` by kind. VMED's (LBTYA) and MHS's
(ESRX) were diagnosed by the loop. VMED's row is now a scored truth row.

## Carried

- To 5f: `cash_currency`, JCI's cash-plus-stock package, CCE's New CCE stock leg (the library prices KO), and VMED's
  two-class leg (0.2582 class A plus 0.1928 class C).
- Deferred: ASD and WCRX fixtures, and abbreviated acquirer names (CB&I).
- Expected live: `_line_wins` may make a few extra cached OpenFIGI requests.
