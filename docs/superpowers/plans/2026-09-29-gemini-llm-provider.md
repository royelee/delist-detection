# Plan: Gemini as a second LLM provider for merger-terms extraction

Written 2026-09-29. Revised the same day: Gemini goes through its OpenAI-compatible endpoint first, with the
existing client, and a native client only if that falls short.

## Context

`--extract-merger-terms-llm` reads each merger's filing through `llm_client.OpenAIJsonClient`, the OpenAI SDK's chat
completions. The client already takes a `base_url`, from `OPENAI_BASE_URL`.

Gemini serves an OpenAI-compatible chat-completions endpoint,
`https://generativelanguage.googleapis.com/v1beta/openai/`, authenticated with a Gemini API key. So the same client
can talk to Gemini by pointing `base_url` there and naming a Gemini model. No new SDK is needed.

In principle this works today with no code, from `.env` alone:
`OPENAI_BASE_URL=<that URL>`, `OPENAI_API_KEY=<Gemini key>`, `CHAT_MODEL=<Gemini model>`. Three things make a small
amount of code worth it:

- **Settings.** The OpenAI variables would hold Gemini values, and switching back means editing three lines.
- **The cache key can name the wrong model.** `pipeline.default_clients` builds
  `LLMMergerTermsExtractor(edgar, default_llm_client(llm_model), ...)` without `model=`. The extractor then labels
  its cache with `$CHAT_MODEL`, so `--llm-model X` reads and writes answers under the `.env` model's name. Gemini
  and OpenAI model names differ, so the `.env` recipe alone does not mix them. `--llm-model` does.
- **Every LLM failure is a silent miss.** `_extract` catches any exception per filing and moves on. On 2026-09-29
  the OpenAI key ran out of credit (HTTP 429 `insufficient_quota`). A run started then would have written all of its
  merger rows as misses, and without terms `merger_at_par` goes from 53 to 269. A second key and a second quota make
  this likelier.

## Outcome

- `--llm-provider gemini` (or `LLM_PROVIDER=gemini`) sends the extraction to Gemini through `OpenAIJsonClient`.
  OpenAI stays the default, and an existing `.env` behaves exactly as before.
- Each model keeps its own cache entries. The existing OpenAI answers (`*_gpt-5.4-mini_v2.json`) still hit.
- A refused or exhausted key stops the run before anything is written, for either provider.
- `run_manifest.json` records the provider, the model and the prompt version.
- Gemini is scored on the 10 labeled deals and compared with OpenAI on the full run before anyone relies on it.

## Design

### Settings

| setting | OpenAI | Gemini |
|---|---|---|
| provider | `LLM_PROVIDER=openai` (default) | `LLM_PROVIDER=gemini` |
| key | `OPENAI_API_KEY` | `GEMINI_API_KEY` |
| model | `CHAT_MODEL` | `GEMINI_MODEL` |
| endpoint | `OPENAI_BASE_URL` (optional) | `GEMINI_BASE_URL`, default `https://generativelanguage.googleapis.com/v1beta/openai/` |

- Each setting is read from the environment, else the repo `.env`.
- `--llm-provider` and `--llm-model` override the provider and model on the command line.
- A missing key or model for the chosen provider stops the run at start: exit 2, with one stderr line naming the
  missing setting.

### Code

- **`llm_client.py`.**
  - `default_llm_client(provider=None, model=None)` resolves the table above and builds `OpenAIJsonClient` with that
    key, base URL and model.
  - The client gains `provider` and `model` attributes.
  - Nothing else in the client changes: its three steps (strict `json_schema`, then `json_object`, then plain) and
    its fence stripping cover both providers.
- **Cache label.**
  - The extractor takes its label from the client: `f"{provider}-{model}"`, except OpenAI keeps the bare model name,
    so existing caches still hit.
  - `default_clients` passes the client's label, not `$CHAT_MODEL`.
  - This fixes the `--llm-model` bug for both providers.
- **Errors that stop a run.**
  - `OpenAIJsonClient` maps the SDK's errors onto two exceptions:
    - `LlmBlocked`: authentication, permission, or a 429 that says the quota or credit is gone.
    - `LlmUnavailable`: timeouts, 5xx and rate-limit 429s after `retries.retrying`.
  - Both join `fatal.FATAL`, so the extractor's per-filing `except Exception` re-raises them.
  - The CLI exits 2 ("LLM refused …; no outputs written") or 4 ("LLM unavailable after retries …; rerun later"), as
    it does for OpenFIGI.
  - Gemini's compatible endpoint answers errors in OpenAI's shape. Task 0 confirms which body means what.
  - A malformed answer is not an error: it still goes down the three steps and ends as a miss.
