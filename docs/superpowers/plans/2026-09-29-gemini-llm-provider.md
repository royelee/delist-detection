# Plan: Gemini as a second LLM provider for merger-terms extraction

Written 2026-09-29.

## Context

`--extract-merger-terms-llm` reads each merger's filing through one LLM client, `llm_client.OpenAIJsonClient`
(OpenAI chat completions). `LLMMergerTermsExtractor` only needs the duck-typed
`extract(system, user, schema) -> dict`, so a second provider is a second client plus the settings to choose it.

Three things about today's code shape the plan:

- **The cache key can name the wrong model.** `pipeline.default_clients` builds
  `LLMMergerTermsExtractor(edgar, default_llm_client(llm_model), ...)` without `model=`. The extractor then labels
  its cache with `$CHAT_MODEL`, so `--llm-model X` reads and writes answers under the `.env` model's name. With two
  providers this would mix one provider's answers into the other's run.
- **Every LLM failure is a silent miss.** `_extract` catches any exception per filing and moves on. On 2026-09-29
  the OpenAI key ran out of credit (HTTP 429 `insufficient_quota`). A run started then would have written all of its
  merger rows as misses: `merger_at_par` rises from 53 to 269 without LLM terms. SEC and OpenFIGI refusals already
  stop a run (`fatal.FATAL`).
- **No run records which LLM answered.** `run_manifest.json` does not list the provider or the model.

## Outcome

- `--llm-provider gemini` (or `LLM_PROVIDER=gemini`) runs the same extraction through Google's Gemini API. OpenAI
  stays the default, and an existing `.env` behaves exactly as before.
- Each provider and model keeps its own cache entries. The existing OpenAI answers (`*_gpt-5.4-mini_v2.json`) still
  hit.
- A refused or exhausted key stops the run before anything is written, whichever provider it is.
- `run_manifest.json` records the provider, the model and the prompt version.
- Gemini is calibrated on the 10 labeled deals (`scripts/eval_merger_extractor.py`) and compared with OpenAI on the
  full run before anyone relies on it.

## Design

### Settings

| setting | OpenAI | Gemini |
|---|---|---|
| provider | `LLM_PROVIDER=openai` (default) | `LLM_PROVIDER=gemini` |
| key | `OPENAI_API_KEY` | `GEMINI_API_KEY` |
| model | `CHAT_MODEL` | `GEMINI_MODEL` |
| endpoint | `OPENAI_BASE_URL` (optional) | the SDK's default |

- Each setting is read from the environment, else the repo `.env`.
- `--llm-provider` and `--llm-model` override the provider and model on the command line.
- A missing key or model for the chosen provider stops the run at start: exit 2, one stderr line naming the missing
  setting.
- Each provider has its own model variable, so `CHAT_MODEL=gpt-5.4-mini` is never sent to Gemini.

### `llm_client.py`

- `GeminiJsonClient(model=, api_key=, client=None)` has the same `extract(system, user, schema) -> dict` contract.
  - It uses the `google-genai` SDK, imported lazily as `openai` is, so the offline tests never need it.
  - The SDK is an optional extra: `pip install -e .[gemini]`.
- It degrades the same way `OpenAIJsonClient` does, one call per step, until one parses:
  1. `generate_content` with `system_instruction`, `temperature=0`, `response_mime_type="application/json"` and
     the result schema;
  2. JSON mime type without the schema;
  3. plain text.
  The shared `_parse_content` strips code fences.
- `RESULT_SCHEMA` uses JSON Schema union types (`["number", "null"]`). Task 0 settles whether Gemini takes that
  schema as it is; if not, `GeminiJsonClient` converts it itself (unions to `nullable`), and the extractor's schema
  stays one object.
- Both clients expose `provider` and `model`.
- `default_llm_client(provider=None, model=None)` resolves the settings above and builds the matching client.
- `LlmBlocked` (401/403, or a 429 that says the quota or credit is exhausted) and `LlmUnavailable` (timeouts, 5xx
  or rate-limit 429s after `retries.retrying`) are raised by both clients.
  - Each client maps its SDK's errors onto these two.
  - A malformed answer is not an error: it goes down the degradation steps and ends as a miss, as today.

### Extractor and pipeline

- The extractor takes its cache label from the client, as `f"{llm.provider}-{llm.model}"`.
  - The one exception keeps existing caches: OpenAI keeps the bare model name.
  - Keys look like `{accession}_gemini-<model>_v2.json` next to `{accession}_gpt-5.4-mini_v2.json`.
  - This fixes the `--llm-model` key bug for both providers.
- `LlmBlocked` and `LlmUnavailable` join `fatal.FATAL`, so every catch site, including the extractor's per-filing
  `except Exception`, re-raises them.
