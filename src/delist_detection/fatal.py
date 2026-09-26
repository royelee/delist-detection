"""The exceptions that stop a run instead of becoming a review row.

A refusal (SEC's 403/429 `EdgarBlocked`, OpenFIGI's 401/403 `OpenFigiBlocked`)
or OpenFIGI down after its retries (`OpenFigiUnavailable`) says nothing about
one security: every later request would fail the same way. Every catch site
that turns a per-security failure into a row -- the pipeline's delisting
search and payout stages, `listing_status.listing_answers`, the prefetch pool
-- re-raises `FATAL` first, and the CLI turns it into its exit code. A new
fatal exception is added here only.
"""
from __future__ import annotations

from .edgar import EdgarBlocked
from .openfigi import OpenFigiBlocked, OpenFigiUnavailable

FATAL: tuple[type[BaseException], ...] = (EdgarBlocked, OpenFigiBlocked, OpenFigiUnavailable)
