# Sample delistings by category

Two real examples per CRSP bucket, each with: the actual corporate event,
how `delist_detection` classifies it, and the concrete train and backtest
mechanics. Use this as a sanity check when wiring the package into a new
pipeline — for every bucket below, the suggested method is what the
default `build_train_label_adjustment` / `build_backtest_exit` functions
emit, except where called out.

---

## 1. MERGER (CRSP 231 — acquired by external acquirer)

### Example 1A — `ALTR` (Altair Engineering)

**Reality.** Siemens AG announced acquisition Oct 30, 2024 at $113.00
cash per share (~$10.6 B equity). Deal closed Mar 26, 2025; ALTR ceased
trading on Nasdaq close of business that day. Last close $111.85.
Shareholders received $113.00 cash per share three business days later.

**Classification evidence.** Form 25-NSE filed 2025-03-26 by Nasdaq; 8-K
filed 2025-03-28 with items `2.01 + 3.01 + 5.01` (completion of
acquisition + delisting notice + change of control); Form 15-12G filed
2025-04-07. CRSP code **231**, confidence **high**.

**Train method.**
```
last_close      = 111.85    # from Tiingo
payout          = 113.00    # populate manually or from Form 8-K parser
forward_return  = payout / last_close - 1   = +1.03%
```
Write `+0.0103` into the LABEL column for the last `horizon_days` (e.g.
21) observations of ALTR. **Do not drop the row** — that would silently
bias your model toward unsuccessful M&A targets (which keep trading on
rumors and never get the payout pop).

**Backtest method.**
If you hold ALTR going into 2025-03-26, mark the position at $111.85
(last close) on 2025-03-26, then on 2025-03-27 a cashflow of
`(113.00 − 111.85) × shares = +$1.15 × shares` lands as "deal arb" P&L.
Reinvest the proceeds per portfolio policy (cash bucket, next rebalance).

Practical: `exit_date=2025-03-26, exit_price=113.00`. Don't try to hold
ALTR after delist — there is nothing to hold.

### Example 1B — `ATVI` (Activision Blizzard)

**Reality.** Microsoft acquired Activision Jan 2022 at $95.00 cash per
share. Closed after UK CMA approval Oct 13, 2023 ($68.7 B). Last trading
day Oct 13, 2023 at $94.42.

**Classification evidence.** Form 25-NSE 2023-10-13; 8-K 2023-10-13 items
`2.01 + 3.01 + 5.01`; Form 15-12G filed shortly after. CRSP **231**,
**high** confidence.

**Train method.** `forward_return = 95.00 / 94.42 − 1 = +0.61%`. Inject
for the last horizon of ATVI.

**Backtest method.** Exit at $95.00 on 2023-10-13.

**Important nuance — long deal duration.** Microsoft–ATVI took 21 months
from announcement to close. During that window ATVI traded at a discount
to $95 reflecting deal-break risk. A label that just uses the final
payout misses the deal-arb dynamic. If your model's prediction horizon
is 21 days, only the **terminal** observation needs the payout label —
earlier observations still get realized 21-day returns from the price
panel. The classifier and the qlib adapter handle this correctly:
`inject_terminal_labels(horizon_days=21)` only rewrites the last 21 rows.

---

## 2. EXCHANGE_TRANSFER (CRSP 304 — ticker continues elsewhere)

### Example 2A — `WYN` (Wyndham Worldwide spin-off)

**Reality.** May 31, 2018, Wyndham Worldwide separated into two public
companies:

* Hotel franchising business spun off as **Wyndham Hotels & Resorts
  (WH)** on NYSE
* Remaining vacation-ownership business renamed **Wyndham Destinations
  (WYND)**, later **Travel + Leisure Co. (TNL)**

The old CIK 1361658 *continued filing 10-Qs* as Travel + Leisure.
Shareholders of pre-spin WYN received 1 share of WH per share of WYN
held + retained their WYND shares. The pre-spin price ($117) split into
roughly $66 WYND + $59 WH.

**Classification evidence.** CIK 1361658 has 10-Q filings well after
2018-05-31 + 180d. Triggers the exchange-transfer rule. CRSP **304**,
**medium** confidence.

**Train method.**
```python
adj = build_train_label_adjustment(rec, last_close=117,
                                   successor_map={"WYN": "WH"})
# → keep_in_training=False, notes="Exchange transfer; re-link to WH"
```
Drop WYN's terminal observation **and** stitch the WH price series back
onto WYN (or simply trade the successor going forward). The total
economic return is preserved.

