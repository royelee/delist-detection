# Worked example: THI (Tim Hortons) → Restaurant Brands International, 2014

The shape every report copies. Facts and links come from the operator's plan document ("Plan: Skill to Diagnose
Unknown Delisting Classifications"); a real report re-checks each one through `sec.py` before citing it.

Source row (abridged): `case_id` BBG000BB2N27_2014-12-25, `exit_kind` merger, `continuation` false,
`last_trade_date` 2014-12-12, `dlret_fill` 0.0 (assumed par), `value_rule` cash_plus_stock, `cash_per_share`
65.50, `cash_currency` blank, `stock_ratio` 0.8025, `price_ticker` QSR, `price_date` 2014-12-15,
`terms_source` llm, `terms_gate` failed, verdict uncertain.

---

## 1. Verdict

A real merger: each THI share became C$65.50 cash plus 0.8025 Restaurant Brands International shares (the
default package). The library's kind, date and payout terms are right; only the currency is missing, and its
fill of assumed par is replaced once qlib_practice prices the package.

## 2. Library vs evidence

| Field | Library says | Evidence says | Status |
| --- | --- | --- | --- |
| exit_kind | merger | merger | agree |
| drop_reason | — | — | agree |
| continuation | false | false (cash plus another company's stock; not one for one) | agree |
| successor | none | none (RBI is the acquirer, not a continuing line) | agree |
| last_trade_date | 2014-12-12 | 2014-12-12 (ceased trading at the close) | agree |
| value_rule | cash_plus_stock | cash_plus_stock | agree |
| terms | 65.50 (no currency) + 0.8025 × QSR on 2014-12-15 | C$65.50 + 0.8025 RBI (QSR) shares; QSR first traded 2014-12-15 | missing (currency) |
| issuer | 1345111 | 1345111 | agree |
| ticker_history | THI 2007-12-26 .. 2014-12-12 | same | agree |

## 3. Corrected classification

```text
exit_kind        = merger
drop_reason      =
continuation     = false
successor        =
last_trade_date  = 2014-12-12
value_rule       = cash_plus_stock
cash_per_share   = 65.50
cash_currency    = CAD
stock_ratio      = 0.8025
price_ticker     = QSR
price_sec_id     =            (not in the run)
price_date       = 2014-12-15
recovery_ratio   =
value_formula    = (65.50 CAD + 0.8025 × price(QSR, 2014-12-15)) / last_close − 1
event_type       = merger
consideration    = cash_and_stock (an election deal; default package, to which elections were prorated)
holder_value     = 65.50 CAD cash + 0.8025 RBI shares
effective_date   = 2014-12-12
successor_ticker = QSR (RBI common, first traded 2014-12-15)
confidence       = verified
```

## 4. Why this confidence

Verified.
- Exit kind: filing (the 8-K of 2014-12-17 reports the arrangement's completion).
- Successor: filing (the 424B3: holders receive cash and RBI shares, no continuing line).
- Last trade date: filing (EX-99.1: THI ceased trading at the 2014-12-12 close).
- Payout rule: filing (the 424B3's default package).
- Terms: filing (424B3: C$65.50 and 0.8025; EX-99.1: QSR first traded 2014-12-15).

## 5. What happened

- The arrangement closed on 2014-12-12; THI became an indirect subsidiary of the new holding company
  ([SEC 8-K 2014-12-17](https://www.sec.gov/Archives/edgar/data/0001345111/000119312514445447/d839026d8k.htm)).
- THI ceased trading at the 2014-12-12 close; QSR began trading 2014-12-15
  ([SEC EX-99.1](https://www.sec.gov/Archives/edgar/data/0001345111/000119312514441344/d837647dex991.htm)).
- Default consideration C$65.50 cash + 0.8025 RBI shares; elections of C$88.50 cash or 3.0879 shares were
  prorated to that package ([SEC 424B3](https://www.sec.gov/Archives/edgar/data/1618755/000119312514398439/d786007d424b3.htm)).
- About 2% elected cash, 72% stock, 26% mixed or none
  ([SEC EX-99.2](https://www.sec.gov/Archives/edgar/data/0001345111/000119312514438325/d835305dex992.htm)).
- The NYSE removed THI because the shares came to represent other securities as of 2014-12-12
  ([SEC Form 25](https://www.sec.gov/Archives/edgar/data/0001345111/000087666114000652/ruleprovisionnotice.htm)).

## 6. Decision-tree bucket

Replaced: the old security was exchanged for cash plus another company's shares — a merger, not a continuation.

## 7. Why the library got it wrong

Only the currency: the library publishes `cash_per_share` 65.50 with `cash_currency` blank, and the cash is
Canadian dollars. Its own price check failed (`terms_gate=failed`), most likely because it compared C$65.50 plus
the stock leg with a USD close; the terms themselves match the filing. Cause tag: `currency_missing`.

## 8. Fix and open checks

- Publish `cash_currency=CAD`; qlib_practice converts it to the close's currency on 2014-12-12 when it prices
  QSR on 2014-12-15.
- No other check: the terms come from the 424B3.
- Golden case: yes — a cash-and-stock election deal with a non-USD cash leg.
</content>
