# Architecture: concept subpackages, imports one way

## Package layout and import direction

The package is laid out by concept (architecture step 16): nine subpackages and the run at the root.

```
src/delist_detection/
  __init__.py   lazy: `import delist_detection` loads none of its modules; the README's eight names load on first use
  pipeline.py   the run: observations in, the seven tables and the contract out, one function per stage
  vocabulary/   the leaves, each importing nothing of the package: identifiers, names, trading_calendar, crsp_codes,
                exchanges, exit_kind
  sources/      the SEC, OpenFIGI, Nasdaq and LLM clients and their plumbing: atomic_io, settings, retries,
                sec_limiter, sec_stats, fatal, html_text, edgar, sec_http, openfigi, cik_lookup, ftd, midas,
                nasdaq_halts, llm_client, prefetch, capabilities
  filings/      what SEC filings say, read by several stages: evidence, form25, listing_status, filing_search
  outputs/      what a run publishes, as rows: store, review_triage, degraded, manifest, run_snapshot, verdict,
                contract, dlret, payout_rule, price_requests, reconstruction
  identity/     a security's identity, stages 1 to 4c: observations, figi_resolution, security_master,
                ticker_resolver, issuer_record, issuer_in_force, identity, history, added_securities,
                ticker_evidence, line_follow, derived_lines, carried_price
  endings/      every delisting, found, dated and classified, stages 5 to 9g: delistings, trading_record, classifier,
                end_of_era, distress, exchange_terms, own_shares, continuation_evidence, last_trade, rewrites,
                registrants, successors, handoffs
  terms/        what one share of a merger ending became, stage 8: merger_value, payout_gate, payout_extractor,
                llm_merger_extractor, filing_selection, currency, acquirer_line, acquirers, acquirer_ticker
  measurement/  how far a published run is from the truth: lifecycle, scorecard, audit, truth, diagnosis_truth,
                truth_set, truth_build, truth_update, regression, loop_round
  handling/     delistings.csv for training and backtests: handling, qlib_adapter
```

Imports run one way, and `tests/test_import_closure.py` reads them from the real import graph (top level, inside a
function and under `TYPE_CHECKING`). The vocabulary imports nothing; sources import the vocabulary; filings and
outputs import sources; identity imports filings and outputs; endings import identity; terms import endings; each
also imports everything below what it names. measurement and handling import outputs and the vocabulary, and from
sources only the plumbing that loads no client (`atomic_io`, `sec_stats`), never a client. Nothing imports
`pipeline.py`. outputs sits below the stages because every stage writes into it (a review row, a delisting's key, a
value input, a price answer) while it reads none of them. Two imports break the direction, both type only, so they
load nothing: `outputs/dlret.py` names terms' `MergerTerms` (a `MergerInputs` carries the LLM's answer, which the
value rule reads) and `outputs/degraded.py` names endings' `Delisting` (the row it flags). The test lists them as
named exceptions and fails when one stops being type only.

## The hand-off object: DelistRecord

The `DelistRecord` dataclass (`outputs/reconstruction.py`) is the hand-off object from the classifier to the table
and the handling: `ticker, cik, observed_delist_date, crsp_code, bucket, confidence, reason, evidence`, plus
`sec_id`, `delist_date`, `successor_sec_id` (a continuation only) and `ticker_successor_sec_id` (a ticker takeover)
— optional fields the pipeline (`endings/delistings.py`/`pipeline.py`) fills in alongside the original ones.

## The run: pipeline.py