**Backtest method.**
Position in WYN on the eve of 2018-05-31: do **not** mark to cash.
Convert to position(s) in the successor(s) using the spin ratio. For
1:1 + retained:
```
on_exit_date=2018-05-31:
    sell WYN at last_close=117
    buy WH at WH's open price on 2018-06-01 (= 1 share)
    buy WYND at WYND's open price on 2018-06-01 (= 1 share)
```
In a long-only or systematic portfolio, the simpler approach is: stop
trading WYN, start trading WH and WYND from the next bar — the price
action of WH+WYND collectively replaces WYN's continuation.

### Example 2B — `ATH` (Athene Holding)

**Reality.** Apollo Global Management completed an all-stock merger with
Athene Jan 1, 2022. Athene shareholders received 1.149 Apollo (APO)
shares per ATH share. The ATH ticker delisted 2021-12-31. CIK 1527469
(Athene) continued filing 10-Ks/Qs as a subsidiary of the combined
entity.

**Classification.** Continued 10-K/Q filings after delist → CRSP **304**.

**Train method.**
* `successor_map = {"ATH": "APO"}`. Drop ATH terminal label; the
  supervised model trades APO going forward.
* Alternative if you want a clean realized return for ATH's final row:
  `forward_return = 1.149 × APO_open_2022_01_03 / ATH_close_2021_12_31 − 1`.
  This is the "in-kind merger" payout.

**Backtest method.**
2021-12-31: convert 1 share ATH → 1.149 shares APO at APO's next open.
Position size, transaction-cost-adjusted, becomes APO going forward.

---

## 3. COMPLIANCE_FAILURE (CRSP 570 / 580 / 573 — the bad delistings)

### Example 3A — `RSH` (RadioShack Ch.11)

**Reality.** RadioShack filed Chapter 11 on Feb 5, 2015. NYSE suspended
trading Feb 2, 2015 (the last actual trade was ~$0.24). Equity was wiped
out; the entity reorganized as "RS Legacy Corp" and shareholders
received nothing.

**Classification evidence.** 8-K with item `3.01` (delisting notice)
filed alone; Form 25-NSE 2015-03-20; Form 15-12B. CRSP **570**, **high**
confidence. Renamed company has CIK 96289 = "RS Legacy Corp" in EDGAR.

**Train method.**
```python
forward_return = -1.0   # -100%
keep_in_training = True
```
This is *the most important bucket to get right.* If you simply drop RSH
from training because its data ends, your model never learns that
"stock at $0.24, 10-Q delinquencies, going-concern auditor's note" →
catastrophic. Forcing the −100% label preserves the cautionary signal.

**Backtest method.**
Exit RSH on 2015-02-02 at `$0.00`. Not at the last quote ($0.24) — by
the time the 12d2-2 hits, the OTC mark is illusory liquidity and your
real-world execution would have failed. **0.0 is the realistic mark.**

If your strategy held RSH from $20 down to $0.24, your backtest needs
to show the full path including the final `−100%` (or `−99%` if you
choose to honor the $0.24 mark). Otherwise you're hiding tail risk.

### Example 3B — `MDR` (McDermott International Ch.11)

**Reality.** McDermott filed prepackaged Chapter 11 on Jan 21, 2020.
Existing equity holders received nothing; debt holders took over. Stock
delisted from NYSE Jan 22, 2020. Re-emerged as a private company.

**Classification evidence.** Form 25 filed; 8-K item 3.01. CRSP **570**,
**high**. (If NT 10-K had been filed in the prior year, my classifier
would upgrade to 580 — "delinquent in filings".)

**Train method.** `forward_return = −1.0` for the last horizon of MDR.

**Backtest method.** Exit at $0.00 on 2020-01-22. Don't honor any
post-delist OTC pink-sheet trading — for a public-strategy backtest,
you can't realistically transact there.

---

## 4. LIQUIDATION (CRSP 400 / 470)

### Example 4A — `AABA` (Altaba dissolution)

**Reality.** Altaba was the renamed Yahoo holding company after Verizon
bought Yahoo's operating business in 2017. It held the Alibaba stake +
cash. In 2019 the board began voluntary dissolution under Plan of
Liquidation. Shareholders received cash + Alibaba shares (BABA) in
installments. Stock delisted Nasdaq Nov 6, 2019. Total payouts roughly
tracked NAV.

**Classification evidence.** Form 25-NSE 2019-10-07; 8-K with items
`7.01 + 9.01` (regulation FD + exhibits — *no* M&A items because the
dissolution was announced months earlier in separate filings); Form
15-12G 2019-12-15. The Form 25 + Form 15 with no merger 8-K triggers
CRSP **400**, **medium**.

**Train method.**
```python
# Default recovery_ratio = 0.10 is too pessimistic here — Altaba paid
# out >95% of NAV.
# Override with the actual payout ratio if you have it.
forward_return = (payout_total / last_close) - 1   # close to 0 for AABA
# Or use the default: -0.90 (conservative)
```
For AABA specifically, the realized total return through the wind-down
was near 0% (or slightly positive). A blind −90% label is wrong.
**Recommendation:** populate `payouts={"AABA": <actual_per_share_distribution>}`
when you call `inject_terminal_labels`. The default −90% is for
*generic* liquidations where you don't have payout data.

