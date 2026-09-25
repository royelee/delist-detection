"""Triage for review.csv: what each review flag means, how urgent it is, and
which rows a person still has to look at.

`CATALOG` holds every flag the pipeline can emit, keyed by its name (the text
before the first `:`; `terms_gate_failed:no_acq_price` is `terms_gate_failed`),
with a severity:

- `fix`   -- the run failed, a security could not be identified, or the
             decisions file is stale; always needs a person.
- `check` -- a rule could not settle the answer; read the cited filing.
- `info`  -- the answer came from a less precise source but nothing suggests it
             is wrong. A row whose flags are all `info` leaves review.csv (a
             delisting row's flags stay on delistings.csv; a security-level
             one such as `no_figi` is counted in review_summary.csv, and
             securities.csv lists every placeholder).

A delisting row (one with a `bucket`) with no DLRET always needs a person:
`triage()` gives it the token `no_dlret` (`fix`, acceptable) before decisions
are applied, so accepting its other flags never silently drops it -- only
accepting `no_dlret` itself (or supplying the value) does.

`triage()` turns the pipeline's merged review rows plus a person's decisions
(`load_decisions`: "I checked this flag on this row, it is fine") into the
final review.csv rows, ordered by what they can do to a return, and a per-flag
summary. It never touches delistings.csv. Pure: no I/O but `load_decisions`
and `append_decisions`.

`accept_by_flag`/`append_decisions` are the reusable half of
`scripts/accept_review.py`'s bulk accept: build one `Decision` per row
currently carrying a given flag, then append them to the decisions file
(skipping any already there).
"""
from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .store import replace_on_success

SEVERITIES = ("fix", "check", "info")        # this order is the sort order

UNMATCHED_FLAG = "review_decision_unmatched"
NO_DLRET_FLAG = "no_dlret"     # injected by triage() on every delisting row whose DLRET is still blank
_MAX_EXAMPLES = 3


@dataclass(frozen=True)
class FlagInfo:
    severity: str
    description: str
    action: str
    acceptable: bool = True
    # Per-bucket severity overrides, e.g. (("exchange_transfer", "info"),): a flag
    # whose urgency depends on the delisting bucket (I3, final review). The
    # catalog's own `severity` (used by review_summary.csv) is always the base
    # value; `severity_for` is what `row_severity` actually uses.
    severity_by_bucket: tuple[tuple[str, str], ...] = ()

    def severity_for(self, bucket: str) -> str:
        for b, s in self.severity_by_bucket:
            if b == bucket:
                return s
        return self.severity


def _accept_if(when: str = "right") -> str:
    return f"accept it in data/review_decisions.csv if {when}"


_ACCEPT = _accept_if()

