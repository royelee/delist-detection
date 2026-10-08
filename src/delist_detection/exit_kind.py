"""The row vocabulary (architecture step 8a): one reading of a delistings.csv row, and the text its producers write
for the readers to read back. Producers (the end-of-era resolver, the handoff stage, the delisting finder, the
rewrites, the payout gate, the last trade module, stage 9g) write through it; readers (the verdict, the scorecard,
the contract, the lifecycle walk, the audit, the truth judges, the regression report, the loop) read through it.
It imports nothing of the package, so a measurement module reads a row without loading a network client.

- **The contract's view** (spec: Delist Library Reset, "delistings · one row per ended security"; decisions 9 and
  12): `ending_fields` gives a row's exit kind, drop reason and whether it is a continuation. Today's bucket and CRSP
  code map to `exit_kind` and `drop_reason`: a bankruptcy delisting (the classifier's code 470, today's
  `liquidation` bucket) is `dropped` for `bankruptcy`; a compliance failure is `dropped` for the reason its code
  names; `unknown` asserts no kind. `is_distress` reads it. Its value, a measured `dlret` or a `dlret_fill`, is the
  value's own answer (`dlret.contract_value`, architecture step 10: each method's kind is defined beside it).
- **Real endings** (`is_real_ending`, `is_continuation`, `last_endings`): a row whose successor is not the security
  itself ended it; a successor other than itself is a continuation (decision 9); each security's last real ending is
  the one contract/delistings.csv keeps (decision 12).
- **Flags** (`flag_tokens`, `flag_name`, `flag_detail`, `flag_names`): the review_flags cell's tokens
  (`payout_gate_failed:34.88`), and the gate flags the verdict, the payout rule and the rewrites read (`GATE_FLAGS`).
- **The evidence a reason names.** The parts of the published `reason` a reader parses, each written by one
  function here and read back by its reader beside it: the continued-filings rule (`CONTINUED`,
  `rests_on_continued_filings`), an end-of-era branch that relabelled it (`relabel`,
  `resolved_from_continued_filings`) to a merger (`change_in_control_reason`, `completed_acquisition_reason`,
  `merger_relabel`), a successor registration (`successor_registration_reason`, `continuation_reason`,
  `names_successor_registration`), and a handoff linked by timing alone (`TIMING_CIK` inside `continuation_reason`
  or `successor_note`, `linked_by_timing`). The published text is the producers' as before, byte for byte.
- **The value rules** (`VALUE_RULES`): contract/delistings.csv's `value_rule` column.
- **The last trade** (decision 12; the last trade module's facts, architecture step 4): its sources and flags,
  `LastTrade` and its facts (`confirmed`, `worked_out`, `publishable`), the day an ending ends its security's listing
  (`end_day`), the Form 25's effective date (`effective_date`), and over a row: `of_row`, `effective_of`,
  `published` (contract/delistings.csv's last_trade_date) and `end_day_of`. last_trade.py dates an ending and
  answers a `LastTrade`; its definition is here, so the measurement side reads it without the dating's clients.
- **What stage 9g read for a continuation** (`ContinuationReading`): the verdict's one input that is not a table.

Pure, on string rows as store.read_table returns them."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

# -- the contract's view of a row --------------------------------------------------------------------------------
EXIT_KINDS = frozenset({"merger", "exchange", "liquidation", "dropped", "lost_source", "expiration"})
DROP_REASONS = frozenset({"moved_otc", "price", "capital", "went_private", "bankruptcy", "filings_fees",
                          "guidelines", "sec_order"})
NOT_DISTRESS = frozenset({"moved_otc", "went_private"})        # drop reasons that carry no harsh mark

# The drop reason of each code a dropped security can carry: the codes this
# library gives (classifier.py: 470 a bankruptcy, 570 a listing deficiency, 573
# an SEC revocation, 580 a delinquent filer), and the other 5xx codes of
# crsp_codes.DLST_CODE_TO_BUCKET by CRSP's meaning.
DROP_REASON_OF_CODE = {
    "470": "bankruptcy", "574": "bankruptcy", "520": "moved_otc", "550": "price", "552": "price",
    "560": "capital", "570": "guidelines", "584": "guidelines", "573": "sec_order", "585": "sec_order",
    "580": "filings_fees",
}


@dataclass(frozen=True)
class EndingFields:
    exit_kind: str           # one of EXIT_KINDS, or "" when the row asserts none (today's `unknown`)
    drop_reason: str         # one of DROP_REASONS on a `dropped` row whose code names one, else ""
    continuation: bool


# -- real endings ------------------------------------------------------------------------------------------------
def is_real_ending(row: Mapping[str, str]) -> bool:
    """A delistings.csv row that ended its security: its successor is not the security itself (a security that went
    on, a continuing exchange move, has no real ending there). The one definition every reader of the tables asks."""
    return row["successor_sec_id"] != row["sec_id"]


def is_continuation(row: Mapping[str, str]) -> bool:
    """A successor other than the security itself: the same holders own it now. The one definition every reader of
    the tables asks."""
    return bool(row["successor_sec_id"]) and is_real_ending(row)


def last_endings(delistings: Sequence[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    """Each security's last real ending, by delist date (of two on one day, the later row): the one
    contract/delistings.csv keeps (decision 12), the one the verdict settles a security's seeds by, and the one a
    lifecycle walk follows."""
    out: dict[str, Mapping[str, str]] = {}
    for r in sorted((r for r in delistings if is_real_ending(r)), key=lambda r: r["delist_date"]):
        out[r["sec_id"]] = r
    return out


def _kind(row: Mapping[str, str]) -> tuple[str, str]:
    bucket, reason = row["bucket"], DROP_REASON_OF_CODE.get(row["crsp_code"], "")
    if bucket == "merger":
        return "merger", ""
    if bucket == "exchange_transfer":
        return "exchange", ""
    if bucket == "liquidation":
        return ("dropped", reason) if reason == "bankruptcy" else ("liquidation", "")
    if bucket == "compliance_failure":
        return "dropped", reason
    if bucket == "expiration":
        return "expiration", ""
    return "", ""


def ending_fields(row: Mapping[str, str]) -> EndingFields:
    """The contract's kind columns for one delistings.csv row (its value cells are the value's: dlret.contract_value)."""
    kind, reason = _kind(row)
    return EndingFields(kind, reason, is_continuation(row))


def is_distress(row: Mapping[str, str]) -> bool:
    """A liquidation, or a drop for a reason that carries a harsh mark: every
    drop reason but a move to OTC or going private. A drop whose code names no
    reason counts, as today's compliance_failure bucket always did."""
    f = ending_fields(row)
    return f.exit_kind == "liquidation" or (f.exit_kind == "dropped" and f.drop_reason not in NOT_DISTRESS)