- **Manifest.** `run_manifest.json` gains `llm: {provider, model, prompt_version}`, or `null` when extraction is off.

### What could make the endpoint fall short (Task 0 checks each)

- **The strict step fails.** Gemini may reject step 1: our `RESULT_SCHEMA` uses union types such as
  `["number", "null"]` under `strict: true`. Every extraction would then cost a failed call before the
  `json_object` step answers. If so, the client remembers per model that step 1 failed and starts at step 2, which
  is a small change. Changing the schema is not needed.
- **`temperature=0` is rejected.** Step 3 already retries without it.
- **Answers differ in quality.** Scoring on the labeled deals (Task 6) decides; the endpoint does not change that.

**Fallback.** If the endpoint cannot give usable JSON, a native `GeminiJsonClient` on the `google-genai` SDK takes its
place. It would be an optional extra, `pip install -e .[gemini]`, and would keep the same `extract()` contract and
the same settings. The rest of this plan stays as it is.

## Tasks

Test first; keep the offline suite green; one commit per task.

- **Task 0 — live spike, no code committed.**
  - **Needs:** network access to `generativelanguage.googleapis.com` in the environment's settings, and a
    `GEMINI_API_KEY`.
  - **Run:** `OpenAIJsonClient(base_url=<Gemini endpoint>, api_key=<key>, model=<Gemini model>)` on the extractor's
    real `SYSTEM_PROMPT`, `RESULT_SCHEMA` and a few cached excerpts: AET→CVS cash-and-stock, a cash deal, an
    election deal.
  - **Record in this plan:**
    - which of the three steps answers;
    - whether the answers match the labeled terms;
    - the error bodies for a bad key and for an exhausted quota;
    - the model chosen for `GEMINI_MODEL`.
  - **Decide:** go on with the compatible endpoint, or switch to the fallback client.
- **Task 1 — errors that stop a run.** Add `LlmBlocked`/`LlmUnavailable`, the error mapping in `OpenAIJsonClient`,
  the entries in `FATAL`, and the CLI exit codes. Tests:
  - an extractor whose client raises `LlmBlocked` re-raises it, and does not fall through to the next filing;
  - a malformed answer is still a miss;
  - the CLI exits 2 or 4 and writes nothing.
- **Task 2 — cache label from the client.** Tests:
  - `--llm-model` changes the key;
  - an existing `*_gpt-5.4-mini_v2.json` is still a hit, with no LLM call.
- **Task 3 — provider settings.** `default_llm_client(provider, model)`, `--llm-provider`, the start-of-run check,
  and the manifest's `llm` key. Tests:
  - an `.env` with only the OpenAI settings behaves as today;
  - `LLM_PROVIDER=gemini` builds the client with Gemini's base URL, key and model (checked on a fake);
  - a missing `GEMINI_API_KEY` exits 2;
  - the manifest records the provider.
  - If Task 0 showed the strict step failing on Gemini, the "start at step 2" memory goes in here, with its test.
- **Task 4 — scripts.**
  - `eval_merger_extractor.py --provider/--model`;
  - `build_golden_fixtures.py` checks the chosen provider's key, not only `OPENAI_API_KEY`;
  - the golden replay stays offline.
- **Task 5 — docs.** CLAUDE.md (commands, `llm_client.py`, `fatal.py`, the new exit reasons), README, and
  `docs/data-flow.md` (the LLM step and its cache key). List the `.env` keys for each provider.
- **Task 6 — live check.**
  - Run `eval_merger_extractor.py` on the 10 labeled deals with each provider, and record both pass counts here.
  - Run `classify_universe.py --observations data/observations.csv --as-of 2026-09-25 --extract-merger-terms-llm
    --llm-provider gemini` into a scratch output directory (warm SEC caches; one Gemini call per merger filing not
    yet cached). Compare with the committed OpenAI output:
    - merger rows with terms;
    - agreeing and differing terms, with each difference checked against its filing;
    - `terms_gate_failed`, `llm_gate_failed` and `merger_at_par`.
  - `output/` stays the OpenAI run unless that comparison says otherwise.

## Open questions

- **Transient failures.** Should `LlmUnavailable` stop the run, as planned, or degrade to a miss flagged
  `resolution_degraded`? Stopping matches OpenFIGI. It also keeps an outage from quietly rewriting DLRETs.
- **Default provider.** Should the default ever move from OpenAI to Gemini? That waits for Task 6's numbers.