CATALOG: dict[str, FlagInfo] = {
    # --- fix: the run itself failed, or the decisions file is stale ---
    "error": FlagInfo(
        "fix", "A stage raised an exception for this security (the reason names it), so its output is missing "
               "or partial.",
        "Fix the cause and rerun; it cannot be accepted.", acceptable=False),
    "resolution_degraded": FlagInfo(
        "fix", "An answer rested on a failed SEC request or a stale cached copy, and it was not saved.",
        "Rerun once SEC answers; it cannot be accepted.", acceptable=False),
    UNMATCHED_FLAG: FlagInfo(
        "fix", "A line of the decisions file accepts a flag that no review row carries (a typo, or a line "
               "written against an older run).",
        "Correct or remove that line of data/review_decisions.csv; it cannot be accepted.", acceptable=False),
    # --- fix: a security could not be identified ---
    "observation_unresolved": FlagInfo(
        "fix", "Neither a FIGI nor an issuer CIK was found for this ticker era, so its observations make no "
               "security.",
        "Pin a cik or sec_id on the observations (or fix their ticker or name) and rerun; accept it in "
        "data/review_decisions.csv if the security is out of scope."),
    # --- fix: a delisting has no return yet ---
    NO_DLRET_FLAG: FlagInfo(
        "fix", "The delisting has no delisting return (DLRET). `triage()` adds this token to every delisting "
               "row whose dlret is still blank, so accepting its other flags never silently drops it.",
        "Supply the missing value via --last-trade-closes, --merger-terms or --recoveries and rerun, or "
        f"{_accept_if('no value exists to supply')}."),
    # --- fix: the security stopped being observed but has no delisting row ---
    "ended_without_delisting": FlagInfo(
        "fix", "The security was observed and then stopped being observed, but no delisting was found: it has "
               "no delisting row and no DLRET, so it drops out of a backtest with no terminal return -- a "
               "missing delisting can hide a loss as large as -100%.",
        "Find the Form 25/15, bankruptcy or merger filing that ended it (search the issuer's filings around "
        "last_seen); if the identity is wrong, pin the right cik/sec_id on the observations. Accept only "
        "after confirming the security really still trades (e.g. under another ticker) or is out of scope -- "
        "there is no override to add a missing delisting."),

    # --- check: a rule could not settle the answer ---
    # merger terms and payouts
    "merger_at_par": FlagInfo(
        "check", "A merger whose consideration was never found or never passed the gate, so its DLRET was set "
                 "to 0 (terminal value = last close).",
        "Read the merger 8-K or proxy for the per-share consideration and supply it in --merger-terms; "
        f"{_accept_if('0% is right')}."),
    "terms_gate_failed": FlagInfo(
        "check", "LLM-read cash+stock merger terms were dropped: no acquirer ticker (no_acq_ticker), no "
                 "acquirer price (no_acq_price), no last close (no_last_close), or cash plus stock at the "
                 "acquirer's price is too far from the last close (fail_sanity).",
        "Read the merger filing and supply cash_per_share, stock_ratio, acquirer_price and acquirer_ticker "
        "in --merger-terms."),
    "payout_gate_failed": FlagInfo(
        "check", "The cash payout the regex read from the filing (the value after the colon) is more than the "
                 "tolerance away from the last close, so it was not used.",
        f"Check the row's payout against the merger filing and supply the right terms in --merger-terms; "
        f"{_ACCEPT}."),
    "llm_gate_failed": FlagInfo(
        "check", "The LLM's cash (or cash-or-stock election) terms did not reconcile with the last close, so "
                 "they were dropped.",
        f"Read the merger filing and supply the terms in --merger-terms; {_ACCEPT}."),
    # classification
    "distress_at_normal_price": FlagInfo(
        "check", "A compliance-failure or liquidation delisting whose last close is $5 or more, so its distress "
                 "bucket and negative DLRET may be wrong.",
        f"Read the Form 25 and the 8-Ks around it; supply a --recoveries ratio if the distress is real but "
        f"the mark is not, or {_ACCEPT}."),
    "bankruptcy_before_merger": FlagInfo(
        "check", "A confirmed Chapter 11 came long before the delisting and a change-in-control 8-K sits near "
                 "it, so the merger rules classified it instead of the bankruptcy.",
        f"Confirm the company emerged and was then acquired, not liquidated; {_ACCEPT}."),
    "bankruptcy_tag_unconfirmed": FlagInfo(
        "check", "An 8-K tagged Item 1.03 (bankruptcy) never mentions a bankruptcy in its text, so the tag was "
                 "ignored.",
        f"Read the 8-K (anchor_8k) to confirm it is not a bankruptcy; {_ACCEPT}."),
    "bankruptcy_text_missing": FlagInfo(
        "check", "An Item 1.03 8-K's text could not be fetched, so its bankruptcy tag was trusted unread.",
        f"Rerun once EDGAR answers, or read the 8-K on EDGAR to confirm the bankruptcy; {_ACCEPT}."),
    "notice_text_missing": FlagInfo(
        "check", "The Item 3.01 delisting notice's text could not be fetched, so the classification rests on "
                 "weaker evidence.",
        f"Rerun once EDGAR answers, or read the 3.01 8-K on EDGAR to confirm the bucket; {_ACCEPT}."),
    "no_evidence_default": FlagInfo(
        "check", "Delisted with no merger or distress evidence, so the bucket is unknown; DLRET is set to 0 at "
                 "par only when a Form 25 or Form 15 also confirms deregistration and a last close exists, else "
                 "it is blank.",
        f"Read the filings around the delisting to learn why it ended; {_ACCEPT}, otherwise the classifier "
        "needs a rule."),
    "spac": FlagInfo(
        "check", "A blank-check company (SPAC) whose trust was liquidated, classified as an expiration redeemed "
                 "at trust value.",
        f"Confirm the trust liquidation in its 8-K; {_ACCEPT}."),
    "submissions_stale": FlagInfo(
        "check", "The issuer's EDGAR submissions list could not be refreshed, so the classifier read a cached "
                 "copy older than the delisting.",
        "Rerun once EDGAR answers."),
    "frozen_tail": FlagInfo(
        "check", "The Form 25 is dated long before the last trade or observation (the number after the colon "
                 "is the gap in days, over 45), so the observations ran past the real end.",
        f"Confirm from the Form 25 and the deal filings when the security really stopped trading; {_ACCEPT}."),
    # dating the delisting and the last trade
    "no_form25": FlagInfo(
        "check", "No Form 25 was found, so the delisting was dated and classified from other filings (a "
                 "bankruptcy or anchor 8-K, an SEC revocation or a Form 15).",
        f"Check the delisting date and bucket against the cited filing; {_ACCEPT}."),
    "delist_date_approx": FlagInfo(
        "check", "No filing dated the delisting near the last observation, so delist_date is the last "
                 "observation itself.",
        f"Look in the issuer's filings for the real end date; {_accept_if('the last observation is close')}."),
    "last_trade_date_conflict": FlagInfo(
        "check", "The filing text dates the last trade differently from the date used (MIDAS volume, a Nasdaq "
                 "halt, or the other filing).",
        "Read the Form 25 notice or the 3.01 8-K to confirm the last trading day; supply its close in "
        f"--last-trade-closes if the close is wrong, or {_ACCEPT}."),
    "no_last_trade_date": FlagInfo(
        "check", "No source (MIDAS, a Nasdaq halt, the Form 25 notice or the 8-K text) dates the last trade.",
        "Matters when the row also carries no_dlret, or for a liquidation or compliance_failure delisting "
        "(their DLRET needs a close): find the last trading day in the delisting filings and supply that "
        "day's close in --last-trade-closes. On an exchange transfer the DLRET is 0 whatever the close; "
        "accept it in bulk with `accept_review.py --flag no_last_trade_date --bucket exchange_transfer`.",
        severity_by_bucket=(("exchange_transfer", "info"),)),
    "no_last_close": FlagInfo(
        "check", "No last-trade close was found in SEC fails-to-deliver data (or there is no last trade date), "
                 "so the DLRET may be blank.",
        "Matters when the row also carries no_dlret, or for a liquidation or compliance_failure delisting "
        "(their DLRET needs a close): supply the close in --last-trade-closes "
        "(sec_id,last_trade_close[,delist_date]). On an exchange transfer the DLRET is 0 whatever the close; "
        "accept it in bulk with `accept_review.py --flag no_last_close --bucket exchange_transfer`.",
        severity_by_bucket=(("exchange_transfer", "info"),)),
    "successor_unknown": FlagInfo(
        "check", "An exchange-transfer delisting (CRSP code 304: filings continued more than 180 days after "
                 "the delisting) whose successor security (successor_sec_id) was not found.",
        "Confirm the security really moved -- to OTC or another venue -- and was not acquired or dropped for "
        "cause; if the bucket itself is wrong, no bucket override exists, so note it for a classifier rule "
        f"instead of chasing the successor. Otherwise find the security the holders kept and add an "
        f"observation of it; {_accept_if('none exists')}."),
    "observed_after_delisting": FlagInfo(
        "check", "The delisting is a Form 25 filed before the observations stopped: a stale snapshot kept "
                 "listing a security already gone.",
        f"Confirm from the Form 25 and the deal filings that it really ended then; {_ACCEPT}."),
    # Form 25s and listing status
    "form25_unclassified": FlagInfo(
        "check", "A Form 25 of the issuer whose class text names no recognized class, so it was matched to no "
                 "security.",
        f"Read the Form 25 (accession in the reason); {_accept_if('it is not about this security')}, "
        "otherwise extend form25.class_kind for its class text."),
    "form25_unmatched": FlagInfo(
        "check", "A Form 25 whose class could not be matched to exactly one of the issuer's securities.",
        "Read the Form 25 (accession in the reason) to see which class it removed; "
        f"{_accept_if('it is not about this security')}, otherwise pin the securities' sec_id."),
    "form25_unreadable": FlagInfo(
        "check", "A Form 25's text could not be fetched from EDGAR, so it was not considered.",
        "Rerun once EDGAR answers, or read the filing on EDGAR (accession in the reason)."),
    "listing_status_unknown": FlagInfo(
        "check", "Whether the security trades today could not be told, and no delisting was found for it.",
        f"Check whether it still trades; if it ended, find its Form 25 or delisting filing, else {_ACCEPT}."),
    # identity
    "member_name_mismatch": FlagInfo(
        "check", "EDGAR's issuer name on the delisting date does not agree with the observed name, so the CIK "
                 "may belong to another company.",
        "Compare resolved_name with the observed name; pin the right cik on the observations if it is wrong, "
        f"or {_accept_if('the company was renamed')}."),
    "ticker_unconfirmed": FlagInfo(
        "check", "SEC fails-to-deliver data never shows this ticker near the era's first and last observation "
                 "(the snapshot may carry a ticker adopted later).",
        f"Check which ticker the company traded under then and fix the observations, or {_ACCEPT}."),
    "ticker_shared": FlagInfo(
        "check", "Two securities hold the same ticker on overlapping dates in ticker_history (the reason names "
                 "both ranges).",
        f"Check which security traded under the ticker then and fix the other's observations, or {_ACCEPT}."),
    "ticker_range_overlap": FlagInfo(
        "check", "One security's own ticker_history ranges overlap each other (the reason names both).",
        f"Check the security's ticker changes in its filings and fix the observations, or {_ACCEPT}."),
    "observation_conflict": FlagInfo(
        "check", "One ticker was observed under two or more names on the date after the colon; the reason "
                 "names each name and the security it went to.",
        "Check which company traded under the ticker that day and fix the other name's observation (its "
        f"ticker, or a cik or sec_id pin), or {_ACCEPT}."),

    # --- info: a less precise source, nothing suggests it is wrong ---
    "no_figi": FlagInfo(
        "info", "OpenFIGI confirmed no US composite FIGI, so sec_id is a placeholder CIK<cik>-<CLASS>.",
        "If the security had a FIGI, pin its sec_id or cusip on the observations; otherwise nothing to do."),
    "resolved_by_current_ticker_map": FlagInfo(
        "info", "The issuer CIK came from SEC's current company_tickers.json, today's holder of the ticker.",
        "Check resolved_name is the right company; if not, pin the cik on the observations."),
    "resolved_by_cik_map": FlagInfo(
        "info", "The CIK came from the observations' cik pin although EDGAR's name disagrees (it sits beside "
                "member_name_mismatch).",
        "Nothing if the pin is right; otherwise correct the cik pin in the observations."),
    "resolved_by_manual_override": FlagInfo(
        "info", "The CIK came from MANUAL_OVERRIDES in scripts/classify_universe.py although EDGAR's name "
                "disagrees (it sits beside member_name_mismatch).",
        "Nothing if the override is right; otherwise correct it in scripts/classify_universe.py."),
    "ftd_close_prior": FlagInfo(
        "info", "No fails-to-deliver row followed the last trade, so the last close is an earlier one (the "
                "number after the colon is its age in trading days).",
        "Nothing unless the price moved in those days; supply the close in --last-trade-closes to override."),
    "ftd_close_lagged": FlagInfo(
        "info", "The last close came from a fails-to-deliver row dated a few trading days late rather than the "
                "next trading day, so it may be an OTC or stale price.",
        "Nothing unless the price looks off; supply the close in --last-trade-closes to override."),
    "acquirer_close_lagged": FlagInfo(
        "info", "The acquirer price in the merger's stock leg came from a fails-to-deliver row dated a few "
                "trading days late, so it may be an OTC or stale price.",
        "Nothing unless the price looks off; supply acquirer_price in --merger-terms to override."),
    "last_trade_date_unconfirmed": FlagInfo(
        "info", "The last trade date came from filing text (or the last observation) that neither MIDAS volume "
                "nor a Nasdaq halt confirms.",
        "Nothing unless the date looks off; the close is priced on it, so supply --last-trade-closes if "
        "needed."),
}

