"""output/disputes.csv (FB-011): what the truth files dispute in one run, as rows a caller can join to the contract.

One row per checked field that a truth case of `data/scorecard.json`'s truth files fails on the run: the golden
lifecycles, the decision-17 audit and the diagnosis truth set, a failing `pass` case and a `known_wrong` case alike.
The rows come from the judgements the scorecard's G, A and D lines count (`truth.judge_all`,
`diagnosis_truth.judge_all`): their `Mismatch`es, judged by the same judges, never by another rule.

The verdict never reads the truth files (it states what the run's evidence supports; `V.audit.confirmed_but_wrong`
measures how often that is wrong), and disputes.csv is where a caller finds what the truth files dispute. It is
regenerated each run, so a fixed case drops out; header-only when nothing is disputed. It is not a contract file
(no schema_version change), and nothing in measurement reads it back.

Columns: `sec_id` is the security the judge resolved (a diagnosis case's own, a golden or audit case's security on its
ticker and date), blank when it found none; `last_trade_date` that security's contract/delistings.csv day, blank when
it has no contract row; `truth_file` the file as data/scorecard.json names it; `case`, `field`, `truth` and `library`
the case id and the `Mismatch`. Sorted by sec_id, truth_file, case, field (the table's key). Pure."""
from __future__ import annotations

from collections.abc import Sequence

from . import truth
from .diagnosis_truth import LibraryRows, judge_all as judge_diagnosis
from .lifecycle import LifecycleView
from .scorecard import ScorecardConfig
from ..outputs import store
from ..outputs.run_snapshot import RunSnapshot


def dispute_rows(snapshot: RunSnapshot, config: ScorecardConfig) -> list[dict[str, str]]:
    """One row per mismatch of every truth case of `config` against the run `snapshot` (module docstring). A
    diagnosis set is judged only when the run has a contract with payout columns, as the D lines are."""
    contract = {r["sec_id"]: r for r in (snapshot.contract_delistings or [])}
    view = LifecycleView(snapshot)
    rows: list[dict[str, object]] = []

    def add(file: str, resolve, judgements: Sequence[truth.Judgement]) -> None:
        for j in judgements:
            for m in j.mismatches:
                rows.append({"sec_id": resolve(j), "last_trade_date": contract.get(resolve(j), {}).get("last_trade_date", ""),
                             "truth_file": file, "case": m.case_id, "field": m.field, "truth": m.truth,
                             "library": m.library})

    on_ticker = lambda j: view.security_on(j.case.ticker, j.case.on) or ""
    add(config.golden_name, on_ticker, truth.judge_all(config.golden, view))
    add(config.audit_name, on_ticker, truth.judge_all([c for c in config.audit if not c.pending], view))
    if config.diagnosis and snapshot.contract_delistings is not None:
        lib = LibraryRows.of(snapshot)
        # a case whose security the run lacks has a `sec_id` mismatch: the judge resolved no security
        add(config.diagnosis_name, lambda j: "" if any(m.field == "sec_id" for m in j.mismatches) else j.case.sec_id,
            judge_diagnosis(config.diagnosis, lib))
    return store.formatted("disputes", rows)
