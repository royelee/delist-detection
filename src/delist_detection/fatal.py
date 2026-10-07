"""The exceptions that stop a run instead of becoming a review row.

A refusal (SEC's 403/429 `EdgarBlocked`, OpenFIGI's 401/403 `OpenFigiBlocked`)
or OpenFIGI down after its retries (`OpenFigiUnavailable`) says nothing about
one security: every later request would fail the same way. Every catch site
that turns a failure into a row, a miss or a transient answer re-raises
`FATAL` first:
- the issuer record's reads (`issuer_record.IssuerRecord`: every read of an
  issuer's EDGAR record by the resolver, the classifier's name check and the
  pipeline's stages, and SEC's name index); a failed read there is unknown;
- the pipeline's delisting search (`_find_delistings`) and stage 8's payout
  extraction (`merger_value`);
- `listing_status.listing_answers`;
- the prefetch pool (`prefetch.warm`);
- the ticker resolver's company search (`TickerResolver._name_search`).
The CLI (`classify_universe.entry`) turns it into its exit code: 2 for a
refusal, 4 for an OpenFIGI outage. A new fatal exception is added here only.
"""
from __future__ import annotations

from .edgar import EdgarBlocked
from .openfigi import OpenFigiBlocked, OpenFigiUnavailable

FATAL: tuple[type[BaseException], ...] = (EdgarBlocked, OpenFigiBlocked, OpenFigiUnavailable)
