# Truth rules: one report into one truth row

You turn one diagnosis report into the row the contract should publish for that security (spec
`docs/superpowers/specs/2026-10-03-diagnosis-truth-fixes-design.md`, sections 1.1 and 2). The report is the evidence;
you do not re-diagnose. Read the whole report, including section 9 (the skeptic): a field the skeptic refuted takes
the skeptic's correction, never the report's section 3.

## Output

One JSON file, `data/diagnosis/truth_rows/<case_id>.json`:

```json
{"case_id": "...", "sec_id": "...", "shape": "ending | no_ending | ending_moved",
 "fields": {"exit_kind": "", "drop_reason": "", "continuation": "", "successor_sec_id": "", "last_trade_date": "",
            "value_rule": "", "cash_per_share": "", "cash_currency": "", "stock_ratio": "", "price_sec_id": "",
            "price_ticker": "", "price_date": "", "recovery_ratio": ""},
 "internal_last_trade_date": "",
 "legs": [],
 "identity_check": null,
 "residual": "",
 "pending": [],
 "notes": "one line: what the row rests on"}
```

Every field is a string. `""` means the contract must publish a blank; `"*"` means the report leaves it open (not
scored). Use `*` sparingly: a field the report settles gets its value.

## Shape

- `ending`: the security ended here (or later, at an ending the report fully states): one contract row.
- `no_ending`: the security did not end: a rename or ticker change of the same security, a reverse split that kept
  the line (ruling R2 below), a same-FIGI successor (CCO, GTES), a line still trading.
- `ending_moved`: this ending is not real, but the line ended later (JNY's 2014 merger after a 2010 rename). Fill the
  fields only where the report states the later ending; else `*`.

## Fields, as the contract publishes them

- `exit_kind`: merger | exchange | liquidation | dropped | lost_source | expiration; blank for unknown.
- `drop_reason`: on a `dropped` row only: moved_otc | price | capital | went_private | bankruptcy | filings_fees |
  guidelines | sec_order; else blank.
- `continuation`: "true" or "false". When true: `successor_sec_id` is the successor line's sec_id in the run (look
  it up in `output/securities.csv` / `output/contract/security_history.csv`; `*` when the run does not hold it yet),
  `value_rule` is `continuation`, and every value field is blank.
- `last_trade_date`: published only when the corrected date rests on an exchange print or a filing's statement about
  trading: MIDAS, a Nasdaq halt, the Form 25 EX-99.25 notice, an 8-K / 8-K12B / 6-K or filed press release that says
  when trading stopped or was suspended ("suspended before the open on D" is the trading day before D; "after the
  close on D" is D), and no later than the Form 25 effective date. A date worked out from a merger effective date or
  closing date alone, from fails rows, from a last sighting or from the web is NOT published: write `""` here and put
  the date in `internal_last_trade_date`. No last trade at all (a continuing line): `""` and no internal date.
- `value_rule`: cash | stock | cash_plus_stock | otc_print | recovery | worthless | transfer | continuation |
  expiration | unknown | basket. Then:
  - cash: `cash_per_share`, `cash_currency` (USD when the filing says "$"; CAD for "C$"; blank if not stated).
  - stock: `stock_ratio`, `price_sec_id` (the acquirer's line in the run, or `*`), `price_ticker` (the acquirer's
    symbol on the price date, as a filing states it), `price_date`.
  - cash_plus_stock: both sets.
  - otc_print (decision 11): `price_sec_id` = the security's own sec_id, `price_ticker` = its own OTC symbol if the
    report knows it, else `*`; `price_date`.
  - recovery: `recovery_ratio`. worthless, transfer, expiration, unknown, continuation: every value field blank.
  - basket (ruling R3: two lines per share, a spin-off leg, a one-to-many reclassification): the cash leg, if any, in
    `cash_per_share`/`cash_currency`; each stock leg in `legs` as {"leg": 1, "ratio", "price_sec_id",
    "price_ticker", "price_date"}; `stock_ratio`, `price_*` blank on the main row.
- `price_date`: the trading day after the published `last_trade_date`; blank when `last_trade_date` is blank.
- Numbers as plain decimals ("1.05", "65.50"); dates YYYY-MM-DD.

## Rulings (spec section 2)

- R1: continuation only when the old holders get exactly one new share per old share and no cash in the exchange,
  even when other holders join (BHI) or the class or issuer changes; any other ratio or cash in the exchange is a
  stock or cash_plus_stock merger.
- R2: a CUSIP or ticker change of one issuer and class (reverse split, rename): write the shape as if it is one
  security (`no_ending` or `ending_moved`) and fill `identity_check` with {"old_cusip", "new_cusip"} from the report;
  the build script checks the FIGI and turns it into a continuation when the new CUSIP has its own composite.
- R4: an election deal publishes the final prorated package a filing states, else the default package; never the sum
  of the elections; a CVR goes in `notes`.
- R5: a non-USD cash leg keeps its currency, unconverted.
- R6: a bankruptcy plan exchanging old equity for new shares is `stock` on the new line when the old line did not
  trade OTC first; `otc_print` when it did.
- R7: EXE (one FIGI over pre- and post-bankruptcy stock): set `residual` to the reason.
- BHI rule: a dividend the successor pays after the exchange is not consideration; cash the deal documents make part
  of the consideration is.

## When you cannot settle a field

Add {"field": "<name>", "question": "<what would settle it>"} to `pending` and write `*` in that field. Set
`residual` (a short reason) when the library cannot reach the right value with any general rule (data it does not
have, such as an OTC ADS with no price source). Never guess.