# -- flags -------------------------------------------------------------------------------------------------------
# The gates of a merger's value (stage 8, payout_gate): a gate that did not pass, or (sub-plan 5f) could not check.
# The payout gate writes them; the verdict (decision 4), the payout rule's terms_gate and the rewrites read them.
PAYOUT_GATE_FAILED = "payout_gate_failed"     # the regex cash missed the last close (`payout_gate_failed:<value>`)
LLM_GATE_FAILED = "llm_gate_failed"
TERMS_GATE_FAILED = "terms_gate_failed"       # `terms_gate_failed:<why>`
TERMS_GATE_SKIPPED = "terms_gate_skipped"     # `terms_gate_skipped:<why>`: never a price-side failure
GATE_FLAGS = frozenset({PAYOUT_GATE_FAILED, LLM_GATE_FAILED, TERMS_GATE_FAILED, TERMS_GATE_SKIPPED})


def flag_tokens(row: Mapping[str, object]) -> list[str]:
    """The review flag tokens on a row (delistings.csv's or a review row's `review_flags`), whole and in order
    (`payout_gate_failed:34.88`); none for a blank or missing cell."""
    cell = row.get("review_flags")
    return [t for t in ("" if cell is None else str(cell)).split(";") if t]


def flag_name(token: str) -> str:
    """A token's flag name: the text before the first `:`."""
    return token.split(":", 1)[0]


