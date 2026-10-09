# Sub-plan 5f: terms extraction (operator report)

Base ca58ee1. Design note `docs/superpowers/plans/research/2026-10-04-5f-terms.md`. Run and accepted with 5i in wave
2; the shared steps, floors and open items are in `../wave2/report.md`.

## Result

**Accepted by the controller, with wave 2.** Of the 127 truth cases 5f owned at ca58ee1, 107 pass. The other 20 are
residual: ARD, CBSS, CCE, CHTR, CZR, DVMT, FRK, FWLT, IAC, LGFB, LMCA, LMCK, MIC, MLNM, PARA, RAI, ROVI, TAHO, TWC and
VSTO.

## What 5f changed

- **Currency (R5).** The regex read keeps its "$" prefix (C$ is CAD). The LLM's currency is checked against its own
  quote, and a bare "$" never overrides a stated non-USD code. The gate skips a non-USD leg
  (`terms_gate_skipped`). THI's C$65.50 is the one non-USD deal.
- **Prompt v3** returns the package one share became (R4: the final prorated result, else what non-electors got,
  never the sum of the alternatives), with the stock issuer and class, a dollar-valued leg and further legs.
  Candidates put completion filings first. All about 780 LLM answers are new (cache/llm/).
- **Baskets.** Two or more securities per share is the `basket` rule, with `contract/payout_legs.csv` (schema 3; each
  leg carries its class) and a price request per extra leg. PCYC's dollar-valued leg names its averaging window in
  `value_formula`.
- **Further rules:**
  - spec 5c's rule 6 on the successor branch: CHTR is a merger, and SIRI's 0.1 stays a continuation;
  - a 6-K near the Form 25 that states the completion, with a role check (TAHO, KING, BPYU);
  - SPB restored as a continuation;
  - stage 8a falls back to the acquirer's name (FDC);
  - `plan_stock` is the R6 plan value's own method;
  - update_truth judges payout legs.
- **Fix wave (dea52c9):**
  - an election with no stated default reads the cached v2 answer, flagged `election_no_default`;
  - acquirers named by a defined term are resolved through the filing's definitions, SEC's name index and the fails
    rows (`acquirer_ticker.py`): SHAW is CBI, HBI is GIL, CLP is MAA;
  - every answer shape is safe in the gate;
  - basket legs keep their class (CAA's LEN-B);
  - R4 is applied the same way to NMX and EP.
- **0624495 and 1244bc7:** an election with no stated non-electors' package publishes the base reading of its first
  candidate filing, and never moves on to later filings (TRH 14.22 + 0.145 Y; NMX cash 81.16).

## Rulings

- SCS's last trade is MIDAS's 2025-12-09.
- BLUE's default is $3.00.
- VSTO's one security plus cash is cash_plus_stock.
- VMED is a two-leg basket, and MHS's currency is USD.
- EP's package is the non-electors' 14.65 + 0.4187 (R4).
- FRK's truth becomes stock 0.63 VMC (R4).
- TRH's regression row is USD.

## Changes outside the truth set

- 370 rows gained `cash_currency` USD. The review checked all 512 cash amounts against their filings.
- Value changes: NMX, PXP, CYN, PAS, TMX, NSM, AYE, HTV, EVHC, the baskets CAA, BKW and PARAA, SHAW, HBI and CLP
  (acquirer tickers), and WSC (flagged).
- In the review's sample, 7 of 41 changed mergers were wrong. All were fixed in dea52c9, 0624495 or 1244bc7, except
  WSC: its flag asks a person to settle it (the review says all-cash $385.00).

## Carried

EQC's $1.60, MLNM's EX-99.1 day, R1 at the handoff stage (the Liberty baskets), 6-K exhibit text, and CCE 2016's
"Orange".
