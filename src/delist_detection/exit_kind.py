"""The contract's view of one delistings.csv row (spec: Delist Library Reset,
"delistings · one row per ended security"; decisions 9 and 12): its exit kind,
drop reason, whether it is a continuation, and its value split into a measured
`dlret` and a `dlret_fill`.

Today's bucket and CRSP code map to `exit_kind` and `drop_reason`: a bankruptcy
delisting (the classifier's code 470, today's `liquidation` bucket) is `dropped`
for `bankruptcy`; a compliance failure is `dropped` for the reason its code
names; `unknown` asserts no kind. A successor other than the security itself is
a continuation (decision 9). A cash or stock consideration or a recovery is
measured; a Shumway mark, assumed par and a transfer's 0.0 are fills; a
continuation has neither. contract/delistings.csv, the golden judge and the
scorecard all read a row through `ending_fields`, so they see the same values.
Pure, on string rows as store.read_table returns them."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
MEASURED_METHODS = frozenset({"cash_only", "stock_only", "cash_plus_stock", "recovery_ratio", "worthless"})
FILL_METHODS = frozenset({"assumed_par", "shumway_nyse_amex", "shumway_nasdaq", "exchange_transfer_zero"})


@dataclass(frozen=True)
class EndingFields:
    exit_kind: str           # one of EXIT_KINDS, or "" when the row asserts none (today's `unknown`)
    drop_reason: str         # one of DROP_REASONS on a `dropped` row whose code names one, else ""
    continuation: bool
    dlret: str               # the measured value as delistings.csv writes it, or ""
    dlret_fill: str          # the fill as delistings.csv writes it, or ""


def is_continuation(row: Mapping[str, str]) -> bool:
    """A successor other than the security itself: the same holders own it now."""
    return bool(row["successor_sec_id"]) and row["successor_sec_id"] != row["sec_id"]


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
    """The contract's columns for one delistings.csv row."""
    kind, reason = _kind(row)
    cont = is_continuation(row)
    method, value = row["dlret_method"], row["dlret"]
    return EndingFields(kind, reason, cont,
                        value if method in MEASURED_METHODS and not cont else "",
                        value if method in FILL_METHODS and not cont else "")


def is_distress(row: Mapping[str, str]) -> bool:
    """A liquidation, or a drop for a reason that carries a harsh mark: every
    drop reason but a move to OTC or going private. A drop whose code names no
    reason counts, as today's compliance_failure bucket always did."""
    f = ending_fields(row)
    return f.exit_kind == "liquidation" or (f.exit_kind == "dropped" and f.drop_reason not in NOT_DISTRESS)
