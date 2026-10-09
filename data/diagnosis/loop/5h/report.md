# Sub-plan 5h: identity (operator report)

Base 0de5d8f. Design note `docs/superpowers/plans/research/2026-10-04-5h-identity.md`. Run and accepted with the rest
of wave 1; the shared steps, floors and open items are in `../wave1/report.md`.

## Result

**Accepted by the controller, with wave 1.** Of the 11 truth cases 5h owned at the base, 6 pass: CRC, ERA, LMCA, MSG,
UAC-C and UAG. The golden ERA row flipped to pass.
- IAC and ROVI now name 5f.
- WW and ABBI are residual: their real later endings (WW's 2025 chapter 11, ABBI's 2010 Celgene merger) need a CUSIP
  their securities do not hold.
- OKE is residual for its last trade.

## What 5h changed

- **Identity rules:** class-ticker base rows (rule A), a cross-class switch, foreign ticker rows, and name checks.
- **Rule D:** the issuer in force decides an era's issuer.
- **Rule F:** a ticker-tier pick folds into the 2015 split's line (BTU).
- OKE's line is followed past the end of the fails data.
- **Rule G:** no continued-filings guess for a security without a CUSIP. This removed the false endings of WW 2013,
  CRC 2016, UAG 2009, ABBI 2008, NCRA 2013, UAC-C 2016, MSG 2015, LMCA 2013 and ERA 2013.
- **Fix wave (979601b):**
  - Rule D decides by the era's own fails rows when it has at least 3 (ERA 2013 stays on Era Group).
  - `history.clip_at_takeovers` ends a range carried on to the next ticker the day before another security's first
    day under it: MSG, GOOG 2014, GCI 2015 and IAC's IACI range.
  - OKE's added successor starts on the next trading day.
  - FIGI-to-FIGI renames (BTU, CRC) get `contract/id_changes.csv` rows.
  - Rule A relabels a base-symbol row only before the base symbol's own first sighting. The reviewer's ±30-day bound
    split UAC-C into three ranges.
  - The ruling script is idempotent.

## Rulings

`scripts/apply_5h_truth_rulings.py --after-run` renamed three truth rows:
- ABBI to the new Abraxis placeholder CIK1409012-COMMON;
- ERA to the run's FIGI BBG001YH8PR9;
- CRC to BBG0060B3M63, shaped ending_moved.

The integration renamed BTU to BBG000FW00S1. The loop round renamed MSG, LMCA, UAC-C and UAG from id_changes. The
UAG audit row now lists PAG only.

## Carried

- To 5i: a closed_no_event security (WW) is counted as confirmed; it should be uncertain.
- Optional: rule F's check that the ticker pick is today's holder.
