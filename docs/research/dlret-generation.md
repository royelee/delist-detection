# How CRSP's `DLRET` Is Generated — and How to Reconstruct It

*Research report · 2026-05-31 · for review*

> **Scope.** How CRSP computes and populates the delisting return (`DLRET`),
> backtraced across every delisting situation; the missing-value problem; the
> Shumway / Shumway-Warther / Beaver-McNichols-Price corrections; and what a
> non-CRSP (EDGAR-derived) reconstruction must replicate. The last section ties
> the findings back to this repo's `bmp_correction.py` and `crsp_codes.py` and
> flags two concrete discrepancies worth fixing.
>
> Findings were produced by a fan-out web-research pass (5 angles → 15 sources →
> 64 candidate claims → 25 adversarially verified, 21 confirmed). Load-bearing
> claims rest on **primary** sources — Shumway (1997, *J. Finance*), Shumway &
> Warther (1999, *J. Finance*), Beaver-McNichols-Price (2007, *JAE*), and the
> official CRSP / WRDS documentation — each verbatim-verified with unanimous
> votes. Citations are inline; full source list at the end.

---

## TL;DR

1. **Mechanism.** `DLRET` compares a security's *terminal value after delisting*
   against its **last on-exchange trading price**. The terminal value is one of
   three things: an off-exchange (OTC) trade price, an off-exchange bid/ask quote
   (if found within 10 trading periods), or the **sum of a series of distribution
   payments**. If there is no chance to trade before the stock is declared
   worthless, the terminal value is 0 → `DLRET = −1` (−100%).

2. **The bias is an asymmetric-missingness problem, not a computation problem.**
   For mergers, exchange moves, and up-migrations, `DLRET` is almost always
   present (≤1% missing). For **performance-related (distress) delistings it is
   ~99.8% missing** in CRSP's Nasdaq data. Dropping those rows silently deletes
   the worst outcomes → survivorship/delisting bias.

3. **The corrections are magnitude- and venue-specific — do not mix them:**
   - **−30%** — Shumway (1997), missing **NYSE/AMEX** performance delistings.
   - **−55%** — Shumway & Warther (1999), missing **Nasdaq** performance delistings.
   - **−100% (`−1`)** — the *upper bound* of the bias, or the genuinely worthless case.
   - **BMP (2007)** — replace each missing `DLRET` with the **average of *similar*
     delistings**, *not* a single constant (this is the whole point of BMP).

4. **Apply corrections only to performance-related codes.** Never to mergers
   (200–240), exchange moves (300–390), or **up-migrations 501/502** — those are
   neutral-to-positive and already populated.

5. **Sentinels, not NaN.** Missing `DLRET` is encoded as `−55.0 / −66.0 / −88.0 /
   −99.0` in raw CRSP, and `−88.0` is *also* the WRDS reporting-tool default for
   missing. These must be **detected and replaced**, never treated as realized
   returns (a literal `−66.0` = −6600% will nuke a portfolio).

---

## 1. How CRSP generates `DLRET`

CRSP does **not** read a "merger payout" off a filing. It computes a return from
two prices/values:

```
DLRET = (value_after_delisting / last_trading_price) − 1
```

where `last_trading_price` is the close on the security's **last day of regular
on-exchange trading**, and `value_after_delisting` ("Amount After Delisting") is,
per the *CRSP US Stock & Indexes Database Data Descriptions Guide* (Ch. 5, CRSP
Calculations), one of:

| Terminal-value source | When CRSP uses it |
|---|---|
| **Off-exchange price** | A real OTC/Pink-Sheets trade after the security left the exchange. |
| **Off-exchange price quote** | A bid/ask quote, *if* found within **10 trading periods** of the last on-exchange price. |
| **Sum of a series of distribution payments** | Liquidations / dissolutions paid out as one or more cash distributions to shareholders. |

> Verbatim (CRSP Data Descriptions Guide): *"It is calculated by comparing a value
> after delisting against the price on the security's last trading date. The value
> after delisting can include a price on another exchange or the total value of
> distributions to shareholders. If there is no opportunity to trade a stock after
> delisting before it is declared worthless, the value after delisting is zero."*
> Validity rule: *"Valid delisting payment information is either a valid price with
> at least a bid and ask quote within ten trading periods, or a complete set of
> payments received for the shares."*