`pipeline.py`'s `run()` is the orchestration that turns a list of observations into the seven output tables: a short
`_run` calls one function per numbered stage (stages 1 to 4b are one call, `derived_lines.identify_with_lines`: the
rounds of `identity.identify` (stages 1 to 4: the eras, each era's issuer and FIGI, the securities and their CUSIPs, one
`identity.Identity` whose facts the later stages read) and `line_follow.follow_lines` described next, repeated with the
derived lines up to `MAX_DERIVE_ROUNDS` times over the one fails index; a run that refuses no derivable step makes one
round; each stage is metered once per round and the meter adds them up;
`line_follow.follow_lines` (stage 4b, one call over the `Identity`: each security's line followed past its
observations across a CUSIP or ticker change; the same security takes the new CUSIP and ticker,
a placeholder folds into the FIGI line its new CUSIP names, a FIGI line with another composite records a line
successor for stage 9; its `Lines` answer carries the review items of stages 1 to 4b; metered as "line follow"; sub-plan
5h's today-holder fold: a ticker-tier line whose
candidate holds the ticker today folds into its next CUSIP's composite when that composite left the ticker, CRC and
BTU, whose post-bankruptcy lines took the ticker), `_other_issuers` (stage 4c: the one CIK other than a
security's own that was its issuer in force on every sighting, `issuer_in_force.issuer_changes`; stage 5 reads its
Form 25s too; metered as "other issuers in force"), `_find_delistings` (stage 5: every security searched by
`delistings.DelistingFinder` over the contexts the finder builds itself, `delistings.SecurityContexts.observed`: each
security's trading record, `trading_record.TradingRecord`, over its observations, its own CUSIPs and the fails
index, with its issuer's securities as siblings, its other CIK in force and its issuer's lookup tier; the warm pass
and the sequential pass ask that one object, so both search one context; the records' sightings are the stage's
answer; FB-004 part b, `_search_security`: a security whose ending goes on as the security itself (`registrants.goes_on`)
and whose old registrant a new one replaced (`registrants.SuccessorRegistrants`: the 8-K12B/8-K12G3 search naming it) is
searched again with that registrant in force, whose Form 25s the finder reads from its registration and whose listing
is the listed-today answer, up to `MAX_REGISTRANTS`; the stage logs `successor registrants: N securities`, and
`_DelistingSearch.registrants` is what stage 10c3's issuer timeline and the open range's exchange read),
`_dead_before_sighting` (stage 5b: a security whose last real ending came before its
first observation and that has fewer than two trading fails rows on or before that ending and none from its first
observation on (one fails sighting makes no range; rows settling in between do not count: TRB 2007, FB-009) died
before the run's fails window began or showed it trading, so (eligibility decided first, then) the fails index is
asked for its tickers' rows over
[end − 1095 d, end + 10 d] (`FtdIndex.around`), it takes the CUSIPs `history.backfill_cusips` finds that no other
security holds (one an earlier security of the stage took included) and its sightings are rebuilt; it returns them
(`_Backfill`: CUSIPs and sightings) and `_run` merges them over stage 5's, so it changes no input; no `sec_id`
or issuer changes),
`_check_overrides`, `_last_trade_closes` (stage 7, a `_Closes` of two maps: the run's own close, a
`--last-trade-closes` row, else the fails close; and the one the value reads, the caller's answer to the
delisting's `last_close` request, `price_requests.PriceAnswers`, in its place), `_merger_values` (stage 8: one call
into `merger_value.value_mergers`, which answers one `MergerValue` per merger ending, its acquirer and requests on
the run's own closes; the module map has its steps), `_r1_continuations` (stage 8b: a merger whose published terms are one share and no cash (`exchange_terms.one_share_no_cash`, a special dividend set aside: `OwnShares.consideration`), whose registrant's filings say the same of its own shares (the ending's own-share reading, `own_shares.of`: the one the delisting carries, else one made at its anchor), into a new issuer (`own_shares.new_issuer`, `NEW_ISSUER_DAYS`) or the same issuer (`successors.successor_by_terms` over the reading's statement, else the new issuer's 8-K12B), is an exchange transfer to that successor, flagged `r1_continuation`, its payout reads dropped (`rewrites.continuation`, `Rule.R1`, with the run's merger values); the LLM's final terms must agree, unless the payout gate compared them with a close and refused them (`MergerValues.gate_failed`: FNFV 2017, whose terms were the Black Knight distribution's 0.3066; a gate that could not check them, `no_last_close`, `no_acq_price` or `no_ratio`, refused nothing: Paramount Global's class A 2025), when the statement's shares are a new issuer's (`OwnShares.target_issuer`) the run holds no security of, the row stays a merger whose terms are the statement's (`MergerValues.restate` with a `dlret.StatementTerms`: the ratio, the new issuer's EDGAR ticker and name, `OwnShares.new_issuer_entry`; a received close asked under that ticker, `lookup_name` its name; `terms_source` `registrant_statement`, `terms_gate` skipped, flag `terms_gate_skipped:own_statement`; FNFV 2017 into Cannae, FB-003), logged `R1 statements as merger terms`; the new issuer is named by the R1 statement's target (the name tie, `own_shares.names_target`), its 8-K12B candidate included; a degraded read, now or when the carried reading was made (`OwnShares.degraded`), keeps the merger and flags the row; the run logs `role refusal: N rows (...)`, the delistings whose end-of-era reading refused a merger on the registrant's role; metered as "R1 continuations"),
`_find_successors` (stage 9, with sub-plan 5c's `_terms_links` before the 8-K12B search, over the ending's own-share reading (`own_shares.of`): the same issuer's class, a new issuer, or the security's own same-CIK 8-K12B line via OpenFIGI and R2 (the CUSIP the reading's texts name); a name tie for any 8-K12B link; sub-plan 5h: `_own_registration_link` takes a text-named CUSIP with no fails row
yet when the fails data ends before the day, OKE 2026: the added successor starts on the next trading day, as every successor the run adds does (`last_trade.first_day_after`), and a Form 25 that already owns a delisting of the run raises no unmatched row in stage 9d; the stage ends by recording its links as rewrites, `_link_successors`; a merger row at the switch when stage 4b followed the step (the old registrant carries on: TEAM, LSXMA, FWONA) is linked and rewritten too, unless its payout reconciled with the last close), `_handoffs` (stage 9b: first `rewrites.mark_going_on` over `history.Histories.going_on`, the clip check's merger or transfer that does not end its security goes on as itself, here and only here, so the handoffs see it; then the handoffs), `_date_from_notices` (stage 9c: `last_trade.Dating.from_notice`, a handoff continuation row's last trade day from its own Form 25's confirmed EX-99.25 notice, when before the successor's first sighting, the handoff rewrite's typed `successor_from`, and no later than the effective date; the stage keeps the failed-read watch; metered as "handoff notice dates"), `_successor_endings` (stage 9d: the Form 25 search, matches only, for the line and 8-K12B successors the run added, each searched from its own trading record (`TradingRecord.added`: its ticker, its span, to the run date when it has no fails rows, and its CUSIPs; no era or observation is made up for it, and its issuer's lookup tier is none) beside the run's securities of its issuer; the finder's items about a Form 25 that already owns a delisting are dropped by their typed `ReviewItem.filing`; its mergers are valued by `_merger_values` like any ending (C5); metered as "successor endings"), `_unexplained_endings` (stage 9h, FB-004 part d, after 9e and 9g and before the history rows: an observed security the history over every earlier stage's delistings closes with no ending (`Histories.end`: no day, not listed, not sighted at the fails data's last day) and whose listing status is known gets the spec's end-of-era branch 6 ending, `unknown`, `delistings.unexplained_ending`, dated by `Dating.unexplained`, flag `unexplained_ending` (fix); the finder's `ended_without_delisting` item is dropped for it and for a security the history keeps open; the history is built again over the result; metered as "unexplained endings"), `_distress` (stage 9e,
sub-plan 5g: for each liquidation, compliance-failure or unknown delisting with no successor, a bankruptcy plan's
stock rule (R6), a price-only removal's code 552, and the OTC symbol of its first off-exchange print, anchored on the
last trade day stage 5 dated; `dlret.DistressTerms` for the contract; metered as "distress notices"; at stage 10a a
plan's `received_close` answer times its ratio is that ending's value and an answered OTC print a drop's, each read
through its own request, `PriceAnswers.ending_values`), then the row builders (stage 10a builds one
`dlret.ValueInputs` per delisting and `reconstruction.enrich`es it; stage 8's records feed 10a, 10c and 10g:
`MergerValues.table_terms`, `contract_inputs` and `requests`), `_issuers_in_force` (stage 10c3: the
contract's issuer timeline, read before triage so a failed or stale read is a `resolution_degraded` row, as 4c's; FB-015:
it also takes the derived eras of each sighted security and, for a history open on the run date, the company SEC
lists the ticker under) and
`_triage`; the contract (stage 10g) takes sub-plan 5h's `Identity.renames` too: each placeholder whose eras
now hold one FIGI line is a `contract/id_changes.csv` rename, across a class label), each with explicit
inputs and outputs and the run-wide `_RunContext` (clients, run date, log,
workers, SEC meter `manifest.StageMeter`). `Clients` is the seam every stage reads SEC, OpenFIGI, the fails files,
MIDAS, the halt feed and the LLM through (architecture step 11): each adapter, production's (`default_clients`) or a
test double, provides its client's required reads and states each optional capability (`sources/capabilities.py`) offered
or absent; stages ask `Clients.full_text_search`, never a `getattr` default, and `run` logs each absent
capability once (`Clients.absent()`). Each stage returns what it produces
(`_Successors` for stage 9, for instance) and `_run` combines the answers. Every change of an ending's kind or
successor after the finder built it is a rewrite (`endings/rewrites.py`), never a stage's own field edit. Helpers that
belong to one kind of data live with it, not in `pipeline.py`:
`identity/issuer_record.py` (every stage's reads of an issuer's EDGAR record, `Clients.issuers`, and their failure policy),
`endings/rewrites.py` (an ending's kind, successor, flags and provenance after it is built),
`outputs/degraded.py` (the `resolution_degraded` rows and flags), `ftd.close_age`,
`review_triage.merge_review_rows`, the era review rows in `security_master`.
See `CONTEXT.md` for the vocabulary its docstrings and variable names assume
(security, era, sighting, pin, …).

## vocabulary/

**`vocabulary/`: the leaves (each imports nothing of the package):**
- `vocabulary/identifiers.py` — architecture step 13, a leaf (it imports nothing of the package): how a security's identifiers
  are spelled and how its share class is read from text. Ticker spellings: `normalize_ticker` (the tables' spelling,
  "brk.b" and "BRK B" are BRK-B), `regular_way` (EHAB-WI is EHAB), `bloomberg_ticker` (OpenFIGI's BF/A),
  `bare_ticker` (the fails files' BRKB, with a post-split "...D" or a new CUSIP's "...ZZZZ" appended to it),
  `class_suffix` (a one-letter class ticker's base and letter: UAC-C is UAC and C). The placeholder sec_id:
  `placeholder_id` (`CIK<cik>-<CLASS>` from a class code, `SHARE_CLASS_CODE`; an optional CUSIP appends
  `-<CUSIP>`, one of several lines of an issuer and class, FB-005) and `is_placeholder` (a prefix test). A class code
  (COMMON, CLASS X, SERIES X) and its letter (`class_letter`). One reader per kind of text, each its own rule:
  a security's name, observed, EDGAR's or OpenFIGI's (`share_class_from_name`: a series letter apart from SER or
  SERIES, so OpenFIGI's SERV for services is no series V, FB-003; `name_class_letter`, the era split's
  and the identity rules'; `strip_class_words`, the name an 8-K12B prints, for stage 9's and the handoffs'
  searches); the class letter an OpenFIGI name ends with (`figi_class_letter`: "MSG NETWORKS INC- A", which the
  name reader reads as COMMON); one fails description (`description_class_letter`: CL or CLASS, a "-" allowed; the
  fails index's base relabel and the line follow's class refusal); a CUSIP's descriptions together
  (`descriptions_class_letter`: CL, CLASS, SER or SERIES and a space, one letter over all; R2's letter hint); an
  LLM answer's share class (`answer_class_letter`: "B", "Class B", "Series C common"; a basket leg's class); a
  filing's prose (`prose_class_letters`: "Class X"/"Series X", a following "-" not, Series A-1; the own-share
  statements and the acquirer line's quote); `CLASS_MODIFIERS` and `class_of` (the letter and the words, SPECIAL,
  NON-VOTING, LIMITED VOTING, a security's statements must name). `descriptions_class_letter` also reads a "CL"
  joined to one letter that ends a description ("WASHINGTON POST CO CLB", never "CLB HOLDINGS" or "CLUB"), and
  `fits_class` (FB-003) says whether a COMMON security, which states no class, is the one lettered class of its
  issuer: the only letter its CUSIPs' descriptions and its issuer's eras and securities name, never beside a second
  letter (Liberty's tracking stocks); `line_follow.decide` and the identity stage's `_handoff_joins` share it. A
  Form 25's class text stays `form25`'s. The data
  clients (ftd, midas, nasdaq_halts) read their spelling here, not from the observations
  (`tests/test_import_closure.py`).
- `vocabulary/crsp_codes.py` — the truth table: `DLST_CODE_TO_BUCKET` plus a leading-digit
  range fallthrough (`2xx→merger`, `3xx→exchange_transfer`, `4xx→liquidation`,
  `5xx→compliance_failure`, `6xx→expiration`). **The bucket — not the exact code
  — drives all downstream handling.** `CONTINUATION_CODE` (304) is every exchange transfer's code, one constant.
- `vocabulary/trading_calendar.py` — NYSE trading days (weekends, exchange holidays,
  unscheduled closures); turns "suspended before the open on D" into the
  actual last trading day and lines up FTD rows (dated D, priced at D−1's close).
- `vocabulary/exit_kind.py` — the row vocabulary (architecture step 8a): one reading of a delistings.csv row, and the text its
  producers write for the readers to read back. It imports nothing of the package (`tests/test_import_closure.py`
  pins it, and that no measurement or contract module loads a network client, nor a classification module a
  measurement one). Producers (end_of_era, handoffs, the finder, rewrites, the payout gate, last_trade, stage 9g)
  write through it; readers (verdict, scorecard, contract, payout_rule, lifecycle, audit, truth, diagnosis_truth,
  regression, loop_round, review_triage) read through it.
  - The contract's view: `ending_fields` (exit kind, drop reason, continuation; the value cells are
    `dlret.contract_value`'s, whose methods' kinds are defined beside them) and `is_distress`. Today's bucket and CRSP code map to the exit kind (a code-470 bankruptcy is `dropped`
    for `bankruptcy`; `unknown` asserts none; a compliance failure the exchange removed for a price deficiency only,
    its Form 25 notice, else its 3.01 items, carries CRSP 552, drop reason `price`, from stage 9e, and an issuer's
    own Form 25 changes nothing: sub-plan 5g).
  - Real endings, one definition each: `is_real_ending` (the successor is not the security itself),
    `is_continuation` (a successor other than itself) and `last_endings` (each security's last real ending by delist
    date, a tie keeping the later row: the contract's row, the verdict's `earlier_ending` and stale-seed rule, the
    lifecycle walk's final ending, the diagnosis judge and the loop's context).
  - Flags: `flag_tokens`, `flag_name`, `flag_detail`, `flag_names` (review_triage, the verdict, the lifecycle grade,
    the scorecard, the payout rule and the rewrites read the cell through them); the gate flags `GATE_FLAGS`
    (`PAYOUT_GATE_FAILED`, `LLM_GATE_FAILED`, `TERMS_GATE_FAILED`, `TERMS_GATE_SKIPPED`), which the payout gate
    writes and the verdict's ruling D, the payout rule's `terms_gate` and the rewrites read.
  - The evidence a reason names, each writer beside its reader: the continued-filings rule (`CONTINUED`,
    `rests_on_continued_filings`), an end-of-era relabel (`relabel`, `resolved_from_continued_filings`) to a merger
    (`change_in_control_reason`, `completed_acquisition_reason`, `merger_relabel`), a successor registration
    (`SUCCESSOR_FORMS`, `successor_registration_reason`, `continuation_reason`, `names_successor_registration`), a
    link's note (`successor_note`) and a handoff linked by timing (`TIMING_CIK`, `linked_by_timing`). The published
    text is byte for byte the producers' as before; `tests/test_exit_kind.py` reads the resolver's and the handoff
    stage's own text back.
  - `VALUE_RULES` (contract/delistings.csv's `value_rule`).
  - The last trade's sources, flags and facts (`LastTrade`, `end_day`, `effective_date`, `cites_form25`, and over a
    row `of_row`, `effective_of`, `published`, `end_day_of`; endings/last_trade.py's module entry) and stage 9g's answer,
    `ContinuationReading` (the verdict's input beside the tables).
- `vocabulary/names.py` — issuer-name tokens and agreement, a leaf (FB-006: `names_agree` and `description_names` share
  one word equivalence, `_word_matches`: plural S, in-order abbreviation or truncation of at least four letters on
  either side (never the only word shared), the vendor's `_VENDOR_ABBREVIATIONS` (PPTYS), run-together words; a name
  with no word of three letters compares as one string, `2U INC` and `2U, Inc.`; FB-009: letters and digits run
  together are one word, also spelled by each run of four letters or more in it, so SKY440 is never SKY and
  L3HARRIS meets HARRIS; FB-004: `description_names` leaves a holding word out of the words it compares, on either
  side when another word is left, `_HOLDING_WORDS`: a holding company that keeps the name, EXXONMOBIL HLDGS CORPORATION
  beside EXXON MOBIL CORP, is that name; FB-004 part c: `has_name`, whether a name can agree with another, a word of
  three letters or the letters and digits left after the fillers; `same_letters`, two names of the same letters in any
  order, the name run together, split or reordered; FB-003: `description_names` of a description and a name that both
  have no word to compare reads their letters and digits, security words out, as `names_agree` does, so WW INTL INC
  COM names WW INTERNATIONAL INC): `name_tokens`, `names_agree`, `has_name`, `same_letters`, `description_names`,
  `names_an_issuer` and `description_matches` (a fails row's description against a security's names), read by the
  observations, the identity rules, the fails index, the Form 25 match, the classifier and the merger readers.
- `vocabulary/exchanges.py` — a listing's exchange, normalized, a leaf: `Exchange` (NYSE, AMEX, NASDAQ, OTHER, the four buckets
  the Shumway constants were estimated on) and `normalize_exchange` (NYSE Arca, NYSE MKT, Nasdaq Global Select, ...).

## sources/

**`sources/`: the clients and their plumbing (network):**
- `sources/edgar.py` — throttled, on-disk-cached SEC client. `submissions()`,
  `recent_filings()`, `fetch_filing_text()`/`fetch_filing_raw()` (HTML-stripped
  and raw text caches), `company_tickers()`, and `full_text_search()`, the optional capability
  `capabilities.FULL_TEXT_SEARCH`, which this adapter offers. Owns `EdgarBlocked`, `resolve_user_agent()`, and
  `sec_get()`: the one SEC request path (`sec_limiter.throttle`, User-Agent,
  `sec_stats` counting, `retry_request`, `EdgarBlocked` on 403/429) that
  `EdgarClient` and `sources/sec_http.py` share.
- `sources/sec_limiter.py` — the SEC rate limit: `SEC_LIMITER` (a `RateLimiter`, 8
  request starts/s across the process's threads), `MachineGate` and
  `use_machine_wide_limit()` (the same limit across every process on the
  machine through the lock file), `throttle()` (every SEC request waits here),
  `PrefetchCancelled`.
- `sources/sec_stats.py` — the counters behind run_manifest.json: `SEC_STATS` (a
  `RequestStats`: requests, cache answers and latency per endpoint,
  `endpoint_of`, and degraded answers), and fill-only mode (`fill_only`/
  `filling_only`: a prefetch thread only fills missing cache entries).
- `sources/capabilities.py` — the clients' optional capabilities, declared once for the `pipeline.Clients` seam
  (architecture step 11): one, EDGAR full-text search (`FULL_TEXT_SEARCH`, stated as `edgar.full_text_search`, a
  `FullTextSearch`). Each adapter states a capability offered or absent (the attribute, or None); one that states
  nothing is refused where the statement is read (`stated`, `offers`, `Undeclared`). `Clients.absent()` lists the absent ones; `run` logs each once, with what
  the run goes without (`Capability.without`), before anything is read; run_manifest.json is unchanged. Every
  other read a stage makes of a client is required of its adapters: EDGAR's `submissions`, `recent_filings`,
  `fetch_filing_text`, `fetch_filing_raw` and `company_tickers`; the resolver's `flush` and `shadow`; the
  classifier's `shadow` (`DelistClassifier.shadow`, the delisting warm-up's twin over a shadow issuer record); the
  halt feed's `failed_days`; the LLM extractor's one call shape, `extract(record, security_name=)`, filled ahead on
  the worker threads. The resolver and the classifier state the issuer record they read through
  (`issuers`, None for none of their own), from which `Clients.issuers` takes the run's.
- `sources/fatal.py` — `FATAL`: the exceptions that stop a run instead of becoming a
  review row (`EdgarBlocked`, `OpenFigiBlocked`, `OpenFigiUnavailable`).
- `sources/retries.py` — `retrying()`: the one retry loop (attempts, the wait between
  them) behind SEC's `edgar.retry_request`, `OpenFigiClient._post` and
  `NasdaqHaltClient.halts_on`; each client passes its own policy (what is
  retried, how long to wait, what a refusal raises).
- `sources/settings.py` — `env_setting()`: a setting from the environment, else the
  repo `.env` (one key only, `os.environ` untouched), behind
  `edgar.resolve_user_agent` and `openfigi.resolve_api_key`.
- `sources/atomic_io.py` — atomic file writes: `write_atomic` (one cache file, durable,
  through a writer-named temp file), `write_atomic_with` (the same for a file a
  library writes itself, a SQLite store: it is handed the temp path), `clean_orphan_temps` (a killed writer's
  leftovers), and `replace_on_success`/`replace_all_on_success` (the output
  tables and the decisions file: every temp file is written first and nothing
  is replaced unless all are; then each is renamed into place, one at a time).
- `sources/sec_http.py` — throttled, cached `download()`/`get_text()` for the other SEC
  data files (FTD and MIDAS ZIPs and their index pages), sent through
  `edgar.sec_get` (so the same throttle, retries and `EdgarBlocked` on
  403/429). Index pages and ZIPs are both cached through
  `atomic_io.write_atomic` (text or bytes). Every cache file
  (EDGAR, SEC data files, MIDAS summaries, halt days, OpenFIGI and LLM answers)
  goes through it, and each client removes a killed run's temp files
  (`atomic_io.clean_orphan_temps`, also old `.part` downloads) when it starts.
- `sources/ftd.py` — `FtdClient`/`FtdIndex`: SEC fails-to-deliver rows (`(date, CUSIP,
  symbol, price)`, 2004+). Architecture step 12: the index is the only reader of the fails files (its source, an
  `FtdSource`: `FtdClient` or a test's double with `urls_for` and `rows`). `FtdIndex(rows)` holds given rows (with no
  source they are all it has); `FtdIndex.opened(source, lo, hi, through=, symbols=, cusips=, names=, first_seen=)`
  is the run's index, opened by `identity` (stage 1) over the eras' tickers and CUSIPs, its run's fails window
  [lo, `through`] (the run date). A stage asks it, never the files: `follow(cusips=, symbols=)` (the keys' rows over
  the run's fails window: stages 4 and 4b), `around(days, before=, after=, cusips=, symbols=)` (from `before` days
  before the earliest day to `after` days after the latest: stages 5b, 7 and 8's gate), `apart(days, ...)` (a
  separate index of CUSIPs' rows around days with this one's rows of them, this one left as it was: stage 8a's early
  mergers) and `every_row(lo, hi)` (every row of the files in a span, as spelled, held nowhere: stage 8a'). An ask
  reads only the keys not held over its whole span, in one pass, and leaves the rows it added sorted (`_settle`): a
  query never reads the files and never changes the index (the warm passes read it on worker threads at once; the
  file periods behind the coverage answers are filled once, under a lock), and a windowless one (`by_cusip(c)`) answers every row held, those other keys'
  asks brought in too. Coverage is stated: `opened_from` (the window the index was opened over:
  `cusip_handoffs`' margin; `Identity.ftd_lo`), `data_covers(lo, hi)` and `data_end()` (the fails data's own
  coverage, the periods of SEC's file index up to the run date: `guarded_eras`, the line follow's data edge, stage
  9's OKE rule; an index with no file index answers from its rows held; `files_end()` is the file index's answer alone,
  None for an index over rows, which the history's data-edge rule reads). `close_after()` supplies every last-trade
  close and acquirer-completion price (`close_of`/`close_known_on`: by the security's
  CUSIP on the day, then its symbol, never from a row of a CUSIP another security of the run holds: `skip`,
  WEN 2008, sub-plan 5d); `by_cusip`/`by_symbol` supply CUSIP
  history, `trading_rows(cusips, lo=, hi=)` the rows not under a deleted symbol, `symbol_deleted`
  whether a CUSIP's last rows are all under one, `descriptions` a CUSIP's names;
  `FTD_START` (2004-01-01, the data's first day) and `close_age` (a fails
  row's close age in trading days, for `ftd_close_prior:<n>`). `trades_after` (sub-plan 5b): whether a security's own CUSIPs, under any symbol it trades under
  (`is_trading_symbol`: no deleted, unassigned or digit-bearing symbol), have at least 20 fails rows over at least
  20 days at two or more prices after a day; the finder's test of whether it went on after a Form 25. `is_unassigned_symbol` (a new CUSIP's first-day
  `…ZZZZ` rows, no ticker) and `settled_last` (the row that opens a CUSIP's last one-price run: the fails still
  settling after its last trade). Sub-plan 5h: a one-letter class ticker whose suffix FTD writes onto a whole symbol
  (a snapshot's `UAC-C` for Under Armour's class C, FTD's `UAC`) also loads that base spelling; a base row is keyed
  by the class ticker only when the ticker's observed names agree with its description and the description names
  the class letter and is dated before the base symbol's own first observation when the run observes the base as a
  ticker (`FtdIndex.opened(..., first_seen=)`: a class C spelled UA-C, whose base UA became its own line's symbol
  on 2016-12-08) (`_relabel_base`); `by_symbol(base)` keeps only the rows left under it (HEI beside HEI-A). The
  relabel rules stay in the index (they decide how it keys its rows); the spellings and the description's letter
  they read are `identifiers`' (`bare_ticker`, `class_suffix`, `description_class_letter`). A row is relabelled
  when it is added, with the spellings asked for by then: the replay holds Berkshire's and Lions Gate's BRKB/LGFB
  rows twice, once relabelled after the gate asked BRK-B and LGF-B (step 12's log, open for a ruling).
- `sources/ftd_store.py` — a fails ZIP parsed once into `sec_data/ftd/parsed/<zip>.sqlite` (the ZIP's size and
  mtime recorded, and a digest of what the line rule makes of a set of probe lines; rebuilt when the ZIP or the
  rule changes; written through `atomic_io.write_atomic_with`), read by symbol and CUSIP through its indexes, in
  the ZIP's row order; `split_line` is the one reader of a fails line (`ftd.parse_ftd_lines` uses it too);
  `FtdClient.rows` reads through it.
- `sources/midas.py` — `MidasClient`: SEC MIDAS per-security exchange volume (2012+,
  ticker-keyed); `last_trade_day()` confirms the last day with lit+hidden
  exchange volume, suppressed to `None` when the window runs past MIDAS's
  coverage end and the found day is within 5 trading days of that edge (an
  unpublished quarter always yields nothing). A quarter that fails to
  download is remembered in-memory for the rest of the run.
- `sources/nasdaq_halts.py` — `NasdaqHaltClient`: Nasdaq's keyless trade-halt feed;
  `deletion_halt()` finds a code-`D` ("security deletion") halt as a second
  last-trade-date confirmation when MIDAS has none. A 404 is an answer (no
  halts); a timeout, connection error, 429/5xx after the retry, other status
  or unparseable body is a failure: never cached, counted as
  `degraded:nasdaq_halt_feed`, listed by `failed_days()` on the reading
  thread, carried on `LastTrade.halt_feed_failed` by the last trade module, and turned
  into `resolution_degraded` on that delisting by the pipeline.
- `sources/openfigi.py` — `OpenFigiClient`: OpenFIGI `/v3/mapping` and `/v3/filter`,
  cached on disk (`atomic_io.write_atomic`: a run that dies mid-write leaves no
  cut-off answer), paced on the `ratelimit-*` headers. Owns `OpenFigiBlocked`
  (401/403) and `OpenFigiUnavailable` (timeouts/5xx after its retries).
- `sources/html_text.py` — `strip_html()`: filing HTML as plain text, for the EDGAR
  client's text cache and Form 25 parsing.
- `sources/cik_lookup.py` — SEC's company-name index, `cik-lookup-data.txt`, as a local name -> CIK search:
  `CikLookupClient` (the download, cached 30 days under `cache/sec_data/cik_lookup/`) and `CikNameIndex` (exact, then
  character-prefix matches, and `containing`, the entries holding a whole word, FB-004 part c); the ticker resolver's
  name tier and the acquirer ticker read it (the ticker resolver's entry has the rules).
- `sources/llm_client.py` — the injectable LLM client for JSON extraction: an adapter has `extract(system, user, schema) ->
  dict` and states its `model`; `OpenAIJsonClient` is the one provided, `default_llm_client` builds it from the repo
  `.env` (the only `load_dotenv` call).
- `sources/prefetch.py` — `warm`: before a sequential stage, its per-item work on worker threads under
  `sec_stats.fill_only()`, only for what it fetches, results thrown away, so the sequential pass reads the copies a
  one-thread run would read (`--sec-workers`; see the SEC fair-access invariant).

## filings/

**`filings/`: what SEC filings say, read by several stages:**
- `filings/filing_search.py` — the EDGAR full-text searches several stages send, built in one place so a warm pass and the
  sequential pass read one cache entry: `successor_query(name, day)` (a successor registration, 8-K12B/8-K12G3,
  naming the issuer in [day − 30, day + 60] d), which stage 4b's other-registrant check, stage 9's 8-K12B successor
  and the handoffs' continuation filing send. It imports nothing of the package.
- `filings/form25.py` — parses a Form 25's XML or text (exchange, `class_text`, rule),
  labels the exchange, reads `class_kind` (common/preferred/warrant/unit/…)
  from the class text, and matches it (`match_securities`: the securities it names, `tied_securities` for a tie) to the observed securities of that kind/class letter. Sub-plan 5b: `is_involuntary` (a removal under rule 12d2-2(b)); `notice_last_trade` never reads the NYSE (b) template's "an
  announcement was made on the 'ticker' ... at the close of the trading session on D" press day, and `_class_expiry`
  takes an expiry only within [filing - 30 d, filing + 10 d]; `Form25.solely` and
  `other_class` (R3: a Form 25 that relates solely to a non-common class, or whose lettered tracking-stock segments
  name no word of the security's name, is not its own; a "solely" text that names a common class (COMMON, ORDINARY,
  SHARES) is the common's, generic descriptors such as SUBORDINATE, CONVERTIBLE, RESTRICTED, LIMITED,
  PARTICIPATING, REDEEMABLE, EXCHANGEABLE or MULTIPLE are not another tracking group, and CAPITAL is a group word,
  Liberty Capital); `notice_says_acquired` (R6b: the EX-99.25 notice says acquired or paid in cash, and nothing of
  a reclassification, a holding company or a reorganization); `SecurityRef.letter_hint` (R2: a letterless class
  takes the one letter its own CUSIP's fails descriptions name, `identifiers.descriptions_class_letter`, only for a
  letter no sibling's share class carries). The class text's letters stay read here (`class_letters`: CLASS X, else SERIES X, per segment, past attached rights and a common's preferred clauses; the
  segments feed the match and R3 too), each turned into a letter by `identifiers.class_letter`. FB-004: a text
  Form 25 reads up to 4,000 characters of class above its caption (Freddie Mac's 2010 list of a common and 18
  preferred series) and its exchange from the words above the "(Exact name of Issuer ...)" caption, a national
  exchange beside a regional one being the national's (`_filing_exchange`: Fannie Mae's "New York Stock Exchange,
  Chicago Stock Exchange"); `class_kind` reads "Subscription Rights to Purchase Shares of ..." as a right; the
  letterless siblings the text's group words name are as many of the classes no lettered sibling took as there are
  such classes (`_class_matches`: Liberty SiriusXM's Series C line beside the Series B and C the text names), unless
  their own fails descriptions name another letter (`letter_hint`) or there are more of them than classes;
  `tie_candidates` (the siblings a Form 25 its text cannot place may be about: the tied ones, else, for a text with
  no class letter, every security of its kind) is the finder's to break by trading. `every_class` (FB-003, Twenty-First
  Century Fox 2019's "Class A Common Stock & Class B Common Stock"): a text that names two or more class letters
  while the issuer's lines of that kind are as many and carry no letter names each of them, whichever is which.
  `about_class` (a Form 25 is about the security's own class: not of a preferred, warrant, right, unit, fund or
  debt class, not another tracking group's (`other_class`), and not naming only other class letters) and
  `names_only_other_group` (an 8-K section that names tracking groups' common stock and none is the
  security's): the line follow's `otc_move` reading.
- `filings/listing_status.py` — `unlisted_cover()` (FB-004: the first annual report after a day whose "Name of each
  exchange on which registered" column is there to read and holds no exchange; an unread report is none),
  `quoted_over_the_counter()` (FB-004 part b: EDGAR's submissions JSON lists one of the security's tickers on the OTC
  market and none on a major exchange; an issuer it lists nowhere says nothing),
  `exchanges_around()`/`withdrawal_kind()`: reads the
  10-K cover page's exchange list before and after a Form 25 to tell a real
  delisting from the withdrawal of a secondary/regional listing while the
  main one continues; `listed_today()` for the completeness check;
  `issuer_exchange()` the exchange EDGAR's submissions JSON lists for a ticker.
- `filings/evidence.py` — pure predicates over one issuer's EDGAR record: its names over time (`edgar_names`, `name_at`,
  `names_near`, `names_between`, `names_until`, `renamed_near`), its filings (`first_filing`, `bankruptcy_8ks`,
  `filed_operating_between`, `still_operating`, `merger_evidence`, `is_spac`, `own_filings`: the list without
  `FILED_BY_OTHERS`, the forms EDGAR lists under an issuer that another party filed about it, ownership schedules,
  insider forms 3/4/5 and 144, a bidder's tender offer, the SEC staff's UPLOAD) and an 8-K's item text
  (`item_mention`, `item_sections`, `item_text`, `mentions_bankruptcy`, `says_listing_transfer`,
  `cites_listing_deficiency`). The identity stages read its name readers, so it sits below them.

## outputs/

**`outputs/`: what a run publishes, as rows (no client):**
- `outputs/store.py` — every output table's column order, key and sort order (`ticker_history` is the one table with
  `TableSpec.written` False: the run holds it in memory for the verdicts and the contract, `write_tables` skips it)
  (`TABLES`), `DelistingKey` (a delisting's `(sec_id, delist_date)` key, here so
  every stage — the finder among them — and the handling can both use
  it without one importing the other), `format_cell` (the one cell formatter
  every table shares), `write_tables`/`read_table` (every table to a temp
  file first, then renamed into place one by one,
  `atomic_io.replace_all_on_success`), and `read_delistings_frame`
  (delistings.csv as a typed pandas DataFrame: `qlib_adapter.load_delistings`
  reads through it). `CONTRACT_SCHEMA_VERSION` 3 adds `contract/payout_legs.csv` (sub-plan 5f). Every table read — `qlib_adapter`, `accept_review.py`,
  and `run_snapshot` for every measurement reader — goes through this module's specs, so
  a later move to DuckDB changes only this module and `run_snapshot`'s adapters.
- `outputs/review_triage.py` — pure (no network): `CATALOG` maps every review flag to
  a severity (`fix`/`check`/`info`), a description and an action;
  `row_severity`/`triage()` turn the pipeline's merged review rows plus a
  decisions list into `review.csv` (severity-sorted, info-only rows hidden)
  and `review_summary.csv` (one row per flag). `Decision`/`load_decisions`/
  `ReviewDecisionError` read `data/review_decisions.csv`; `accept_by_flag`/
  `append_decisions` back `scripts/accept_review.py`'s bulk accept.
  `ReviewItem` is a flag raised outside a delisting's own row (the finder's,
  the security master's and the pipeline's), `.row()` its review row; a finder's
  item about a Form 25 carries it typed (`filing`, a `FilingRef`: form, accession,
  filing date), never written;
  `merge_review_rows` joins rows that share a key. Called by `pipeline.run()`
  just before the write; never touches `delistings.csv`.
- `outputs/degraded.py` — answers that rested on a failed request or a stale copy:
  `DegradedWatch` (an SEC read on this thread counted itself degraded; a stage whose reads include an issuer's
  record asks `IssuerRecord.watch()` instead, which also sees an issuer read that failed without counting itself),
  `degraded_item`/`flag_degraded` (the `resolution_degraded` review row and
  the flag on a delisting's own row), `report_halt_feed_failures` (a
  last-trade decision that asked a Nasdaq halt-feed day that failed).
- `outputs/manifest.py` — `run_manifest.json` (`build`/`write`) and `StageMeter`, the
  per-stage SEC traffic it reports (a stage that runs more than once is added up). Its `continuation_filings` are stage 9g's readings, a confirmation's filing or a
  doubt (`run_snapshot.continuation_entries` writes them, `RunSnapshot.continuations` reads them back). Its
  `merger_terms` (FB-004) is the LLM reader's model and its answers by source (`LLMMergerTermsExtractor.usage`: the
  sequential pass's answers `from_cache` as the run found it, `asked` of the model this run, a warm fill included, and
  `failed`), null with no LLM reader, so a value change can be read against a model change.
- `outputs/dlret.py` — an ending's value, decided once (architecture step 10). `decide(ValueInputs) -> EndingValue`: one typed
  input record per ending (bucket, exchange, last close, a merger's terms, `--recoveries`, an answered OTC print or
  plan value, the cash read's confidence, `deregistered`) gives the method (`DlretMethod`), the value, the terminal
  value, its confidence, whether it is measured or a fill (`METHODS`: each method's kind and confidence beside it;
  `plan_stock` is medium like `otc_print`, step 10's declared fix), the table's cell (`table_dlret`: an abstain and an
  unknown are blank) and the firm month's DLRET (`firm_month`: before the table's assumed-par fill, so an expiration
  with a last close is 0.0 in the table and a drop in the firm month; open for the operator's ruling, step 10's
  measurement). `rule_of(row, merger, distress) -> Rule`: the value rule (`exit_kind.VALUE_RULES`) and its terms from
  a delistings.csv row, a merger's pre-gate reads (`MergerInputs`) and stage 9e's `DistressTerms` (both defined here);
  `contract_value(row)`: the contract's `dlret`/`dlret_fill`/`terminal_value` (none for a continuation). A
  liquidation's value and rule read one order (`_distress_rule`: a recovery, else a plan, else the first OTC print).
  Two endings have no value and no fill, each `uncertain` by the verdict's `value_pending`: a wind-down whose
  distributions are not read (`pending_recovery`, FB-002) and a merger whose terms nothing states
  (`pending_terms`, FB-016: `ValueInputs.terms_read` False, from `MergerInputs.read` through
  `MergerValues.terms_read`; terms the gate refused keep assumed par, which the verdict doubts). A third ending has
  a value the library knows to be incomplete: a merger whose LLM terms note a contingent value right, a warrant or
  another contingent payment beside the package (`MergerTerms.unvalued_right`, matched on the note's words) is
  flagged `contingent_right_unvalued` by stage 8 (`merger_value._flag_unvalued_rights`, which logs every note and
  how it read it) and is `uncertain` with `value_incomplete:contingent_right` (FB-024); its terms and `dlret`
  stand as the value of the valued part.
  It loads only the row vocabulary and the leaf enums (`tests/test_import_closure.py`).
- `outputs/reconstruction.py` — `DelistRecord` (the classifier's hand-off, defined here, below the stages, so the
  table, the merger readers and the handling read it without loading the classifier: architecture step 16),
  `EnrichedDelistRecord` (its `answer` is dlret's `EndingValue`), `enrich(record, value,
  *, acquirer_ticker, payout_source, extra_flags)` (refuses value inputs of another bucket; adds `merger_at_par` and
  `distress_at_normal_price`), `delisting_row`, and the override files' readers. `output/delistings.csv` is the
  **primary output**, keyed by `(sec_id, delist_date)` (`store.DelistingKey`; `for_delisting` looks a delisting up
  in a map keyed by it or by the bare `sec_id`).
- `outputs/run_snapshot.py` — architecture step 8b: `RunSnapshot`, every table one run wrote (every `store.TABLES` name is an
  attribute, read the first time a reader asks, once; `has`, `require`) and the manifest fields measurement reads
  (`as_of`, today without a manifest; `continuations`, stage 9g's `exit_kind.ContinuationReading`s from
  `continuation_filings`). Three adapters, one interface: `RunSnapshot.read(out_dir)` (an output folder),
  `RunSnapshot.at(repo, rev, out_dir)` (a commit's copy of it, `git show`), `RunSnapshot.of(tables, as_of=,
  continuations=)` (the rows the pipeline is about to write, `store.formatted`: stages 10f to 10h). `ticker_history` is
  not written: `of` holds the run's own (every security's ranges, the merger acquirers the run adds included), and a
  folder or a commit gives it rebuilt from contract/security_history.csv (`ticker_ranges`: a security's and ticker's
  issuer-split rows merged back into one range, `exchange` and `source` blank, no row for an acquirer the contract
  leaves out), even when an older commit still holds ticker_history.csv. The older-schema
  rule lives here once: a table newer than the first seven (`FIRST_TABLES`; an older commit's payouts.csv is simply not read) the run did not write is None (uncertain
  before reset-2, the contract before reset-3, payout_legs before schema 3), a missing first-seven table raises
  `SnapshotError`; a file must have its table's columns in order, except a schema-1 contract/delistings.csv
  (`CONTRACT_SCHEMA_1`, before the payout rule), which reads as None; any other header raises `SnapshotError` naming
  the file and the columns. The scorecard, both judges, the verdicts, the contract, the regression diff, the loop
  round, update_truth, the audit draw and the verdict fixture builder read a run only through it.
- `outputs/verdict.py` — one verdict per seed (an observation_map row), security and
  ending (a delistings.csv row whose successor is not itself): `decide(snapshot, evidence)`
  returns `Verdicts`; `uncertain_rows()` is `uncertain.csv`. A function of the run snapshot: the rules are the
  spec's invariants, read from the tables (FIGI source, intervals, each
  ending's reason, flags, last-trade source and Form 25 date) through the row
  vocabulary (`exit_kind`), and stage 9g's `exit_kind.ContinuationReading`s
  (`RunSnapshot.continuations`, so a written folder's snapshot gives the run's own verdicts), plus each
  placeholder's ticker evidence (stage 10e, recorded nowhere: an offline caller supplies it). The diagnosis-truth spec's 2.3 rulings
  (sub-plan 5i: a relabel its own Form 25 settles, a successor registration, the
  Form 25's filer as issuer evidence, an unpriced gate, a stale seed, no ending
  at all; A to F in its docstring) are its own private rules (architecture step
  8a folded `verdict_rules` in), tested through `decide`
  (`tests/test_verdict_rulings.py`). A seed is an era's first sighting for the
  security's coverage rule; later sightings outside the history are listed
  seeds only.
- `outputs/contract.py` — the contract's rows (spec "The contract", decisions 6, 7, 9, 10, 12), written under
  `output/contract/` beside today's tables for one release: `security_history_rows` (ticker ranges split where
  the issuer in force changes), `delisting_rows` (one per ended security, its last: `exit_kind.last_endings`), `seed_rows` (the seed
  echo), `id_change_rows` (baseline placeholders that now hold a FIGI; stage 4b's folds by name, `renames`; and a baseline
  FIGI the run no longer holds that `renames` maps to a FIGI of this run, rule F: BTU, CRC; `regression.renamed_to`
  and `truth_set.TruthSet.rename` read every row alike, placeholder or not), `payout_leg_rows` (schema 3, R3: each
  security of a basket ending per share, `contract/payout_legs.csv`). `id_change_rows` also writes split rows
  (`store.SPLIT`, FB-005, FB-001's CHK; `split_holders`): with the baseline's `contract/security_history.csv`
  (`baseline_history=`, found beside a `--id-baseline` securities.csv or in the output folder by
  `classify_universe.read_id_baseline_history`; none found, none written, logged) and this run's, a baseline id whose
  ranges this run holds, under the same ticker, under other ids that each hold at least `SPLIT_MIN_DAYS` (90) days and
  `SPLIT_MIN_SHARE` (10%) of the days it held is split when it is gone and two or more ids hold them or when it is
  still here and another holds a part, one row per other id (that id's issuer and class); an id one other id
  fully took over stays a rename, and a split id gets no rename row. `run_manifest.json` carries
  `schema_version` (`store.CONTRACT_SCHEMA_VERSION`, 4: price_requests.csv gains `lookup_name`, FB-008, and id_changes.csv a
  `kind`, `store.RENAME` or `SPLIT`; readers follow only renames, `regression.follows`, a row with no kind cell is one, and
  `run_snapshot` reads an older file's missing last column filled). It loads no client (its value inputs are dlret's
  types; its value cells `dlret.contract_value`), so the regression report reads `id_change_rows` from it.
- `outputs/payout_rule.py` — the payout rule of each contract ending as the contract writes it (`value_fields`, the eleven
  columns after `verdict` in `contract/delistings.csv`: the columns came in schema 2, the contract is now schema 4
  with `payout_legs.csv`), from the rule `dlret.rule_of` decides (step 10: which rule, which terms, their source and
  gate, whose price): `value_rule` (`exit_kind.VALUE_RULES`), `cash_per_share`, `cash_currency`, `stock_ratio`,
  `price_sec_id`/`price_ticker`/`price_date` (the acquirer for a stock leg, the security itself for `otc_print`; the
  trading day after the last trade), `recovery_ratio`, `terms_source`, `terms_gate` and `value_formula` (written
  here); the caller computes `dlret = payout / last close − 1` with its own prices. The rule's two inputs beyond the
  row are dlret's: `DistressTerms` (stage 9e's OTC symbol and plan ratio) and `MergerInputs` (stage 8's
  `MergerValues.contract_inputs`), which holds a merger's `--merger-terms` row, LLM terms and regex read from before the
  payout gate: terms the gate dropped are still published,
  `terms_gate=failed` (a failed election publishes both legs as read), `skipped` when the gate could not check them
  (`terms_gate_skipped:<why>`: a non-USD cash leg, a basket, a dollar-valued leg), blank with no last close.
  `cash_currency` (sub-plan 5f, R5) is the currency of the read that supplied the cash (the LLM's, the regex's;
  blank for a `--merger-terms` row). A package of two or more securities is `basket` (R3): the main row keeps the
  cash, `basket_legs` gives `contract/payout_legs.csv`'s rows; one security plus cash stays `cash_plus_stock`. A
  dollar-valued stock leg is carried in `value_formula` over `avg_price(<ticker>)`, no ratio. The payout gate
  (`payout_gate`) reads a v3 answer as its package (`MergerTerms.is_package`: basis final_prorated, default or fixed; a `none`
  answer keeps 5e's either-or reading): cash only in pass 1, with stock in pass 2; a regex cash never stands beside
  an election package with stock, a package no last close can check, or as the package's own cash leg (SUG, FWLT,
  AWH, SHAW); an LLM's "NULL" ticker is no ticker (GRUB, `MergerTerms` cleans it). Review fixes (5f): an election whose v3 answer states no leg (WSC, THE) takes the
  earlier prompt's cached either-or reading of the same filing (`LEGACY_VERSION`, cache only, never asked again; `no_default`,
  flag `election_no_default`), as does any election answer that states no package for non-electors (basis `none` with no cash or ratio stated, TRH; a basis `none` answer that states a leg, CYN, keeps it; or a
  `final_prorated` answer that is only one election class's result, `electors_only`, NMX: R4, the package is what
  non-electors received, `llm_merger_extractor.base_reading`; the first candidate that answers decides, a later candidate is never read (TRH, NMX); with no cached
  earlier answer the electors' result is a miss and the regex read stands); `MergerTerms.published` publishes any other
  non-package election only as its all-cash alternative, but a `no_default` reading as read (TRH's 14.22 + 0.145 Y); `MergerTerms.skip_reason` is checked for every answer shape (a dollar value, a further leg, CAD
  cash, a basket stating no package), a stock leg with no ratio is `terms_gate_failed:no_ratio`; a bare "$" never overrides
  the answer's non-USD code; a non-dict answer counts `degraded:llm_call`. `terms/acquirer_ticker.py` (stage 8a'): a stock leg
  with no ticker and no acquirer line takes it from the filing's defined terms, SEC's name index and the issuer's EDGAR
  tickers, else the fails rows' description (SHAW's "CB&I" is CBI); a one-word name the filing does not define is no
  name (Orange). A basket leg keeps its class (`payout_legs.share_class`, `MergerTerms.legs`: CAA's Lennar class B
  is LEN-B, a preferred class has no ticker), and two legs never share a price request. `measurement/regression.py` diffs the
  legs too. The scorecard counts
  `R2.7.value_rule.<rule>` and floors `R2.7.payout_rule_known`. A stock leg's `price_ticker` is the published
  acquirer security's symbol on the price date (`MergerInputs.price_ticker`, sub-plan 5e). `value_fields(...,
  distress=)` (sub-plan 5g): an `otc_print` row is priced under `DistressTerms.otc_symbol` (blank when stage 9e read
  none; the exchange ticker only for a caller that passes no terms); a bankruptcy plan with a read ratio is `stock`
  on the new line (`stock_ratio` as read, a string; no `price_sec_id`; `terms_source` `form25_notice` or `plan_8k`).
- `outputs/price_requests.py` — both directions of the price round trip, matched on one key derivation: the requests
  (`request_rows`: `last_close` per ending with a published date, `received_close` per stock leg as stage 8 asked it
  (`MergerValue.request`: the acquirer security's symbol on the price date, sub-plan 5e, a leg with no LLM ticker
  asking once the line is known, a dollar-valued leg too, 5f), of a plan's new line (`plans=`, 5g) and of each
  further leg of a basket (`leg_rows=`; accepted, not used: the library prices no basket), `otc_print` per
  `dropped`/`liquidation` ending that is not a continuation, under the published OTC symbol (none asked when it
  is blank, FB-007), dated the session after the last trade; a plan's `stock` row asks no OTC print) and the answers
  (`load_answers` for `--price-answers`, which refuses a price that is not a finite positive number, and
  `PriceAnswers`). Each request fills one value input, and a stage reads its answer only through the request it
  makes: `last_closes` (stage 7; one also given by `--last-trade-closes` stops the run), `received_close` (stage 8's
  stock leg, by its ticker), `ending_values` (stage 10a: an OTC print, else a plan's ratio times its new line's
  close) and `refuse_unrequested` (stage 10g: an answer whose `PriceKey` matches no request stops the run). A last
  close or an OTC print is matched on the security, its last trade day and the kind (the ticker and date are a
  hint), a received close on its ticker too. Every request carries `lookup_name` (FB-008, schema 4; informational, part
  of no key): the security's own name (`names=`, sec_id -> securities.csv name, built in `_contract`) for a last close,
  an OTC print and a plan's new line; for a stock leg or a basket's further leg the name of the security the request
  names when the run holds it (in securities.csv, published or not), else the LLM's issuer name for the leg
  (`MergerValues.requests`' third cell, `MergerValues.leg_issuers` -> `leg_issuers=`), else blank. `load_answers`
  requires the columns of `PriceKey` and `price`; `lookup_sec_id` and `lookup_name` are optional.

## identity/

**`identity/`: a security's identity, stages 1 to 4c (network):**
- `identity/observations.py` — `Observation`, `TickerEra`, `ObservationIndex`: splits
  one ticker's observations into eras (runs that belong to one security),
  splitting on a name mismatch, a pin change, or a gap over `ERA_GAP_DAYS`
  that neither side's name confirms as continuous (the class letter a name states is
  `identifiers.name_class_letter`). `identifiers.regular_way` maps a when-issued ticker to its regular-way one
  (EHAB-WI is EHAB): `ObservationIndex` groups by it and each era carries it, while each observation keeps the
  caller's ticker. A derived era carries the step it came from (`TickerEra.derived_from`, a `DerivedFrom(sec_id,
  issuer_cik, why, old_cusip, first)`: the refused security, its issuer, the refusal, the step's old CUSIP and first
  day), which `identify` sets and checks the era against. It no longer spells tickers itself, and imports nothing of
  FIGI's rules (step 13 removed the cycle). The second split, on the fails rows, is `identity.refine_eras`; `identity.identify` is the one
  place both run.
  `Observation.derived` marks an observation the library made from the fails rows, not the caller; `TickerEra.derived`
  (every observation derived) and `TickerEra.caller_observations` (those not derived) are what a reader of the
  caller's observations uses.
- `identity/figi_resolution.py` — pure rules turning an OpenFIGI answer into one US
  composite FIGI: `us_candidates()` groups rows by composite and keeps only US
  venues; `accept()` never trusts Bloomberg's current name alone (a dead line
  gets renamed to its acquirer) — a CUSIP hit needs no name check, a
  ticker/name hit does. The placeholder `CIK<cik>-<CLASS>` used when nothing is
  confirmed, and the class code read from a candidate's name, are `identifiers`' (`placeholder_id`,
  `share_class_from_name`).
- `identity/issuer_record.py` — `IssuerRecord`, the run's issuer record (architecture step 2): one per run
  (`Clients.issuers`, the resolver's and the classifier's; `forget` when a run starts), over the EDGAR client. It
  reads each issuer's submissions JSON and filing list once (every issuer's `profile`, the JSON without its filings
  block, and first filing kept; at most `MEMO_SIZE` filing lists, least recently asked dropped) and answers `names`,
  `names_near`/`names_between`/`names_until`, `first_filed`, `existed_by`, `recent_form_dates` (read from the
  client each time), `profile`, `filings`, `text`, `exact_holders` (SEC's name index, `name_index`, loaded on
  first use) and `listed_under` (the CIK SEC's ticker map lists a ticker under today; the map is read once a run,
  and a failed read is logged under `NO_ISSUER`). `about=` (an event day) asks for a copy fetched by `edgar.submissions_fresh_after(about, today)`;
  every refresh of the run goes through it (the resolver's reads and the classifier's up-front read), so a held
  profile is the client's cached copy's. The failure policy, once: a
  `requests.RequestException` is unknown (None, [], (), "", False) and never remembered, `fatal.FATAL` stops the
  run, any other exception propagates, and a failed, stale (`STALE_KEY`) or self-counted degraded read logs its
  CIK on the reading thread; `watch()` gives a `ReadWatch` (`ciks`, `failed`, and `tripped()`, which also sees any
  other degraded SEC read on the thread) for the `resolution_degraded` rows. A warm pass reads through `shadow()`.
- `identity/ticker_resolver.py` — the memoized (ticker, date, observed name) → CIK lookup the identity stage asks
  (`identity.IssuerLookup`: `resolve`, `is_degraded`, `frequency_candidates` (its 8-K frequency tier's candidates
  and whether the search failed, for the second pass's rule B; its own state left as it was), `shadow`, `flush`);
  it imports no `security_master`. `resolve(..., exclude=)` never answers an excluded CIK from any tier (the company-ticker
  map, the Form 25 search, the company-name search and its agreeing-issuer fallback, the 8-K frequency rank), for a
  derived era asked without the old line's issuer (`identity.identify`, rule X); its answer has a memo key of its own
  (`_key`, the one place a key is built: the usual key and `|!` and the CIKs), so it is never read by a lookup without
  the exclusion, nor the other way, and `is_degraded(..., exclude=)` builds the same key. It states the issuer record
  it reads through (`issuers`), which `pipeline.Clients`
  takes as the run's and the classifier as its own. 6 strategies in order of
  precision (caller's `cik` pin → manual override → `company_tickers.json` →
  EFTS Form-25/15 → observation-name company search → 8-K frequency rank),
  each strict-validated. Every read of an issuer's EDGAR record (names over time, first filing, filings, forms)
  and the name index go through its issuer record (`issuers`, built over its client, run date and `name_index=`
  unless given); a read that failed or was stale in a resolve (`_reset`/`_rested_on_failure`, the record's watch)
  marks its answer transient, as a failed search does. `expected_name` is the name an answer is checked with (the
  observed name, else the AV name, the first that can agree with another, `names.has_name`: a name with no word of
  three letters, 2U INC, is one, and the name tier and its observed-name acceptance read it, FB-004 part c, TWOU). The name tier finds its candidates in SEC's
  `cik-lookup-data.txt` (`sources/cik_lookup.py`: `CikLookupClient`, cached 30 days
  under `cache/sec_data/cik_lookup/`, and `CikNameIndex`, exact then
  character-prefix matches, read through their submissions JSON as the live
  search answered, `_index_candidates`: the one active holder of the exact
  name, else the 25-NSE/25/15-12G form filter's one filer the query names
  (`_one_filer`), else the exact name; when none of those candidates is accepted, the last resort
  `_agreeing_issuer` (FB-004 part c, DD): the one CIK listed under the same name written with its words run
  together, split or reordered (`names.same_letters`: EDGAR's DUPONT E I DE NEMOURS & CO for E I DU PONT DE
  NEMOURS) that existed by the era's first sighting, carried an agreeing name within 30 days of the date and filed
  a Form 25 or 15 within 540 days of it; several, or more than `AGREEING_MAX`, none; `name_index=`, wired by
  `default_clients`; the rules and the cases behind them in
  `docs/data-flow.md`), not
  in the live company search, which runs only without an index (the offline
  tests, the golden replay) or when it cannot load. The pin and the observation name (from
  `ObservationIndex.cik_pin_on`/`.name_on`, wired in by `pipeline.py`) replace
  the old `--cik-map`/`--names` CLI files; the pin still beats every other
  tier and is never written to the on-disk resolver cache. The pipeline looks
  each era up under its own pin and name (`resolve(..., pin=, name=)`) and
  its first sighting (`since=`): every search tier, and a cached answer from
  one, takes only a company that had filed by then. The identity stage asks it at two dates for each era: the capped date
  (`identity.era_capped_seen`: the last observation, or a later fails row of the era's own within 400 days) and the end of the
  era's own fails rows (`identity.last_sightings`: its own CUSIP's rows under its ticker for as long as they continue, each step at
  most 400 days, stopping before the ticker's next era; one seed in 2008 is asked at the security's real end).
  `identity.choose_first_pass` picks the answer. A miss has no CIK; a weak answer is a CIK from one of `WEAK_SOURCES`
  (`efts_name_mismatch`, `efts_frequency_name_mismatch`, `rename`); any other CIK is strong (`TickerResolution.strong`).
  Both strong and one CIK: the capped date's answer. Both strong and two CIKs: the end of the line's (another company of
  the name answers early: ITC Holdings 2016, Sprint 2020), unless it is `company_tickers` and the capped date's is not (by
  the end a successor holds the ticker and the name: Prologis 2011, Merck 2009). One strong: that one. Neither: no
  first-pass answer, the weak one (the capped date's first) kept aside, standing only when no pass infers an issuer and the era's own
  fails rows fit it (`EraIssuers.rows_fit`: at least `ERA_MIN_ROWS` rows, and guard G's row test). The
  name search drops EDGAR's nameless multi-company hits and ranks up to 5
  candidates by the words the name shares with their EDGAR names (current
  and former). The era-level passes, which read the run's other eras and its fails rows and are never saved,
  are `identity.EraIssuers`.
- `identity/identity.py` — architecture step 6: a security's identity, stages 1 to 4 behind one interface.
  `identify(index, clients, as_of=, limit=, log=, workers=, meter=, derive=, ftd=, verdicts=)` gives `Identity`: the refined eras
  (`refine_eras`, the second split after `observations.split_eras`: a CUSIP switch under the ticker, or a gap over
  `ERA_GAP_DAYS` no fails row bridges; its `derive` pairs (ticker, CUSIP) keep a part with no observation as an era
  of one derived observation, `_derived_era`, when it follows an era of its gap group and its CUSIP has no rows
  under the ticker from the next era's first day on; `identify`'s `derive` is the same pairs, each with the step it
  came from (`DerivedFrom`), and its `ftd` an index an earlier call opened, read in place of a new one). After stage 3
  `identify` checks every derived era that has no verdict yet against its step (`_check_derived`). Rule J: an era whose
  security is the one its step was refused from is made only when the price carried over across the step
  (`carried_price.step_price_ratio` within `CARRIED_PRICE`, or either price missing); else the verdict is `not_made` and
  the step stays refused (Uniti 2025: 4.91 to 8.09; IR 2020, ENR 2015, CFFN 2010, WE 2023). Rule X: an era from a
  `merged_out` step whose issuer answer is the origin's issuer while its security is another composite (both ids
  FIGIs; a placeholder is no second composite: Thornburg Mortgage 2008), with no pin and no
  given answer (`manual`, `cik_map`), is asked again with the origin's issuer excluded from every resolver tier (and
  from an answer 2b or the second pass gives): verdict `without_old_issuer` (Coca-Cola Enterprises 2016, Aaron's 2020,
  IGT 2015); what that lookup answers stands, another issuer or none. A new verdict sends stages 1 to 3 around again
  with it, at most `MAX_VERDICT_PASSES` (3) times, and the result equals a fresh call given the verdicts
  (`verdicts=`, `Identity.verdicts`; a pair with a verdict is not judged again). It logs `derived eras not made: N whose
  price did not carry over onto the line they came from (...)` and `derived eras asked without the old line's issuer:
  N (...)`. The same loop judges the folds (`_check_folds`): a part of the fails rows with no observation that
  `_split_era` joined to the era before it (`TickerEra.folds`, a `Fold` each: XRX 2017, ITT 2011, ALEX 2012) is kept only
  when (a) the era has no US composite of its own (no CUSIP it held before the fold, observed or from its fails rows,
  has one in OpenFIGI: the fold exists to supply one) and (b) stage 4b's own R1 test, `line_follow.corroborate`
  (`line_follow.step_refusal`), follows the step from the era's last CUSIP to the part's with the era's issuer; an era
  with no issuer fails (b). A fold that fails gets the verdict `fold_refused` and the next pass splits the part off as
  a derived era (`refine_eras(unfold=...)`): HTZ 2016 (R1 refuses `name`), Z 2015 (`merged_out`) and NRF 2014 (the era
  has a composite of its own) are new securities, not the old one. A read that failed or came from a stale copy decides
  nothing: the fold stays and the era gets a `resolution_degraded` item. It logs `folds not kept: N (...)`. Stage 1
  alone (`refine_eras` without a verdict) keeps every fold. The run's fails index, opened by stage 1 over the fails files (`ftd`;
  `ftd_lo`, its `opened_from`; later stages ask it for more rows), each era's issuer (`issuers`, by era key, the one source of an era's CIK: asked at its capped date and at its last sighting,
  `era_capped_seen` and `era_last_seen`, with its own pin, name and first sighting; `choose_first_pass` takes one answer), each era's FIGI resolution, the securities, each
  security's CUSIPs over its whole life (`cusips`, their rows followed to the run date), the identity review items, and the
  facts later stages read: `tier`/`resolution_source` (the lookup tier that found an era's or a security's issuer;
  "security_master" for none), `rows_decided` (stage 2b's `ticker_rows` and `later_ticker` eras: stages 4c and 10g
  keep their CIK in force), `securities_of(resolutions)` (stage 4b's rebuild after a fold, `build_securities`) and
  `renames(resolutions)` (contract/id_changes.csv: a placeholder one FIGI now holds, across a class label). Its
  adapters: the issuer lookup (`IssuerLookup`: `TickerResolver`, or a double with the same five methods; no
  capability is probed), the run's issuer record, OpenFIGI and the fails client. The CUSIP links between eras
  (`security_master.cusip_handoffs`) are computed once, for the second pass and stage 3; a foreign era
  (`foreign_ticker_eras`) is given once, to `FigiResolver(foreign=)`, which guards it as an unconfirmed one. The era
  helpers live here: `era_cusips`/`candidate_cusips` (an era takes an FTD CUSIP only when a fails row's description
  names its issuer, `names.description_matches` against the observed and EDGAR names — spec D21), `era_capped_seen`/`capped_sightings`
  (the capped date) and `era_last_seen`/`last_sightings` (the last sighting, followed along the era's own CUSIP rows),
  `era_rows`. The second pass (`EraIssuers.infer`) runs twice on the same first-pass answers, with the capped dates and then
  with the followed ones; an era the first run answers keeps that answer. `EraIssuers` is the era-level issuer passes, over the issuer record and the
  lookup's frequency candidates, with their own state (`degraded`, by era key: a failed search, or an issuer read
  that failed or was stale since the era began, reported `resolution_degraded` beside the lookup's own
  `is_degraded`). `infer` is the second pass, never cached, for eras left
  with no CIK and no pin (a renamed issuer files no Form 25 and keeps filing
  10-Ks): an 8-K frequency candidate (`efts_frequency_renamed`), or the issuer
  of an era linked by a shared CUSIP or a CUSIP switch after a rename
  (`shared_cusip`/`cusip_handoff`), each
  through guard G (existed by the era's first fails row, every row's
  description matches a name it carried by 30 days after the row, the only
  candidate that did) and matching one of the era's own names; a switch's
  issuer must be the old CUSIP's, renamed (existed when it began, renamed near
  the switch, each old row named word by word by a name it carried in the 30
  days up to that row or by the name the switch renamed it from, no
  other CUSIP of its own and of the same class, begun before the switch,
  trading at it). Answers are checked again at the fixed point; each carries
  the check flag `issuer_inferred`. Rule D (FB-004 part c, `cusip_issuer`, after the fixed point, on the answers
  the others made): the one issuer of the other eras holding a CUSIP of the era's issuer code (its first six
  characters) over the same dates, when it had filed by the era's first sighting; no name check, the code is the
  evidence (FNFV Group, a tracking stock, on Fidelity National Financial's 31620R105; UHALB on U-Haul Holding);
  eras of two issuers or none give nothing. Rule C also runs over first-pass answers:
  where the CUSIP evidence points elsewhere, the first pass's answer stands
  and the check flag `issuer_cusip_disagrees` names both CIKs. Sub-plan 5h: `check_names` (stage 2b, never
  saved): a first-pass name-search answer is replaced by the one other CIK SEC's name index lists under exactly the
  observed name that carried it over the era's span (`name_in_force`: ABBI 2008, an era with fewer than
  `ERA_MIN_ROWS` fails rows of its own) or, for an era with at least that many, whose name the era's own fails rows
  carry and the answer's do not (guard G's `_fits_rows`, `ticker_rows`: ERA 2013 is Era Group's; the rows alone
  decide, so the result never depends on which holder the first pass named);
  reported as `issuer_inferred`. Before either (FB-013, `_later_ticker`, no name index needed): for an era whose
  ticker the fails data does not show near its dates (`guarded_eras`), the company SEC's ticker map lists the ticker
  under (`IssuerRecord.listed_under`) is the issuer when it is not the answer, had filed by the era's first sighting,
  the ticker's first rows after the era are its rows (guard G) and it carried a name agreeing with the observed one
  by then; not when the ticker's last rows before the era are the answer's own, a stale row (`later_ticker`: the
  GHC row of 2012-06-29, GRAHAM HOLDINGS COMPANY, is Washington Post Co's, CIK 104889, which took the ticker and
  the name on 2013-11-29; the name search had answered Graham Corp, whose name compares as the same one word). A
  `ticker_rows` or `later_ticker` era keeps its CIK in force in stage 4c and the contract's issuer timeline
  (`Identity.rows_decided`): its observed name is not the issuer's on its dates.
- `identity/security_master.py` — `FigiResolver.resolve_many()` (a `sec_id` pin wins;
  else CUSIP jobs, then the ticker, then a name filter — see the spec's
  Implementation notes), `build_securities()` (merges eras sharing a
  `sec_id`; `Security.observed` is True when any of its eras is not derived, `Security.figi_ticker` is OpenFIGI's
  ticker for the line when its eras' candidates give exactly one, and `observation_conflict_review`
  reads the caller's observations only); `identity.identify` is the one stage that calls them. `Issuer` (a CIK and its EDGAR names;
  `issuers_by_era` builds the era key -> `Issuer` map that `identity.candidate_cusips`,
  `resolve_many` and `build_securities` take, the one source of an era's CIK,
  read with `cik_of`) is its type. The identity guard: an era the fails
  data covers but never shows under its ticker (`guarded_eras`), when the one
  line its issuer and class are confirmed on over its dates exists, is placed
  on it (`figi_source=backfill`) instead of asking the ticker or name tier
  (with no such line it keeps them: a stale snapshot's dead company finds its
  own line; own-name picks are not checked by `_contradicted`, since a line
  keeps its composite through a change of issuer, Merck 2009); `resolve_with_identity_guard` takes back
  a weak era whose merge would cross another security's confirmed span of the
  ticker (`crossing_weak_eras`, review `identity_detached`, `detached_review`), and (FB-003 IR, FB-001 CHK) a weak
  era with CUSIPs of its own that took a composite another era confirms by a different CUSIP, when no CUSIP carries
  the line on (`weak_eras_on_another_line`; `_carrying_links`: a shared CUSIP, or a lone CUSIP switch, whose new
  CUSIP no other era's old one ended into and which is no bankruptcy's emergence) and the evidence says two lines:
  a bankruptcy between them (`bankrupt_between`, `identity._went_bankrupt`: a Q symbol on the old CUSIP's fails rows,
  or an Item 1.03 8-K within `BANKRUPTCY_DAYS` before the new CUSIP's first row and no earlier than
  `BANKRUPTCY_LEAD_DAYS` before the old CUSIP's last; decision 9), or the line's issuer going on as another
  confirmed security of the run (same CIK and class, begun after the line and no later than the confirmed era: Trane
  beside the new Ingersoll Rand). A redomicile with no CUSIP link in the fails rows stays one line. The eras of one
  such line go where its last era did (a placeholder of its issuer, or the line it joined: old IR joins Trane), and a
  switch to an era confirmed on the composite a detached era left does not take it back; and (FB-014, SandRidge
  2016) a weak era whose line a bankruptcy left behind while its ticker went on as other shares, though no era of
  the run is confirmed on the composite (`weak_lines_left_behind`, over `identity._LeftBehind`: after the last day the
  era's own CUSIPs traded under the ticker the ticker's fails rows are another CUSIP's, the own CUSIPs have no
  trading row later than `LEFT_BEHIND_SETTLE_DAYS` after that CUSIP's first, and `_went_bankrupt` between them; the
  old stock, only observed in 2014, had taken the id of the stock issued under the plan, and becomes
  `CIK1349436-COMMON`; a new CUSIP with no bankruptcy, Equinix 2015 or Thomson Reuters 2018, changes nothing); and
  (FB-003, Fox 2019) a CUSIP switch is no carrying link when another registrant replaced the class
  (`identity._Replaced`: the old registrant's Form 25 and an 8-K with item 2.01 or 5.01 within `REPLACED_DAYS` of the
  new CUSIP's first fails row, the new registrant's Form 10-12B/10-12G (a spin-off's registration; an S-4 with an
  8-A is an exchange of shares, Clearwire 2008) from `REGISTRATION_LEAD_DAYS`
  before it, and no 8-K12B/8-K12G3 of the new registrant: Twenty-First Century Fox's FOXA to Fox Corporation's;
  Merck 2009, Clearwire 2008, Express Scripts 2012 and Disney 2019 are one-for-one and stay one line), so the old weak era is another
  line (`weak_eras_on_another_line`'s `replaced`), and (`weak_eras_before_registrant`, over
  `identity._RegistrantAfter`) a weak era with CUSIPs of its own, no CUSIP carrying it on to an era confirmed on the
  composite, whose ticker SEC lists today under another company that had filed nothing when the era began and is no
  8-K12B/8-K12G3 successor registrant (`IssuerRecord.listed_under`, `first_filed`) loses its pick, even when no later
  era of the run is confirmed on the composite (`detached_review`: `BEFORE_REGISTRANT`); `superseded_placeholders` marks a placeholder a later FIGI line of its
  issuer and class holds the ticker for (not listed today), and `identity.left_behind_placeholders` one a
  bankruptcy left behind that way (EDGAR's listing under the ticker is the later shares': stage 5 takes it as not
  listed, so the exchange's Form 25 is its ending). Its era-level
  review rows: `ticker_unconfirmed_review` (`ticker_unconfirmed`) and
  `observation_conflict_review` (`observation_conflict:<date>`). `Security.line_tickers`/`own_tickers()` (the era
  tickers and the ones stage 4b found; every own-ticker check reads it); `cusip_handoffs` times a switch from
  `ftd.settled_last` (SLE to HSH); `_handoff_joins` lets a shared CUSIP reach an era the ticker or name tier picked
  on its own name (SPW to SPXC); `cusip_job` is the one OpenFIGI CUSIP job. Sub-plan 5h: `foreign_ticker_eras`: an
  era whose rows under its ticker are all another security's (none names its issuer) is guarded too, and its
  backfill may take the line whose confirming CUSIP traded over its dates (`FigiResolver(cusip_span=, foreign=)`:
  UAG 2008-09 on PAG's line), or, when none traded over them, the one whose CUSIP's last trading row came at most
  `ERA_GAP_DAYS` before the era began (FB-004 part c: the snapshots kept listing a dead company, so the era is its
  line's stale tail, BSC and CCU of 2008-11 to 2009-06 on Bear Stearns' and Clear Channel's FIGIs, instead of a
  placeholder no Form 25 can end). `_handoff_joins` lets a CUSIP switch join a lettered era to a plain-named era of its
  issuer when OpenFIGI names that line with the same letter and the issuer's eras name no other
  (`identifiers.figi_class_letter`, `one_class_issuers`: MSG onto MSG Networks, LMCA onto Starz); never a shared CUSIP
  (tracking stocks). The other way too (FB-003): a switch joins a plain-named era to a lettered one of its issuer
  when `identifiers.fits_class` holds over `issuer_letters` (the letters the issuer's eras name) and the letter the
  old CUSIP's fails descriptions name: WPO ("WASHINGTON POST CO CLB") onto Graham Holdings' class B GHC.
  A placeholder holds one line (FB-005): `split_placeholder_lines`, the end of `resolve_with_identity_guard`,
  groups the eras that took one placeholder (an issuer and class) by shared CUSIP or a CUSIP switch
  (`_carrying_links`), makes two groups separate lines when their CUSIPs' trading fails rows (`FigiResolver.cusip_span`)
  share `PLACEHOLDER_OVERLAP_DAYS` (60) days, puts an era with no CUSIP of its own with the line holding an era of its
  ticker (else the nearest in time), and, with more than one line, names every line by its first CUSIP (the earliest
  trading row: Liberty's `CIK1355096-COMMON-53071M104` for LINTA/QVCA and `-53071M302` for LCAPA); one line keeps
  the unsuffixed id. `Identity.renames` leaves out a placeholder whose lines are suffixed (that is a split).
- `identity/history.py` — a security's dated history: its sightings
  (`ticker_sightings`, `cusip_sightings` and `observation_map_rows` read an era's `caller_observations`: a derived
  observation is no sighting and no row of `observation_map.csv`)
  (`ticker_sightings`/`cusip_sightings`, and `span_sightings` for a successor the run added, stage 9d: its span's
  days, source `SPAN`, and its CUSIPs' fails rows; a fails row is a ticker
  sighting only when its symbol has a letter, because SEC's Aug–Dec 2007 files mask some symbols as "**********";
  a ticker observed with and without a separator is written one way per security, the separator's, except from the
  day the line itself lost it, `_bare_since`, FB-013: OpenFIGI's ticker for the line, `Security.figi_ticker`, is the
  bare spelling, the security's rows under the ticker are two or more CUSIPs' in turn, and from one of them on the
  caller saw the bare spelling alone; Hubbell's class B is HUB-B to 2015-12-27 and HUBB from its new CUSIP's first
  row, while BF-B, FCE-A and a one-CUSIP VIA-B keep the one spelling),
  `ranges_from_sightings()` (dated `Sighting`s into `ticker_history`/
  `cusip_history` ranges; `value_on` reads one), `backfill_cusips()` (the
  CUSIPs of fails rows under a dead security's tickers in the 120 days before its
  end, not under a deleted symbol, whose description names its issuer), and the range review
  (`ticker_range_review`: `ticker_range_overlap`/`ticker_shared`).
  `filtered_ticker_sightings()` drops a backfilled observation
  (`is_backfilled`: no fails-to-deliver row of the security's CUSIPs under the
  observed ticker within 30 days, but at least one under another symbol) from
  the ticker_history-building sightings only — the delisting search's own
  copy is untouched; it also drops an old CUSIP's settling tail (`_settling_tail`: its fails rows from the one that
  opens its last one-price run on, dated once another CUSIP of the security, begun after it, has begun; Kraft's KFT
  rows of 2012-10-15 after MDLZ's CUSIP began) unless another row sights the same ticker that day.
  `observation_map_rows(eras, sec_id_of, issuer_cik_of, history, conflicts)` builds
  `observation_map.csv` from the history's own answer (`Histories`):
  one row per observation, its era, `sec_id`, issuer CIK, `ticker_history`
  spelling/coverage on its date, and a status (`unresolved`,
  `after_unconfirmed_delisting` — past the clip, but the delisting that set it
  has no confirmed last-trade day, so the caller keeps and checks the member
  rather than dropping it — `after_delisting`, `conflict`, `backfilled_ticker`,
  `mapped`) — the caller's join surface:
  membership from this table, ticker look-ups through contract/security_history.csv (the
  `ticker_history` ranges, which are not written) by `history_ticker`. A row from before the fails files give a new
  CUSIP its symbol (`…ZZZZ`, or the CUSIP's own first six characters: `_no_symbol_yet`) is no ticker of its own; it
  dates the ticker's first day when the CUSIP's first row under the ticker follows on the next trading day
  (`_first_days`, FB-022: a fails row carries the close of the trading day before its date, so the security traded
  on the unassigned row's day; Liberty Media 2016, Monster 2015). An observation is a sighting of its era's ticker. Sub-plan 5h: `cusip_sightings` drops an old CUSIP's `…ZZZZ`
  settle rows dated once another CUSIP of the security, begun after it, has begun (MSG 2015: the new CUSIP's range
  starts on its first row). What the sightings say of the security's trading (the ticker on a day, the last
  own-ticker sighting) is the trading record's (`endings/trading_record.py`).
  Where a security's history ends is one module, `Histories` (architecture step 5): the caller passes the observed
  securities, their sightings, their CUSIPs, the fails index, a summary of every ending (`Ending`: key, `LastTrade`,
  bucket, successor, exchange; built by `delistings.Delisting.ending`, so history imports no `Delisting`), the
  listed-today answers, the securities the run adds, and an `exchange_today(security, ticker)` adapter for an open
  range's exchange (asked only when the rows are read). It answers `going_on` (the endings that do not end their
  security: `rewrites.mark_going_on`'s input), `end(sec_id)` (`SecurityEnd`: the day, whether it is a confirmed last
  trade, read from `LastTrade.confirmed`, and whether the security is listed today), and `ticker_rows`/`cusip_rows`.
  Its three rules: an ending ends its security unless its successor is the security itself, or it is a merger or
  exchange transfer (`CONTINUATION_BUCKETS`) with a confirmed last trade after which its own CUSIPs keep trading
  under its own tickers (`_continues_after`: `CONTINUATION_MIN_ROWS` 20 rows over `CONTINUATION_MIN_DAYS` 60 days
  at `CONTINUATION_MIN_PRICES` 2 prices; WRK, DIS), or any other kind with a confirmed last trade of a security
  listed today whose CUSIPs begun by that day so trade on (it returned: GTX 2021, FB-001; a CUSIP begun after the
  ending is a new line's, CHK 2021); the history ends at the end day (`exit_kind.end_day`) of the
  last ending that ends it, unless it is listed today. A successor's ticker is not its predecessor's
  (`_successor_starts`, over the endings: the successor's first sighting under the ticker within `TAKEOVER_DAYS`,
  120, the handoff window, defined here, after the confirmed last trade, else from the delist date less
  `SUCCESSOR_TICKER_LOOKBACK_DAYS`, 30), and a range carried only to the security's next ticker stops the day before
  another security's first day under it (`_clip_at_takeovers`, over the built ranges: its own last sighting under it
  is earlier, the range is not its security's end; MSG 2015): two conditions, kept apart (the plan's step 5 log says
  why). A security with an ending that ends it whose ticker a successor took is not listed today (AON 2012). A
  security with no ending that ends it, not listed today, closes at its last sighting - unless that sighting is a
  fails row under an own ticker within `DATA_EDGE_TRADING_DAYS` (2) trading days of `FtdIndex.files_end()`, the fails
  data's last day (FB-004: DIS, whose issuer CIK lists nothing): it is still trading, its history stays open; so is a
  fails row under an own ticker at the edge under a CUSIP no security of the run holds whose description names the
  security (`history.unheld_trading_days`, `description_names`: XOM 2026, 30233Q108 "EXXONMOBIL HLDGS CORPORATION" after
  the holding-company reorganization whose line follow was refused for want of a filing)
  (`Histories._at_data_edge`; a security gone weeks before the edge, SBNY, FRCB, is not; an ending that ends it
  always wins; an index over rows alone has no edge). `keeps_trading` is the one continues-after test, shared with
  `endings/registrants.goes_on`. Pipeline
  builds it twice (`pipeline._histories`): stage 9b's first step reads `going_on`, and 10b and 10c2 read the
  history over the final delistings.
- `identity/added_securities.py` — `AddedAcquirer`/`AddedSuccessor`/`AddedLineSuccessor` (`AddedSecurity`; the last a FIGI
  line's successor stage 4b found, linked in stage 9 and added only for an ending that takes it): a
  security the run adds that no observation names, with its one
  ticker_history row. An `AddedSuccessor`'s span runs to its own ending's last trade when stage 9d found one
  (`last`).
- `identity/line_follow.py` — sub-plan 5a, stage 4b as one module (architecture step 7a): a security's line across a CUSIP or
  ticker change. Its interface is `follow_lines(identity, clients, *, as_of, log, meter) -> Lines`: the caller passes
  the identity stage's answer (left as it was: a security the follow changes is a copy; its fails index, which the
  stage asks to follow the lines' rows, holds more rows after) and the
  run's clients (`LineSources`: the issuer record, the EDGAR client for a successor filer's listing, EDGAR's
  full-text search as `Clients.full_text_search` states it, and OpenFIGI) and gets the securities, era resolutions and CUSIPs after the follow, the folds
  (`renames`), the line successors (`successors`, sec_id -> `LineSuccessor`) and the review items of stages 1 to 4b
  (a folded placeholder's moved to its FIGI line, its `no_figi` dropped). Behind it: the rounds, the holders, the
  8-K text sources (`_Reads.text_sources`, the filter before the `MAX_TEXTS` cap, read once per line end in the
  round the line first has no step: YRCW's two reverse splits under its own ticker, then Yellow's YELL and CUSIP
  985510106, which only the rename 8-K names; Reliant Energy's RRI Energy step, then the 8-K that names GenOn; for
  a line they name nothing for, in the first round only,
  an issuer EDGAR dates a rename to within `RENAME_DAYS` of the settled row gets `_Reads.renamed_cusips`: one
  `FtdIndex.every_row` pass over the window for a CUSIP, none of its own, whose rows carry a name the issuer held
  then, DeVry's ATGE that EDGAR no longer lists and the 8-K 5.03 does not name), the fold (`_fold`: a fold of a fold
  points at the last FIGI) and sub-plan 5h's `_today_holder_fold`, and every EDGAR read in one place (`_Reads`: the
  issuers' submissions, filing lists and 8-K texts through the run's issuer record, listed-today from the issuer's
  profile, `listing_status.lists_on_major_exchange`; the other-registrant search and its filer's listing through
  `other_registrant`, a failure there `read_failed`: a search that counted itself degraded, production's answer of
  no hits for a failed read, a search or a filer listing that raised; a filer listing answered from a stale copy
  decides, and the step is degraded. So an attach, a fold or a line successor never rests on a failed read). Its
  rules stay importable for their own tests and only
  `follow_lines` calls them in a run: `candidate_steps` (the
  next step in the fails rows from `LINE_DAYS` (10) trading days before the old CUSIP's settled row to `LINE_DAYS`
  after its last row (a flat settling tail can run weeks: QRTEA's QVCGA began the day after QRTEA's last row, 14 trading
  days after the settled one): a new
  CUSIP under the line's ticker, its `…ZZZZ`/`…D` spellings, a ticker of the issuer EDGAR lists or its 8-K text
  names (`text_symbols`, which also reads "symbol ... changed from X to Y" as Y, curly quotes included: sub-plan 5c, RRI to GEN; `text_cusips`), or the same CUSIP under a new non-OTC ticker; with `late` (FB-015, asked by the stage only of a
  line whose FIGI its own CUSIP or a pin confirms and that the round found no step for), a step that begins after the
  window, since the fails files hold a row only on a day with a fail: the first later CUSIP under the line's own
  ticker (Ocwen's post-split CUSIP, first row three years after the old one's last), which the stage takes only when
  OpenFIGI names the line's own composite for it, or the same CUSIP under a ticker EDGAR lists for the issuer or
  its 8-K names (ONIT); `corroborate` opens a late step's bankruptcy and listing-ended windows at the old rows'
  last day and asks it for no filing near its first row, and a late step that is not confirmed is dropped with a
  log line and no review item; never a CUSIP another
  security holds, nor a switch while the old CUSIP trades on at changing prices more than `SWITCH_DAYS` trading
  days after the new CUSIP's first row, applied only at the data edge (the old CUSIP's last row within
  `SWITCH_TAIL_DAYS` of `FtdIndex.data_end()`, the fails data's last day, passed as `data_end`: a live line has no stop to see; CHTR's new
  preferred; elsewhere the window is the whole of it, HYH 2018); the own-ticker pick is made before held CUSIPs are
  dropped, and a pick another security holds is no step (LMCA 2016), unless the issuer was renamed (FB-003, News Corp
  2013): the held pick's rows do not name the issuer (the spin-off kept NWSA) and another free switch's rows name the
  issuer's EDGAR name in force from its first row (`issuer_names`; Twenty-First Century Fox's FOXA, found through
  its renamed-CUSIP scan or its 8-K text), which is then the issuer's own next line (`_issuers_next_line`; of
  several, the one that began the day the held pick did, FOXA beside the new News Corp's NWSA, class B a day
  later)); `corroborate` (R1: refused for an 8-K 1.03 in
  [first − 180, first + 30] d, an OTC move (a new symbol with an 8-K 3.01, a Form 25 or a Form 15 within
  `FILING_DAYS`; a Form 25 counts only when `form25.about_class` says it is about the line's own class, an 8-K 3.01
  unless its section `form25.names_only_other_group`: Liberty Interactive's March 2018 Form 25 and 3.01 are the
  Liberty Ventures group's, so QRTEA's rename on the same CUSIP is followed; an unread Form 25 counts), a description that names no name in force (a holding word does not
  count, `names.description_names`: ExxonMobil Holdings, XOM 2026, keeps the name), a class conflict, a
  registrant that merged out or that another CIK's 8-K12B/12G3 replaces (`other_registrant`, the CIK of
  `successor_filer`, which also gives the day it filed: stage 5's successor registrants), no filing stating
  the change, or a failed `other_registrant` read (`read_failed`); the registrant carries on by a periodic report in `PERIODIC_FORMS`, which includes the small-business
  forms 10-K405, 10-KSB, 10-KSB40 and 10-QSB, or by a registered investment company's report in
  `INVESTMENT_COMPANY_FORMS` (N-CSR, N-CSRS, N-Q, N-CEN, NPORT-P, NSAR-A, NSAR-B: Altaba 2017), each for a period
  after the step); `decide` (R2: attach, fold a placeholder, a line successor, or
  refused: `unsettled`, `type` for an OpenFIGI preferred/warrant/right/unit, `other_issuer`, `class`, which
  `fits_class` can lift for a COMMON placeholder: WPO's "CLB" to GHC's class B). A placeholder is not kept from its
  next CUSIP by a security of its own issuer that holds it and that it would fold into (`holders_for`: same issuer, a
  class that fits, no other CUSIP of the holder failing more than `LINE_DAYS` after the CUSIP's first row; a FIGI
  line still takes no step to another security's CUSIP, WLL 2017: IAC 2008, WPO 2013). Up to
  `MAX_ROUNDS` steps a line (the tickers a round attached, CEB beside EXBD, are loaded into the fails index when the next begins); a CUSIP, or a successor composite, one
  security took is held for the rest of the round (a second is refused `taken`). A FIGI line with a line successor
  is not listed today (stage 5's `retired`). A failed EDGAR read is never cached, and any degraded read of a CIK gives each
  of that CIK's steps a `resolution_degraded` row, as does any other SEC read of the step that counted itself
  degraded, and so does a security with no step when a read of its CIK failed. Review flags `line_followed`,
  `line_follow_refused:<why>` (info), and the run log names each refused step (`line follow refused: <sec_id>
  <old CUSIP> -> <new CUSIP> under <symbol> from <day> (<why>)`). Stage 9's own-registration link reads `is_line_symbol`, `text_cusips` and
  `composites` too (the same R2 reading of a same-CIK 8-K12B's new CUSIP). Its real cases replay offline from
  `tests/fixtures/lines/` (`scripts/build_line_fixtures.py`), through the rules and through `follow_lines`; the
  stage's own rules are tested at `follow_lines` with doubles (tests/test_line_stage.py). It also returns the steps
  it refused (`Lines.refused`, a `RefusedStep(sec_id, step, why)` each; its `sec_id` follows a fold, like the review
  items'), which `derived_lines` reads. `follow_lines(..., memo=LineMemo)`: the reads of a line's end (the issuer's 8-K
  texts, and the renamed-CUSIP pass over the fails files when they name nothing, which is most of the stage's time) are
  taken from the memo when the line is what an earlier call read, and asked again, then kept, when it is not. The
  stamp that decides is everything the two reads and their round read: the security (issuer, class, name, eras with
  their observations, line tickers), its eras' resolutions, its CUSIPs, the line's end in the fails index and whether
  it is the call's first round; a read that rested on a failed request or a stale copy is never kept. The answer is
  the same with or without a memo; the log says how many line ends were taken and how many read again.
- `identity/derived_lines.py` — seeds-only parity S2: which refused steps are lines of the run. `derivable(refused,
  securities, profile)` gives the `(ticker, new CUSIP)` pairs, each with its origin, a `DerivedFrom` (the first step
  that names a pair wins; the ticker as the security's eras spell it, `BF-B`
  not the fails files' `BFB`; one pair per ticker of its eras, never a line ticker learned from the fails rows) of the refused SWITCH steps whose
  reason is in `DERIVABLE` (`merged_out`, `other_registrant`, `name`) and whose new rows' descriptions name the old
  line's issuer: `names.description_names_issuer` against `old_line_names` (the line's observed names and every
  EDGAR name its issuer carried until the day before the step). `description_names_issuer` is `description_names`
  with at least one word as spelled: SEA LTD is not SPECTRA ENERGY (SE 2017), one word of GLOBAL is not LIBERTY
  GLOBAL naming TELEWEST GLOBAL. On the seeds input it accepts 42 `merged_out` steps, 3 `other_registrant` and 10
  `name`; on the full input 13, 0 and 0. `identify_with_lines(index, clients, *, as_of, limit, log, workers, meter)
  -> (Identity, Lines)` is the loop `_run` calls: `identify` and `follow_lines`, then again with the pairs `derivable`
  gives (`derive=`) over the fails index the first round opened (`ftd=Identity.ftd`), until a round earns no pair it
  has not already used or `MAX_DERIVE_ROUNDS` (3) rounds have added one (it logs `not derived` for the steps left). It
  returns the last round's identity and lines, so a derived line is a security of the run like any other: the FIGI
  stage resolves it by its own CUSIP, the handoff stage pairs it with the line before it, the finder searches its
  Form 25. The step stage 4b refused is held by the derived security in the next round, so it is not refused again.
  Each round's `Identity.verdicts` (`not_made`, `without_old_issuer`, `fold_refused`) go to the next round's `identify`,
  and a pair with `not_made` is never counted as new. The loop makes one `LineMemo` and gives it to every round's
  `follow_lines`, so a repeat round asks stage 4b again only about the lines the round touched (a derived era joined
  the security; the new CUSIP of a step is now a derived line's; its eras, resolution, issuer or CUSIPs changed; the
  fails index shows the line's end otherwise) and takes every other line's reads from the round before.
- `identity/carried_price.py` — whether a share became one share across a CUSIP change: `CARRIED_PRICE` (2/3 to 3/2,
  the one band), `price_carried(ratio)` (None is carried) and `step_price_ratio(ftd, ticker, old_cusip, new_cusip)` (the
  new CUSIP's first fails price under the ticker over the old CUSIP's last on or before it; None when a side has no
  row or a price is missing or not above zero). `identity.identify` (rule J) and `endings.handoffs` (a continuation by
  timing across two issuers) both read it; `handoffs` defines no band of its own.
- `identity/ticker_evidence.py` — decision 1: what ties a placeholder's ticker to its
  CIK. A resolver tier that names the ticker (`TICKER_TIERS`), else one
  EDGAR full-text search of the CIK's own filings (`full_text_search(...,
  ciks=)`), cached like every search.
- `identity/issuer_in_force.py` — the issuer CIK on each sighting's date: the era's CIK when its EDGAR name that day agrees
  with the observed name, else the one other CIK SEC's name index lists under that name whose name agreed then
  (MRK 2008: old Merck & Co, CIK 64978). `issuer_changes` dates each change: it sorts sightings by day then CIK
  and records at most one change per day (a same-day sighting under another CIK changes nothing). FB-004:
  `with_registrants` adds a security's successor registrants (`endings/registrants.py`: the new registrant a
  holding-company reorganization put in the old one's place) as the issuer in force from the day they registered,
  dated after the timeline's last change; stage 10c3 applies it, and only for a security whose line goes on.
  FB-015, for a seed list, where a security has one sighting and nothing after it names a later registrant: the
  other CIK must have filed a registrant's own report (`REGISTRANT_FORMS`: 10-K, 10-Q, 8-K, 20-F, 40-F, 6-K,
  N-CSR) no more than `FILING_DAYS` (400) before the sighting (`_filing_around`: LUMN's CIK 1008114 is another
  "LUMEN TECHNOLOGIES INC" whose reports stop in 1999, and MAN's CIK 62072 holds only its holders' Schedule 13Gs);
  a sighting with no name (stage 10c3
  passes each derived era of a sighted security as one, on its first day) changes the issuer on its own day (MDT,
  ICE, PRGO, MYL: the line after the refused CUSIP step is the new registrant's); and `listed_issuer` ends the
  timeline of a history open on the run date with the company SEC lists the ticker under
  (`IssuerRecord.listed_under`), when its EDGAR name agrees with the security's and its name's first day or the
  old issuer's Form 25 or 15 dates the change (MRK: old Merck kept filing, so no era names CIK 310158). The filing
  days come through the injected `filed` read (`IssuerRecord.recent_days`, None for a list that is not known and [] for a company with no filing, which was not filing; `filed_in` reads a submissions
  JSON's own block for the tests): the run's profile keeps no filings block, so before FB-015 the Form 25 bound
  below never applied in a run.
  A change to a CIK whose agreeing name began before the old CIK's listing ended (a holding company's, from its
  formation: ICE 2013, formed 2013-03-20) is dated no earlier than the old CIK's first Form 25 or Form 15 in the gap
  between the two sightings (`_deregistered`, its submissions JSON's recent filings).

## endings/

**`endings/`: every delisting, found, dated and classified, stages 5 to 9g (network):**
- `endings/trading_record.py` — architecture step 14: a security's trading record (CONTEXT.md), what its sightings and its
  own CUSIPs' fails rows say of its trading, read by the finder and the last trade module; data only, no closure.
  Two constructors: `TradingRecord.observed(security, fails, cusips[, sightings])` (a security of the run: its
  sightings `history.ticker_sightings` unless given; its last era's ticker and name, its eras' first and last day)
  and `TradingRecord.added(security, ticker, span, fails, cusips)` (stage 9d's added successor, over its span, no
  era). Its answers: `ticker`, `known_from`, `known_until`, `expected_name`, `own_tickers` (the eras', the line's and
  an added security's own), `has_cusips`; `ticker_on(day)` (the latest sighting on or before the day, else the
  first), `last_seen` (the last own-ticker sighting, not an OTC tail; else `known_until`), `seen_after(day)`,
  `seen_in_fails_after(day)` (a fails row under an own ticker), `span` (a sibling's first sighting to its last own
  one), `tickers(lo, hi)` (every ticker sighted in a window: SAVE and SAVEQ); `trades_after(day)`
  (`ftd.trades_after` over its own CUSIPs' trading rows, any symbol), `traded_within(day, days)` (a trading row,
  `ftd.is_trading_symbol`, in the days up to a day: the late reach), `cusip_switches` (each later CUSIP's first
  sighting, `history.cusip_sightings`: QGEN 2026), `letter_hint` (R2: a letterless class's one letter its CUSIPs'
  descriptions name, `identifiers.descriptions_class_letter`), `taken` (rule 3, `ticker_taken`: the trading day
  before another CUSIP's first priced fails row under the ticker, on or after the own last one; a $0.01 row is no
  trade) and `trades_until()` (rule 4's floor, `last_row_trade_day`: the trading day before `ftd.settled_last`'s row
  of the CUSIP it held last). Cached answers are read from the one fails index on the warm pass's threads too.
  Tested at its interface (`tests/test_trading_record.py`).
- `endings/successors.py` — the successor after a FIGI change: a security of the run
  that starts right after the last trade (`successor_in_run`, `SecurityStart`: the one candidate of the same issuer
  and share class outranks a ticker another issuer took, FB-003: Alcoa Inc's common went on as Arconic while Alcoa
  Corp took AA; two of the issuer, or one of another class, stay ambiguous),
  else the successor issuer's 8-K12B found by full-text search
  (`successor_search_args`, `filing_search.successor_query`, `successor_from_8k12b`,
  `successor_search_name`). Sub-plan 5c: `successor_by_terms` (the security an R1 statement names, the statement
  of the ending's own-share reading: the same issuer's class the target names, or a new issuer's line,
  `own_shares.new_issuer`, first sighted in the window and named by the target, `own_shares.names_target`; a
  target that is a subsidiary of the registrant, a split-off's Splitco, `OwnExchange.target_subsidiary`, names the
  new issuer when one is found, as `OwnShares.target_issuer` reads it, and the registrant's own classes drop out:
  FB-003, Liberty Capital 2011 into the new Liberty Media Corporation, not Liberty Interactive's Series A, which the
  registrant's former name ties); a successor is looked for around the ending's anchor (`Delisting.anchor`,
  `last_trade.anchor_day`). It imports `delistings`; the classifier no longer imports it (step 7b: no classifier,
  successors, delistings cycle).
- `endings/registrants.py` — FB-004 part b, the issuer in force after a holding-company reorganization: Disney 2019 (CIK
  1001039 to 1744489) and WestRock 2018 (1636023 to 1732845) ended the old registrant's listing with a merger-looking
  Form 25 and an 8-K12B of the new one, while the security's own CUSIP kept trading under its ticker; the old CIK lists
  nothing today and the later Form 25 (WRK 2024-07-08) is the new registrant's. A `Registrant` is the CIK whose
  8-K12B/8-K12G3 names the old registrant around the ending, and the day it filed. `goes_on(d, record)`: the ending is
  not real (the security is its own successor), or a merger or exchange transfer with a confirmed last trade after which
  the security's own CUSIPs keep trading under its own tickers (`history.keeps_trading`, the clip rule's test).
  `SuccessorRegistrants.of(record, delistings)` searches (`line_follow.successor_filer`, the search stage 4b's
  other-registrant check sends, one cache entry for both; a filer that is another issuer's own still-listed stock is
  skipped) once for each ending that goes on, at most `MAX_REGISTRANTS`; no search capability, none. A successor
  registration alone changes nothing: a merger the security did not trade through sends no search. Stage 5
  (`pipeline._search_security`) hands the registrants to the finder (`SecurityContext.registrants`: their Form 25s,
  from their registration on, as `other_cik`'s; the listed-today answer is read through the last one), and stage 10c3
  gives the contract's issuer timeline (`issuer_in_force.with_registrants`); `securities.csv` and the observation map
  keep the security's resolved issuer. A live run sends one search per ending that goes on (125 securities over the
  last full run; the four mergers among them are DIS, WRK, MIC and Inphi), cached afterwards.
- `endings/handoffs.py` — ticker handoffs (CONTEXT.md: one security stops under a
  ticker, another of the run starts under it within days): `find_handoffs`
  (candidate pairs, [-10, 120] days), `decide_handoff` (continuation by the
  successor issuer's 8-K12B/8-K12G3 `continuation_filing`, found by the full-text
  search for the predecessor's name, else in the successor issuer's own filing list,
  `own_continuation_filing`, unless the old issuer carries on in another line; else by timing and
  the same CIK or a `cusip_switch` whose price carried over (`switch_price_ratio` within `carried_price.CARRIED_PRICE`, 2/3 to 3/2, or
  unknown; a same-issuer pair does not read it); else a takeover when the new line traded
  before), `apply_handoffs` (a continuation's missing `exchange_transfer` row
  or its successor, `handoff_continuation`/`handoff_rebucketed`/
  `handoff_conflict`; a takeover's `ticker_successor_sec_id` or
  `handoff_takeover_no_delisting`; a rule-6 merger, sub-plan 5f, stands as a `handoff_conflict`; every continuation,
  the row it writes included, is `rewrites.continuation` with `Rule.HANDOFF`, a rewritten merger's value dropped from
  `payouts=`; the ambiguous Form 25 is the finder's item's typed `filing`),
  `drop_resolved_shared`. Run by
  `pipeline._handoffs` after the successor search, before the history rows.
- `endings/last_trade.py` — architecture step 4: the last trade date as one module. The finder (stage 5 and 9d), the handoff
  stage (9b), stage 9c, the clip and the contract ask it; no other module decides or edits a last trade.
  `Dating(edgar, midas=, halts=)` dates an ending: `of_group` (a Form 25 group: the first notice that states a day,
  an exchange's 25-NSE first; the best 3.01 8-K reading filed in [earliest − 60 d, latest + 15 d]; MIDAS over
  [earliest − 75 d, latest effective + 10 d] under every ticker the security carried then, `TradingRecord.tickers`:
  SAVE and its OTC SAVEQ; the halt feed around the text days, else the Form 25 day, PHLY 2008), `of_fallback` (no
  Form 25: the 3.01 8-Ks up to the last sighting + 5 d, VRM 2024, MIDAS anchored on the dating filing; a merger
  left undated ends on the closing day its latest 2.01/5.01 8-K near the last sighting states, FCL, SGP 2009, never
  after the last sighting; else the last sighting, unsourced and unconfirmed), `midas_drop` (FB-004 part d: the last
  day MIDAS shows exchange volume under any ticker the security carried, `midas_last`, when the issuer made no filing
  of any form within `MIDAS_DROP_QUIET_DAYS` (180) of it (what others filed about it, its holders' SC 13G/As, does not
  count: `evidence.own_filings`) and the security's own CUSIPs go on trading after it at
  changing prices, `TradingRecord.trades_after`: source `midas`, confirmed, so published; Signature Bank, First
  Republic Bank, which filed with the FDIC), `unexplained` (FB-004 part d: an unexplained ending's last trade
  from SEC data only: the last day the security's own CUSIPs' fails rows show it trading, `TradingRecord.trades_until`
  and not before the first row of the CUSIP it held last (rows at one price throughout show no stop), source
  `fails_rows`; else `midas_last`, source `midas`; else the last sighting, source `last_sighting`; always
  `UNCONFIRMED`, so the verdict doubts it) and `from_notice` (stage 9c: a
  handoff row dated by its last sighting takes its own Form 25 notice's confirmed day, before the successor's first
  sighting and no later than the effective date). MIDAS and the Nasdaq halt feed are its two adapters
  (`last_trade_day`; `deletion_halt`, `failed_days`), each a real client or a fixture-backed double; a halt-feed
  day it could not read rides on `LastTrade.halt_feed_failed`. Rule 3, the ticker's tenure (the security's trading
  record, `trading_record.TradingRecord.taken`, which the finder passes in: the trading day before another CUSIP's
  first priced fails row under the ticker, on or after the security's own last one there; none without an own row;
  a $0.01 row is no trade): a MIDAS or halt day after a
  text day, from that day on, is the other security's: MIDAS is read up to the day before, the halt dropped (CCE,
  JCI 2016, GRUB 2021); without a disagreeing text day nothing is bounded (a successor's first fails rows can lag
  its first day: Sinclair Inc 2023, new TCF 2019). Rule 4, inside `of_group`: a group left undated, not continued,
  whose winner is an exchange's Form 25 (not the issuer's 25 or 25/A, not under (b): it follows the suspension by
  weeks, TMA) takes the closing day (`closing_day_read`: the 8-Ks in [F − 10, F + 10] for [F − 10, F]), else F,
  source `closing_day`, flagged unconfirmed (`LastTrade.worked_out`: the classification keeps F as its anchor); the
  closing day never comes before the last day its own fails rows show it trading (`TradingRecord.trades_until`,
  `trading_record.last_row_trade_day`: the trading day before `ftd.settled_last`'s row of the CUSIP it held last; AVGO 2018, Z
  2015) unless the text dated the closing before the open (Imclone 2008's 8:28 A.M.). `at_handoff` (stage 9b): a row
  the handoff writes, or a kept row with no day, takes A's last sighting, and never a day later than the trading day
  before B's first (`handoff_day`, source `last_sighting`). `before_successor` (FB-022): a day no exchange print gave
  (a worked-out closing day, a last sighting, an unsourced fallback) never reaches B's first day under the ticker;
  from that day on it becomes the trading day before it. It applies to a continuation's kept row, to a takeover's
  row and to a row that stands against the handoff (old Charter 2016), and A's own last fails row is no cap (old
  Caesars 2020). `anchor_day` (the day an ending is
  read around: its last trade, else its Form 25's filing date, else the anchor 8-K's, else its delisting date;
  `Delisting.anchor`: the successor searches and links, the R1 reading, the handoff pairs, stage 5b) and
  `first_day_after` (an added successor's first day after a last trade: the next trading day, at all three sites
  that add one). Its answer type and the derived facts are defined once in `exit_kind` (the row vocabulary,
  architecture step 8a), which this module imports and the measurement side reads without its clients:
  `LastTrade.confirmed` (dated and not flagged `last_trade_date_unconfirmed`: what the clip, the successor starts
  and 9c test), `LastTrade.print_confirmed(effective)` (confirmed, from an exchange print, `EXCHANGE_PRINTS`, and no
  later than the Form 25 effective date, `exit_kind.effective_date`: the verdict's test of the day, each failing
  part a reason; over a delistings.csv row, `of_row`, `effective_of` and `published`, the contract's
  `last_trade_date`, which is the day the row holds whatever its source, FB-019 and FB-020), `end_day` (the
  day it ended its security's listing: its last trade, else its delisting date, the Form 25's effective date; the
  clip and stage 9e; over a row `end_day_of`), the sources (`SOURCES`: `midas`, `nasdaq_halt`, `ex99_notice`,
  `8k_301`, `closing_day`, `last_sighting`, and `UNSOURCED` "") and the flags it writes (`UNCONFIRMED`, `CONFLICT`,
  `NO_DAY`). Its interface is tested in `tests/test_last_trade.py`, through fake MIDAS and halt adapters; the facts
  in `tests/test_exit_kind.py`.

  The readers: `eightk_last_trade()` (Item 3.01 text) and `decide_last_trade()`, which picks among the Form 25
  notice, the 8-K text, MIDAS and the Nasdaq halt (MIDAS beats a halt beats text; a text/measured disagreement is
  flagged `last_trade_date_conflict`). The text's `_OPEN` wordings (suspended/halted "before the open", "prior to
  the market opening", "before market open", "prior to the commencement of trading", "as of the open of business",
  "at the opening of business", a halt "at the NYSE market open" on D) date the last trade on the trading day before
  D (source `8k_301`, kind `8k_open`). Sub-plan 5d: the reader reads every 3.01 section (`sections_3_01`: to the next
  item heading, not a cross-reference; the heading's number read with spaces inside it, `evidence.item_mention`, as
  sub-plan 5g's `item_sections` reads it: CBL 2020's "ITEM 3 . 01") sentence by sentence (`_read_sentence`, a stop
  word in the sentence, never a record date): `_CLOSE` ("at/after/following/as of the close/closing of
  trading/business/market [on <venue>] on D"; the Closing Date and an "after the Effective Time" at 4 p.m. or later
  resolve from the filing), a suspension at a stated clock time (architecture step 4, SPNV 2020: "suspended
  effective as of approximately 4:00 p.m. Eastern Time on September 17, 2020": at or after the close D,
  `8k_close_clock`; before the 9:30 open the trading day before, `8k_open_clock`; during the session nothing), the
  last day ("last day ... traded", "which was the last day", "continue to be listed through D"), a bare "suspended
  (trading ...) on D" (`8k_suspended`, the trading day before D: ruling R8) and "suspended immediately on D" (D,
  unconfirmed), and, date first, "On D, ... had been/was suspended (from trading)" (`8k_suspended` too: CBL 2020; no
  modal, completion word, other date or "immediate": BMC 2013, WeWork 2023); a weekday may precede any date ("on
  Friday, December 5, 2008": TMA, IDARQ); a stated close or last day that falls on no session moves to the trading
  day before (CNDT 2019); a stated timing ranks first (`reading_rank`). Source order: MIDAS, then a halt (but the
  8-K's day when it puts the halt at the open of the halt day, `HALT_AT_OPEN_KINDS`: an open wording, WM 2008, ruling
  R8, or a stated last day that is the trading day before the halt's, CC 2008, FB-011), the notice's own
  timing, then an 8-K timing that disagrees with the notice's bare date (`BARE_NOTICE_KINDS`: TMHC 2026), then the
  notice, then the 8-K. `closing_day(texts, lo, hi)` (rule 4): when nothing states the last trade, the latest
  completion the 8-Ks state in the window (a defined Closing Date, "On D, ... completed its acquisition", "Merger Sub
  merged with and into", "the closing of the transactions on D", "the evening of D", an effective time with a clock
  time; the trading day before when every clock time that day is before 9:30 a.m.): source `closing_day`
  (`CLOSING_DAY`), published unconfirmed.
- `endings/rewrites.py` — architecture step 3: the one owner of a delisting's kind and successor after its record is built.
  Every rewrite names its rule (`Rule`, a closed set: `ISSUER_MOVE` the finder's R7, `CONTINUED` the finder's continued
  transfer, `TRADES_ON` the clip check at stage 9b's start, `R1` stage 8b, `LINE_FOLLOW` and `SUCCESSOR_LINK` stage 9,
  `HANDOFF` stage 9b, `PLAN_BANKRUPTCY` and `PRICE_DEFICIENCY` stage 9e, `MOVED_OTC` the finder's CRSP 520, `MIDAS_DROP` the finder's CRSP 500; the unexplained ending is no rewrite: it is built, not changed) and is recorded as typed provenance on the
  delisting (`Delisting.rewrites`, one `Rewrite` each: the rule, the successor, how it was found, the evidence,
  a handoff's `successor_from`). `continuation(d, successor, rule, ...)` sets CRSP `crsp_codes.CONTINUATION_CODE` (304)
  and the bucket together and drops what a continuation cannot carry, one rule for all: `no_evidence_default`,
  `successor_unknown` (`SUCCESSOR_UNKNOWN`), every payout or terms-gate flag (`PAYOUT_FLAGS`: `payout_gate_failed:*`,
  `terms_gate_*`, `acquirer_close_lagged`, ...) and the merger's value (one `MergerValues.drop` call through
  `payouts=`; a merger made a continuation without it raises). `security_goes_on(d, rule)` makes the security its
  own successor and keeps the kind and value (WRK, DIS); `mark_going_on(delistings, going_on)` is the clip check's
  (`history.Histories.going_on`), filling only a blank successor; `reclassify(d, code, rule, ...)` any other kind (470, 552), a kind leaving
  `unknown` dropping the no-evidence default. Readings: `awaits_successor`, `is_real_ending` (in memory; the tables'
  is `exit_kind.is_real_ending`), `rewrite_by` (a rewrite's `how` says how its successor was found); a link's
  reason note is `exit_kind.successor_note`,
  the reason's one wording of how a successor was found ("; successor by same ticker"), and the payout flags a
  continuation drops include `exit_kind.GATE_FLAGS`. The classifier's own edits of the end-of-era verdict before it
  builds the record (rule 6, branch 5b, R6b) are no rewrites. Its rules are tested at its interface
  (`tests/test_rewrites.py`).
- `endings/delistings.py` — `DelistingFinder.find()`: lists an issuer's Form 25s,
  matches and groups them into one delisting per removal (chained within
  `SAME_EVENT_DAYS` of the group's earliest filing, across exchanges), dates
  and classifies each, and falls back to the classifier's no-Form-25 paths
  when none exists. A security the master types a unit whose issuer's Form 25s all remove stock, and whose issuer
  has no common stock beside it, is searched and classified as common stock (`_issuers_stock`: STAY 2021's
  "Paired Shares", FB-018; the security master's own kind is left alone). Its interface is `SecurityContext` (architecture step 14, all data): the security's trading
  record (`trading_record.TradingRecord`), the records of its issuer's securities (`siblings`, itself among them),
  whether it is listed today, its other CIK in force and its issuer's lookup tier; the finder works out the ticker on
  a day, the last sighting, trading after a day, rows near a Form 25, the CUSIP switches, the tenure and the rows'
  last trading day from the record. `SecurityContexts` builds them (stage 5 and the real-case harnesses:
  `SecurityContexts.observed(securities, cusips, fails, other_ciks=, resolution_source=)`, each record built once and
  read by the warm pass and the sequential pass alike; stage 9d: from an added successor's
  `TradingRecord.added` beside its issuer's records). `SecurityContext.spans` (each sibling's first sighting to its
  last own one) keeps a Form 25 from being
  matched to a sibling security that wasn't alive on the filing date. `TradingRecord.cusip_switches`: a Form 25
  within `OWN_SWITCH_DAYS` (5) trading days of the security's own CUSIP switch, while it trades on, is no
  delisting (QGEN 2026). Sub-plan 5b: `_continued` (listed today; the issuer's own Form 25 (25 or 25/A, not
  25-NSE, not under (b)) with its 8-A12B (not 8-A12B/A, a rights-plan amendment) within `EIGHT_A_DAYS`, 10, R7; judged on every member
  of a group, the earliest member anchoring the row; or, not under (b),
  `TradingRecord.trades_after`; an observation alone never continues a security), `_moved_otc`/`_to_otc` (FB-004,
  `Rule.MOVED_OTC`: a group the security traded on past, when it is not listed today, no member is the issuer's Form
  25 with its 8-A12B and either the first annual report after it names no exchange on its cover, `listing_status.
  unlisted_cover`, or EDGAR lists the security's own tickers on the OTC market and on no exchange today, `listing_status.
  quoted_over_the_counter` (Light & Wonder's LNWO, whose inline-XBRL cover has no column to read), is no transfer: the
  classifier's listing deficiency, default transfer, `unknown` or a merger only the continued-filings rule relabelled
  (`exit_kind.merger_relabel`: Retail Value Inc. 2022's Item 2.01 and a registrant that kept filing) becomes CRSP
  520, compliance failure, drop reason `moved_otc`, medium; a cover not in the cache, unread or naming an exchange,
  with no OTC listing, changes nothing; Freddie Mac and Fannie Mae, June 2010, both on EDGAR's OTC listing too), `_tie_owner` (FB-003: a Form 25 that names as many classes as the issuer has letterless lines, `form25.every_class`,
  belongs to each of them when none trades on after it and each traded or was sighted within `TIE_STOP_NEAR_DAYS`
  before it; FB-004: a Form 25 the text leaves between
  siblings, `form25.tie_candidates`, belongs to the one that stops at it: the candidates whose own CUSIPs trade on
  past it (`_goes_on`: `trades_after`, after a removal under (b) only a row under an own ticker) are not removed, and
  when at least one trades on and exactly one of the rest was sighted within `TIE_STOP_NEAR_DAYS` (90) before the
  filing it owns it; a going-on sibling first sighted within `TIE_RELINE_DAYS` (30) of its last sighting may be its
  new line, so then only a text naming a word of the stopper's name the new line's lacks ("GGP Inc. Common Stock")
  breaks the tie: Linde, Aptiv, Labcorp, whose binding ruling is no ending for the old line; no trading evidence, or
  several stoppers, leave the tie to review), `_judge` (one Form 25 against
  the security; `_judge_early`, the one judgement of a Form 25 before the floor, for the early window and the
  fallback's early group alike: the security and the siblings alive then, the letter rule when it stands alone),
  early reach (Form 25s up to `EARLY_REACH_DAYS`, 365, before the floor, for a security gone today,
  the latest early group, flagged `observed_after_delisting`; none when an unreadable early Form 25 is dated
  after it, or for an issuer's own Form 25 with its 8-A12B), late reach (`TradingRecord.traded_within`,
  `LATE_ROW_DAYS` 30; and, with early reach where the security stands alone, the other CIK's reach, take only a Form 25 that names
  no class letter, or the security's own share-class letter or its `letter_hint`, `_names_other_letter`), and the
  other CIK in force (`SecurityContext.other_cik`, R5; the delisting carries the filer
  CIK; stage 4c gives a security whose submissions read failed a `resolution_degraded` row). An `unknown` row of a continued group with the issuer's 8-A12B becomes 304 with the security as its own
  successor. Each delisting is dated by the last trade module (`last_trade.Dating`, `self.dating`, built over the
  `midas` and `halts` adapters the finder is given: `of_group` for a Form 25 group, rules 3 and 4 inside;
  `of_fallback` for the no-Form-25 path), reading the security's own trading from its trading record
  (`SecurityContext.record`: its sightings, own CUSIPs, their trading fails rows and the fails index); a worked-out
  closing day (`LastTrade.worked_out`) is not the classification's anchor or the delisting's ticker day, which stay
  the Form 25's. Sub-plan 5h: `TradingRecord.has_cusips`: a security with no CUSIP gets no continued-filings
  ending dated by its last sighting alone (`ended_without_delisting` instead: WW 2013, NCRA 2013). FB-004 part d,
  `_dropped_without_filings`: where the classifier finds nothing (`unknown`, no deregistration) and `Dating.midas_drop`
  dates a drop, the delisting is CRSP 500 (compliance failure, reason unavailable: the exchange's removal is measured
  and nothing filed says why, so no drop reason and the harsh mark applies; 520 would be no mark, 574 a bankruptcy
  nothing states), rewrite `Rule.MIDAS_DROP`, flags `no_form25` and `midas_drop` (info); stage 9e then reads its OTC
  symbol from the fails rows (First Republic's FRCB; Signature's SBNY has too few rows in the 60 days after its last
  day, so none). The finder's R7 and
  its continued transfer's successor are rewrites (`rewrites.continuation`, `security_goes_on`); each `form25_*` review
  item carries the Form 25 typed (`review_triage.FilingRef`, `ReviewItem.filing`): the handoff stage and stage 9d read
  its form and accession there, never from the reason.
- `endings/distress.py` — sub-plan 5g's pure readers for drop and bankruptcy endings: `otc_symbol_from_fails` (the
  security's own CUSIPs' fails rows after the last trade: the exchange symbol when its rows before any other symbol,
  leaving out those at the settled last close (the first own row's price), span more than `OTC_SETTLE_DAYS` (10) at
  two or more prices, else the first other trading symbol within `OTC_SYMBOL_DAYS` (60: PMI 2011, PPMIQ 40 days
  after the halt), else None), `otc_symbol_from_text` (a 3.01 sentence naming an OTC venue and "symbol X", the last
  one the sentence names, not about warrants or preferred only), `new_cusips` (the CUSIPs a plan notice gives the
  new shares: stage 7 never reads the old line's last close from their fails rows, WOLF 2025), `price_only` (price wording and no other listing standard: market
  capitalization, equity, back-door listing, filings), `substitutes_new_shares`/`plan_ratio` (R6: a 12d2-2(a)(3)
  notice naming new shares; the notice's stated ratio, else the plan 8-K's one old-share and one new-share count
  outside a condition), and `liquidating` (a liquidating distribution, trust, or plan of liquidation or
  dissolution). What stage 9e hands the contract from them is `dlret.DistressTerms`.
- `endings/classifier.py` — the filing-trio fingerprint (**Form 25 + 8-K item codes +
  Form 15**), now anchored on the Form 25/fallback filing date rather than a
  vendor end date. `_classify_items()` maps an 8-K item set to a `DLSTCD`
  code; the surrounding logic handles non-equity kinds,
  exchange-transfer detection, and SEC-revocation. Rule order unchanged; the
  continued-filings rule now asks `end_of_era.resolve` instead of
  deciding alone, and records the branch in `evidence["end_of_era"]`. Sub-plan 5b: a revocation filed after a
  matched Form 25 the security did not trade past never decides its row (R6a); the continued-filings default
  (`continued_filings`) gives way to that Form 25's path when its notice says the class was acquired (R6b,
  `_classify_filings`; any answer but a merger is 231, `evidence["end_of_era"] == "form25_notice"`);
  `_confirms_bankruptcy` reads every Item 1.03 section (`evidence.item_sections`). Sub-plan 5c: rule 1 (before
  end-of-era branches 3 and 4: `OwnShares.survived`) and R1 (a one-for-one, no-cash statement of the security's class
  into the same issuer or a new one, `OwnShares.target_issuer`, before the no-evidence default gives 304 with
  `r1_continuation`), both of the ending's own-share reading the finder hands `classify_event(..., own_shares=)`
  (`own_shares.Reader.ending`; without one, a reading at the observed date of the class its name gives, with the
  notice of the Form 25 it is anchored on). Its text answers to the resolver are typed (`end_of_era.Filed`: the
  deficiency, bankruptcy and liquidation 8-Ks). Sub-plan 5g: `evidence.item_sections`
  and the classifier's heading strip read an item number the HTML stripping spaced out ("ITEM 1 .0 3", CBL 2020); no
  further digit may follow, and spaces only where the sub-number starts with 0 (a 10-K's index entry "Item 8. 29" is
  no heading). `_liquidation_notice` reads end-of-era branch 5b's 3.01 8-K. Sub-plan 5f: spec 5c's rule 6 is the
  resolver's (branch 2, `EraSignals.successor_terms`: the reading's statement, read only where branch 2 decides,
  `end_of_era.registers_successor`); and before the no-evidence default, a 6-K or 8-K in [F − 30, F + 10] of the
  Form 25 day that states a completed acquisition, merger or arrangement (`_completion_report`, `COMPLETION`) is a
  merger 231 (TAHO, KING, BPYU), unless the registrant made it (its role, `own_shares.other_role`).
- `endings/end_of_era.py` — the end-of-era resolver's first step: where the registrant
  kept filing after the end. `signals()` reads the filings in the windows around
  the end date (8-K items, successor filings and Form 25s in [end − 30 d,
  end + 120 d]; merger filings — DEFM14A, DEFM14C, PREM14A, SC 14D9, SC TO-T,
  SC TO-I, SC 13E3, 425, S-4 — in [end − 540 d, end + 30 d]); `resolve()` takes
  the first branch that fits: (1) still trading after the end (the finder's
  `continued`, passed as `classify_event(..., trading_after=)`) → today's
  transfer; (2) a successor registration (8-K12B, 8-K12G3) → a transfer whose
  successor stage 9 finds, or a merger 231 (`successor_merger`, spec 5c rule 6, sub-plan 5f) when the registrant's
  own-share statement (`successor_terms`) changed the holders' stake (`OwnExchange.stake_changed`: another ratio
  than one or a split factor, or cash: CHTR 2016's 0.9042; SIRI 2024's 0.1 is a consolidation); (3) a change in
  control (8-K 5.01) → merger; (4) a
  completed acquisition (8-K 2.01) with a merger filing or a Form 25 → merger,
  unless a bankruptcy 8-K the classifier confirmed (`bankruptcy_filing`) came on
  or before it → liquidation 470 (5g sub-rule 2, built in sub-plan 5b);
  (5) a 3.01 notice whose text cites a listing deficiency → compliance failure
  570; (5b, sub-plan 5g) a 3.01 8-K announcing a liquidating distribution, trust or plan of liquidation or
  dissolution → liquidation 400 (EQC 2025), read by `classifier._liquidation_notice` only when branch 6 would
  decide; (6) else today's continued-filings transfer (304), its reason string
  unchanged. Its reasons are written through the row vocabulary (`exit_kind`: `CONTINUED`, `relabel` and its
  suffix, `change_in_control_reason`, `completed_acquisition_reason`, `successor_registration_reason`), whose
  readers the finder, stage 9g, the verdict and the scorecard ask. EDGAR evidence only.
  Tried only where the continued-filings rule fires. Sub-plan 5c, rule 1: branches 3 and 4 never fire when
  `EraSignals.survived` holds (the classifier found no exchange of the registrant's own shares, and an acquirer's
  or a distributor's statement); `merges` says when they would, `registers_successor` when branch 2 would. The
  classifier's answers arrive typed (step 7b): a filing is a `Filed` (form and day; a reason prints it as
  "8-K 2020-11-09", the resolver compares its day), an 8-K item's first filing a date, a statement an
  `exchange_terms.OwnExchange`.
- `endings/exchange_terms.py` — what a filing says the registrant's own shares became (sub-plan 5c, R1): `statements`
  reads each "each share of S ... converted into N shares of T" (and "received N shares of T for each share",
  "on a one-for-one basis", a cash one); `own_exchange` keeps those whose subject is the registrant's (its EDGAR
  names in the year before the event, a defined term for one, "the Company"/"its"/"our") and the security's class,
  and gives the ratio, cash in the exchange (par values, cash in lieu of fractions and special dividends set aside:
  a special dividend is never consideration; rollover shares and cash conversions are read), the target clause and
  its names (defined terms expanded), the target's class letter (`identifiers.prose_class_letters`), and whether
  readings disagree (`ambiguous`). A conversion clause whose own subject is preferred stock is no statement about
  the common (`Statement.preferred`: GGP 2018's "each ... share of 6.375% series A cumulative perpetual preferred
  stock ... was converted into one share of" BPR's preferred, FB-017), and one share of preferred stock for a
  share is not one for one (`OwnExchange.target_preferred`);
  `acquires` (another party's shares became the registrant's, or it issued shares under the merger agreement) and
  `distributes` ("for every four shares", kept) are the registrant's other roles. What a statement means for its
  holders is its own: `OwnExchange.one_for_one` (R1's shape, `one_share_no_cash`, which 8b reads over the terms and
  9b's `MergerValues.reconciled` over the gated terms), `split` (`split_factor`: n or 1/n for a whole n up to
  `SPLIT_FACTOR_MAX`, 100, 1 included; the one split rule, rule 6's and the verdict's `ratio_doubt`) and
  `stake_changed` (rule 6). A plain class with no letter of its own takes a lettered statement of its own tracking
  group (`_names_group`: LCAPA's "LIBERTY CAPITAL" takes "its Series A Liberty Capital common stock", not Liberty
  Starz's); `defined_terms` also reads a term after a former name ("Liberty Media Corporation (formerly known as
  Liberty CapStarz, Inc., \"Splitco\")") and `OwnExchange.target_subsidiary` says the filing calls the target the
  registrant's (former) subsidiary (`subsidiary_terms`: a new issuer even when it carries a name the registrant
  carried until then, `OwnShares.target_issuer`). Pure: which texts, names and class an ending's statement is read
  in is `own_shares`'.
- `endings/own_shares.py` — the own-share reading (CONTEXT.md, step 7b): what the registrant said each of a security's shares
  became at one ending, read once per ending. `Reader(edgar, issuers).ending(cik, share_class=, name=, day=,
  form25=)` gives a lazy `OwnShares` (nothing read until asked): the registrant's 8-Ks in [day − 3, day + 10] of the
  ending's anchor day (`filings`, then their `texts`) and its matched Form 25's notice (a parsed `Form25`, or the
  filing, read when the notice is asked), its EDGAR names in the year up to two days before the day
  (`registrant_names`, then the security's name), and the security's own share class (`identifiers.class_of`: the
  FIGI's, never the name's). It answers `statement` (8-Ks and notice), `registrant_statement` (the 8-Ks alone:
  stage 9g; Actavis 2013's notice reads another company's 0.160), `one_for_one`, `consideration` (a special dividend is no cash),
  `names_target` (the one name tie: a ticker of two letters or more as a word of a target name, or `names_agree`),
  `target_issuer` (stage 5's R1: `SAME_ISSUER` or `NEW_ISSUER` by EDGAR's ticker file and `new_issuer`,
  `NEW_ISSUER_DAYS` 1095), `survived(deal_days)` (rule 1, the deal's 5.01/2.01 8-Ks read too; `other_role`) and
  `degraded` (it rested on a failed or stale read). The finder makes one per ending at its anchor (the last trade,
  worked out or not, else the Form 25's filing date; the last sighting with no Form 25) and keeps the one the
  classifier read (`stated`) on `Delisting.own_shares`; `of(d, reader, security)` gives a later stage that one, else
  makes one at `Delisting.anchor`. Stages 8b, 9 and 9g read it, never the texts again. Reads go through the issuer
  record (filing list, names) and the EDGAR client (texts); a warm finder's copy reads through its shadow record.
- `endings/continuation_evidence.py` — stage 9g (sub-plan 5i), for the verdict only, over the ending's own-share reading's
  `registrant_statement`: `confirming_filing` (a 3.03 8-K or successor registration among the reading's 8-Ks whose
  own text holds a one-for-one statement whose target names the registrant or the successor; no text read without
  one) and `successor_doubt` (`ratio_doubt`: a ratio that is neither one nor a split factor, or cash). Which
  continuations are read is decided on the row's reason (`needs_filing`, `needs_doubt_check`, through the row
  vocabulary's readers: `exit_kind.rests_on_continued_filings`, `linked_by_timing`, `names_successor_registration`),
  as the verdict reads the same row. Its answer is `exit_kind.ContinuationReading`; it imports no measurement
  module.

## terms/

**`terms/`: what one share of a merger ending became, stage 8 (network):**
- `terms/merger_value.py` — stage 8, one module (architecture step 1): `value_mergers(delistings, index, *, clients,
  closes, caller_terms, answers, tol, ftd_lo, workers, log)` gives `MergerValues`, one `MergerValue` per merger
  ending: the regex read and the LLM terms (`read`/`raw`, `llm`), the gate's verdict (`payout`, `source`,
  `confidence`, the priced stock leg `terms`, `flags`, `priced_by`), the acquirer security, its `price_ticker`, a
  basket's `leg_sec_ids`, and the received close its stock leg asks (`request`), plus the acquirers the run adds and
  the review items. `MergerValue.dividend` is the closing dividend the last gate pass counted (FB-021): `table_terms`
  adds it to the cash delistings.csv carries, `contract_inputs` hands it to the payout rule, and `read_terms` and
  `reconciled` never read it. Its steps: the reads (the LLM told the target's name; both filled ahead on the worker threads,
  the sequential pass then reading what they cached), sub-plan 5e's stage 8a acquirer line of every stock leg before
  the gate, passed or not (`acquirer_line`; a merger before the run's fails window reads its lines' rows into a
  private index, `FtdIndex.apart` and `LineIndex.fresh`), stage 8a' (`acquirer_ticker`: a leg with no ticker and no line), the gate
  (`payout_gate`: the terms' ticker price, then the line's, the line's first for a `line_first` leg whose ticker's
  rows are another line of the issuer's, TWC, VIA, STRZA), the acquirer (`acquirers`: the fails-row acquirer for
  ticker-settled terms, the only source of `AddedAcquirer`s, else the line or holder; a `line_first` leg publishes
  the line, another issuer's ticker security, IPHI, still wins) and its symbol on the price date. The regex read's
  sanity bound and the first gate pass read only the run's own last closes (stage 7's `own`: a `--last-trade-closes`
  row, else the fails close) and none of the caller's `--price-answers`, neither a last close nor a received close:
  the acquirer, each leg's request and the run's decisions (8b's `read_terms`, 9b's `reconciled`, through
  `MergerValue.own_verdict`) come from it. A second pass sets the values on the answered last closes and takes a
  received close only through the request it answers (the path the first pass settled on), so a second run changes
  values only (IPHI, WBS: an answered close that fails the gate keeps new Marvell and Santander). A `--merger-terms` row (`caller_terms`) wins for every delisting of its security and asks nothing; its
  acquirer ticker is published as given. The later stages read the records: `read_terms`, `gate_failed`, `drop` and `restate` (8b),
  `reconciled` (9b), `table_terms` (10a: a `TableTerms`, the terms delistings.csv carries, for any delisting),
  `contract_inputs` and `requests` (10g). The four rule
  modules are its collaborators, each with its own interface and real-case tests. Its real cases replay offline from
  `tests/fixtures/acquirer_gate/` (`tests/acquirer_gate_cases.py`, through `value_mergers`).
- `terms/acquirers.py` — a merger's acquirer as a security (a collaborator of `merger_value`): `find_acquirer` (its
  composite FIGI from the fails rows under the acquirer ticker) and
  `acquirer_cik` (its issuer CIK, never the target's).
- `terms/acquirer_line.py` — a merger's acquirer as a line of the run (sub-plan 5e; a collaborator of `merger_value`;
  `LineIndex.fresh` reads the same lines again over a fails index extended since). The terms' ticker and acquirer name
  are only evidence of the issuer. The issuer is the security that held the ticker on the last trade day
  (`LineIndex.holder`; a ticker beginning at the closing counts from the price date, and a hold that ends before the
  price date was handed over to the new holder), its issuer only when it filed by then and carries an agreeing name
  (`issuer_fits`); else the resolver's issuer of the ticker on that day, asked with the name (`issuer_by_ticker`);
  else the run's issuer that carried the name around the closing, best by shared words (`issuer_by_name`).
  `choose_line` picks the issuer's line: the class the quote names, else the CUSIP that began at the closing, else
  the holder; the class letter is read only from a quote about the target's own class (`named_class(quote,
  own_class)`: Viacom class B shares class A's read; the letters are `identifiers.prose_class_letters`).
  `LineIndex.price` prices a closing CUSIP at its close on the price date, past the $0.01 and $1.00 placeholder rows
  (`is_placeholder_row`), and any other line at the last trade day's close. `symbol_on` gives the line's symbol
  from the row that carries that close: for a closing CUSIP the first non-placeholder row from the next trading day
  (JCI 2016, ABI's LIFE: the row dated the price date is still the old CUSIP), for any other line the row dated the
  price date.
- `terms/payout_extractor.py` — extracts the per-share **cash**
  merger consideration from EDGAR filing text (network, regex) for the `merger` bucket. Each read carries its
  currency (`PayoutResult.currency`, sub-plan 5f, ruling R5: the letters before its "$", `currency.prefix_currency`).
- `terms/currency.py` — sub-plan 5f, ruling R5, pure: the currency a filing states for a cash amount ("$"/"US$" USD,
  "C$"/"Cdn$" CAD, a sign or an ISO code next to the amount: `prefix_currency`, `stated_currency`; an LLM answer as
  a code, `normalize`). Never converted, never inferred from where a company is based: blank when not stated.
- `terms/llm_merger_extractor.py` — the **cash+stock** counterpart: an LLM reads a
  filing and returns full structured terms (`cash_per_share`, `stock_ratio`,
  `acquirer_ticker`) the regex extractor can't generalize over. Uses
  `sources/llm_client.py` (`OpenAIJsonClient`: injectable, speaks the OpenAI
  chat-completions API to OpenAI or Anthropic; every LLM client adapter states the model it calls, `model`, None for
  none, the cache label's first choice, then `$CHAT_MODEL`) and `terms/filing_selection.py`
  (filing-tier picker shared with `terms/payout_extractor.py`); responses cached under
  `cache/llm/`. Every extractor adapter takes one call shape, `extract(record, security_name=)` (stage 8 names
  the target security), and `extract_offer_terms(record, security_name=)` for a merger neither reader found terms
  for (FB-016): the offer's own documents among the target's filings on or before the delisting, the SC TO-T and
  its amendments, then the Rule 425 filings, then the SC 14D9, newest first and `max_filings` of a kind at most
  (CureVac 2026, whose 6-Ks state no ratio and whose third newest SC TO-T/A sets it; exhibits are never opened:
  TAHO 2019). Disabled by default — enabled by `--extract-merger-terms-llm`;
  `acquirer_price` and `last_trade_close` come from `sources/ftd.py`, not a filing. `MergerTerms` answers for its own
  package, so the gate, the payout rule, the requests and stage 8 ask it instead of reading its fields: `ticker`
  (normalized; a spelled-out null, `NULL_TICKERS`, is cleaned when the answer is built, `clean_ticker`),
  `is_package`, `has_stock` (any security), `stock_leg` (a ratio or a dollar value: what asks a received close),
  `skip_reason` (why the gate cannot check it), `published` (the contract's legs: a non-package election only its
  all-cash alternative) and `legs(main_ticker)` (each security with its class and the ticker its class trades
  under). Prompt v3 (sub-plan 5f): the answer is
  the PACKAGE one share of the named target security became (ruling R4: the final prorated per-share result when
  stated, else what non-electors got, else the fixed terms, never the sum of an election's alternatives), with
  `cash_currency` (R5; the quote's own sign wins), `stock_value` (a dollar-valued leg, PCYC), the stock leg's issuer
  and class (`acquirer_*`: whose shares are received, New CCE not KO), `extra_legs` (a basket, R3), `package_basis`
  and notes. The user prompt names the target security and the filing; the cache key is
  `{accession}_{model}_v3_{ticker}`. Candidates, latest completion documents first: the closing 8-K, an 8-K reporting
  the closing without 2.01 (3.01/3.03/5.01 within 30 days), an announcement 8-K filed after the last merger proxy (an
  amendment, BOT), DEFM14A, the other announcement 8-Ks, PREM14A, a 6-K near the delisting; an unsure one-for-one
  answer whose quote states no share count is passed over (`unsupported_one_for_one`: ATH, CHTR; a count written as a multiplier, SUG's "1.00x ETE common unit", is a count); a spelled-out null
  ticker ("NULL") is none. A failed LLM call is a
  degraded miss (`SEC_STATS.degraded("llm_call")`: the delisting is `resolution_degraded`), never cached; with
  the calls are filled ahead on `--llm-workers` threads (default 8), one lock per answer file so no call is paid for twice. Calibrate with
  `scripts/eval_merger_extractor.py --truth` (the 10 deals and the truth set's terms cases).
  `closing_dividend(record, security_name=)` (FB-021) is the third call every adapter takes: the cash the target
  paid its holders because the deal closed (`ClosingDividend`: every such dividend the filing names, summed,
  without one the stated consideration already includes). The package never holds it (the prompt's rule, operator
  ruling 2026-10-04). It is read from the closing 8-K, then an 8-K that reports the closing without 2.01,
  `max_filings` at most; only a filing whose text names a dividend with a dollar amount is sent, with the text
  around each "dividend" and its own question (`DIVIDEND_PROMPT`, `DIVIDEND_SCHEMA`), cached as
  `{accession}_{model}_div1_{ticker}`. Stage 8 asks it for a merger with terms and the payout gate decides whether
  it counts. The proxy and the exhibits are never opened for it.
  `earlier_dividend(record, security_name=)` (FB-023) is the fourth call: the same question put to the target's
  8-Ks filed in the 60 days before the delisting, newest first, the closing search's own filings left out, the
  first that states a closing dividend answering and `max_filings` questions at most (Plains Exploration 2013:
  $3.00 declared a week before the closing 8-K, which does not restate it). Stage 8 asks it only for a merger the
  gate valued more than 1% under its last close with no dividend read (`merger_value._EarlierDividends`).
- `terms/payout_gate.py` — every merger payout checked against the last trade before it reaches the table
  (`reconcile`, `gate_payouts` -> `GatedPayouts`); the payout rule's entry has the gate's reading of an LLM answer.
  A closing dividend as read (`dividends`, FB-021) counts beside a value when the total is nearer the last close
  than the value alone (`_counted`), and the gate checks the total it chose (`_checked`). The answer names a
  counted dividend apart (`Reconciled.dividend`, `GatedPayouts.dividends`) and never adds it to `payouts` or
  `merged_terms`: those are the package, which the run's decisions read.
- `terms/filing_selection.py` — the merger extractors' filing picker, pure: the closing 8-K, the announcement 8-K and the
  merger proxies within a window (`closing_8k`, `announcement_8k`, `form_filings`, `in_window`), shared by
  `payout_extractor` and `llm_merger_extractor`.
- `terms/acquirer_ticker.py` — stage 8a': the ticker of a stock leg the LLM names by a defined term and gives no ticker
  for, from the filing's defined terms, SEC's name index and the issuer's EDGAR tickers, else the fails rows'
  description (the payout rule's entry has the cases).

## measurement/

**`measurement/`: how far a published run is from the truth (no client), over a run snapshot:**
- `measurement/lifecycle.py` — `LifecycleView` over a run snapshot: every security's and every input ticker's lifecycle
  (`active`, `ended`, `ended_incomplete`, `left_view`, `closed_no_event`,
  `no_interval`, `loop`; `active`/`ended` are covered), quality (the weakest
  `event_grade` on a covered chain, `medium` for a ticker-only FIGI), and the
  look-ups a truth case needs (`security_on`, `issuer_of`, `tickers_of`,
  `end_of`: the final ending's `exit_kind.end_day_of`). The walk follows each
  security's last real ending (`exit_kind.last_endings`) and reads its kind and
  flags through the row vocabulary.
- `measurement/truth.py` — truth cases, checked by hand at a cited source. What every truth set shares is defined here once
  (step 15): the statuses `PASS` and `KNOWN_WRONG` and their rule (`check_status`: a known_wrong case names its
  fixer in `fixed_by`; the diagnosis set adds its own `ruling_pending`), the one error `TruthFileError` (any truth
  file, golden, audit or diagnosis, its legs, change log or ledger), the judgement (`Judgement`: a case and one
  `Mismatch` per checked field that disagrees, with `field`, `truth`, `library` and the judge's own `wording` where
  `<field> <library> != <truth>` would not read; both judges return it), `tally` (one set's judgements counted:
  cases, matching, pass holding and failing, known_wrong, now right, mismatches by field through the set's `key`,
  the failing pass cases' text; the scorecard's G.*, A.* and D.* lines read it), the flip rule (`now_right`: every
  known_wrong case whose judgement now holds becomes pass, fixed_by cleared, reason `NOW_MATCHES`) and the note
  convention (`noted`). Then the golden set (`data/golden_lifecycles.csv`, `pass` or `known_wrong` + `fixed_by`)
  and the decision-17 audit (`data/accuracy_audit.csv`, `census:<group>` or `random`; an unfilled row is pending):
  `TruthCase` (named by `case_id`, its file's `case`), `load_truth`, `write_truth`, `judge`, `flip(path, view)` (the
  flip rule on a golden file: the flipped rows' status, fixed_by and note change, and the file is rewritten only
  when a case flipped), `clopper_pearson_upper`. The golden `last_trade_date` column is delistings.csv's internal
  day of the lifecycle's final ending, the chain's (a successor's, when the chain continues), never the contract's:
  `TruthCase.final_last_trade_date` in code.
- `measurement/diagnosis_truth.py` — the diagnosis truth set's row format (`data/diagnosis_truth.csv`, spec
  2026-10-03-diagnosis-truth-fixes): one row per diagnosed case. `shape` is ending, no_ending or ending_moved. Scored
  contract fields hold a value, a blank or `*`, and a side file holds a basket's legs. The two last trade dates: the
  scored `last_trade_date` is the contract's published day of the security's own last ending;
  `internal_last_trade_date` is delistings.csv's day of that same ending (a worked-out date when the contract leaves
  it blank). Neither is the golden column of the same name (`truth.TruthCase.final_last_trade_date`). Its statuses
  are `truth`'s pass and known_wrong (`truth.check_status`) and its own `RULING_PENDING`; a bad file is a
  `truth.TruthFileError`. `examined_delist_date` is the delist_date of the ending the case examined (step 9b): an
  ending_moved case needs it, and refuses it as the last real ending; it is never read from the case_id (a loop-added
  case's id ends in its round). `parse_rows` and `parse_legs` turn rows into validated cases (`truth_set` reads the
  files). A leg's field name is `leg_field(n, name)` (`legN.x`, the judge's and the change log's), and `field_key`
  reads it back as `legs` for the `D.mismatches.*` names.
  Its judge (`LibraryRows.of(snapshot)`: the contract rows, the last real endings, the
  securities and contract/payout_legs.csv, None before schema 3; `judge_case`) gives a `truth.Judgement`, one
  `truth.Mismatch` per scored field, or one `sec_id` mismatch when the case's security is not in the run. The
  scorecard's `D.*` lines and `tests/test_diagnosis_truth_cases.py` (strict xfail on known_wrong) read it.
- `measurement/truth_set.py` — the diagnosis truth set as one unit (step 9a): `TruthSet.open(truth, ledger=)` reads the truth
  rows, the legs, the change log and, when a change settles loop errors, the ledger, and validates them once (each
  header exact; `parse_rows`; `parse_legs`; no legs without a case; a row with a missing or an extra cell is a
  `truth.TruthFileError` naming the file and line; a change-log record may carry cells past its six, kept as read).
  Where the files are: data/scorecard.json's "diagnosis" names the truth file (`truth_file_of`, `configured`); the
  legs and the change log are named after it (`legs_path`: `<truth>_legs.csv`, `changes_path`:
  `<truth>_changes.csv`). The changes: `rule(Ruling)` (a sub-plan's or the controller's ruling as data: cells, legs,
  `tag: why`, report and the `owner` whose rows it applies to; it applies once: a cell the change log already
  records it setting is never set again), `correct(Correction)` (a reason a ruling stated wrongly, in the note and
  the log), `rename(id_changes)` (sec_id, price_sec_id, successor_sec_id and every leg's price_sec_id, through
  `regression.renamed_to`, the one chain rule), `flip(lib)` (the flip rule, `truth.now_right`, the golden set's
  too: known_wrong cases that now match become pass, one change-log row each),
  `apply_round(cases, records, base_contract, run, ...)` (truth_update's rules, on the round's `loop_round.RoundCase`s;
  `loop_round.Round.close` calls it) and `settle(ledger_rows)`, all made of `set_cells`, `move_status`,
  `add_row` and `settle`: every changed cell is one change-log row, a note grows by `; tag: why` (`truth.noted`).
  `commit()` validates and writes every file whose content changed, together (`atomic_io.replace_all_on_success`);
  an unchanged file keeps its bytes, and the change log is appended to, its old records written back as read.
  `TruthSet.new(truth, rows, legs)` is a set whose rows and legs are given (sub-plan 5-0's build, tests);
  `read_ledger` is the ledger's validated read (scripts/scorecard.py); `LEDGER_COLUMNS` is the ledger's file format
  (its path is the loop folder's, `loop_round.Loop.ledger`). The truth files' only reader and writer:
  the scorecard, the loop scripts, the apply_5f/5h/5i_truth_rulings.py and apply_fb003/fb020/fb021_truth_rule.py scripts (their rulings as data), the fixture
  builders and tests/test_diagnosis_truth_cases.py go through it.
- `measurement/regression.py` — the contract diff between two run snapshots (the base commit's, `RunSnapshot.at`, and the
  folder's), outside the truth set and its successor chains (`excluded`); `build_report(base, new, cases)` is the one
  place that builds the report (the standalone script, the round script and the scorecard all call it) and
  `id_changes_since(base, new)` finds renames against the base run. A snapshot without contract/delistings.csv or
  security_history.csv raises `run_snapshot.SnapshotError` (exit 2 in the scripts).
  `SKIPPED_COLUMNS` leaves out `verdict` and the price-derived columns. `report_row` builds one report row, and
  `pending_regression` names a regressed truth row the loop could not settle (it stays in the report). A row's key
  and field name, and which rows the ledger explains, are the loop round's (`loop_round`). A renamed placeholder is
  compared under its FIGI (`renamed_to`, a chain of renames followed to
  its end; the truth set renames by the same rule): one `renamed` id_changes row (`regression.RENAMED`,
  `diff_contract(..., renames=)`) instead of its removed row and the FIGI's added one.
- `measurement/loop_round.py` — one round of the diagnosis truth loop (step 9b), and every token a round's errors are known by.
  `Loop.of(repo, folder=)` is the loop folder (default `data/diagnosis/loop`): its `ledger` (the one
  place the ledger's path is named), `reports` (the kept reports, in the folder's parent: data/diagnosis/reports/,
  cited as `reports/<case_id>.md`, `Loop.kept`), `truth_set(truth)` (the truth set with that ledger),
  `seed(truth, run, label=)` (sub-plan 5-0's `known` rows, round 0) and `round(label, n)`. A `Round` names its files
  (`<label>/round-<N>/`: cases.csv, records/, reports/, summary.md; reports recorded relative to the repository) and
  has two operations: `open(truth, run, base, report=)` (rename the truth rows by `regression.id_changes_since` and
  commit, judge the run, write the regression report, keep the errors the ledger has not seen, write them as case
  rows with the security's context) and `close(truth, run, base, dry_run=)` (cases.csv read back as `RoundCase`s,
  records/*.json, `TruthSet.apply_round` with the base contract and the run as the judge reads it, the reports the
  truth set goes on citing, `kept_reports`: a truth or change-log row's and a pending ledger row's, cited at their
  copy, `TruthSet.recite`; a missing one refuses the close before anything is written; `TruthSet.flip`; then, unless
  a dry run, the copies into `Loop.reports`, the commit and summary.md). Each answers the line its script prints (`line()`). The tokens, each built here
  and read back by its inverse here: an error's key (`mismatch_key`, `regression_key`; `parse_key`, `key_kind`; no
  part may hold `|`), a regression's field name (`Field.of(row).name`, `parse_field`: a changed delistings column by
  its name, `delistings.added` or `delistings.removed`, `<table>.<field>`) and a case id (`case_id`, built only:
  `<subject>_<label>-r<N>`; a label holds letters, digits, `.` and `-`). A ledger row's kind is its key's
  (`ledger_row`). The keys a truth row the loop adds settles are the judge's (`new_row_keys`, in the case's field
  order), never spelled from its wording; a case carries the ending it examined (`RoundCase.delist_date`), never read
  from its id. The record vocabulary (`MODES`, `RIGHTS`, `CONFIDENCES`, `VERDICT_KEYS`, `RECORD_KEYS`) is defined
  once: tests/test_loop_round.py reads the workflow's RECORD schema, round folder and commands and checks they agree.
  `unexplained(base, run, cases, ledger_rows)` is `D.unexplained_regressions` (`Unexplained.count`: the securities of
  the report rows the ledger has not settled as `new_right`, plus the truth set's unsettled regressed rows) beside its
  gate (`passes`: 0); scripts/scorecard.py asks it only with `--base`. scripts/truth_loop_round.py and
  scripts/update_truth.py are argparse over it.
- `measurement/truth_update.py` — spec 1.6's rules for what a round's diagnoses may change in the truth file, applied to a truth
  set through its primitives (`apply_round(truth, cases, records, base_contract, run, ...)`, called by
  `TruthSet.apply_round`, which returns a `RoundResult`; `run` is the run as the judge reads it). It reads the
  round's `loop_round.RoundCase`s, the record vocabulary and the field names from `loop_round`, and asks it for the
  keys a new truth row produces (`new_row_keys`). A regression is added only when it is verified and upheld; the row
  keeps the ending its case examined (`examined_delist_date`). A mismatch changes the truth only when the diagnosis
  cites a filing the earlier report missed. A regression of a sec_id the run lacks, or of a renamed placeholder, adds
  no truth row (`run.sec_ids`, `renamed`). The flip after a round is `TruthSet.flip`.
- `measurement/truth_build.py` — the first truth file, built from the normalization workflow's JSON rows (the R2 FIGI check,
  pending fields, the residual list, statuses; notes by `truth.noted`; the examined ending from the diagnosis's
  source.csv); scripts/build_diagnosis_truth.py writes it as `TruthSet.new`.
- `measurement/scorecard.py` — `build(snapshot, config=)` (the spec's gap table as one flat dict: L1/L2, R1.x,
  R2.x, G.x, A.x, D.x, V.x; its `as_of` the snapshot's; the G, A and D lines count each set's judgements through
  one `truth.tally`), `METRICS` (each floored number's good direction), `drops`,
  `raise_floor`, `load_config` (`data/scorecard.json`: the caller's window, the
  floor, the truth files, read as cases and named as files, `golden_file` and `diagnosis_file`; the diagnosis truth
  set through `truth_set`, its legs named after its truth file), `flip(snapshot, config)` (the flip rule on both
  sets: `truth.flipped` for the golden file, `TruthSet.flip` for the diagnosis set, which is flipped only when the
  run has a contract; both written as one write set, `TruthSet.commit(also=)`; returns the flipped ids, `Flipped`;
  scripts/scorecard.py --flip),
  `write` (`output/scorecard.json`). `D.unexplained_regressions` is not built here: it needs a base commit, and is
  the loop round's (`loop_round.unexplained`), added by scripts/scorecard.py with `--base`.
- `measurement/disputes.py` — `dispute_rows(snapshot, config)` (FB-011): output/disputes.csv, one row per `truth.Mismatch` of
  every golden, audit (not pending) and diagnosis case (not ruling_pending) of the config against the run, from the same
  judges the scorecard's lines count, with the resolved `sec_id` (blank when none), its contract `last_trade_date` and the
  truth file as `ScorecardConfig.golden_name`/`audit_name`/`diagnosis_name` (data/scorecard.json's own spelling).
- `measurement/audit.py` — decision 17's sample: `census` (each ending in its first group of
  distress, continuation, left_view, blank_no_value, assumed_par), `random_sample`
  (seeded, avoiding census chains), `worksheet_rows`.

## handling/

**`handling/`: delistings.csv for training and backtests (pure), keyed by `sec_id`:**
- `handling/handling.py` — event-level: `build_train_label_adjustment` (forward-return
  label) and `build_backtest_exit` (exit cashflow + universe-exit date), one
  deterministic policy per bucket (handling's own, not the ending's value rule). Each still takes a `DelistRecord`
  plus scalar `last_close`/`payout_per_share`/`recovery_ratio` (unchanged
  signature); `adjustments_from_rows` is the new wrapper that calls both
  straight from a `delistings.csv` row, via `qlib_adapter.record_from_row`/
  `row_payout` — no more ticker-keyed dictionary arguments to assemble. The firm-month BMP 2007 correction
  (architecture step 10 folded bmp_correction.py in): `firm_month_correction(record, prior_month_end_close, value)`,
  `R_month = (1+R_partial)(1+DLRET)−1` with the DLRET `dlret.decide(value)` answers for the firm month
  (`EndingValue.firm_month`), from one `dlret.ValueInputs`; `build_firm_month_correction(record, prior, last_close,
  exchange, **value)` is the README's keyword form (`exchange=None` is `Exchange.OTHER`). `vocabulary/exchanges.py` holds the
  venue enum the Shumway constants are chosen by.
- `handling/qlib_adapter.py` — DataFrame splicers over a `(datetime, instrument)` panel,
  where `instrument` is a `sec_id`: `inject_terminal_labels`,
  `apply_backtest_exits`, `apply_bmp_corrections`, each reading every input
  straight off the matching `delistings.csv` row; the firm month reads the row as one `dlret.ValueInputs`
  (`value_inputs`: a merger's terminal value as its payout, and an `otc_print` or `plan_stock` row's terminal value as
  the print or plan value it is) and asks `handling.firm_month_correction`. All three, and
  `handling.adjustments_from_rows`, skip a row whose `successor_sec_id`
  equals its own `sec_id` (a continuing security, e.g. an exchange transfer
  that kept the same FIGI) — it isn't an exit, so no label/exit/correction
  is emitted for it.

There are **two return-correction APIs** for different research conventions:
event-level (`handling.build_train_label_adjustment`/`build_backtest_exit`) vs CRSP-style firm-month
(`handling.firm_month_correction`, its DLRET from `dlret.decide`). Don't conflate them.
The firm-month correction and delistings.csv's `dlret` can differ on purpose: the table publishes only a value the
library knows and flags the rest `no_dlret`, while the firm-month correction gives every ending a number, filled by
bucket (BMP 2007). On the committed output, 25 of 873 corrected endings differ (2026-10-08): a merger that abstains
or needs its last trade, and an `unknown` ending, are blank in the table and filled in the firm month; an assumed-par
expiration is 0.0 in the table and no correction in the firm month, which leaves the month's return the same.
