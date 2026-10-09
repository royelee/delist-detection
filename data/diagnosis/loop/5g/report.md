# Sub-plan 5g: distress endings (operator report)

Base 0de5d8f. Design note `docs/superpowers/plans/research/2026-10-04-5g-distress.md` (commit 266be6c). Run and
accepted with the rest of wave 1; the shared steps, floors and open items are in `../wave1/report.md`.

## Result

**Accepted by the controller, with wave 1.** All 25 truth cases 5g owned at the base pass: ASNA, BTU, CBL, CWTR, DF,
EPE, EQC, FST, FTR, GPOR, GTX, HTZ, IDARQ, IMB, KWK, LTRPA, MNI, RAD, RHDC, SDRL, SPNV, TMA, VRM, WFT and WOLF. CBL,
IDARQ, RAD, TMA and VRM needed 5d's last trade dates. The golden CBL-2008 row flipped to pass.

## What 5g changed

- **Stage 9e** gives each distress ending its OTC symbol, from a notice or the fails rows, and the price drop
  reason. It also handles the R6 plan exchange: a bankruptcy plan's new shares give the ending its ratio.
- **Spaced item numbers** ("ITEM 3 . 01"; CBL).
- **The end-of-era liquidation branch** (EQC).
- **Fix wave (f5dea83):**
  - PMI's OTC symbol PPMIQ, from a 60-day window and a kept-trading test that ignores the settled last close; only
    PMI changes.
  - An answered `received_close` feeds an R6 plan's value.
  - An R6 ending's last close comes from the old CUSIP, never the plan's new one: WOLF's is 1.85, where it was 22.10.
  - `otc_symbol_from_text` takes the last symbol in a sentence (Ambac: ABKFQ).
  - A tighter spaced-item pattern rejects 10-K table-of-contents entries.
  - A test covers stage 9e's degraded path.

## Rulings

- EPE's drop reason is price, not guidelines: both filings cite only the 802.01D abnormally low price.
- WOLF's stock ratio is 0.00835187 (1,306,896 / 156,479,390).
- BTU 2008–2016 is BBG000FW00S1 (5h's finding).

## Changes outside the truth set

30 OTC symbols on bankruptcy endings, settled `new_right` by kind. SIVB's symbol is now blank: the old value was the
exchange ticker, and SIVBQ is likely but has no cited filing.

## Carried

- To 5f: EQC's stated $1.60 final distribution. It keeps the Shumway fill, labelled as a fill.
- An answered plan value shows `dlret_method=otc_print`; a dedicated method would be clearer.
- GOCO stays residual.
