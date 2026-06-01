"""Offline tests for OpenAIJsonClient.

All tests inject a fake OpenAI-SDK-shaped client via the ``client=`` param.
No real HTTP calls are made; ``default_llm_client`` is not exercised here.
"""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

from delist_detection.llm_client import OpenAIJsonClient


# ---------------------------------------------------------------------------
# Fake OpenAI SDK shaped objects
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """Records all create() kwargs and returns canned content."""

    def __init__(self, response_content: str) -> None:
        self._response_content = response_content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(dict(kwargs))
        return _FakeCompletion(self._response_content)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, response_content: str) -> None:
        completions = _FakeCompletions(response_content)
        self.chat = _FakeChat(completions)

    @property
    def _completions(self) -> _FakeCompletions:
        return self.chat.completions


class _FallbackFakeCompletions:
    """Raises on json_schema response_format; succeeds on json_object."""

    def __init__(self, response_content: str) -> None:
        self._response_content = response_content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(dict(kwargs))
        rf = kwargs.get("response_format", {})
        if isinstance(rf, dict) and rf.get("type") == "json_schema":
            raise Exception("json_schema response_format not supported by this model")
        return _FakeCompletion(self._response_content)


class _FallbackFakeOpenAI:
    def __init__(self, response_content: str) -> None:
        completions = _FallbackFakeCompletions(response_content)
        self.chat = _FakeChat(completions)

    @property
    def _completions(self) -> _FallbackFakeCompletions:
        return self.chat.completions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYSTEM = "Extract JSON"
_USER = "Here is text about a merger."
_SCHEMA = {"type": "object", "properties": {"cash_per_share": {"type": "number"}}}
_PAYLOAD = {"cash_per_share": 42.50}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_returns_parsed_dict(monkeypatch):
    """extract() parses valid JSON and passes model + messages + json_schema format."""
    monkeypatch.setenv("CHAT_MODEL", "gpt-test")
    fake = _FakeOpenAI(json.dumps(_PAYLOAD))
    client = OpenAIJsonClient(model="gpt-test", client=fake)

    result = client.extract(_SYSTEM, _USER, _SCHEMA)

    assert result == _PAYLOAD

    # Check exactly one call was made
    calls = fake._completions.calls
    assert len(calls) == 1
    call = calls[0]

    # Model should be passed through
    assert call["model"] == "gpt-test"

    # Messages: system + user
    messages = call["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == _SYSTEM
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == _USER

    # First attempt should use json_schema response_format
    rf = call["response_format"]
    assert isinstance(rf, dict)
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "extraction"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == _SCHEMA


def test_markdown_fenced_json_is_stripped(monkeypatch):
    """extract() strips ```json ... ``` fences before parsing."""
    monkeypatch.setenv("CHAT_MODEL", "gpt-test")
    fenced = f"```json\n{json.dumps(_PAYLOAD)}\n```"
    fake = _FakeOpenAI(fenced)
    client = OpenAIJsonClient(model="gpt-test", client=fake)

    result = client.extract(_SYSTEM, _USER, _SCHEMA)

    assert result == _PAYLOAD


def test_fallback_to_json_object_on_json_schema_rejection(monkeypatch):
    """When json_schema response_format raises, extract() retries with json_object."""
    monkeypatch.setenv("CHAT_MODEL", "gpt-test")
    fake = _FallbackFakeOpenAI(json.dumps(_PAYLOAD))
    client = OpenAIJsonClient(model="gpt-test", client=fake)

    result = client.extract(_SYSTEM, _USER, _SCHEMA)

    assert result == _PAYLOAD

    calls = fake._completions.calls
    # At least two calls: first json_schema (rejected), then json_object (success)
    assert len(calls) >= 2

    # First call used json_schema
    assert calls[0]["response_format"]["type"] == "json_schema"

    # A subsequent call used json_object
    json_object_calls = [c for c in calls if isinstance(c.get("response_format"), dict) and c["response_format"].get("type") == "json_object"]
    assert len(json_object_calls) >= 1


def test_model_resolution_raises_without_chat_model(monkeypatch):
    """ValueError when no model is supplied and CHAT_MODEL env var is absent."""
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    fake = _FakeOpenAI(json.dumps(_PAYLOAD))

    with pytest.raises(ValueError, match="model"):
        OpenAIJsonClient(client=fake)  # no model= kwarg, no CHAT_MODEL env
