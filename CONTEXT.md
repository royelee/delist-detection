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
A run of one ticker's observations that the library takes to be one security, before it looks up that security's FIGI. A new era starts when a pin changes, when the observed name stops agreeing, or when the class letter in the name changes; then, from SEC fails-to-deliver rows under the ticker, when the CUSIP switches or when more than 400 days pass with no observation and no fails row of the era's CUSIP. A ticker used by two securities (DELL, Dell Inc. and later Dell Technologies) therefore gives two eras. Two eras can still be one security: they merge when they resolve to the same FIGI. An era is a grouping step, not a listing.

**Delisting**:
The removal of a security from its US exchange listing, after which it is listed on no exchange or has moved to another one. It is recorded by a Form 25 (or, where none was filed, by the filing that ended its trading) and classified by a CRSP `DLSTCD` code. A rename is not a delisting, and neither is withdrawing a secondary listing while the main one continues. A security can have more than one, such as an exchange transfer followed years later by a merger.
_Avoid_: termination, delist event

**Bucket**:
The handling class a delisting's CRSP code maps to: `merger`, `exchange_transfer`, `liquidation`, `compliance_failure`, `expiration`, or `active` when no delisting occurred. The bucket, not the exact code, decides the training label and the backtest exit.
_Avoid_: category

**Successor**:
The security a holder keeps after an `exchange_transfer` delisting. It is the same security after an exchange move, and a different one when the FIGI changes, as with Google to Alphabet.

**Observation**:
A caller-supplied record that a ticker was seen on a date, with the name and CUSIP it carried then when known.
_Avoid_: member name, names row

**Pin**:
A CIK or `sec_id` the caller attaches to an observation because it has already settled that observation's identity. A pin beats the library's own resolution but is still checked against the observation's name.
_Avoid_: cik-map, override
