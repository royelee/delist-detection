# Sub-plan 5d: last trade date (operator report)

Base 0de5d8f. Design note `docs/superpowers/plans/research/2026-10-04-5d-last-trade.md` (no separate plan). Run and
accepted with the rest of wave 1; the shared steps, floors and open items are in `../wave1/report.md`.

## Result

**Accepted by the controller, with wave 1.** Of the 36 truth cases 5d owned at the base, 13 pass: APA, DBD, FCL,
HLTH, LLYVA, LLYVK, MNK, MYL, ODP, PMI, TMUSR, WEN and WM.
- 5g's cases CBL, IDARQ, RAD, TMA and VRM waited on 5d's last trade dates, and now pass.
- Of the 23 left, 21 now name 5f, mostly for `cash_currency`; CCE, JCI and SGP moved there from 5e. DADE and IFIN
  are residual: no filing states either day.

## What 5d changed

- **The 3.01 reader** reads every 3.01 section sentence by sentence:
  - "at/after the close of trading on D";
  - the last day traded;
  - R8, published: "suspended on D" reads as the trading day before D, in both word orders. The second order, "On
    D, ... had been suspended", came in the fix wave.
  - "suspended immediately on D", unconfirmed;
  - a weekday before the date (fix wave).
- **Source order:**
  - MIDAS, then a halt; an 8-K that puts the halt at the open wins (WM 2008).
  - The notice's own timing, then an 8-K timing that disagrees with a bare notice date (TMHC).
- **Rule 3:** a MIDAS or halt day under a ticker another CUSIP had taken by then belongs to the other CUSIP (CCE,
  JCI 2016, GRUB 2021).
- **Rule 4:** an undated row under an exchange's Form 25 takes the closing day its 8-Ks state, unconfirmed and never
  published. Since commit 34737db, that day is never earlier than the last day the fails rows show the security
  trading (AVGO 2018, Z 2015). The rule never runs under an involuntary (b) Form 25 (fix wave).
- **Fix wave (01c5ee7), more readings:** the no-Form-25 fallback reads 3.01 8-Ks to the last sighting + 5 days (VRM).
  The NYSE (b) template's press day is never a last trade (TMA, IAR). A day on no session moves back one (CNDT). A
  class expiry is bounded to the filing's dates.

## Rulings

- **5d's own** (in the decisions file): DBD 2023 MIDAS 05-26, GRUB 2021 06-14, HTS 2016 07-12, and DTV and PHLY
  published.
- **Wave 1's:** RAD 2023 MIDAS 10-13, golden JCI-2010 2016-09-02, and CZR 2020 07-20 on MIDAS evidence (this
  **overrides your R8 ruling**).

## Changes outside the truth set

- The loop settled seven ticker ranges that now end at the closing day as `new_right`: CI, MRVL, AZPN, VNOM, PNFP,
  AVGO and Z. AVGO and Z were settled after the fix.
- CB's last trade is 2016-01-14, FTI's 2017-01-13 and WCN's 2016-05-31.
- CNDT's Sunday became 2019-12-20, and LNT 2019 gained 2018-12-28.

## Carried

The 5a carry (a rename's ticker boundary 1–3 days late) is still deferred. OKE's last trade is residual.
