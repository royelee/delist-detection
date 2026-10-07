"""Rewrites (CONTEXT.md): the one owner of a delisting's kind and successor after its record is built (architecture
step 3).

The finder (stage 5) builds each delisting with the classifier's kind. Later rules change it: the finder's own R7
(the issuer moved the class) and its continued transfers, stage 8b's R1, stage 9's successor links and the line
continuation, the clip check before the handoffs (a delisting that did not end its security), stage 9b's handoffs and
stage 9e's bankruptcy plan and price deficiency. Every one of them goes through this module, which:

- names the rule that decided the rewrite (`Rule`, a closed set) and records it on the delisting as typed provenance
  (`Delisting.rewrites`, one `Rewrite` each: the kind before, the successor, how it was found, the evidence), so no
  in-run reader parses a reason for it;
- sets the CRSP code and the bucket together (`CONTINUATION_CODE` for every continuation, `crsp_codes.bucket_for_code`
  for any other kind);
- drops what the new kind cannot carry, by one rule. A continuation carries no no-evidence default, no open successor
  (`SUCCESSOR_UNKNOWN`), no payout or terms-gate flag (`PAYOUT_FLAGS`) and no payout read: its merger value is
  dropped with one call (`MergerValues.drop`, the `payouts` argument; a merger made a continuation without it is
  refused). Any kind that is no longer `unknown` drops the no-evidence default.

A delisting that did not end its security (`security_goes_on`) is its own successor and keeps its kind and its value:
a holding company's merger the security traded through is still a merger row (DIS 2019, WRK 2018).

The interface: `continuation`, `security_goes_on`, `mark_going_on`, `reclassify`; the readings `awaits_successor`,
`is_real_ending`, `successor_by`, `rewrite_by` and the reason note `successor_note`. Pure, over the in-memory
delisting (`delistings.Delisting`); the published tables keep their columns and their text."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from .crsp_codes import CONTINUATION_CODE, CrspBucket, bucket_for_code

if TYPE_CHECKING:
    from .delistings import Delisting
    from .store import DelistingKey

# The review flag of an exchange transfer whose successor is not known yet (the finder's); a continuation drops it.
SUCCESSOR_UNKNOWN = "successor_unknown"
# The classifier's flag for an `unknown` ending it found no evidence for; any other kind drops it.
NO_EVIDENCE_DEFAULT = "no_evidence_default"
# The flags a merger's value raises (stage 8: the payout and terms gates, the acquirer's close, assumed par); a
# continuation has no value, so it carries none of them. Matched by flag name (`payout_gate_failed:87.69`).
PAYOUT_FLAGS = frozenset({"payout_gate_failed", "terms_gate_failed", "terms_gate_skipped", "llm_gate_failed",
                          "llm_election_package", "election_no_default", "merger_at_par", "acquirer_close_lagged"})
# The flags a continuation rule leaves on the row it made (published in review_flags).
R1_CONTINUATION, LINE_CONTINUATION = "r1_continuation", "line_continuation"
HANDOFF_CONTINUATION = "handoff_continuation"


class Rule(str, Enum):
    """The rule that decided a rewrite (the closed set; module docstring)."""
    ISSUER_MOVE = "issuer_move"            # stage 5, R7: the issuer's own Form 25 with its 8-A12B (Kraft Heinz 2026)
    CONTINUED = "continued"                # stage 5: a transfer the security traded through (`_continued`)
    TRADES_ON = "trades_on"                # stage 9b's first step: the clip check says it did not end the security
    R1 = "r1"                              # stage 8b: one share, no cash, into a new or the same issuer
    LINE_FOLLOW = "line_follow"            # stage 9: stage 4b's line successor (and the line continuation, GTES 2026)
    SUCCESSOR_LINK = "successor_link"      # stage 9: a security of the run, the R1 terms, the own registration, 8-K12B
    HANDOFF = "handoff"                    # stage 9b: a continuation the ticker's handoff shows
    PLAN_BANKRUPTCY = "plan_bankruptcy"    # stage 9e: an `unknown` Form 25 whose notice says new shares, a bankruptcy
    PRICE_DEFICIENCY = "price_deficiency"  # stage 9e: a compliance failure the exchange removed for its price (552)


@dataclass(frozen=True)
class Rewrite:
    """One rewrite of a delisting, as typed provenance: the rule, the kind before (`was_bucket`, `was_code`), the
    successor it set ("" when none), how the successor was found (`how`: stage 9's link names, "handoff", ...), what
    decided it (`evidence`: a handoff's "<form> <accession>" or "timing:cik", R1's statement, R7's filings) and, for a
    handoff, the successor's first sighting under the ticker (`successor_from`: stage 9c's cap)."""
    rule: Rule
    was_bucket: CrspBucket
    was_code: int | None
    successor: str = ""
    how: str = ""
    evidence: str = ""
    successor_from: str = ""


class Payouts(Protocol):
    """The payout side a continuation drops its reads from: stage 8's `merger_value.MergerValues`."""

    def drop(self, key: DelistingKey) -> None: ...


def _flag_name(flag: str) -> str:
    return flag.split(":", 1)[0]


def _record(d: Delisting, rule: Rule, **kw) -> Rewrite:
    rw = Rewrite(rule, d.record.bucket, d.record.crsp_code, **kw)
    d.rewrites.append(rw)
    return rw


def continuation(d: Delisting, successor: str, rule: Rule, *, reason: str | None = None,
                 confidence: str | None = None, flag: str | None = None, how: str = "", evidence: str = "",
                 successor_from: str = "", payouts: Payouts | None = None) -> Rewrite:
    """Make `d` a continuation into `successor` (another security, or the security itself), decided by `rule`.

    A delisting of another kind becomes an exchange transfer (CRSP `CONTINUATION_CODE`) and takes `reason` and
    `confidence`, both required then; an exchange transfer keeps its kind, and takes `reason` when given (a link's
    note, `successor_note`). Its flags lose the no-evidence default, `successor_unknown` and every payout flag, then
    gain `flag` (the rule's own, once); a merger's value is dropped (`payouts.drop`: required for a merger, whose
    reads a continuation cannot carry). Records and returns the `Rewrite`."""
    rec = d.record
    if rec.bucket is not CrspBucket.EXCHANGE_TRANSFER and (reason is None or confidence is None):
        raise ValueError(f"{d.key}: a {rec.bucket.value} made a continuation needs its own reason and confidence")
    if rec.bucket is CrspBucket.MERGER and payouts is None:
        raise ValueError(f"{d.key}: a merger made a continuation drops its payout reads: pass the run's merger values")
    rw = _record(d, rule, successor=successor, how=how, evidence=evidence, successor_from=successor_from)
    if rec.bucket is not CrspBucket.EXCHANGE_TRANSFER:
        rec.crsp_code, rec.bucket = CONTINUATION_CODE, CrspBucket.EXCHANGE_TRANSFER
    if confidence is not None:
        rec.confidence = confidence
    if reason is not None:
        rec.reason = reason
    rec.successor_sec_id = successor
    kept = [f for f in d.flags if f not in (NO_EVIDENCE_DEFAULT, SUCCESSOR_UNKNOWN)
            and _flag_name(f) not in PAYOUT_FLAGS]
    if flag is not None and flag not in kept:
        kept.append(flag)
    rec.evidence["flags"] = kept
    if payouts is not None:
        payouts.drop(d.key)
    return rw


def security_goes_on(d: Delisting, rule: Rule) -> Rewrite:
    """`d` did not end its security (`rule`: the finder's continued transfer, the clip check): the security is its own
    successor, and `d` keeps its kind and its value. Its open successor (`successor_unknown`) goes."""
    rw = _record(d, rule, successor=d.sec_id)
    d.record.successor_sec_id = d.sec_id
    d.record.evidence["flags"] = [f for f in d.flags if f != SUCCESSOR_UNKNOWN]
    return rw


def mark_going_on(delistings: Iterable[Delisting], endings: Mapping[DelistingKey, bool]) -> int:
    """The clip check's answer on the delistings (`Rule.TRADES_ON`): each merger or exchange transfer that `endings`
    says does not end its security (`pipeline._delisting_endings`: the DIS 2019 holding-company reorganization, WRK
    2018) goes on as itself. Only a blank successor is filled: one a search already found (MWV to WRK) stands, and a
    delisting `endings` says ends its security, or has no answer for, is untouched. Returns how many it marked."""
    marked = 0
    for d in delistings:
        if not d.record.successor_sec_id and endings.get(d.key) is False:
            security_goes_on(d, Rule.TRADES_ON)
            marked += 1
    return marked


def reclassify(d: Delisting, code: int, rule: Rule, *, reason: str, confidence: str | None = None) -> Rewrite:
    """Give `d` another kind that is no continuation (stage 9e): CRSP `code` and its bucket together, `reason`, and
    `confidence` when given. A delisting that leaves `unknown` drops the no-evidence default."""
    bucket = bucket_for_code(code)
    if bucket is CrspBucket.EXCHANGE_TRANSFER:
        raise ValueError(f"{d.key}: CRSP {code} is a continuation's code: use `continuation`")
    rw = _record(d, rule)
    rec = d.record
    if rec.bucket is CrspBucket.UNKNOWN and bucket is not CrspBucket.UNKNOWN:
        rec.evidence["flags"] = [f for f in d.flags if f != NO_EVIDENCE_DEFAULT]
    rec.crsp_code, rec.bucket, rec.reason = code, bucket, reason
    if confidence is not None:
        rec.confidence = confidence
    return rw


def successor_note(how: str, evidence: str = "") -> str:
    """The note a successor link adds to an existing reason ("; successor by same ticker", "; successor by handoff
    (timing:cik)"): the published reason's one wording of how a successor was found."""
    return f"; successor by {how.replace('_', ' ')}" + (f" ({evidence})" if evidence else "")


def awaits_successor(d: Delisting) -> bool:
    """An exchange transfer whose successor is not known yet (`successor_unknown`): what stage 9's links look for."""
    return SUCCESSOR_UNKNOWN in d.flags


def is_real_ending(d: Delisting) -> bool:
    """`d` ended its security: its successor is not the security itself (`security_goes_on`)."""
    return d.record.successor_sec_id != d.sec_id


def rewrite_by(d: Delisting, rule: Rule) -> Rewrite | None:
    """The latest rewrite of `d` that `rule` decided, else None."""
    return next((rw for rw in reversed(d.rewrites) if rw.rule is rule), None)


def successor_by(d: Delisting) -> str:
    """How `d`'s successor was found, as the rewrite that set it recorded it ("" when none says)."""
    return next((rw.how for rw in reversed(d.rewrites) if rw.successor), "")
