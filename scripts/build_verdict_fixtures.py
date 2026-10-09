"""Build tests/fixtures/verdicts/ from the committed output/ and the local caches, once (sub-plan 5i): the real cases
whose verdicts tests/test_verdict_cases.py recomputes offline (spec ruling 2.3, `verdict`'s rulings, and stage 9g's
`continuation_evidence`).

  PYTHONPATH=src python scripts/build_verdict_fixtures.py        # -> tests/fixtures/verdicts/

Offline: every SEC request is refused (scripts/build_form25_fixtures.py's guard). It reads output/ as one run
snapshot (`run_snapshot.RunSnapshot`) and writes:

- cases.json: for each case (tests/verdict_cases.py's CASES), the rows of output/'s securities, ticker_history,
  delistings, observation_map and review tables for the case's securities and the successors their endings name,
  the uncertain.csv rows the committed run gave them (the verdicts before 5i), and stage 9g's readings of those
  rows as run_manifest.json recorded them (`continuation_filings`);
- edgar.json.gz: what stage 9g's readings of the cases' continuations asks of EDGAR (each CIK's filings and names, and
  every filing text it reads), recorded through the cached client by the harness's replay (`verdict_cases.readings`).
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import build_form25_fixtures  # noqa: E402,F401  (refuses every SEC request on import)
import verdict_cases as vc  # noqa: E402
from delist_detection.sources.edgar import EdgarClient  # noqa: E402
from delist_detection.outputs.run_snapshot import RunSnapshot, continuation_entries  # noqa: E402


class RecordingEdgar:
    """The cached client, recording the answers stage 9g's readings take."""

    def __init__(self, inner: EdgarClient) -> None:
        self.inner = inner
        self.filings: dict[str, list[dict]] = {}
        self.subs: dict[str, dict] = {}
        self.texts: dict[str, str] = {}

    def recent_filings(self, cik):
        got = self.inner.recent_filings(cik)
        self.filings[str(int(cik))] = [asdict(f) for f in got]
        return got

    def submissions(self, cik, **kw):
        sub = self.inner.submissions(cik, **kw)
        if isinstance(sub, dict):
            self.subs[str(int(cik))] = {"name": sub.get("name", ""), "formerNames": sub.get("formerNames", [])}
        return sub

    def fetch_filing_text(self, cik, accession, primary_doc):
        text = self.inner.fetch_filing_text(cik, accession, primary_doc) if (
            ROOT / "cache/edgar/text" / f"{accession.replace('-', '')}.txt").exists() else ""
        self.texts[accession] = text
        return text


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    t = RunSnapshot.read(ROOT / "output")
    edgar = RecordingEdgar(EdgarClient(cache_dir=ROOT / "cache/edgar", sleep=lambda s: None, today=vc.AS_OF))
    out: dict[str, dict] = {}
    for case in vc.CASES:
        ids = set(case.sec_ids)
        ids |= {r["successor_sec_id"] for r in t.delistings if r["sec_id"] in ids and r["successor_sec_id"]}
        out[case.name] = {name: [r for r in t.table(name) if r["sec_id"] in ids] for name in vc.TABLES}
        out[case.name]["uncertain_before"] = [r for r in t.uncertain if r["sec_id"] in ids]
        out[case.name]["continuation_filings"] = continuation_entries(
            {k: r for k, r in t.continuations.items() if k[0] in ids})
        vc.readings(out[case.name], edgar)          # records what stage 9g reads for the case's rows
    target = ROOT / "tests/fixtures/verdicts"
    target.mkdir(parents=True, exist_ok=True)
    (target / "cases.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    with gzip.open(target / "edgar.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"filings": edgar.filings, "submissions": edgar.subs, "texts": edgar.texts}, fh, sort_keys=True)
    print(f"{len(out)} cases, {len(edgar.texts)} texts -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
