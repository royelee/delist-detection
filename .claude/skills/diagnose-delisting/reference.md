# Reference for diagnose-delisting

## The contract's fields (what the report's corrected classification uses)

| Field | Values | Meaning |
| --- | --- | --- |
| `exit_kind` | `merger`, `exchange`, `liquidation`, `dropped`, `lost_source`, `expiration`, blank | How the listing ended. `exchange` is an exchange transfer or a continuation; blank means the library asserts none (its `unknown` bucket). |
| `drop_reason` | `bankruptcy`, `moved_otc`, `price`, `capital`, `went_private`, `filings_fees`, `guidelines`, `sec_order` | Only on `dropped`. From the CRSP code: 470/574 bankruptcy, 520 moved_otc, 550/552 price, 560 capital, 570/584 guidelines (a listing deficiency), 573/585 sec_order, 580 filings_fees. |
| `continuation` | true / false | The same holders own the same claim in a successor line (decision 9). Then `successor_sec_id` names it and there is no value. |
| `successor_sec_id` | a sec_id | The continuing security (continuation only). |
| `ticker_successor_sec_id` | a sec_id | Another security that took over the ticker (a takeover, not a continuation). |
| `last_trade_date` | date | Published only from an exchange print (MIDAS, the Form 25's EX-99.25 notice, 8-K item 3.01, a Nasdaq halt) and never after the Form 25 effective date (filing + 10 days) — decision 12. Internally the library may hold a guessed date. |
| `dlret` | number | A measured delisting return: cash, stock, cash+stock, a recovery ratio, an OTC print, worthless (−1). |
| `dlret_fill` | number | A fill, not a measurement: assumed par (0.0), a Shumway mark (−0.30 NYSE/AMEX, −0.55 Nasdaq), an exchange transfer's 0.0. |
| `terminal_value` | number | What one share turned into, per share, in the last close's currency. |

## The payout rule (contract schema 2; what the report's payout uses)

The library publishes what one share turned into; qlib_practice prices it and computes
`dlret = payout per share / last trading close − 1`. A diagnosis states the rule and its terms and never a
market price.

| `value_rule` | Payout per share | Terms to give |
| --- | --- | --- |
| `cash` | the cash | `cash_per_share`, `cash_currency` |
| `stock` | `stock_ratio` × the price of `price_ticker` on `price_date` | `stock_ratio`, `price_ticker` (`price_sec_id` if in the run), `price_date` |
| `cash_plus_stock` | cash + `stock_ratio` × that price | all of the above |
| `otc_print` | the first off-exchange print within 10 trading days (decision 11) | `price_ticker` = the security's own OTC symbol if known, `price_date` = the session after the last exchange trade |
| `recovery` | `recovery_ratio` × the last close (liquidation payments) | `recovery_ratio`, or the payments with dates in the report |
| `worthless` | 0 | — |
| `transfer` | the same shares (an exchange move; 0 return) | — |
| `continuation` | not an exit | the successor |
| `expiration` | none (a right or warrant expired) | — |
| `unknown` | not known from the filings | say what is missing |

`price_date` is the trading day after the last trade (the acquirer's first price after the deal closes; the
first OTC session). For an election deal (cash or stock at the holder's choice, prorated), give the default or
aggregate package the agreement fixes and say so. `terms_gate=failed` on the library's row means its own check
against its fails-based close failed: the published terms may be misread (RAI shows 1 BTI per share where the
filing says 0.5260 BAT ADS) — check each term against the filing. `cash_currency` is blank in the library today;
give the currency the filing states. `value_formula` is one line, e.g.
`(65.50 CAD + 0.8025 × price(QSR, 2014-12-15)) / last_close − 1`.

Internal columns (`output/delistings.csv`): `bucket` (merger, exchange_transfer, liquidation, compliance_failure,
expiration, unknown) maps to `exit_kind` as merger→merger, exchange_transfer→exchange, compliance_failure→dropped,
liquidation→dropped (if bankruptcy) or liquidation, expiration→expiration, unknown→blank. `dlret_method` names how
the value was made (`cash_only`, `stock_only`, `cash_plus_stock`, `recovery_ratio`, `otc_print`, `worthless` are
measured; `assumed_par`, `shumway_*`, `exchange_transfer_zero` are fills; `needs_last_trade`,
`abstain_no_consideration`, `unknown` leave it blank).

## The spec's decisions that define the right answer

- **Continuation (decision 9, CRSP's rule).** Same holders, same claim, one for one, no cash, no bankruptcy. An
  unchanged CUSIP always continues. A 1:1 holding-company reorganization (Alphabet 2015, ANAT 2020, Xerox 2019)
  is a continuation with a successor link. Post-bankruptcy equity is a new security. A link resting on timing
  alone is uncertain.
  **"No cash" means no cash in the exchange** (operator ruling, 2026-10-03, case BHI 2017). Ask what the holder
  received *for surrendering the old share*. Cash paid as part of that exchange makes it a merger (a terminal
  event). A dividend the successor pays to holders of the *new* security after the exchange does not, even a
  special dividend and even a large one (BHGE's $17.50, about 30% of the price): the case stays a continuation,
  and the report records the dividend as a distribution on the successor. The size of the cash is not the test;
  its role in the transaction is. Exception: when the transaction documents make the payment part of the
  consideration for the old shares, it is merger consideration whatever it is called.
- **Rename / ticker change.** Not an ending: the same security (same CUSIP) keeps trading under a new ticker.
  The ticker history should continue under the new ticker.
- **A move to OTC is an ending with a value (decision 11).** CRSP 520 (or the drop's own reason, e.g. a
  bankruptcy 574): the value is the first off-exchange print within 10 trading days of the last exchange trade.
- **Assumed par (decision 4).** A fill of 0.0 is acceptable for a merger only when the payout gate passed; after a
  failed gate it is uncertain.
- **Distress values (decision 3).** A solvent liquidation is valued from its payments; harsh Shumway marks stay
  only where no value is known. Equity cancelled for nothing is worthless (−1.0).
- **Last trade date (decision 12).** See the field table. "Suspended before the open on D" means the last trade
  was the trading day before D.

## Decision table: what happened to the holder's shares

| Kept the same security? | Evidence | event_type | exit_kind / drop_reason | continuation |
| --- | --- | --- | --- | --- |
| Kept: same CUSIP, new ticker | 8-K 5.03 or a name change; fails rows: same CUSIP under the new symbol | name_change / ticker_change | not an ending (no row) | — |
| Kept: same CUSIP, other exchange | Form 25 + listing on another exchange (8-A12B), same CUSIP | exchange_transfer | not an ending, or `exchange` with successor = itself | — |
| Replaced 1:1 by a new line of the same holders | successor's 8-K12B / 8-K12G3, scheme or holdco merger at one for one; a dividend the successor pays afterward does not change this (BHI → BHGE) | reorganization | `exchange` | true, successor named |
| Replaced by cash / stock of another company | 8-K 2.01 (+ 5.01, 3.01), DEFM14A / 424B3 terms, Form 25 | merger / acquisition / going_private | `merger` | false |
| Lost: bankruptcy, then OTC | 8-K 1.03, 3.01 suspension, fails rows under a Q / OTC symbol | bankruptcy | `dropped` / `bankruptcy` (CRSP 574/470), value = first OTC print | false |
| Lost: delisted for a deficiency, then OTC | 8-K 3.01 deficiency notice, Form 25 by the exchange, OTC trading | exchange_delisting | `dropped` / `guidelines` / `price` / `filings_fees` | false |
| Lost: wound down | plan of dissolution, liquidating distributions | liquidation | `liquidation` (solvent) or `dropped` / `bankruptcy` | false |
| Expired | a right, warrant or unit that expired | expiration | `expiration` | false |

The plan's extra fields: `consideration` (cash, stock, cash_and_stock, cash_or_stock_election, none, other),
`holder_value` (per-share package in the original currency, e.g. "65.50 CAD cash + 0.8025 RBI shares"; for an
election deal the default or aggregate package the agreement fixes), `cash_per_share`, `exchange_ratio`,
`effective_date` (close date per the filing), `successor_ticker`.

## Why the library is unsure: its reason codes (`uncertain_reasons`)

| Code | Meaning |
| --- | --- |
| `continued_filings_rule` | No Form 25 found; the ending is the fallback "the issuer kept filing 10-K/10-Qs over 180 days after", labelled an exchange transfer (304). Often a guess. |
| `resolved_from_continued_filings` | The end-of-era resolver relabelled a continued-filings ending from 8-K evidence (5.01, 2.01, 3.01, 8-K12B); kept uncertain until checked. |
| `issuer_from_todays_ticker_map` | The issuer CIK came from today's `company_tickers.json`, weak for the past. |
| `no_last_trade_date` / `last_trade_date_unconfirmed` / `last_trade_not_exchange_print:<source>` | The date is missing, guessed, or not from an exchange print. |
| `last_trade_date_text_conflict` / `last_trade_after_form25_effective` | The date sources disagree, or the date falls after the Form 25 took effect. |
| `assumed_par_after_failed_gate` | The merger's value is assumed par after the payout, LLM or terms check failed. |
| `continuation_by_timing_only` | A continuation linked by timing, with no filing or CUSIP switch. |
| `no_evidence_default` / `unknown_exit_kind` | No rule could classify the ending. |
| `earlier_ending:<date>` | This is not the security's last ending. |
| `security_uncertain` | The security's identity itself is uncertain (see `security_uncertain_reasons`: `ticker_overlap`, `seeds_outside_history`, `placeholder_without_ticker_filing`). |

## Cause tags (the summary's `cause`; pick the one that, fixed, would make the library right)

| Tag | When |
| --- | --- |
| `resolver_no_bankruptcy_branch` | A bankruptcy drop read as an exchange transfer or still trading (CBL 2020). |
| `rename_not_followed` | A rename or ticker change on the same CUSIP read as an ending (CLI → VRE 2021). |
| `successor_not_in_run` | A real continuation whose successor line the run never added (an 8-K12B successor, BHI → BHGE). |
| `holdco_not_linked` | A 1:1 holdco reorganization left as a merger or a dangling transfer. |
| `late_form25` | The Form 25 came long after the suspension, so the finder fell back to a guess. |
| `continued_filings_guess` | The continued-filings fallback invented an ending; the real event is something else or later. |
| `wrong_exit_kind` | The ending is real but the kind is wrong (a merger called distress, an LBO called a transfer, …). |
| `no_last_trade_print` | The kind is right; only the exchange-print date is missing. |
| `terms_not_extracted` | The payout terms exist in filings but the library publishes none (`value_rule` unknown, or a missing leg). |
| `terms_misread` | The library publishes the wrong rule or a wrong term (ratio, cash, acquirer, price date). |
| `currency_missing` | Rule and terms right, but the cash is not in USD and the library gives no currency. |
| `identity_wrong` | Wrong FIGI, wrong issuer or wrong share class for the security. |
| `issuer_history_bug` | `security_history`'s issuer per interval is wrong (APA: CIK 1841666 in 2012). |
| `library_right_but_uncertain` | The library's row is right; only its evidence is weak. |
| `truth_or_judge_issue` | The library is right but a truth file or the scorecard's judge reads it wrong. |
| `other:<short note>` | None of the above. |
</content>