_UNKNOWN = FlagInfo("check", "not in the flag catalog", "add it to review_triage.CATALOG")


def flag_name(token: str) -> str:
    """The flag's name: the text before the first `:`."""
    return token.split(":", 1)[0]


def flag_info(token: str) -> FlagInfo:
    """The catalog entry for `token`'s name; an unknown name is `check`."""
    return CATALOG.get(flag_name(token), _UNKNOWN)


def _blank(v: object) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def is_blank(v: object) -> bool:
    """True for `None`, NaN, or an empty/whitespace-only string -- the same
    "no value" test `_inject_no_dlret`/`row_severity` use for `dlret`, exposed
    publicly so `pipeline.py` can decide whether a delisting needs `no_dlret`
    without reaching into a private helper (I2, final review)."""
    return _blank(v)


def _text(v: object) -> str:
    return "" if v is None else str(v)


def _tokens(flags: object) -> list[str]:
    return [t for t in _text(flags).split(";") if t]


def _most_severe(severities) -> str:
    return min(severities, key=SEVERITIES.index, default="info")


def _is_delisting(row: Mapping) -> bool:
    """A delisting row has a bucket. A Form 25 review item (`form25_unmatched`,
    ...) carries the Form 25's date in `delist_date` but no bucket: it is not one."""
    return not _blank(row.get("bucket"))


