"""Build tests/fixtures/verdicts/ from the committed output/ and the local caches, once (sub-plan 5i): the real cases
whose verdicts tests/test_verdict_cases.py recomputes offline (spec ruling 2.3, `verdict_rules`, and stage 9f's
`continuation_evidence`).

  PYTHONPATH=src python scripts/build_verdict_fixtures.py        # -> tests/fixtures/verdicts/

Offline: every SEC request is refused (scripts/build_form25_fixtures.py's guard). It writes:

- cases.json: for each case (tests/verdict_cases.py's CASES), the rows of output/'s securities, ticker_history,
  delistings, observation_map and review tables for the case's securities and the successors their endings name,
  and the uncertain.csv rows the committed run gave them (the verdicts before 5i);
- edgar.json.gz: what stage 9f's reading of the cases' continuations asks of EDGAR (each CIK's filings and names, and
  every filing text it reads), recorded through the cached client.
"""
from __future__ import annotations

import gzip
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import build_form25_fixtures  # noqa: E402,F401  (refuses every SEC request on import)
import verdict_cases as vc  # noqa: E402
from delist_detection.continuation_evidence import confirming_filing, needs_filing  # noqa: E402
from delist_detection.edgar import EdgarClient  # noqa: E402
from delist_detection.lifecycle import Tables  # noqa: E402

TABLES = ("securities", "ticker_history", "delistings", "observation_map", "review")


class RecordingEdgar:
    """The cached client, recording the answers stage 9f's reading takes."""

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


def main() -> int:
    t = Tables.read(ROOT / "output")
    rows = {name: getattr(t, name) for name in TABLES}
    edgar = RecordingEdgar(EdgarClient(cache_dir=ROOT / "cache/edgar", sleep=lambda s: None, today=vc.AS_OF))
    out: dict[str, dict] = {}
    for case in vc.CASES:
        ids = set(case.sec_ids)
        ids |= {r["successor_sec_id"] for r in t.delistings if r["sec_id"] in ids and r["successor_sec_id"]}
        out[case.name] = {name: [r for r in rows[name] if r["sec_id"] in ids] for name in TABLES}
        out[case.name]["uncertain_before"] = [r for r in t.uncertain if r["sec_id"] in ids]
        names = {r["sec_id"]: r["name"] for r in t.securities}
        for r in out[case.name]["delistings"]:
            if r["sec_id"] in names and needs_filing(r["reason"], r["sec_id"], r["successor_sec_id"]):
                days = [date.fromisoformat(d) for d in (r["last_trade_date"], r["delist_date"]) if d]
                confirming_filing(edgar, int(r["cik"]), days, names[r["sec_id"]])
    target = ROOT / "tests/fixtures/verdicts"
    target.mkdir(parents=True, exist_ok=True)
    (target / "cases.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    with gzip.open(target / "edgar.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"filings": edgar.filings, "submissions": edgar.subs, "texts": edgar.texts}, fh, sort_keys=True)
    print(f"{len(out)} cases, {len(edgar.texts)} texts -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
