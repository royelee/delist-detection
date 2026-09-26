"""Settings read from the environment, else from the repo's `.env` file: the SEC
User-Agent (`edgar.resolve_user_agent`) and the OpenFIGI key
(`openfigi.resolve_api_key`). Only the one key asked for is read from the file,
and `os.environ` is never written (`llm_client.default_llm_client` is the only
place that calls `load_dotenv`)."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ENV = Path(__file__).resolve().parents[2] / ".env"


def env_setting(name: str, env_file: str | Path = REPO_ENV) -> str | None:
    """`name` from the environment, else from `env_file`, stripped; None when
    neither sets it. A blank value counts as unset, in either place."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if not Path(env_file).exists():
        return None
    from dotenv import dotenv_values  # noqa: PLC0415 -- only a caller with no environment value pays for it

    return (dotenv_values(env_file).get(name) or "").strip() or None