def row_severity(row: Mapping) -> str:
    """The most severe of the row's tokens' catalog severities (`fix` > `check`
    > `info`); `info` for a row with none. A token whose `FlagInfo` carries a
    `severity_by_bucket` entry for this row's `bucket` (I3, final review: e.g.
    `no_last_close` is `info` on an `exchange_transfer` row, whose DLRET is 0
    whatever the close) uses that instead of its base severity -- the base
    severity is what `review_summary.csv`'s own `severity` column shows.
    A delisting row with a blank DLRET is `fix` because `triage()` injects the
    `no_dlret` token (see `_inject_no_dlret`) before this is ever called --
    this function itself no longer special-cases the bucket/dlret fields."""
    bucket = _text(row.get("bucket")).strip()
    return _most_severe(flag_info(t).severity_for(bucket) for t in _tokens(row.get("review_flags")))


def _inject_no_dlret(row: Mapping) -> dict:
    """A delisting row (non-blank `bucket`) with a blank DLRET always needs a
    person, whatever its other flags: give it the token `no_dlret` before
    decisions are applied, so accepting its other flags never silently drops
    it. Never applied to a non-delisting review item (a Form 25 review item
    such as `form25_unmatched` carries a date but no bucket)."""
    if _is_delisting(row) and _blank(row.get("dlret")):
        tokens = _tokens(row.get("review_flags"))
        if NO_DLRET_FLAG not in tokens:
            return {**row, "review_flags": ";".join(tokens + [NO_DLRET_FLAG])}
    return dict(row)


