"""The sources: the clients of SEC EDGAR, the SEC data files (fails-to-deliver, MIDAS, the company-name index),
OpenFIGI, the Nasdaq halt feed and the LLM, the files read from them, and their plumbing: the one SEC request path
and its rate limit, the retry loop, the request counters, the settings, atomic file writes, the warm pass, the
exceptions that stop a run and the clients' declared capabilities. Imports the vocabulary only."""
