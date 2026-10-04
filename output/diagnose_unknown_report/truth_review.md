# Diagnosis truth file: review

282 cases. Status: {'known_wrong': 265, 'pass': 17}. Shape: {'ending': 225, 'no_ending': 42, 'ending_moved': 15}.

## known_wrong by sub-plan

- 5a: 41
- 5b: 23
- 5c: 26
- 5d: 31
- 5e: 29
- 5f: 81
- 5g: 12
- 5h: 6
- 5i: 11
- residual: 5

## Mismatches by field (judged cases)

- cash_currency: 123
- value_rule: 76
- internal_last_trade_date: 73
- price_ticker: 69
- last_trade_date: 58
- shape: 57
- price_sec_id: 53
- exit_kind: 49
- price_date: 43
- stock_ratio: 38
- continuation: 35
- successor_sec_id: 28
- cash_per_share: 24
- drop_reason: 20
- legs: 10

## Pending questions


## Residual list

- BBG000BV18Z1_2017-05-18 (TDW): TDW: prepackaged Ch.11, old stock stayed on NYSE to plan effective 2017-07-31 (no Form 25); last day from fails rows only so not published; operator ruling 2026-10-03: residual; residual: the plan package includes Series A/B warrants, which no field carries
- BBG000C11MQ5_2015-06-05 (PCYC): PCYC default package $152.25 cash plus AbbVie shares worth $109.00 over the ABBV trading price; MIDAS agrees on 2015-05-22; operator ruling 2026-10-03: a dollar-valued stock leg over a VWAP: stock_ratio not scored; residual: Floating stock leg ($109.00 / AbbVie Trading Price) cannot be expressed as a fixed stock_ratio.
- BBG000DST2V3_2012-06-04 (EP): Skeptic refuted section 3: 14.53 cash + 0.4231 KMI is the final prorated stock-election package (8-K 2012-05-30, R4); mixed 14.65/0.4187 applies to about 23% of shares; Form 25 notice: suspended 2012-05-25; residual: 0.640 KMI warrant per share is part of the package and the rule has no field for it
- BBG001KWG293_2021-06-25 (GRUB): Stock merger 3.355 JET ADS per share; last trade 06-15 from MIDAS, 8-K says only suspended June 15 (06-14 not excluded); operator ruling 2026-10-03: JET ADS: price_sec_id and price_ticker not scored (no non-fails symbol source); residual: JET ADS (CUSIP 48214T305) trades OTC and the run has no ticker or price source for it
- BBG00Z6DX554_2020-07-30 (EXE): Chapter 11 2020-06-28; NYSE suspended 2020-06-29 per 8-K 3.01 and Form 25; OTC Pink CHKAQ from 2020-06-30; skeptic upheld CHKAQ.; residual: R7: one FIGI spans the old CHK stock and the post-bankruptcy stock (new CUSIP 165167735 from 2021-02-12)