Shumway (1997) independently states the same mechanism. **For a reconstruction,
this is the contract you must imitate: a terminal value over the last trade
price — not a payout in isolation.** *(Verified 3-0, primary.)*

### Why `RET` alone is wrong (the compounding identity)

The normal `RET` series stops at the last trading day, so the gain/loss between
the last trade and the final cash-out is lost. CRSP's prescribed combination is
**multiplicative**, because returns compound:

```
total_return = (1 + RET) · (1 + DLRET) − 1
```

Example: `RET = +10%`, `DLRET = +20%` → `(1.10)(1.20) − 1 = 32%`, **not** 30%.
This is exactly the firm-month identity implemented in `bmp_correction.py`
(`R_month = (1+R_partial)(1+DLRET)−1`).

---

## 2. The missing-value problem (the actual source of bias)

The delisting bias is **not** that CRSP computes `DLRET` wrong — it's that
`DLRET` is *systematically missing for the bad outcomes*. Missingness is
violently asymmetric across categories:

| Category | Codes | Missing `DLRET` rate | Biased? |
|---|---|---|---|
| Merger | 200–240 | **≤ 1%** | No |
| Exchange move | 300–390 | **≤ 1%** | No |
| Migration up to NYSE/AMEX | 501, 502 | **≤ 1%** | No |
| **Performance / distress** | 500, 505–588 | **99.8%** | **Yes — the whole problem** |
| Liquidation | 400 | ~71% | No* |

\* Liquidations are ~71% missing **but not expected to be biased**, because CRSP
flags them as *announced before delisting* — the value was knowable/priced at the
delist, so a missing realized return there is benign, not a hidden wipeout.

