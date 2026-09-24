"""One run date for the whole run: the EDGAR client's fetch stamps, the
submissions freshness of the resolver and the classifier, and the halt feed's
cache rule all use the date they were given, not the clock."""
import json
from datetime import date

import requests

from delist_detection.classifier import DelistClassifier
from delist_detection.edgar import FETCHED_KEY, EdgarClient, submissions_fresh_after
from delist_detection.ticker_resolver import TickerResolver

AS_OF = date(2026, 9, 23)
UA = "Test Co test@example.com"
SUB_URL = "https://data.sec.gov/submissions/CIK0000000042.json"


class _Resp:
    status_code, text, url = 200, '{"name": "Co"}', "u"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        pass


class _Session:
    def get(self, url, headers=None, timeout=None):
        return _Resp()


class _Recording:
    """Wraps FakeEdgar; records the fresh_after of every submissions read."""

    def __init__(self, inner):
        self.inner, self.fresh = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submissions(self, cik, fresh_after=None):
        self.fresh.append(fresh_after)
        return self.inner.submissions(cik)


def test_the_submissions_freshness_is_bounded_by_the_run_date():
    assert submissions_fresh_after(date(2026, 9, 1), date(2026, 9, 23)) == date(2026, 9, 23)
    assert submissions_fresh_after(date(2018, 11, 28), date(2026, 9, 23)) == date(2019, 1, 12)
    assert submissions_fresh_after(date(2026, 9, 1)) == min(date(2026, 10, 16), date.today())


def test_a_client_stamps_its_run_date_not_the_clock(tmp_path):
    client = EdgarClient(cache_dir=tmp_path, user_agent=UA, session=_Session(), today=AS_OF)
    assert client.today == AS_OF
    client.submissions(42)
    assert json.loads(client._cache_path(SUB_URL).read_text())[FETCHED_KEY] == "2026-09-23"
    assert EdgarClient(cache_dir=tmp_path, user_agent=UA).today == date.today()


def test_the_resolver_reads_submissions_fresh_as_of_its_run_date(fake_edgar):
    e = _Recording(fake_edgar)
    r = TickerResolver(e, today=date(2023, 6, 1))
    r._submissions(999001, "2023-05-10")
    assert e.fresh == [date(2023, 6, 1)]              # min(2023-06-24, the run date)


def test_the_classifier_reads_submissions_fresh_as_of_its_run_date(fake_edgar):
    e = _Recording(fake_edgar)
    c = DelistClassifier(e, TickerResolver(e, today=date(2023, 6, 1)), today=date(2023, 6, 1))
    c.classify_event(ticker="BAD", cik=999001, anchor_date="2023-05-10")
    assert e.fresh[0] == date(2023, 6, 1)
