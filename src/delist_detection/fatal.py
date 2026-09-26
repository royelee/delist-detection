"""The exceptions that stop a run instead of becoming a review row.

A refusal (SEC's 403/429 `EdgarBlocked`, OpenFIGI's 401/403 `OpenFigiBlocked`)
or OpenFIGI down after its retries (`OpenFigiUnavailable`) says nothing about
one security: every later request would fail the same way. Every catch site
that turns a failure into a row, a miss or a transient answer re-raises
`FATAL` first:
- the pipeline's issuer-names read (`_issuer_names`), delisting search
  (`_find_delistings`) and payout extraction (`_extract_payouts`);
- `listing_status.listing_answers`;
- the prefetch pool (`prefetch.warm`);
- the ticker resolver's four EDGAR checks (`TickerResolver._fits_date`,
  `_name_search`, `_name_match_score`, `_validate_cik`).
The CLI (`classify_universe.entry`) turns it into its exit code: 2 for a
refusal, 4 for an OpenFIGI outage. A new fatal exception is added here only.
"""
from __future__ import annotations

from .edgar import EdgarBlocked
from .openfigi import OpenFigiBlocked, OpenFigiUnavailable

FATAL: tuple[type[BaseException], ...] = (EdgarBlocked, OpenFigiBlocked, OpenFigiUnavailable)