@dataclass(frozen=True)
class Decision:
    sec_id: str
    delist_date: str
    ticker: str
    flag: str
    note: str


class ReviewDecisionError(ValueError):
    """A decisions file that cannot be trusted: a missing column, a blank flag,
    a decision other than `accept`, or a flag that may not be accepted."""


DECISION_COLUMNS = ("sec_id", "delist_date", "ticker", "flag", "decision", "note")


def _key(sec_id: object, delist_date: object, ticker: object) -> tuple[str, str, str]:
    return _text(sec_id).strip(), _text(delist_date).strip(), _text(ticker).strip()


def load_decisions(path: str | Path) -> list[Decision]:
    """The decisions in the CSV at `path` (header: every DECISION_COLUMNS name;
    other columns are ignored; cells are stripped). Read as `utf-8-sig`, so a
    UTF-8 BOM (as Excel writes on a "CSV UTF-8" save) does not blank the first
    header/cell. A missing file raises FileNotFoundError; a bad file raises
    ReviewDecisionError naming the file and line. Rows repeating a `(sec_id,
    delist_date, ticker, flag)` collapse into the first."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in reader.fieldnames or ()]
        missing = [c for c in DECISION_COLUMNS if c not in header]
        if missing:
            raise ReviewDecisionError(f"{path}:1: missing required column(s) {missing}; found {header}")
        reader.fieldnames = header
        out: dict[tuple[str, str, str, str], Decision] = {}
        for row in reader:
            cell = {c: _text(row.get(c)).strip() for c in DECISION_COLUMNS}
            where = f"{path}:{reader.line_num}"
            if not cell["flag"]:
                raise ReviewDecisionError(f"{where}: empty flag")
            if cell["decision"] != "accept":
                raise ReviewDecisionError(f"{where}: decision must be 'accept', got {cell['decision']!r}")
            if not flag_info(cell["flag"]).acceptable:
                raise ReviewDecisionError(f"{where}: flag {cell['flag']!r} cannot be accepted; "
                                          f"{flag_info(cell['flag']).action}")
            d = Decision(cell["sec_id"], cell["delist_date"], cell["ticker"], cell["flag"], cell["note"])
            out.setdefault((d.sec_id, d.delist_date, d.ticker, d.flag), d)
    return list(out.values())


def accept_by_flag(review_rows: Iterable[Mapping], flag: str, *, note: str,
                    bucket: str | None = None) -> list[Decision]:
    """One `Decision` for every token of `review_rows` named `flag` (the text
    before its `:`), one per matching token, narrowed to rows whose `bucket`
    equals `bucket` when given. `note` is copied onto every decision and must
    be non-empty (the person records what they checked). Raises
    `ReviewDecisionError` for a blank `note`; a `flag` containing `:` (a full
    token such as `payout_gate_failed:45.5` copied from review.csv, rather
    than a flag *name*, would otherwise silently match nothing); a `flag` not
    in `CATALOG` at all (a typo such as `no_last_clsoe` would otherwise fall
    back to the generic "not in the flag catalog" entry -- itself acceptable
    -- and silently match nothing too); or a `flag` whose catalog entry is
    not acceptable (`error`, `resolution_degraded`, `review_decision_unmatched`)
    -- these mean the run itself failed, not that a rule couldn't settle the
    answer."""
    if not note or not note.strip():
        raise ReviewDecisionError("note must be non-empty")
    if ":" in flag:
        raise ReviewDecisionError(f"flag {flag!r} must be a flag name, not a token; drop everything from "
                                  "the first ':' on")
    if flag not in CATALOG:
        raise ReviewDecisionError(f"flag {flag!r} is not in review_triage.CATALOG")
    info = CATALOG[flag]
    if not info.acceptable:
        raise ReviewDecisionError(f"flag {flag!r} cannot be accepted; {info.action}")
    out: list[Decision] = []
    for row in review_rows:
        if bucket is not None and _text(row.get("bucket")).strip() != bucket:
            continue
        for token in _tokens(row.get("review_flags")):
            if flag_name(token) == flag:
                out.append(Decision(_text(row.get("sec_id")), _text(row.get("delist_date")),
                                    _text(row.get("ticker")), token, note))
    return out


def append_decisions(path: str | Path, decisions: Sequence[Decision], *, dry_run: bool = False) -> int:
    """Append `decisions` to the decisions CSV at `path`, creating it with the
    `DECISION_COLUMNS` header when missing. A decision already there (same
    `(sec_id, delist_date, ticker, flag)`, stripped) is skipped, and so is a
    repeat within `decisions` itself. Written atomically
    (`store.replace_on_success`). Returns how many rows would be added
    (`dry_run=True`) or were added.

    C1 (final review): an existing file is validated with `load_decisions`
    first -- a file that does not load (a missing column, a bad decision, an
    unacceptable flag) raises `ReviewDecisionError` and nothing is written, so
    a bad file is never silently rewritten into an empty or half-blanked one.
    A valid file's rows are re-read with the same header normalization
    `load_decisions` uses (stripped header cells, `utf-8-sig` so an Excel BOM
    is ignored) and written back **exactly as read** -- every existing row,
    every existing column including ones `load_decisions` itself ignores (a
    `reviewer` column, say), in the file's own column order. A new row gets a
    blank cell for every column beyond `DECISION_COLUMNS`."""
    path = Path(path)
    try:
        load_decisions(path)      # validates; raises before anything is read further or written
    except FileNotFoundError:
        header = list(DECISION_COLUMNS)
        existing_rows: list[dict[str, str]] = []
        existing_keys: set[tuple[str, str, str, str]] = set()
    else:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            raw_fieldnames = reader.fieldnames or []
            header = [h.strip() for h in raw_fieldnames]
            existing_rows = [{h: (raw_row.get(orig) or "") for h, orig in zip(header, raw_fieldnames)}
                             for raw_row in reader]
        existing_keys = {_key(r.get("sec_id"), r.get("delist_date"), r.get("ticker"))
                         + (_text(r.get("flag")).strip(),) for r in existing_rows}
    seen = set(existing_keys)
    new_rows: list[dict[str, str]] = []
    for d in decisions:
        k = _key(d.sec_id, d.delist_date, d.ticker) + (d.flag.strip(),)
        if k in seen:
            continue
        seen.add(k)
        values = {"sec_id": d.sec_id, "delist_date": d.delist_date, "ticker": d.ticker, "flag": d.flag,
                 "decision": "accept", "note": d.note}
        new_rows.append({c: values.get(c, "") for c in header})
    if dry_run or not new_rows:
        return len(new_rows)
    with replace_on_success(path) as tmp, tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        w.writeheader()
        for r in existing_rows:
            w.writerow(r)
        for r in new_rows:
            w.writerow(r)
    return len(new_rows)


@dataclass(frozen=True)
class Triage:
    review_rows: list[dict]
    summary_rows: list[dict]
    counts: dict[str, int]


def _group(row: Mapping) -> int:
    """0: a delisting row with a blank DLRET; 1: a delisting row with a DLRET;
    2: every other row."""
    if not _is_delisting(row):
        return 2
    return 0 if _blank(row.get("dlret")) else 1


_TIEBREAK = ("sec_id", "delist_date", "ticker", "review_flags", "reason", "cik", "bucket", "dlret", "anchor_8k",
             "last_seen")


def _order(row: Mapping) -> tuple:
    group = _group(row)
    size = -abs(float(row["dlret"])) if group == 1 else 0.0
    return (SEVERITIES.index(row["severity"]), group, size) + tuple(_text(row.get(c)) for c in _TIEBREAK)


def _label(row: Mapping) -> str:
    ticker, day = _text(row.get("ticker")).strip(), _text(row.get("delist_date")).strip()
    if not ticker:
        return _text(row.get("sec_id")).strip()
    return f"{ticker}@{day}" if day else ticker


def _names(row: Mapping) -> set[str]:
    return {flag_name(t) for t in _tokens(row.get("review_flags"))}


def triage(rows: list[Mapping], decisions: Sequence[Decision], *, report_unmatched: bool = True) -> Triage:
    """The final review.csv rows, the review_summary.csv rows and the counts.

    Before anything else, every delisting row (non-blank `bucket`) whose DLRET
    is still blank gets the token `no_dlret` (`_inject_no_dlret`) -- so a
    delisting with no return stays visible until a person supplies the value
    or explicitly accepts `no_dlret`, even once every one of its other flags
    is accepted. This happens before decisions are matched, so a decision may
    target `no_dlret` itself and the summary's "before decisions" counts
    include it.

    A token is accepted by a decision with the same `(sec_id, delist_date,
    ticker)` (stripped, None as "") and exactly that token; accepted tokens
    leave their row. A decision that accepts nothing becomes a `fix` row whose
    token is `review_decision_unmatched:<flag>` (the flag it names, not the
    bare name -- two stale decisions on one row therefore get distinct review
    keys) -- unless `report_unmatched` is False (M3, final review: a `--limit`
    dev subset, or a second universe sharing the repo-relative default
    `data/review_decisions.csv`, can only see a fraction of the rows a
    decisions file was written against, so every decision outside that subset
    would otherwise become noise), in which case no such row is made, though
    `counts["unmatched_decisions"]` still reports how many there were so the
    caller can log it. Rows left with no token, or with a severity of `info`,
    leave review.csv. The rest are ordered by severity; then delisting rows
    (those with a `bucket`) with a blank DLRET, delisting rows by descending
    |DLRET|, every other row; then by `(sec_id, delist_date, ticker,
    review_flags)` and, beyond what those four decide, a few more columns
    (`reason, cik, bucket, dlret, anchor_8k, last_seen`) so two rows that
    still tie never depend on the input order. The caller's input rows are
    not mutated (each is copied before its tokens change)."""
    rows = [_inject_no_dlret(r) for r in rows]
    by_key: dict[tuple[str, str, str, str], Decision] = {}
    for d in decisions:
        by_key.setdefault(_key(d.sec_id, d.delist_date, d.ticker) + (d.flag,), d)

    used: set[tuple[str, str, str, str]] = set()
    accepted_by_name: dict[str, int] = {}
    kept_rows: list[dict] = []
    info_hidden = cleared = 0
    for row in rows:
        key = _key(row.get("sec_id"), row.get("delist_date"), row.get("ticker"))
        tokens = _tokens(row.get("review_flags"))
        kept = []
        for t in tokens:
            if key + (t,) in by_key:
                used.add(key + (t,))
                accepted_by_name[flag_name(t)] = accepted_by_name.get(flag_name(t), 0) + 1
            else:
                kept.append(t)
        if not kept:
            cleared += bool(tokens)
            continue
        out = {**row, "review_flags": ";".join(kept)}
        severity = row_severity(out)
        if severity == "info":
            info_hidden += 1
            continue
        kept_rows.append({**out, "severity": severity})

    unmatched = [d for k, d in by_key.items() if k not in used]
    if report_unmatched:
        for d in unmatched:
            note = f" ({d.note})" if d.note else ""
            kept_rows.append({
                "severity": "fix", "sec_id": d.sec_id, "delist_date": d.delist_date, "ticker": d.ticker,
                # M1 (final review): the flag it names, not the bare UNMATCHED_FLAG, so two stale decisions
                # on one row get distinct keys (sec_id, delist_date, ticker, review_flags) instead of
                # colliding; the catalog still looks it up by the name before ':'.
                "review_flags": f"{UNMATCHED_FLAG}:{d.flag}",
                "reason": f"decision accepts {d.flag!r} but no review row carries it; remove it from the "
                          f"decisions file{note}",
            })
    review_rows = sorted(kept_rows, key=_order)

    input_rows = sorted(rows, key=lambda r: tuple(_text(r.get(c)) for c in _TIEBREAK))
    names = {n for r in rows for n in _names(r)} | ({UNMATCHED_FLAG} if (unmatched and report_unmatched) else set())
    summary_rows = []
    for name in names:
        examples: list[str] = []
        for r in [r for r in review_rows if name in _names(r)] + [r for r in input_rows if name in _names(r)]:
            label = _label(r)
            if label and label not in examples:
                examples.append(label)
            if len(examples) == _MAX_EXAMPLES:
                break
        info = CATALOG.get(name, _UNKNOWN)
        summary_rows.append({
            "severity": info.severity, "flag": name,
            # the unmatched-decision rows exist only after decisions: count them
            "rows": sum(name in _names(r) for r in rows) + (len(unmatched) if name == UNMATCHED_FLAG else 0),
            "in_review": sum(name in _names(r) for r in review_rows),
            "accepted": accepted_by_name.get(name, 0),
            "description": info.description, "action": info.action, "examples": "; ".join(examples),
        })
    summary_rows.sort(key=lambda s: (SEVERITIES.index(s["severity"]), -s["rows"], s["flag"]))

    counts = {
        "fix": sum(r["severity"] == "fix" for r in review_rows),
        "check": sum(r["severity"] == "check" for r in review_rows),
        "info_hidden": info_hidden,
        "accepted": sum(accepted_by_name.values()),
        "cleared": cleared,
        "unmatched_decisions": len(unmatched),
    }
    return Triage(review_rows, summary_rows, counts)
