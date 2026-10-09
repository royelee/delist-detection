# BBG000BF3BG8_5a-r1 (HRTH, Harte-Hanks) — regression, `security_history.ranges`

## 1. Verdict
The new ranges are right: Harte-Hanks common (one CUSIP, 416196202) was suspended on the NYSE after the close on 2020-07-09, quoted on OTCQX as HRTH, and relisted on Nasdaq as HHS on 2021-12-01. Splitting the history into HHS / HRTH / HHS is correct; the old single HHS range misstated the symbol for 17 months. The boundaries are a few days late (fails-row lag), not wrong in kind.

## 2. Library vs evidence
| Field | Old (base run) | New (this run) | Evidence | Right |
| --- | --- | --- | --- | --- |
| `security_history.ranges` | HHS 2008-01-16.. (open) | HHS 2008-01-16..2020-07-15; HRTH 2020-07-16..2021-12-02; HHS 2021-12-03.. | Symbol was HHS on NYSE to 2020-07-09, HRTH on OTCQX from the next session, HHS on Nasdaq from 2021-12-01 | new (bounds lag 1-7 days) |
| `exit_kind` / `successor` / `last_trade_date` / `value_rule` / `terms` | no contract row | no contract row (internal 25-NSE row is `exchange_transfer`, successor = itself) | not a changed field here | unchanged, see open checks |
| `issuer` | CIK 45919 | CIK 45919 | unchanged | agree |

## 3. Corrected classification
```
ranges: HHS ..2020-07-09 (NYSE); HRTH 2020-07-10..2021-11-30 (OTCQX); HHS 2021-12-01.. (Nasdaq)
event_type: exchange_delisting then relisting (uplisting), same CUSIP
confidence: verified (for the symbol sequence)
```
The fails rows date HRTH from 2020-07-16 to 2021-11-16 and HHS again from 2021-12-03, because a fails row is dated a few days after the trade; the filings put the switches at 2020-07-10 and 2021-12-01.

## 4. Why this confidence
verified for the field in question. The symbol sequence rests on filings: 8-K 2020-07-23 cover (HRTH, OTCQX), 25-NSE notice (suspended after the close on 2020-07-09), 8-K 2021-11-30 and 8-A12B (OTCQX "HRTH" until Nasdaq listing as "HHS" expected 2021-12-01). Fails rows (CUSIP 416196202, HRTH 22 rows 2020-07-16..2021-11-16) agree.

## 5. What happened
- [SEC 8-K 2020-07-13](https://www.sec.gov/Archives/edgar/data/45919/000143774920015025/hhs20200710_8k.htm): NYSE determined on 2020-07-09 to delist the common stock.
- [SEC 25-NSE 2020-07-28](https://www.sec.gov/Archives/edgar/data/45919/000087666120000587/xslF25X02/primary_doc.xml): NYSE suspended trading after the close on 2020-07-09 (stockholders' equity / market cap below $50M).
- [SEC 8-K 2020-07-23](https://www.sec.gov/Archives/edgar/data/45919/000143774920015579/hrth20200722_8k.htm): cover lists HRTH on OTCQX.
- [SEC 8-K 2021-11-30](https://www.sec.gov/Archives/edgar/data/45919/000143774921027504/hrth20211128_8k.htm) and [8-A12B](https://www.sec.gov/Archives/edgar/data/45919/000143774921027508/hrth20211128_8a12b.htm): uplisting to Nasdaq expected 2021-12-01 under HHS.
- Fails rows: CUSIP 416196202 under HHS to 2020-07-14, HRTH 2020-07-16..2021-11-16.

## 6. Decision-tree bucket
Same security (same CUSIP) throughout: it left the NYSE for OTC and later relisted. The ticker change on OTC and back is real symbol history.

## 7. Why the library changed
Sub-plan 5a's line follow now reads the fails rows under HRTH as the same security's ticker; before, the period was left under HHS. Cause: `other:improvement` (the base run was the less accurate side).

## 8. Fix and open checks
- No fix needed for the ranges, except that range edges could use the 25-NSE suspension date and the 8-A12B date instead of fails-row dates.
- Open check outside this field: the internal 25-NSE row (2020-07-28, last trade 2020-07-10 from MIDAS) is labelled `exchange_transfer` 304 with successor itself, so no contract ending is published. The NYSE delisting for a capital deficiency (CRSP 560, OTC afterwards) is arguably an ending with an OTC value followed by a relisting; the filings support a last NYSE trade of 2020-07-09, not 07-10. Not part of this field's verdict.
- Not golden-worthy as is (range-edge dates unsettled).
