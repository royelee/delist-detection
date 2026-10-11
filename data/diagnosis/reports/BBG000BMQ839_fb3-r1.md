# BBG000BMQ839_fb3-r1 (NFS, Nationwide Financial Services Class A) - regression

## 1. Verdict
NFS Class A common was bought out for $52.25 cash by Nationwide Mutual (merger completed 2009-01-01, trading suspended at the close of 2008-12-31). The new run's row (exchange transfer 304, last trade unpublished, internal date 2009-06-08 from "continued 10-K/Q filings", no Form 25) is wrong: the ending is a cash merger with a Form 25-NSE filed 2009-01-02. The old run's lack of any delisting row was also wrong; the new run is right only that a row exists and that the issuer CIK 1029786 is filled in.

## 2. Library vs evidence
| field | library says (new) / old | evidence says | status |
| --- | --- | --- | --- |
| delistings.added | new: row exit_kind=exchange, continuation=false, no successor, no last trade, value_rule=transfer; old: no row | a real ending exists (merger) | row right, content wrong |
| exit_kind | exchange | merger | wrong |
| drop_reason / continuation / successor | blank / false / none | blank / false / none (shares cancelled for cash) | agree |
| last_trade_date | blank (internal 2009-06-08, unconfirmed) | 2008-12-31 (8-K 3.01: "suspended at the close of the market on December 31, 2008") | wrong |
| value_rule | transfer | cash | wrong |
| terms | none | cash 52.25 USD per share, no stock leg, price_date 2009-01-02 | missing |
| issuer | new 1029786; old blank | 1029786 (Nationwide Financial Services Inc, file 1-12785) | new agrees |
| security_history.ranges | new NFS:2008-01-16..2009-06-08:1029786; old same with blank issuer | issuer 1029786 right; range should end 2008-12-31 (fails rows end 2009-01-05, a settling tail, 60 rows) | issuer: new right; end date wrong in both |

## 3. Corrected classification
```
exit_kind: merger
drop_reason:
continuation: false
successor: none
last_trade_date: 2008-12-31
value_rule: cash
cash_per_share: 52.25
cash_currency: USD
stock_ratio:
price_ticker:
price_sec_id:
price_date: 2009-01-02
recovery_ratio:
value_formula: 52.25 / last_close - 1
event_type: going_private (acquisition by the majority holder Nationwide Mutual)
consideration: cash
holder_value: 52.25 USD cash per Class A share
effective_date: 2009-01-01
successor_ticker:
confidence: verified
```

## 4. Why this confidence
verified.
- exit kind: filing, 8-K 0001193125-09-000069 (Item 3.01, merger completed 2009-01-01, shares converted to cash) and Form 25-NSE 0000876661-09-000006.
- successor: filing, same 8-K (shares cancelled for cash, no successor security).
- last trade date: filing, same 8-K (trading suspended at the close on 2008-12-31).
- payout rule: filing, same 8-K (cash).
- terms: filing, same 8-K ($52.25 without interest); the proxy is DEFM14A 0001193125-08-245144.

## 5. What happened
- 2008-08-06 merger agreement, $52.25 cash per Class A share not already owned ([SEC 8-K 2009-01-02](https://www.sec.gov/Archives/edgar/data/1029786/000119312509000069/d8k.htm)).
- 2008-12-31 shareholders approve; trading suspended at the close that day; 2009-01-01 merger completed (same 8-K).
- 2009-01-02 NYSE files Form 25-NSE for Class A Common Stock under 12d2-2(b) ([SEC 25-NSE](https://www.sec.gov/Archives/edgar/data/1029786/000087666109000006/xslF25X02/primary_doc.xml)).
- 2009-01-30 six Form 15-15D filings ([SEC 15-15D](https://www.sec.gov/Archives/edgar/data/1029786/000119312509015290/d1515d.htm)).
- 2009-02-18 the Form 25 in the filing list is for Nationwide Financial Services Capital Trust's 7.899% capital securities, not the common ([SEC 25](https://www.sec.gov/Archives/edgar/data/1029786/000119312509032134/d25.htm)). The registrant kept filing a 10-K on 2009-03-02 because of public debt, which is what the continued-filings fallback saw.
- Fails rows of CUSIP 638612101 end 2009-01-05 at about $52.21 (settling tail).

## 6. Decision-tree bucket
Replaced by cash of another company: merger.

## 7. Why the library got it wrong
The finder did not match the 2009-01-02 25-NSE to the security (flags `no_form25`, `delist_date_approx`), so the continued-filings fallback ("Continued 10-K/Q filings >180d after delist") anchored on the last seed sighting 2009-06-08, five months after the deal (stale snapshot seeds). Cause: other:form25_not_matched (the 25-NSE exists and was not matched).

## 8. Fix and open checks
Match the 25-NSE (filed under CIK 1029786); the 8-K 3.01 and the notice then make a merger 231 with cash 52.25 USD and last trade 2008-12-31 (published; it precedes the effective date 2009-01-12). Why the finder skipped the Form 25 is not diagnosed here. Golden-worthy: yes, well sourced.
