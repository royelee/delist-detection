"""What a run publishes, as rows: every table's format and the write (store), the review rows a stage raises and
their triage (review_triage, degraded), the manifest and its SEC meter (manifest), an ending's value (dlret), the
delisting's record and its delistings.csv row (reconstruction), the price round trip (price_requests), the
contract's rows and value cells (contract, payout_rule), the verdicts (verdict), and the run snapshot that reads a
run back (run_snapshot).

Every stage writes into it, and it imports no stage: only the vocabulary and the sources' plumbing (atomic writes,
the request counters), never a client."""
