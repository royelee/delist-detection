"""EDGAR User-Agent resolution: env var, then the repo .env, then a fallback.

SEC 403s requests whose User-Agent it doesn't accept, so the configured
EDGAR_USER_AGENT has to reach every request even when it lives only in .env.
"""

import os

import pytest

from delist_detection.edgar import EdgarClient, resolve_user_agent


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "OPENAI_API_KEY=sk-should-not-leak\n"
        'EDGAR_USER_AGENT="FileCo Research file@example.com"\n'
    )
    return p


@pytest.mark.parametrize(
    "env_value, want",
    [
        ("EnvCo Research env@example.com", "EnvCo Research env@example.com"),
        ("", "FileCo Research file@example.com"),   # blank env var counts as unset
        (None, "FileCo Research file@example.com"),
    ],
)
def test_env_var_wins_over_env_file(monkeypatch, env_file, env_value, want):
    if env_value is None:
        monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("EDGAR_USER_AGENT", env_value)
    assert resolve_user_agent(env_file) == want


def test_reading_env_file_does_not_export_other_keys(monkeypatch, env_file):
    # Tests must stay hermetic: only EDGAR_USER_AGENT is read from .env, and
    # nothing is written into os.environ (llm_client owns load_dotenv).
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resolve_user_agent(env_file)
    assert "OPENAI_API_KEY" not in os.environ
    assert "EDGAR_USER_AGENT" not in os.environ


def test_fallback_has_contact_when_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    ua = resolve_user_agent(tmp_path / "missing.env")
    assert "@" in ua  # SEC requires a contact in the User-Agent


class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {}

    def raise_for_status(self):
        pass


class _RecordingSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(headers)
        return _Resp()


def test_client_sends_configured_user_agent(monkeypatch, tmp_path):
    # Set after delist_detection.edgar was imported: the client must pick it up
    # at construction, not freeze whatever the environment held at import.
    monkeypatch.setenv("EDGAR_USER_AGENT", "EnvCo Research env@example.com")
    session = _RecordingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session)
    client.submissions(320193)
    assert session.calls[0]["User-Agent"] == "EnvCo Research env@example.com"


def test_explicit_user_agent_beats_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGAR_USER_AGENT", "EnvCo Research env@example.com")
    session = _RecordingSession()
    client = EdgarClient(cache_dir=tmp_path, session=session,
                         user_agent="ArgCo Research arg@example.com")
    client.submissions(320193)
    assert session.calls[0]["User-Agent"] == "ArgCo Research arg@example.com"