def flag_detail(token: str) -> str:
    """A token's detail: the text after the first `:` (`34.88` of `payout_gate_failed:34.88`), "" when none."""
    return token.partition(":")[2]


def flag_names(row: Mapping[str, object]) -> set[str]:
    """The flag names on a row."""
    return {flag_name(t) for t in flag_tokens(row)}


# -- the evidence a reason names: one writer and its reader each ------------------------------------------------
# The continued-filings rule (end_of_era branches 1 and 6): its reason is CONTINUED. The finder, stage 9g, the
# verdict and the scorecard read it (`rests_on_continued_filings`).
CONTINUED_FILINGS = "Continued 10-K/Q filings"
CONTINUED = f"{CONTINUED_FILINGS} >180d after delist (moved to OTC or spun off)"
# A branch of the end-of-era resolver that relabelled a continued-filings ending ends its reason with this
# (`relabel`); the verdict keeps it a doubt unless a filing settles it (`resolved_from_continued_filings`).
RESOLVED_FROM_CONTINUED_FILINGS = "; the registrant kept filing after it"
# The two merger branches (a change in control, a completed acquisition) begin with these (`merger_relabel`).
CHANGE_IN_CONTROL = "Change in control (8-K item 5.01"
COMPLETED_ACQUISITION = "Completed acquisition (8-K item 2.01"
# A successor registration: the forms that carry a security to a successor, named by the resolver's successor
# branch ("Successor registration 8-K12B 2017-07-03: ...") and the handoff stage's continuation by filing
# ("Continuation (8-K12B 0001193125-15-336577): ...").
SUCCESSOR_FORMS = ("8-K12B", "8-K12G3")
SUCCESSOR_REGISTRATION = "Successor registration"
CONTINUATION = "Continuation"
# A handoff continuation's evidence by timing and identity (`handoffs.decide_handoff`): the same issuer CIK, or the
# ticker's CUSIP switch. The verdict and stage 9g read the first (a CUSIP switch is evidence of its own).
TIMING_CIK, TIMING_CUSIP = "timing:cik", "timing:cusip"


def _evidence(evidence: str) -> str:
    return f"({evidence})"


def relabel(text: str) -> str:
    """An end-of-era branch's reason over a continued-filings ending: its own text and the relabel suffix."""
    return text + RESOLVED_FROM_CONTINUED_FILINGS


def change_in_control_reason(filed: date) -> str:
    """End-of-era branch 3's reason: the 8-K item 5.01's filing day."""
    return relabel(f"{CHANGE_IN_CONTROL} filed {filed})")


def completed_acquisition_reason(filed: date, filing: object) -> str:
    """End-of-era branch 4's reason: the 8-K item 2.01's filing day and the merger filing or Form 25 beside it
    (`end_of_era.Filed`, printed "<form> <day>")."""
    return relabel(f"{COMPLETED_ACQUISITION} filed {filed}, {filing})")


def successor_registration_reason(filing: object, text: str) -> str:
    """End-of-era branch 2's reason: the successor registration (`end_of_era.Filed`, "8-K12B 2017-07-03") and what
    it says."""
    return f"{SUCCESSOR_REGISTRATION} {filing}: {text}"


def continuation_reason(evidence: str, text: str) -> str:
    """A continuation's reason: what evidenced it ("R1", "line follow, ...", a handoff's "<form> <accession>" or
    `TIMING_CIK`) and what happened."""
    return f"{CONTINUATION} {_evidence(evidence)}: {text}"


def successor_note(how: str, evidence: str = "") -> str:
    """The note a successor link adds to an existing reason ("; successor by same ticker", "; successor by handoff
    (timing:cik)"): the published reason's one wording of how a successor was found."""
    return f"; successor by {how.replace('_', ' ')}" + (f" {_evidence(evidence)}" if evidence else "")