**Backtest method.**
Exit at `recovery_ratio × last_close`. With `recovery_ratio = 0.10` you
mark to 10% of last close — way too low for AABA. Better: model the
staged distributions. Altaba paid out roughly: $51.50 cash + 0.24 BABA
shares per AABA share. If you have BABA prices, you can compute the
realized exit value exactly.

### Example 4B — `CIE` (Cobalt International Energy Ch.11)

**Reality.** Cobalt filed Chapter 11 on Dec 14, 2017 after deep-water
assets became uneconomic. The plan sold most assets; equity got token
recovery. Delisted from NYSE; small distribution to shareholders.

**Classification evidence.** 8-K item 1.03 (Bankruptcy) → CRSP **470**.

**Train method.** Same default `−90%` is appropriate here. Recovery to
equity in a Ch.7-style asset sale is typically 0–15%. If your data
source has the actual recovery, override.

**Backtest method.** Exit at `0.10 × last_close` (or actual recovery if
known). Cobalt's actual equity recovery was ~$0, so 0.0 would have been
more accurate — but in the general 470 case, 10% is a reasonable
default before you have specifics.

---

## 5. EXPIRATION (CRSP 600 — scheduled end)

### Example 5A — `GSF` (Goldman Sachs 6.125% Notes due 2060)

**Reality.** GSF was a **publicly-traded retail-targeted note** —
small-denomination bond exchange listing, not equity. Goldman Sachs
issued these notes in 2010 with a 2060 maturity. They got delisted in
2015 for liquidity reasons (Goldman called them or restructured the
listing). Holders received par + accrued interest, then the issuer's
bond-trustee channel.

**Classification evidence.** AV `assetType="Stock"` but AV company name
contains `"Notes Due 2060"` — the name-hint detector catches it. CRSP
**600**, **high** confidence (no CIK needed).

**Train method.**
```python
keep_in_training = False    # not equity universe; drop from supervision
```
Equity factor models should not learn from notes. Including them would
let bond-yield dynamics contaminate equity-return labels.

**Backtest method.**
Exit at `0.0` is wrong (it implies total loss) — but for an equity
backtest this row should never have been a holdable position. **The
right action is to filter notes out of your tradable universe upstream.**
The `expiration` bucket is essentially a flag saying *"this row is not
equity; remove it from the universe."*

### Example 5B — `TMUSR` (T-Mobile Tradeable Rights, June 2020)

**Reality.** When Sprint shareholders voted to merge into T-Mobile
(April 2020), Sprint holders received contingent merger consideration
including tradeable rights. TMUSR was the tradeable rights instrument,
listed on Nasdaq with a defined June 2020 expiration. After exercise
period, rights expired worthless (or were exercised into TMUS shares).

**Classification evidence.** AV name contains `"Tradeable Rights"` →
name-hint detector → CRSP **600**.

**Train method.** Drop from training. Rights have totally different
return dynamics from underlying equity (binary payoff at expiration,
theta decay, etc.).

**Backtest method.** Filter from universe upstream. If you do hold a
position, exit at `0.0` (worthless expiration) is *sometimes* correct
but not generally — depends on whether the underlying exercise
condition triggered.

---

## Summary cheat sheet

| Bucket | Train label | Backtest exit | When the default is wrong |
|---|---|---|---|
| `merger` | `payout / last − 1` | `payout` | If you don't have `payout`, code uses `last_close` (neutral). Worth populating. |
| `exchange_transfer` | drop, relink successor | hold successor | Spin-offs (WYN → WH + TNL) need successor split logic, not 1:1 relink. |
| `compliance_failure` | **−1.0** | **0.0** | The defaults are intentionally pessimistic. Only override if there was a *genuine* OTC recovery — rare. |
| `liquidation` | `recovery − 1` (default −0.9) | `recovery × close` | Voluntary liquidations (AABA) often recover ≫ 10%. Populate `payouts` per ticker. |
| `expiration` | drop | 0.0 / filter upstream | The row shouldn't have been in your equity universe in the first place. |

**Code paths to populate.**

* `payouts: dict[ticker, float]` — per-share cash payout (M&A and
  voluntary liquidation). Best populated from 10-K / 8-K parsing or a
  corporate-actions feed.
* `successor_map: dict[ticker, ticker]` — for spin-offs and ticker
  renames. Today driven by a small manual dict in
  `scripts/classify_universe.py`; consider externalizing.
* `recovery_ratio: float` — default 0.10 for liquidations. Tune by era
  or sector if you have realized-recovery data.
