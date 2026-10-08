"""The end-of-era resolver, first step (spec: Delist Library Reset, "The end-of-era
resolver (the R1.3 fix)"): what happened to a security whose registrant kept filing
periodic reports after the security stopped trading. The classifier used to call
every such case an exchange transfer (its continued-filings rule), and the reset-1
accuracy audit found most of them false: a merger target keeps filing for its debt,
a delisted company keeps filing from the OTC. The resolver reads the evidence
around the end first, in the spec's order:

1. still trading after the end (the delisting finder knows): today's transfer;
2. a successor registration (8-K12B, 8-K12G3): a transfer, its successor found later; a merger when the
   registrant's own-share statement changed the holders' stake (spec 5c rule 6: another ratio than one or a split
   factor, or cash: CHTR 2016's 0.9042 New Charter);
3. a change in control (8-K item 5.01): a merger;
4. a completed acquisition (8-K item 2.01) with a merger filing or a Form 25: a merger,
   unless a bankruptcy 8-K (item 1.03, its text confirmed by the classifier) came on
   or before it: a Chapter 11 asset sale is a liquidation (470; 5g sub-rule 2, built
   in sub-plan 5b);
   branches 3 and 4 never fire for a registrant that survived the transaction (`survived`,
   sub-plan 5c rule 1: its own shares were not exchanged, and it acquired another party
   or distributed another company's shares to its holders): the resolution goes on to 5;
5. a delisting notice (8-K item 3.01) whose text cites a listing deficiency: a
   compliance failure;
   5b. a delisting notice (8-K item 3.01) whose 8-K announces a liquidating distribution,
   a liquidating trust or a plan of liquidation or dissolution: a liquidation (400;
   sub-plan 5g, EQC 2025: the registrant kept filing to wind down);
6. otherwise the continued filings stand: today's transfer, reason unchanged.

Measured on the audit's 117 left-view truths (2026-10-02), today's rule is right on
the continuations only (about 32); this order is right on about 77. Pure, on EDGAR
filing lists; the classifier supplies the text answers (the 3.01 notices, the confirmed bankruptcy, the
own-share readings of rules 1 and 6), typed: a filing is a `Filed`, a statement an `exchange_terms.OwnExchange`."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

from .crsp_codes import CONTINUATION_CODE, CrspBucket
from .exit_kind import (CONTINUED, SUCCESSOR_FORMS, change_in_control_reason, completed_acquisition_reason, relabel,
                        successor_registration_reason)

if TYPE_CHECKING:
    from .edgar import EdgarSubmission
    from .exchange_terms import OwnExchange

ITEMS_BEFORE_DAYS, ITEMS_AFTER_DAYS = 30, 120          # 8-K items, successor filings, Form 25s around the end
MERGER_FILING_BEFORE_DAYS, MERGER_FILING_AFTER_DAYS = 540, 30
MERGER_FILING_FORMS = frozenset({"DEFM14A", "DEFM14C", "PREM14A", "SC 14D9", "SC TO-T", "SC TO-I", "SC 13E3",
                                 "425", "S-4"})
DELIST_FORMS = frozenset({"25-NSE", "25"})
MERGER_CODES = frozenset({200, 231, 233})
# The reasons a branch writes go through the row vocabulary (exit_kind: `CONTINUED`, `relabel` and the merger and
# successor wordings), which the finder, stage 9g, the verdict and the scorecard read back.


@dataclass(frozen=True)
class Filed:
    """A filing the era's evidence names: its form and its filing day. A reason prints it as "<form> <day>"
    ("8-K 2020-11-09"); the resolver compares its day, never a slice of that text."""
    form: str
    day: date

    def __str__(self) -> str:
        return f"{self.form} {self.day.isoformat()}"


@dataclass(frozen=True)
class EraSignals:
    trading_after: bool
    item_filed: Mapping[str, date] = field(default_factory=dict)   # 8-K item -> its first filing day in the window
    successor_filing: Filed | None = None     # the first 8-K12B/8-K12G3 in the window
    merger_filing: Filed | None = None        # the latest merger filing in its window
    delist_filing: Filed | None = None        # the first Form 25 in the window
    # the classifier's answers: the first 3.01 8-K citing a listing deficiency, the first 8-K in the window whose
    # item 1.03 text confirms a bankruptcy, the sentence that says the registrant acquired or distributed (rule 1,
    # 5c), the first 3.01 8-K announcing a liquidation (branch 5b, 5g), what the registrant's own shares became, read
    # where branch 2 decides (rule 6, `registers_successor`)
    deficiency_notice: Filed | None = None
    bankruptcy_filing: Filed | None = None
    survived: str = ""
    liquidation_notice: Filed | None = None
    successor_terms: OwnExchange | None = None


@dataclass(frozen=True)
class EraVerdict:
    branch: str                       # trading, successor, successor_merger, change_in_control, bankruptcy,
    crsp_code: int                    # completed_merger, delisting_notice, liquidation or continued_filings
    bucket: CrspBucket
    reason: str


def _day(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def signals(filings: Iterable[EdgarSubmission], on: date, *, trading_after: bool,
            deficiency_notice: Filed | None = None, bankruptcy_filing: Filed | None = None,
            liquidation_notice: Filed | None = None) -> EraSignals:
    """The evidence around a security's end date `on`: the items of every 8-K (not
    an 8-K12B/8-K12G3) filed in [on − ITEMS_BEFORE_DAYS, on + ITEMS_AFTER_DAYS], the
    first successor registration and Form 25 in that window, and the latest merger
    filing in [on − MERGER_FILING_BEFORE_DAYS, on + MERGER_FILING_AFTER_DAYS]. The
    classifier supplies the text checks: the deficiency notice, the confirmed
    bankruptcy 8-K and the liquidation notice in the item window."""
    lo, hi = on - timedelta(days=ITEMS_BEFORE_DAYS), on + timedelta(days=ITEMS_AFTER_DAYS)
    mlo, mhi = on - timedelta(days=MERGER_FILING_BEFORE_DAYS), on + timedelta(days=MERGER_FILING_AFTER_DAYS)
    item_filed: dict[str, date] = {}
    successor = merger = delist = None
    for f in sorted(filings, key=lambda f: f.filing_date):
        d = _day(f.filing_date)
        if d is None:
            continue
        if lo <= d <= hi:
            if f.form in SUCCESSOR_FORMS:
                successor = successor or Filed(f.form, d)
            elif f.form.startswith("8-K"):
                for item in sorted(f.item_set):
                    item_filed.setdefault(item, d)
            if f.form in DELIST_FORMS:
                delist = delist or Filed(f.form, d)
        if mlo <= d <= mhi and f.form in MERGER_FILING_FORMS:
            merger = Filed(f.form, d)
    return EraSignals(trading_after, item_filed, successor, merger, delist, deficiency_notice, bankruptcy_filing,
                      liquidation_notice=liquidation_notice)


def merges(s: EraSignals) -> bool:
    """Whether branch 3 or 4 would decide (a change in control, or a completed acquisition with a merger filing
    or a Form 25, and neither branch 1 nor branch 2 first): the only signals for which the classifier reads
    whether the registrant survived (`survived`)."""
    if s.trading_after or s.successor_filing:
        return False
    return "5.01" in s.item_filed or ("2.01" in s.item_filed and bool(s.merger_filing or s.delist_filing))


def registers_successor(s: EraSignals) -> bool:
    """Whether branch 2 would decide (a successor registration, and not still trading): the only signals for which
    the classifier reads what the registrant's own shares became (`successor_terms`, rule 6)."""
    return bool(s.successor_filing) and not s.trading_after