- The CLI reports them like OpenFIGI's:
  - `LlmBlocked` exits 2: "LLM refused (provider, reason); no outputs written".
  - `LlmUnavailable` exits 4: "LLM unavailable after retries; no outputs written; rerun later".
  - This change also applies to OpenAI. The cache means a rerun resends only the calls not yet answered.
- `run_manifest.json` gains `llm: {provider, model, prompt_version, calls, cache_answers}`, or `null` when
  extraction is off.

### Alternative considered

Gemini also serves an OpenAI-compatible endpoint. Setting `OPENAI_BASE_URL` to it would work with
`OpenAIJsonClient` unchanged, and Task 0 checks it. It is not the plan:

- the cache and manifest would name only the model, not the provider;
- `CHAT_MODEL` and `OPENAI_API_KEY` would hold Gemini values;
- the strict `json_schema` step would rest on a compatibility layer rather than Gemini's own structured output.

If Task 0 shows the native SDK cannot take the schema, this becomes the fallback, still behind the same
`LLM_PROVIDER` settings.

## Tasks

Test first; keep the offline suite green; one commit per task.

- **Task 0 — live spike (network: `generativelanguage.googleapis.com` must be allowed in the environment, and a
  `GEMINI_API_KEY`).** Send the extractor's real `SYSTEM_PROMPT`, `RESULT_SCHEMA` and one cached excerpt (the AET
  closing 8-K) to Gemini:
  - natively, with the schema;
  - through the OpenAI-compatible endpoint.
  Record in this plan:
  - whether the union types are accepted;
  - the answer shape;
  - the error bodies for a bad key and for an exhausted quota (these drive the `LlmBlocked` mapping);
  - the model chosen for `GEMINI_MODEL`.
  No code is committed.
- **Task 1 — errors that stop a run.** Add `LlmBlocked`/`LlmUnavailable`, map OpenAI's errors onto them, add them to
  `FATAL`, and report them in the CLI. Tests:
  - an extractor whose client raises `LlmBlocked` re-raises it, and does not fall through to the next filing;
  - a malformed answer is still a miss;
  - the CLI exits 2 or 4 and writes nothing.
- **Task 2 — cache label from the client.** `provider`/`model` on `OpenAIJsonClient`; the extractor's label rule.
  Tests:
  - `--llm-model` changes the key;
  - an existing `*_gpt-5.4-mini_v2.json` is still a hit, with no LLM call.
- **Task 3 — `GeminiJsonClient`.** It is tested offline with a fake SDK-shaped client, as `test_llm_client.py`
  fakes OpenAI. Tests:
  - the schema step is tried first;
  - the degradation order;
  - code fences are stripped;
  - `temperature=0`;
  - the error mapping from Task 0's bodies;
  - the schema conversion, if Task 0 needs it.
  Add the `gemini` extra to `pyproject.toml`.
- **Task 4 — settings and wiring.** `default_llm_client(provider, model)`, `--llm-provider`, the start-of-run check
  for a missing key or model, and the manifest's `llm` key. Tests:
  - an `.env` with only the OpenAI settings behaves as today;
  - `LLM_PROVIDER=gemini` without `GEMINI_API_KEY` exits 2;
  - the manifest records the provider.
- **Task 5 — scripts.**
  - `eval_merger_extractor.py --provider/--model`;
  - `build_golden_fixtures.py` checks the chosen provider's key, not only `OPENAI_API_KEY`;
  - the golden replay stays offline (its fixtures store terms, not model answers).
- **Task 6 — docs.** CLAUDE.md (commands, `llm_client.py`, `fatal.py`, the new exit reasons), README, and
  `docs/data-flow.md` (the LLM step and the cache key). List the `.env` keys each provider needs.
- **Task 7 — live check.**
  - Run `eval_merger_extractor.py` on the 10 labeled deals with each provider, and record both pass counts here.
  - Run `classify_universe.py --observations data/observations.csv --as-of 2026-09-25 --extract-merger-terms-llm
    --llm-provider gemini` into a scratch output directory (warm SEC caches; one Gemini call per merger filing not
    yet cached). Compare with the committed OpenAI output:
    - merger rows with terms;
    - agreeing and differing terms, with every difference checked against its filing;
    - `terms_gate_failed`, `llm_gate_failed`, `merger_at_par`.
  - `output/` stays the OpenAI run unless that comparison says otherwise.

## Open questions

- **Transient failures.** Should `LlmUnavailable` stop the run, as planned, or degrade to a miss flagged
  `resolution_degraded`? Stopping matches OpenFIGI. It also keeps an outage from rewriting DLRETs quietly.
- **Default provider.** Should the default ever move from OpenAI to Gemini? That waits for Task 7's numbers.
