"""Injectable LLM client for JSON extraction.

Duck-type interface
-------------------
Any object with the following method can be used wherever an LLM client is
expected (constructor-injection pattern, same as EdgarClient in PayoutExtractor):

    extract(self, system: str, user: str, schema: dict) -> dict

``system`` and ``user`` are the prompt strings; ``schema`` is a JSON Schema
dict describing the expected output.  The method returns a parsed dict on
success and MAY raise on hard failure (callers should wrap in try/except).

Provided implementation: ``OpenAIJsonClient``.

Factory: ``default_llm_client(model=None)`` — loads ``.env`` from the repo
root (via python-dotenv) and returns a configured ``OpenAIJsonClient``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# OpenAIJsonClient
# ---------------------------------------------------------------------------

class OpenAIJsonClient:
    """JSON-extraction client backed by the OpenAI chat-completions API.

    Parameters
    ----------
    api_key:
        OpenAI API key.  Falls back to ``os.environ["OPENAI_API_KEY"]``.
    base_url:
        Optional API base URL.  Falls back to ``os.environ.get("OPENAI_BASE_URL")``.
    model:
        Chat model name (e.g. ``"gpt-5.4"``).  Falls back to
        ``os.environ.get("CHAT_MODEL")``.  A ``ValueError`` is raised at
        construction time when no model is resolved.
    client:
        Optional pre-constructed OpenAI-SDK-compatible client (duck-typed).
        When provided, ``api_key`` / ``base_url`` are ignored.  Intended for
        testing.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        client: object | None = None,
    ) -> None:
        # Resolve model first so we fail fast even before any API call.
        resolved_model = model or os.environ.get("CHAT_MODEL")
        if not resolved_model:
            raise ValueError(
                "OpenAIJsonClient requires a model — supply model= or set CHAT_MODEL env var."
            )
        self._model = resolved_model

        if client is not None:
            self._client = client
        else:
            # Lazy import so tests that inject a fake never need openai installed.
            import openai  # noqa: PLC0415

            resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
            resolved_base = base_url or os.environ.get("OPENAI_BASE_URL")
            self._client = openai.OpenAI(
                api_key=resolved_key,
                base_url=resolved_base,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, system: str, user: str, schema: dict) -> dict:
        """Call the chat-completions API and return a parsed JSON dict.

        Structured-output strategy (graceful degradation):
        1. Try ``response_format={"type":"json_schema", ...}`` (strict).
        2. On failure, retry with ``response_format={"type":"json_object"}``.
           In json_object mode the word "json" must appear in the prompt; a
           short instruction is appended to ``user`` if it is absent.
        3. On a second failure, retry once with no ``response_format``.

        Markdown code fences (```json ... ```) in the response are stripped
        before JSON parsing.

        Raises on hard failure after all retries are exhausted.
        """
        # --- Attempt 1: json_schema (strict structured output) ---
        rf_json_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction",
                "strict": True,
                "schema": schema,
            },
        }
        try:
            content = self._create(system, user, response_format=rf_json_schema)
            return _parse_content(content)
        except Exception:
            pass

        # --- Attempt 2: json_object ---
        # json_object mode requires the word "json" in the prompt.
        user_json = user if re.search(r"\bjson\b", user, re.I) or re.search(r"\bjson\b", system, re.I) \
            else user + "\n\nRespond with a JSON object."
        rf_json_object = {"type": "json_object"}
        try:
            content = self._create(system, user_json, response_format=rf_json_object)
            return _parse_content(content)
        except Exception:
            pass

        # --- Attempt 3: no response_format, and drop temperature too. Some
        # reasoning models (o-series, gpt-5 family) reject any non-default
        # temperature with a 400; since attempts 1-2 both pin temperature=0,
        # this last resort omits it so such a model still gets one clean call. ---
        content = self._create(system, user, response_format=None, temperature=None)
        return _parse_content(content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create(
        self, system: str, user: str, response_format: dict | None, temperature: float | None = 0
    ) -> str:
        """Thin wrapper around chat.completions.create(); returns message content.

        ``temperature=None`` omits the parameter entirely (for models that only
        accept the default).
        """
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.I)


def _parse_content(content: str) -> dict:
    """Strip optional markdown fences and parse JSON."""
    stripped = content.strip()
    m = _FENCE_RE.search(stripped)
    if m:
        stripped = m.group(1).strip()
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------

def default_llm_client(model: str | None = None) -> "OpenAIJsonClient":
    """Load the repo-root ``.env`` and return a configured ``OpenAIJsonClient``.

    This is the only place ``load_dotenv`` is called.  Tests should NOT call
    this function — inject a fake via ``OpenAIJsonClient(client=fake)`` instead.
    """
    from dotenv import load_dotenv  # noqa: PLC0415

    # Walk up from this file to find the repo root .env (two parents: src/delist_detection → src → repo root).
    repo_root = Path(__file__).parent.parent.parent
    load_dotenv(repo_root / ".env")
    return OpenAIJsonClient(model=model)
