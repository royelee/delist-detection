# delist_detection

Identifies each US-market security a caller cares about and, for every one that stopped trading, records why it ended and what a holder received.

## Language

**Security**:
One share class traded in the US market, identified by its US composite FIGI, which is its `sec_id`. Every US venue it trades on shares that one ID. When no FIGI can be confirmed, the `sec_id` is a placeholder built from the issuer's CIK and the class until one is found.
_Avoid_: instrument, ticker, stock, permaTicker

**Universe**:
The set of securities a caller cares about. The caller defines it; the library learns it only through observations.
_Avoid_: index, instruments file

**Issuer**:
The company that files with the SEC for a security, identified by its CIK. One issuer can have several securities, such as GOOG and GOOGL.
_Avoid_: company, filer

**Listing**:
A security trading under one ticker on one US exchange over a date range. A rename or an exchange move starts a new listing of the same security.
_Avoid_: series

**Ticker era**:
A run of one ticker's observations that the library takes to be one security, before it looks up that security's FIGI. A new era starts when a pin changes, when the observed name stops agreeing, or when the class letter in the name changes; then, from SEC fails-to-deliver rows under the ticker, when the CUSIP switches or when more than 400 days pass with no observation and no fails row of the era's CUSIP. A ticker used by two securities (DELL, Dell Inc. and later Dell Technologies) therefore gives two eras. Two eras can still be one security: they merge when they resolve to the same FIGI. An era is never dropped: when a ticker is seen under two names on one date, both names keep their eras (under distinct keys) and the date is reported for review. An era is a grouping step, not a listing.

**Delisting**:
The removal of a security from its US exchange listing, after which it is listed on no exchange or has moved to another one. It is recorded by a Form 25 (or, where none was filed, by the filing that ended its trading) and classified by a CRSP `DLSTCD` code. A rename is not a delisting, and neither is withdrawing a secondary listing while the main one continues. A security can have more than one, such as an exchange transfer followed years later by a merger.
_Avoid_: termination, delist event

**Bucket**:
The handling class a delisting's CRSP code maps to: `merger`, `exchange_transfer`, `liquidation`, `compliance_failure`, `expiration`, or `active` when no delisting occurred. The bucket, not the exact code, decides the training label and the backtest exit.
_Avoid_: category

**Successor**:
The security a holder's shares became, one for one, after a delisting that did not end their holding: the same security after an exchange move, a different one when the FIGI changes (Google to Alphabet, a holding-company reorganization). A successor means a continuation, so the ticker's price series is one series across it. Recorded as `successor_sec_id`.

**Handoff**:
One security of the run stops trading under a ticker and another security of the run starts trading under the same ticker within days. A handoff is a continuation, a ticker takeover, or neither.
_Avoid_: ticker reuse (a reuse years later is no handoff)

**Continuation**:
A handoff in which the holders' shares became the new security's one for one: a holding-company reorganization, a redomicile, a rename or a share reclassification (AON 2020, Liberty's 2023 reclassification). The old security gets an `exchange_transfer` delisting with a zero return, and the new one is its successor.

**Ticker takeover**:
A handoff in which another, already trading security takes the ticker over, typically an acquirer that renames itself after its target (II-VI as Coherent Corp on COHR, Eldorado as Caesars on CZR). The target keeps its own delisting (a merger); the taker is recorded as `ticker_successor_sec_id`, never as a successor, since the ticker's price series before the handoff is the target's, not the taker's.

**Observation**:
A caller-supplied record that a ticker was seen on a date, with the name and CUSIP it carried then when known.
_Avoid_: member name, names row

**Pin**:
A CIK or `sec_id` the caller attaches to an observation because it has already settled that observation's identity. A pin beats the library's own resolution but is still checked against the observation's name.
_Avoid_: cik-map, override

**Severity**:
How much a `review.csv` row can move a return, one of `fix` (`no_dlret` — a delisting whose return is still blank, injected before its other flags are ever accepted — a security that couldn't be identified, or the run or the decisions file itself is broken), `check` (a rule couldn't settle the answer; read the cited filing), or `info` (the answer came from a less precise source but nothing suggests it's wrong). A row whose flags are all `info` leaves `review.csv`; a delisting row's flags stay on `delistings.csv`, and a security-level one such as `no_figi` is counted in `review_summary.csv` (the placeholder itself is in `securities.csv`). Rows are ordered by severity, then by how much they can still move a return.
_Avoid_: priority, urgency

**Review decision**:
A line in `data/review_decisions.csv` recording that a person checked one exact flag on one exact row and it's fine (`sec_id, delist_date, ticker, flag, decision, note`). The pipeline reads it on every run, so an accepted flag stays off `review.csv`; a decision naming a flag no row carries becomes a `review_decision_unmatched:<flag>` row rather than being silently dropped (unless the run used `--limit`, which only counts it). A decision never changes `delistings.csv`.
_Avoid_: override, exception, waiver

**Lifecycle**:
What the output tables say happened to a security from its first ticker interval to today: it is still trading (`active`), it ended with a known reason, a last trade date and a return (`ended`), or it stops short of that (`ended_incomplete`, `left_view`, `closed_no_event`, `no_interval`). An ending that names a successor continues the lifecycle there. An input ticker's lifecycle is the one of the security its earliest mapped observation resolved to.
_Avoid_: history, chain

**Covered**:
A lifecycle that reaches `active` or `ended` with nothing missing on the way. Coverage, the share of input tickers whose lifecycle is covered, is the reset's headline number.

**Truth case**:
One security's outcome checked by hand at a cited source, naming the security by a ticker and a date it traded and listing only what was checked. The golden set and the accuracy audit are both made of truth cases.
_Avoid_: test case, expectation

**Floor**:
The best value each scorecard number has reached (`data/scorecard.json`). No later change may make a floored number worse.

**Verdict**:
`confirmed` or `uncertain`, one per seed, security and ending. Confirmed means the evidence the spec requires is in hand: a FIGI or a filing tying a placeholder's ticker to its CIK, a history covering every introduction, a filing-backed exit kind and an exchange-printed last trade date. Uncertain rows go to `uncertain.csv` for a person to pin, override or drop.
_Avoid_: confidence, review

**Contract**:
The tables the consumer reads (`output/contract/`): security_history, one-ending-per-security delistings, the seed echo, price requests, id changes, and `schema_version` in the manifest. Built from today's tables by `contract.py`; written beside them for one release.

**Exit kind**:
The contract's kind of ending: merger, exchange, liquidation, dropped (with a drop reason), lost_source, expiration. A continuation is an exchange whose successor is held by the same holders one for one.

**Fill** (`dlret_fill`):
A value the library assumes rather than measures: a Shumway mark, assumed par, a transfer's 0.0. Never in `dlret`.

**Issuer in force**:
The CIK that carried a security's name on a given day; it can change while the security continues (a reverse merger, a holding-company reorganization).
