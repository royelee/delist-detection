"""The line after a CUSIP change that stage 4b refuses is a line of the run (seeds-only parity, S2).

Stage 4b (`line_follow.follow_lines`) follows a security past its observations across a CUSIP change when the old
registrant carries on. When another registrant took over (`merged_out`, `other_registrant`), or the new rows do not
name the issuer's name in force after the step (`name`), it refuses the step, and the line after it belongs to
nobody: a full run has it because the caller kept observing it, a seeds-only run has no observation in it.
`identify_with_lines` gives the line to the run as an era of its own: it asks the identity stage again with the
refused steps whose new rows still name the old line's issuer (`derivable`), so `identity.refine_eras` keeps those
parts as eras whose one observation is derived (`Observation.derived`), until a round refuses no further step.
Everything after the stage sees an ordinary era-born security.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Callable

from ..filings.evidence import names_until
from ..vocabulary.names import description_names_issuer
from .identity import NOT_MADE, Identity, identify
from .line_follow import SWITCH, LineMemo, Lines, RefusedStep, follow_lines
from .observations import DerivedFrom, ObservationIndex
from .security_master import Security

MAX_DERIVE_ROUNDS = 3        # rounds that add derived lines: a derived line whose own next step is refused too is a round
DERIVABLE = frozenset({"merged_out", "other_registrant", "name"})     # the refusals a derived line may follow


def old_line_names(security: Security, profile: Mapping | None, step_first: str) -> list[str]:
    """The names the refused step's old line was known by: its eras' observed names, and every EDGAR name its issuer
    carried until the day before the step (`evidence.names_until`: a name it took after the step is the new line's)."""
    day = date.fromisoformat(step_first) - timedelta(days=1)
    edgar = names_until(profile, day) if isinstance(profile, Mapping) else []
    return list(dict.fromkeys([*(n for e in security.eras for n in e.names), *edgar]))


def derivable(refused: Sequence[RefusedStep], securities: Mapping[str, Security],
              profile: Callable[[int], Mapping | None]) -> dict[tuple[str, str], DerivedFrom]:
    """The (ticker, new CUSIP) pairs of the refused steps whose line is derived, each with the step it came from
    (`DerivedFrom`: the refused security's id and issuer CIK, the refusal, the step's old CUSIP and first day; the first
    step that names a pair wins): a switch refused for one of `DERIVABLE` whose new rows' descriptions name the old
    line's issuer (`description_names_issuer` against `old_line_names`), for each ticker of the security's eras (spelled
    as the eras spell it, `BF-B`; a ticker the line follow learned from the fails files is in their spelling and names
    no era)."""
    out: dict[tuple[str, str], DerivedFrom] = {}
    for r in refused:
        s = securities.get(r.sec_id)
        if s is None or r.why not in DERIVABLE or r.step.kind != SWITCH:
            continue
        names = old_line_names(s, profile(s.issuer_cik) if s.issuer_cik is not None else None, r.step.first)
        if any(description_names_issuer(d, n) for d in r.step.descriptions for n in names):
            origin = DerivedFrom(r.sec_id, s.issuer_cik, r.why, r.step.old_cusip, r.step.first)
            for t in {e.ticker for e in s.eras}:
                out.setdefault((t, r.step.new_cusip), origin)
    return out


def identify_with_lines(index: ObservationIndex, clients: Any, *, as_of: date, limit: int | None = None,
                        log: Callable[[str], None] = lambda *_: None, workers: int = 1,
                        meter: Any = None) -> tuple[Identity, Lines]:
    """Stages 1 to 4b with the derived lines: `identify` and `follow_lines`, again with the lines the last round
    refused that `derivable` gives, over the same fails index (`Identity.ftd`, opened once), until a round adds no
    line or `MAX_DERIVE_ROUNDS` rounds have added one. A repeat round's stage 4b takes what the round before read about
    each line's end (`LineMemo`) and reads again only for a line that changed. Returns the last round's identity and lines."""
    derive: dict[tuple[str, str], DerivedFrom] = {}
    verdicts: Mapping[tuple[str, str], str] = {}
    ftd = None
    memo = LineMemo()          # what stage 4b read about each line's end: a repeat round asks only about a line that changed
    for round_no in range(MAX_DERIVE_ROUNDS + 1):
        identity = identify(index, clients, as_of=as_of, limit=limit, log=log, workers=workers, meter=meter,
                            derive=dict(derive), ftd=ftd, verdicts=verdicts)
        verdicts = identity.verdicts          # what the identity stage found about the derived eras goes to the next
        lines = follow_lines(identity, clients, as_of=as_of, log=log, meter=meter, memo=memo)
        ftd = identity.ftd
        new = {pair: origin for pair, origin in derivable(lines.refused, lines.securities,
                                                          clients.issuers.profile).items()
               if pair not in derive and verdicts.get(pair) != NOT_MADE}
        if not new:
            break
        if round_no == MAX_DERIVE_ROUNDS:
            log(f"derived lines: {len(new)} more steps refused after {MAX_DERIVE_ROUNDS} rounds, not derived")
            break
        derive.update(new)
        log(f"derived lines: round {round_no + 1} derives {len(new)} (ticker, CUSIP) pairs")
    return identity, lines
