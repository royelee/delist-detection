"""history.ticker_on: a security's ticker on a day, from its dated sightings."""
from delist_detection.history import Sighting, ticker_on


def test_the_ticker_on_a_day_is_the_latest_sighting_on_or_before_it():
    on = ticker_on([Sighting("2021-12-31", "FB", "observation"), Sighting("2022-06-09", "META", "ftd")])
    assert on("2022-06-08") == "FB" and on("2022-06-09") == "META" and on("2030-01-01") == "META"


def test_a_day_before_every_sighting_takes_the_first_and_none_without_sightings():
    assert ticker_on([Sighting("2021-12-31", "FB", "observation")])("2000-01-01") == "FB"
    assert ticker_on([])("2021-12-31") is None