> Verbatim (Shumway & Warther 1999): *"No more than one percent of returns are
> missing for merger, exchange, or movement to the NYSE or AMEX. However, virtually
> all (99.8 percent) returns are missing for performance-related delistings… The
> much smaller category of liquidations is a special case, for although 71.0 percent
> are missing returns, CRSP gives them a code indicating the liquidation was
> announced before the delisting."*
>
> **Scope:** the 99.8% / ≤1% / 71% figures are specifically **CRSP NASDAQ,
> 1972–1995**. Modern CRSP files incorporate more off-exchange/distribution
> terminal values, so the present-day gap may be smaller (see [Open Questions](#open-questions)).
> *(Verified 3-0, primary.)*

### Sentinel flags — detect, don't trust

Raw CRSP encodes "no value" as **negative sentinel numbers**, not NaN. Treating
them as returns is catastrophic.

| Flag | Raw-CRSP meaning |
|---|---|
| `−55.0` | No source to establish a post-delist value, *or* cannot value a known distribution. |
| `−66.0` | More than 10 trading periods between last price and first new-exchange price. |
| `−88.0` | **Security is still active.** |
| `−99.0` | Trades on a new exchange post-delist, but CRSP has no price source yet. |
| `−1.0` | Genuine: stock declared/found worthless → −100% loss. |

> **Layer collision (gotcha):** in **raw CRSP data** `−88.0` means *"security still
> active"*, but the **WRDS reporting-tool `DLRET DEFAULT` option emits `−88.0` as
> the sentinel for a *missing* delisting return.** Same number, opposite meaning,
> depending on which layer you pulled from. *(Verified 3-0, primary: CRSP Guide +
> WRDS Programming Access guide.)*

A reconstruction must (a) recognize these as missing, (b) **not** map them to
`0.0` blindly, and (c) decide a replacement by bucket (§4–5).

---

## 3. `DLSTCD` → category ranges (use the ranges, not first-digit folklore)

The correction logic keys off **code ranges**, verified verbatim against Shumway
(1997) Table I and Shumway & Warther (1999):

| Category | Code range | Treatment |
|---|---|---|
| Merger | **200–240** | Populated; positive/neutral. Cash vs stock vs mixed distinguished by sub-code (§6). |
| Exchange | **300–390** | Populated; neutral (security continues). |
| Liquidation | **400** | Often missing but pre-priced; use realized distributions. |
| "Another Exchange" / migration | **501/502** (up to NYSE/AMEX only; 503–519 are performance-related per Shumway & Warther 1999) | **Positive — EXCLUDE from negative correction.** |
| **Performance (negative)** | **500, 520–584** (1997) / **500, 505–588** (1999) | The corrected-substitute bucket (−30% / −55%). Includes **574 = bankruptcy**, **584 = fails exchange financial guidelines**. |

> Verbatim (Shumway & Warther 1999): *"We classify delisting codes 500 and 505 to
> 588 as performance-related (i.e., a negative change for the firm). We do not
> classify delisting codes 501 and 502 (migration to the NYSE or AMEX) as
> performance-related because these events are usually positive changes for a
> firm."*

Two caveats:
- The performance boundary differs slightly between papers (**520–584** in 1997 vs
  **505–588** in 1999) — both are the author's era-specific CRSP groupings, not one
  canonical range.
- ⚠️ **The "first digit = category" taxonomy (2=merger, 3=exchange, 4=liquidation,
  5=exchange-delisted, 7=SEC, 8=multi-exchange) was REFUTED (1-2)** as not
  authoritatively sourced. It's a useful *mnemonic* (and this repo's range
  fallthrough leans on it), but the **defensible mapping is the explicit ranges
  above**, with **501/502 carved out of the 5xx negative bucket**. *(Verified 3-0,
  primary.)*

---

## 4. Backtrace: every delisting situation

What CRSP populates, and what to do if it's missing:

| Situation | DLSTCD | What CRSP populates | If missing → reconstruction |
|---|---|---|---|
| **Cash merger** | 233 | `(cash_per_share / last_price) − 1`; usually present | Extract cash payout from filing; compute vs last price |
| **Stock merger** | 231/232 | Consideration valued via acquirer shares; usually present | Value acquirer shares at close × ratio (or abstain) |
| **Mixed cash+stock** | 241/251/261 | Full consideration if computable | **Abstain → neutral mark** (no clean cash floor) |
| **Going private** | 200s/573 | Cash terminal value; usually present | Use buyout cash; compute vs last price |
| **Liquidation** | 400 | Sum of distribution payments (pre-priced) | Use realized recovery if observed; it's *not* a performance shock |
| **Bankruptcy** | 574 | Usually **missing** (distress) | Performance correction: −30%/−55%, or −1 if worthless |
| **Compliance / failure** | 500, 520–588, 584 | ~99.8% **missing** | Performance correction: −30% (NYSE/AMEX) / −55% (Nasdaq) |
| **Exchange transfer** | 300–390 | Continues at new venue; ≈0 shock | `DLRET ≈ 0`; re-link the successor, don't drop |
| **Migration up** | 501/502 | Populated; positive | **Do not** apply a negative constant; treat as exchange transfer |
| **Worthless** | any perf + worthless | `−1.0` (−100%) | `−1.0` |
| **Insufficient info** | (sentinel) | `−55/−66/−88/−99` | Detect sentinel → bucket-appropriate replacement |

---

## 5. The corrections, precisely

### Shumway (1997) — NYSE/AMEX: **−30%**, upper bound **−100%**

Shumway reconstructed OTC post-delisting outcomes and found the average missing
performance delisting return is about **−30%**. He recommends substituting
**−0.30** for missing performance-related NYSE/AMEX returns, and using **−1** for
*every* performance delist only as an **upper bound on the bias** — the maximum
possible extent, **not** a point estimate.

> Verbatim: *"They can also be tested with returns of −0.3 replacing the missing
> performance delisting returns in CRSP"*; *"With 71 percent of the delisting returns
> accounted for, the average return is −30 percent"*; *"An upper bound for the bias can
> be computed by assuming a delisting return of −1 for every performance-related
> delist… Results obtained with delisting returns of −1 reveal the maximum possible
> extent of the bias."* The 1997 paper contains **zero** occurrences of −55% — that
> figure is the *Nasdaq* result from the 1999 paper. *(Verified 3-0, primary.)*

### Shumway & Warther (1999) — Nasdaq: **−55%**

For CRSP's **Nasdaq** database, substitute **−55%** for any missing
performance-related delisting return. The figure is built in two stages:

1. **Raw −40% terminal price drop**, from a selection-bias-adjusted reconstruction:
   of 3,330 missing-return stocks, post-delist prices were located for 63% (2,107)
   via Pink Sheets / Bloomberg / *Directory of Obsolete Securities*; located returns
   averaged **mean −26.3% / median −30.0%**; 201 stocks worthless within 5 years got
   **−100%**; the unfound 37% were split 50/50 (half "similar" at −26.5%, half
   worthless at −100%):
   ```
   0.63(−26.3) + 0.37(0.5(−100.0) + 0.5(−26.5)) ≈ −40%
   ```
2. **Bid-ask liquidity haircut.** The mean relative spread jumps **0.41 → 0.82** on
   a performance delisting. A holder who could sell at `0.795P` pre-delist can only
   sell at `P(1−0.40)(1−0.82/2) = 0.354P` post-delist:
   ```
   RCorr = (0.354P − 0.795P) / 0.795P = −55%
   ```

> Verbatim: *"We estimate that using a corrected return of −55 percent for missing
> performance-related delisting returns corrects the bias… Researchers can correct
> for the delisting bias by using this return whenever a performance-related
> delisting return is missing from CRSP's Nasdaq database."* *(Verified 3-0, primary.)*

> ⚠️ **Refuted overreach (1-2):** the claim that the −55% derivation *proves CRSP's
> own `DLRET` reflects terminal OTC value net of liquidity collapse* is **not
> supported**. The −55% is an **analyst-constructed substitute** for *missing*
> values — it is not a description of how CRSP computes a *realized* `DLRET`.

### Beaver-McNichols-Price (2007) — **average of *similar* delistings**

BMP's contribution is precisely that it **abandons the single fixed constant**.
Instead, each missing `DLRET` is replaced with the **average realized delisting
return of *similar* delistings**. The authors distribute the actual SAS
implementation: `_dlret_rv.sas` (computes replacement values) and `delistings.sas`
(merges them into monthly returns) on co-author Richard A. Price's site.

> Verbatim (Price webpage): *"replaces missing delisting returns with the average
> delisting return of similar delistings, rather than a single replacement value."*
>
> ⚠️ **Two BMP claims were REFUTED:** that BMP "impute −30% for performance-related
> missing returns" (**0-3** — the opposite of their method) and that BMP classify
> performance as DLSTCD "400 or 500–599" (**1-2** — 400 is announced-liquidation,
> handled separately). Do **not** attribute a flat constant to BMP. *(Verified 3-0,
> primary; refutations noted.)*

### Magnitude cheat-sheet

| Correction | Venue / case | Source | Confidence |
|---|---|---|---|
| **−30%** | NYSE/AMEX missing performance | Shumway 1997 | high |
| **−55%** | Nasdaq missing performance | Shumway & Warther 1999 | high |
| **−100% (−1)** | Worthless, *or* upper-bound stress test | Shumway 1997 | high |
| **avg-of-similar** | Any missing (refinement) | BMP 2007 | high |

*(Note: the brief that kicked this off mentioned "−35%". No primary source
supports a −35% constant — the canonical trio is **−30% / −55% / −100%**. Treat
−35% as a loose midpoint, not a citable figure.)*

---

## 6. Merger sub-codes — cash floor vs abstain

CRSP's detailed consideration-type codes confirm the repo's **cash-only-by-design**
payout policy:

| Code | Consideration | Clean cash floor? |
|---|---|---|
| **233** | Shareholders receive **cash payments** | ✅ Yes — extract & compute |
| **231 / 232** | Primarily **common stock / ADRs** | ❌ No — abstain (or value the stock leg) |
| **241** | Primarily **common stock and cash** | ❌ No clean floor — abstain |
| **251** | Common stock/ADRs **and cash** | ❌ Abstain |
| **261** | Common stock/ADR + cash + preferred/warrants/notes | ❌ Abstain |

> Verbatim (CRSP Delisting Codes doc): *"231 … primarily receive common stock or
> ADRs … 233 … receive cash payments … 241 … primarily receive common stock and
> cash …"* The modern 23x/24x/25x/26x scheme replaced an older coarser 200/201/202/203/205
> scheme. *(Verified 3-0, primary.)*

This is the empirical backing for the repo's stance (CLAUDE.md): extract a payout
**only** for pure-cash deals; abstain on stock/mixed legs because emitting only
the cash leg would *understate* the return, and a neutral mark is the correct
survivorship treatment for a miss.

---

## 7. Reconstruction recipe for a non-CRSP / EDGAR dataset

For a Tiingo/IEX/EDGAR panel with **no** `DLRET` column:

1. **Replicate the mechanism**, not a payout: `DLRET = terminal_value / last_trade_close − 1`.
2. **Classify by `DLSTCD` bucket** (this repo's classifier) — and **carve 501/502
   out of the 5xx negative bucket** (see §8).
3. **Per bucket:**
   - *Merger (cash, 233):* `payout_per_share / last_trade − 1` from the 8-K.
   - *Merger (stock/mixed, 231/232/24x/25x/26x):* **abstain** (neutral `0`); a miss
     here is *correct*, not a coverage gap.
   - *Exchange transfer (300–390, 501/502):* `DLRET = 0`; re-link the successor.
   - *Liquidation (400):* realized recovery if observed; **not** a performance shock.
   - *Performance / compliance / bankruptcy (500, 505–588, 574):* substitute by
     **venue** — **−30% NYSE/AMEX**, **−55% Nasdaq/OTC**; `−1` if evidence of worthlessness.
   - *Expiration (warrants/units/ADRs, 6xx):* drop from the equity universe.
4. **If you *do* have a CRSP column,** sanitize sentinels first:
   ```python
   import numpy as np
   dlret = df["dlret"].where(df["dlret"] > -1.0001, np.nan)   # kill −55/−66/−88/−99 sentinels
   # NOTE: keep genuine −1.0 (worthless). The sentinels are all < −1.
   final_ret = (1 + df["ret"].fillna(0)) * (1 + dlret.fillna(0)) - 1
   ```
   `(1 + RET.fillna(0)) * (1 + DLRET.fillna(0)) − 1` is the standard CRSP starting
   point — but **only after** replacing sentinels and imputing missing performance
   returns; a raw `fillna(0)` on a 99.8%-missing performance bucket *reintroduces*
   the survivorship bias you're trying to remove.

---

## 8. Mapping to this codebase — what's right, what to fix

### ✅ Already correct
- `bmp_correction.py` uses **`SHUMWAY_NYSE_AMEX = −0.30`** and **`SHUMWAY_NASDAQ =
  −0.55`** — these match Shumway (1997) and Shumway & Warther (1999) **exactly**,
  including venue split. The docstring's "Nasdaq ~−55%" citation is accurate.
- The firm-month identity `R = (1+R_partial)(1+DLRET)−1` matches CRSP's prescribed
  multiplicative combination.
- Merger payout policy (cash-only, code 233; abstain on 231/24x/25x/26x) is
  empirically vindicated by CRSP's consideration sub-codes (§6).
- `EXCHANGE_TRANSFER → DLRET = 0` and `EXPIRATION → NaN/drop` are consistent with
  the research.

### ⚠️ Discrepancy 1 — codes **501/502** are misbucketed as compliance failures

`crsp_codes.py` `bucket_for_code()` range fallthrough sends **all** of 500–599 to
`COMPLIANCE_FAILURE`:

```python
if 500 <= code < 600:
    return CrspBucket.COMPLIANCE_FAILURE
```

But the research confirms **501 (migrated to NYSE) and 502 (migrated to AMEX/NYSE
MKT) are positive up-migrations**, which Shumway & Warther *explicitly exclude*
from the negative correction. Under the current code they would be tagged
`COMPLIANCE_FAILURE` and hit with a **−55% Shumway shock** — a sign error on a
*good* event. **Fix:** map 501/502 (and the 503–519 "Another Exchange" sub-range)
to `EXCHANGE_TRANSFER` before the 5xx → compliance fallthrough.

### ⚠️ Discrepancy 2 — `−100%` docstring vs `−55%`/`−30%` code for `COMPLIANCE_FAILURE`

`crsp_codes.py`'s module docstring says:

> `COMPLIANCE_FAILURE — 500s … apply -100% terminal`

…but `bmp_correction.compute_dlret()` actually applies the **Shumway constant
(−30%/−55%)** to `COMPLIANCE_FAILURE`, not −100%. The **code is the more defensible
choice** (−100% is Shumway's *upper bound / stress case*, not the point estimate),
so the **docstring should be corrected** to say "Shumway constant by exchange"
rather than "−100% terminal," to avoid future confusion about which convention is
in force. (These are the "two return-correction APIs / conventions" CLAUDE.md
warns against conflating — the docstring is describing the wrong one.)

### 🔎 Worth a second look — liquidation without recovery
`compute_dlret()` falls back to a **Shumway performance constant** for
`LIQUIDATION` when no `recovery_ratio` is observed. The research notes liquidations
(400) are *announced/pre-priced* and **not** performance-biased — so a missing
recovery there is more likely "we just didn't capture the distribution" than "the
equity was wiped out." A Shumway −30%/−55% may be **too punitive** for a clean
liquidation; consider whether the realized distribution sum (CRSP's actual method)
or a milder default is more appropriate. Low-stakes, but it's an off-label use of
the Shumway constant. *(See [Open Questions](#open-questions).)*

---

## Refuted claims (don't propagate these)

| Claim | Verdict | Why |
|---|---|---|
| BMP (2007) impute a flat **−30%** for missing performance returns | **0-3** | BMP's method is *average-of-similar*, the opposite of a constant. |
| BMP classify performance as DLSTCD **400 or 500–599** | **1-2** | 400 = announced liquidation, handled separately. |
| `DLSTCD` **first-digit taxonomy** is the authoritative bucket basis | **1-2** | Useful mnemonic, but not primary-sourced; use explicit ranges. |
| The −55% derivation proves CRSP's **own `DLRET` reflects terminal OTC net of liquidity** | **1-2** | −55% is an analyst *substitute* for missing values, not CRSP's computation. |

---

## Open questions

1. **BMP replacement schedule.** The concrete per-category "average of similar"
   values (and how "similar" is defined — exchange? code? year? size?) live in
   `_dlret_rv.sas` and the paywalled JAE tables; not extracted here.
2. **Modern missing rates.** Does post-1999 CRSP still show ~99.8% missing for
   Nasdaq performance delistings, or did later incorporation of off-exchange /
   distribution values shrink the gap? The 99.8% figure is 1972–1995.
3. **Exchange-transfer population path.** For 501/502 and 300–390, does CRSP use
   the new-exchange opening price as the terminal value, and how does the `−66.0`
   (>10-period) flag interact with delayed re-listing?
4. **Cash+CVR / stock-election deals.** Is abstaining (neutral mark) *provably* the
   minimum-bias treatment vs marking the cash floor, and does CRSP record a partial
   `DLRET` for the cash leg of mixed (24x/25x/26x) deals? Relevant to the repo's
   payout-extractor abstention policy.

---

## Sources

**Primary (load-bearing):**
- Shumway, T. (1997). "The Delisting Bias in CRSP Data." *J. Finance* 52(1):327–340.
  <https://www.tylergshumway.org/Shumway-DelistingBiasCRSP-1997.pdf>
- Shumway, T. & Warther, V. (1999). "The Delisting Bias in CRSP's Nasdaq Data…"
  *J. Finance* 54(6):2361–2379.
  <https://tylergshumway.org/Shumway-DelistingBiasCRSPs-1999.pdf> ·
  <https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00192> ·
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=11150>
- Beaver, W., McNichols, M. & Price, R. (2007). "Delisting returns and their effect
  on accounting-based market anomalies." *JAE* 43:341–368.
  <https://www.sciencedirect.com/science/article/abs/pii/S0165410106000930> ·
  SAS code: <https://sites.google.com/site/richardaprice3/research/delistings>
- *CRSP US Stock & Indexes Database Data Descriptions Guide* (Ch. 5, Calculations;
  Amount After Delisting; Missing Delisting Return Codes).
  <https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_&_Indexes_Database_Data_Descriptions_Guide.pdf>
- *WRDS — CRSP/Compustat Merged Database Programming Access* (DLRET DEFAULT sentinel).
  <https://wrds-www.wharton.upenn.edu/documents/416/CRSP-Compustat_Merged_Database_Programming_Access.pdf>

**Secondary / practitioner:**
- AlphaArchitect, "Dealing with Delistings."
  <https://alphaarchitect.com/dealing-with-delistings-a-critical-aspect-for-stock-selection-research/>

*Note: several SSRN / ScienceDirect pages 403'd during verification but were
corroborated via author-hosted PDFs and Wiley / RePEc / Stanford GSB mirrors.*
