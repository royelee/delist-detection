"""settings.env_setting: the environment first, then the repo .env, one key only."""
import os

import pytest

from delist_detection.settings import env_setting


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text('OTHER_KEY=not-read\nSOME_SETTING="  from file  "\nBLANK_SETTING=\n')
    return p


def test_the_environment_wins(monkeypatch, env_file):
    monkeypatch.setenv("SOME_SETTING", " from env ")
    assert env_setting("SOME_SETTING", env_file) == "from env"


@pytest.mark.parametrize("env_value", [None, "", "   "])
def test_an_unset_or_blank_environment_value_reads_the_file(monkeypatch, env_file, env_value):
    if env_value is None:
        monkeypatch.delenv("SOME_SETTING", raising=False)
    else:
        monkeypatch.setenv("SOME_SETTING", env_value)
    assert env_setting("SOME_SETTING", env_file) == "from file"


def test_unset_everywhere_is_none(monkeypatch, env_file, tmp_path):
    for name in ("BLANK_SETTING", "MISSING_SETTING", "SOME_SETTING"):
        monkeypatch.delenv(name, raising=False)
    assert env_setting("BLANK_SETTING", env_file) is None
    assert env_setting("MISSING_SETTING", env_file) is None
    assert env_setting("SOME_SETTING", tmp_path / "missing.env") is None


def test_reading_the_file_exports_nothing(monkeypatch, env_file):
    for name in ("SOME_SETTING", "OTHER_KEY"):
        monkeypatch.delenv(name, raising=False)
    env_setting("SOME_SETTING", env_file)
    assert "SOME_SETTING" not in os.environ and "OTHER_KEY" not in os.environ