def rests_on_continued_filings(reason: str) -> bool:
    """The continued-filings rule's reason (`CONTINUED`)."""
    return reason.startswith(CONTINUED_FILINGS)


def resolved_from_continued_filings(reason: str) -> bool:
    """An end-of-era branch relabelled a continued-filings ending (`relabel`)."""
    return RESOLVED_FROM_CONTINUED_FILINGS in reason


def merger_relabel(reason: str) -> bool:
    """A relabel to a merger, by a change in control or a completed acquisition (`change_in_control_reason`,
    `completed_acquisition_reason`)."""
    return resolved_from_continued_filings(reason) and reason.startswith((CHANGE_IN_CONTROL, COMPLETED_ACQUISITION))


_SUCCESSOR_FILING = re.compile(rf"^(?:{SUCCESSOR_REGISTRATION} |{CONTINUATION} \()"
                               rf"(?:{'|'.join(SUCCESSOR_FORMS)})(?:/A)? ")


def names_successor_registration(reason: str) -> bool:
    """A reason that names a successor registration, an 8-K12B or 8-K12G3 (or its amendment): the resolver's
    (`successor_registration_reason`) or the handoff stage's (`continuation_reason` with a filing)."""
    return bool(_SUCCESSOR_FILING.match(reason))


def linked_by_timing(reason: str) -> bool:
    """A handoff continuation linked by timing and the same issuer CIK (`TIMING_CIK`, in the continuation's reason
    or in the successor note it added)."""
    return _evidence(TIMING_CIK) in reason


# -- the value rules ---------------------------------------------------------------------------------------------
# contract/delistings.csv's value_rule column (dlret.rule_of decides it, payout_rule.value_fields writes it).
VALUE_RULES = frozenset({"cash", "stock", "cash_plus_stock", "basket", "otc_print", "recovery", "worthless",
                         "transfer", "continuation", "expiration", "unknown"})


# -- the last trade ----------------------------------------------------------------------------------------------
# last_trade_date_source: where the day came from
MIDAS = "midas"                     # SEC MIDAS: the last day with exchange volume
NASDAQ_HALT = "nasdaq_halt"         # a Nasdaq code-D ("security deletion") halt
EX99_NOTICE = "ex99_notice"         # the exchange's Form 25 notice (EX-99.25)
EIGHTK_301 = "8k_301"               # an 8-K's Item 3.01 text
CLOSING_DAY = "closing_day"         # rule 4: a worked-out closing day (never published)
LAST_SIGHTING = "last_sighting"     # the handoff stage: A's last sighting under the ticker, before B's first
UNSOURCED = ""                      # no source: no day, or the fallback's last sighting with nothing to date it
SOURCES = (MIDAS, NASDAQ_HALT, EX99_NOTICE, EIGHTK_301, CLOSING_DAY, LAST_SIGHTING, UNSOURCED)
EXCHANGE_PRINTS = frozenset({MIDAS, NASDAQ_HALT, EX99_NOTICE, EIGHTK_301})   # an exchange print gave the day
MEASURED = frozenset({MIDAS, NASDAQ_HALT})                                   # measured, not worded
# the review flags a dating writes onto its delisting
UNCONFIRMED = "last_trade_date_unconfirmed"     # nothing confirms the day: never published
CONFLICT = "last_trade_date_conflict"           # the text sources state another day than the one taken
NO_DAY = "no_last_trade_date"
FLAGS = frozenset({UNCONFIRMED, CONFLICT, NO_DAY})
FORM25_EFFECTIVE_DAYS = 10          # a Form 25 takes effect this many days after it is filed


