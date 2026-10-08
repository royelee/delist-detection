"""The clients' optional capabilities, declared once for the run's `Clients` seam (pipeline.py).

A capability is something a stage asks a client for that an adapter of that client may not offer. Each adapter
states it either way under the capability's attribute: the capability itself, or `None` (for a flag, `False`) when
the adapter offers none, as Python's own `__hash__ = None` states an object unhashable. There is no third way: an
adapter that states nothing is refused where the statement is read (`Undeclared`), so a double that leaves a
method out can no longer turn a stage's rule off unseen. `pipeline.run` logs each absent capability once, with
what the run goes without; production's adapters (`pipeline.default_clients`) offer every one.

- **EDGAR full-text search** (`edgar.full_text_search`, a `FullTextSearch`): `edgar.EdgarClient` offers it. A
  fixture double whose fixture recorded no searches states it absent; then stage 4b finds no other registrant's
  8-K12B, stages 8b and 9 search no successor's 8-K12B, stage 9b reads only the successor issuer's own filing list
  and stage 10e gives a placeholder without a ticker tier no ticker evidence.
- **The LLM extractor's named call** (`llm_extractor.names_security`, a flag): `extract(record,
  security_name=...)` names the target security in the prompt (prompt v3), and stage 8 fills those calls ahead on
  the worker threads. `llm_merger_extractor.LLMMergerTermsExtractor` offers it. An extractor that states it absent
  is called as `extract(record)` and never filled ahead.

Every other read a stage makes of a client is required of each of its adapters, with nothing to state: EDGAR's
`submissions`, `recent_filings`, `fetch_filing_text`, `fetch_filing_raw` and `company_tickers`; the resolver's
`flush` and `shadow`; the classifier's `shadow`; the Nasdaq halt feed's `failed_days`. The resolver and the
classifier state the issuer record they read through as `issuers` (None: none of their own), and an LLM client the
model it calls as `model` (None: it names none); neither is a capability a stage goes without."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class FullTextSearch(Protocol):
    """EDGAR full-text search (`edgar.EdgarClient.full_text_search`): the hits for `q` within `forms` filed in
    [`lo`, `hi`], of `ciks`' own filings when given."""

    def __call__(self, q: str, forms: str, lo: date, hi: date, *, ciks: Sequence[int] = ()) -> list[dict]: ...


@dataclass(frozen=True)
class Capability:
    """One optional capability: the `Clients` field whose adapter states it, the attribute it is stated under, and
    what the run goes without when it is absent (the run log's line)."""
    client: str
    attribute: str
    without: str

    @property
    def name(self) -> str:
        return f"{self.client}.{self.attribute}"


class Undeclared(TypeError):
    """An adapter that states nothing about a capability of its client."""


FULL_TEXT_SEARCH = Capability(
    "edgar", "full_text_search",
    "no EDGAR full-text search: the line follow (4b) finds no other registrant's 8-K12B, stages 8b and 9 search no "
    "successor's 8-K12B, the handoffs (9b) read only the successor issuer's own filing list, and a placeholder "
    "without a ticker tier gets no ticker evidence (10e)")
NAMED_LLM_CALL = Capability(
    "llm_extractor", "names_security",
    "the LLM extractor is called without the target security's name, and its calls are not filled ahead on the "
    "worker threads (stage 8)")
CAPABILITIES = (FULL_TEXT_SEARCH, NAMED_LLM_CALL)


def stated(adapter: Any, capability: Capability) -> Any:
    """What `adapter` states of `capability`: the capability, or None (False for a flag) when it offers none. An
    adapter that states nothing is refused (`Undeclared`)."""
    try:
        return getattr(adapter, capability.attribute)
    except AttributeError:
        raise Undeclared(f"{type(adapter).__name__} states nothing about {capability.name}: give it "
                         f"`{capability.attribute}`, or set `{capability.attribute}` to None to state it absent") \
            from None


def offers(adapter: Any, capability: Capability) -> bool:
    """Whether `adapter` offers `capability` (no adapter offers none)."""
    return adapter is not None and stated(adapter, capability) not in (None, False)
