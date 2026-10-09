"""Sub-plan 5i's real cases (tests/fixtures/verdicts/, scripts/build_verdict_fixtures.py) and the harness that
recomputes their verdicts offline. Each case is a run snapshot in miniature: the committed run's rows for the case's
securities and stage 9g's readings as the run recorded them (`continuation_filings`, run_manifest.json's entries for
those rows), read as one `run_snapshot.RunSnapshot`, then `verdict.decide`. Stage 9g itself (the confirming filing,
the contradicting ratio, over each continuation's own-share reading at its anchor) is replayed from the recorded
EDGAR answers by `readings`, which the tests hold to the recorded entries."""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from delist_detection.endings.continuation_evidence import needs_doubt_check, needs_filing, read_continuation
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.vocabulary.exit_kind import ContinuationReading, of_row
from delist_detection.endings.last_trade import anchor_day
from delist_detection.endings.own_shares import Reader
from delist_detection.outputs.run_snapshot import RunSnapshot, continuation_readings
from delist_detection.outputs.verdict import Verdicts, decide

AS_OF = date(2026, 9, 25)
FIXTURES = Path(__file__).parent / "fixtures" / "verdicts"
TABLES = ("securities", "ticker_history", "delistings", "observation_map", "review")


@dataclass(frozen=True)
class Case:
    name: str
    sec_ids: tuple[str, ...]


CASES = (
    # a relabel the matched Form 25 settles (theme 1), and its guards
    Case("PRE", ("BBG000BBBP59",)), Case("WMG", ("BBG000C7B169",)),
    Case("MDRX", ("BBG000BLDXH5",)), Case("FCL", ("BBG000BM1RP0",)), Case("EQC", ("BBG000BLG1L7",)),
    # a successor registration confirms a continuation (themes 2 and 6a), and its guards
    Case("BHI", ("BBG000BD4VG8",)), Case("CHTR", ("BBG000PYZSR8",)), Case("GOOGL", ("BBG000BHSKN9",)),
    Case("SIRI", ("BBG000BT0093",)),
    # stage 9g: an 8-K item 3.03 that states the exchange one for one (theme 7), and its guards
    Case("APA", ("BBG000BC2C10",)), Case("CMCSK", ("BBG000BFTJ91",)), Case("LSXMA", ("BBG00BFHD827",)),
    Case("DVMT", ("BBG00DJ2LJF5",)), Case("HHC", ("BBG000MJRJJ2",)), Case("HUB-B", ("CIK48898-CLASS-B",)),
    # the matched Form 25's filer as issuer evidence (theme 3), and its guards
    Case("EA", ("BBG000BP0KQ8",)), Case("BTU", ("BBG000FW00S1",)), Case("SPB", ("BBG000P4BQM9",)),
    Case("CHK", ("BBG00Z6DX554",)), Case("CBL", ("BBG000B9YSK6",)),
    # an unpriced gate (theme 4), and its guards
    Case("GRUB", ("BBG001KWG293",)), Case("MDP", ("BBG000BNVNY4",)), Case("PNRA", ("BBG000G6BN50",)),
    # stale seeds after a confirmed ending (theme 5), and its guard
    Case("BOL", ("BBG000BDLLR9",)), Case("AT", ("CIK65873-COMMON",)), Case("CDWC", ("BBG000BHD665",)),
    Case("MEL", ("BBG000BNXLK1",)), Case("FRK", ("BBG000BJV732",)),
    # no ending at all (the closed_no_event gap), and an added acquirer
    Case("WW", ("BBG000DY6735",)), Case("NCRA", ("CIK1308161-CLASS-A",)), Case("AZN", ("BBG000BZ0DK8",)),
)


class FixtureEdgar:
    """The recorded EDGAR answers stage 9g's readings take (edgar.json.gz)."""

    def __init__(self, data: dict) -> None:
        self.data = data

    def recent_filings(self, cik):
        return [EdgarSubmission(**f) for f in self.data["filings"].get(str(int(cik)), [])]

    def submissions(self, cik, **kw):
        return self.data["submissions"].get(str(int(cik)))

    def fetch_filing_text(self, cik, accession, primary_doc):
        return self.data["texts"].get(accession, "")


def load() -> tuple[dict, FixtureEdgar]:
    cases = json.loads((FIXTURES / "cases.json").read_text())
    with gzip.open(FIXTURES / "edgar.json.gz", "rt", encoding="utf-8") as fh:
        return cases, FixtureEdgar(json.load(fh))


def snapshot_of(case: dict) -> RunSnapshot:
    """The case as a run snapshot: its rows and stage 9g's recorded readings, on the run date."""
    return RunSnapshot.of({name: case[name] for name in TABLES}, as_of=AS_OF,
                          continuations=continuation_readings(case["continuation_filings"]))


def reading(r: dict, security: dict, reader: Reader):
    """A delistings row's own-share reading, as stage 9g makes it (`own_shares.of`): at the row's anchor (its last
    trade, else its Form 25's filing date, else its delisting date: `last_trade.anchor_day`), of the security's
    class."""
    day = anchor_day(of_row(r), r["delist_date"], filed=r["delist_filing_date"] or None)
    return reader.ending(int(r["cik"]), share_class=security["share_class"], name=security["name"], day=day)


def readings(case: dict, edgar) -> dict[tuple[str, str], ContinuationReading]:
    """Stage 9g replayed over the case's rows from the recorded EDGAR answers (pipeline._continuation_filings, from
    the table rows): the oracle the recorded `continuation_filings` are held to, and the reads the fixture builder
    records."""
    secs = {r["sec_id"]: r for r in case["securities"]}
    names = {sid: r["name"] for sid, r in secs.items()}
    reader = Reader(edgar, IssuerRecord(edgar, today=AS_OF))
    out = {}
    for r in case["delistings"]:
        if r["sec_id"] in names and (needs_filing(r["reason"], r["sec_id"], r["successor_sec_id"])
                                     or needs_doubt_check(r["reason"], r["sec_id"], r["successor_sec_id"])):
            found = read_continuation(reading(r, secs[r["sec_id"]], reader), r["reason"], r["sec_id"],
                                      r["successor_sec_id"], [names.get(r["successor_sec_id"], "")])
            if found.filing or found.doubt:
                out[(r["sec_id"], r["delist_date"])] = found
    return out


def verdicts(case: dict) -> Verdicts:
    """The case's verdicts, a function of its snapshot. A placeholder's ticker evidence (stage 10e, which the run
    records nowhere) is read back from the committed verdicts (one without `placeholder_without_ticker_filing` had
    it)."""
    no_ev = {r["sec_id"] for r in case["uncertain_before"]
             if r["kind"] == "security" and "placeholder_without_ticker_filing" in r["reason"]}
    evidence = {r["sec_id"]: "" if r["sec_id"] in no_ev else "tier:recorded" for r in case["securities"]
                if r["figi_source"] == "placeholder"}
    return decide(snapshot_of(case), evidence)