@dataclass(frozen=True)
class LastTrade:
    """One ending's last trade: the day (None: no source dates it), where it came from (one of `SOURCES`), the
    review flags the dating raised (`FLAGS`), and the Nasdaq halt-feed days the decision asked for and could not
    read (`nasdaq_halts`: a failure, not "no halts"; the decision rests on them, in memory only)."""
    day: date | None
    source: str
    flags: tuple[str, ...]
    halt_feed_failed: tuple[date, ...] = ()

    @property
    def confirmed(self) -> bool:
        """A day that something confirms: dated, and not flagged `UNCONFIRMED` (an involuntary notice's decision day,
        a suspension "immediately on D", a worked-out closing day, the fallback's last sighting). Only a confirmed
        day is tested against fails rows (the clip) or bounds a successor's start."""
        return self.day is not None and UNCONFIRMED not in self.flags

    @property
    def worked_out(self) -> bool:
        """A day no source states, worked out from the closing (rule 4): the classification never anchors on it."""
        return self.source == CLOSING_DAY

    def publishable(self, effective: date | None) -> bool:
        """Whether the contract publishes the day (decision 12, controller ruling of architecture step 4): confirmed,
        from an exchange print (`EXCHANGE_PRINTS`), and no later than the Form 25's effective date `effective` (None:
        no Form 25)."""
        return (self.confirmed and self.source in EXCHANGE_PRINTS
                and (effective is None or self.day <= effective))


def end_day(lt: LastTrade, delist_date: str) -> date:
    """The day an ending ends its security's listing: its last trade, else its delisting date (a Form 25's effective
    date). The clip (`history.Histories`) and stage 9e's off-exchange reads take it, not `last_trade.anchor_day`: an
    undated security stayed listed until its Form 25 took effect (the anchor's filing date would clip FWLT 2014, AWH
    2017, WPG 2021 and ARD 2021 ten days early and read WPG's OTC symbol from before its removal)."""
    return lt.day if lt.day is not None else date.fromisoformat(delist_date)


def effective_date(filing_date: str) -> str:
    """The day a Form 25 filed on `filing_date` takes effect (`FORM25_EFFECTIVE_DAYS` later), as an ISO date."""
    return (date.fromisoformat(filing_date) + timedelta(days=FORM25_EFFECTIVE_DAYS)).isoformat()


def cites_form25(row: Mapping[str, str]) -> bool:
    """The row cites a Form 25 (25 or 25-NSE, or an amendment) with its filing date."""
    return bool(row["delist_filing_date"]) and row["delist_filing_form"].startswith("25")


def effective_of(row: Mapping[str, str]) -> date | None:
    """The day a delistings.csv row's Form 25 takes effect (`effective_date`), or None when the row cites no
    Form 25."""
    return date.fromisoformat(effective_date(row["delist_filing_date"])) if cites_form25(row) else None


def of_row(row: Mapping[str, str]) -> LastTrade:
    """A delistings.csv row's last trade, read back from its published columns: `last_trade_date`,
    `last_trade_date_source` and the dating's flags among `review_flags`."""
    day = date.fromisoformat(row["last_trade_date"]) if row["last_trade_date"] else None
    return LastTrade(day, row["last_trade_date_source"], tuple(t for t in flag_tokens(row) if flag_name(t) in FLAGS))


def published(row: Mapping[str, str]) -> str:
    """contract/delistings.csv's last_trade_date (decision 12): the row's day when it is publishable
    (`LastTrade.publishable` against the row's Form 25 effective date), else blank."""
    lt = of_row(row)
    return lt.day.isoformat() if lt.publishable(effective_of(row)) else ""


def end_day_of(row: Mapping[str, str]) -> date:
    """`end_day` over a delistings.csv row: its last trade date, else its delist date."""
    return end_day(of_row(row), row["delist_date"])


# -- what stage 9g read for a continuation -----------------------------------------------------------------------
@dataclass(frozen=True)
class ContinuationReading:
    """What stage 9g (`continuation_evidence`) read for one continuation, the verdict's input beside the tables
    (run_manifest.json's `continuation_filings` records it; `run_snapshot.RunSnapshot.continuations` reads it back).
    `filing`: `"<form> <accession>"` of the filing whose text states the exchange one for one, for a continuation
    the continued-filings rule or timing linked; `doubt`: why the registrant's own filings contradict an 8-K12B
    continuation (`ratio:0.9042`, `cash`)."""
    filing: str = ""
    doubt: str = ""