def resolve(s: EraSignals, items_code: int | None) -> EraVerdict:
    """The branch that decides (module docstring). `items_code` is the classifier's
    code for the window's 8-K item set (`_classify_items`); a merger keeps it when it
    is a merger code, else 231. Branch 2 is a merger (231, `successor_merger`) when
    the registrant's own-share statement read for it (`successor_terms`) changed the
    holders' stake: another ratio than one or a split factor, or cash (spec 5c rule 6,
    sub-plan 5f: CHTR 2016's 0.9042 New Charter; SIRI 2024's 0.1 is a consolidation)."""
    merger_code = items_code if items_code in MERGER_CODES else 231
    if s.trading_after:
        return EraVerdict("trading", CONTINUATION_CODE, CrspBucket.EXCHANGE_TRANSFER, CONTINUED)
    if s.successor_filing:
        own = s.successor_terms
        if own is not None and own.stake_changed:
            became = (f"each share became {own.ratio:g} shares {own.target[:60].strip()}"
                      f"{' and cash' if own.cash else ''}, a merger (rule 6)")
            return EraVerdict("successor_merger", 231, CrspBucket.MERGER,
                              successor_registration_reason(s.successor_filing, became))
        return EraVerdict("successor", CONTINUATION_CODE, CrspBucket.EXCHANGE_TRANSFER,
                          relabel(successor_registration_reason(s.successor_filing,
                                                                "the security continues under a successor")))
    if "5.01" in s.item_filed and not s.survived:
        return EraVerdict("change_in_control", merger_code, CrspBucket.MERGER,
                          change_in_control_reason(s.item_filed["5.01"]))
    if "2.01" in s.item_filed and (s.merger_filing or s.delist_filing):
        if s.bankruptcy_filing and s.bankruptcy_filing.day <= s.item_filed["2.01"]:
            return EraVerdict("bankruptcy", 470, CrspBucket.LIQUIDATION,
                              relabel(f"Bankruptcy ({s.bankruptcy_filing}, item 1.03) before the completed sale "
                                      f"(8-K item 2.01 filed {s.item_filed['2.01']})"))
        if not s.survived:             # a survivor acquired or distributed: no merger ending (rule 1, 5c)
            return EraVerdict("completed_merger", merger_code, CrspBucket.MERGER,
                              completed_acquisition_reason(s.item_filed["2.01"], s.merger_filing or s.delist_filing))
    if "3.01" in s.item_filed and s.deficiency_notice:
        return EraVerdict("delisting_notice", 570, CrspBucket.COMPLIANCE_FAILURE,
                          relabel(f"Listing deficiency notice ({s.deficiency_notice}), no merger evidence"))
    if s.liquidation_notice:
        return EraVerdict("liquidation", 400, CrspBucket.LIQUIDATION,
                          relabel(f"Liquidation: delisted while winding down ({s.liquidation_notice} announces a "
                                  f"liquidating distribution, trust or plan)"))
    return EraVerdict("continued_filings", CONTINUATION_CODE, CrspBucket.EXCHANGE_TRANSFER, CONTINUED)
