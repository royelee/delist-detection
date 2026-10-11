"""The price band that says a share became one share (`identity.carried_price`): the ratio of a step's new CUSIP's first
fails price to the old CUSIP's last one, and whether it lies in the band."""
import pytest

import delist_detection.endings.handoffs as handoffs
from delist_detection.identity.carried_price import CARRIED_PRICE, price_carried, step_price_ratio
from delist_detection.sources.ftd import FtdIndex, FtdRow


def _rows(old_price, new_price, *, old_last="2025-07-30", new_first="2025-08-05", symbol="UNIT"):
    return FtdIndex([FtdRow("2025-07-01", "91325V108", symbol, "UNITI GROUP INC", 4.5),
                     FtdRow(old_last, "91325V108", symbol, "UNITI GROUP INC", old_price),
                     FtdRow(new_first, "912932100", symbol, "NEW UNITI", new_price),
                     FtdRow("2025-08-12", "912932100", symbol, "NEW UNITI", 9.99)])


def test_the_band_is_two_thirds_to_three_halves_and_handoffs_defines_none_of_its_own():
    assert CARRIED_PRICE == (2 / 3, 3 / 2)
    assert handoffs.CARRIED_PRICE is CARRIED_PRICE


def test_the_ratio_is_the_new_cusips_first_price_over_the_old_cusips_last_one_before_it():
    assert step_price_ratio(_rows(4.91, 8.09), "UNIT", "91325V108", "912932100") == pytest.approx(8.09 / 4.91)
    # an old row after the new CUSIP's first day is not "on or before it"
    after = FtdIndex([*_rows(4.91, 8.09).by_symbol("UNIT"), FtdRow("2025-08-20", "91325V108", "UNIT", "UNITI", 1.0)])
    assert step_price_ratio(after, "UNIT", "91325V108", "912932100") == pytest.approx(8.09 / 4.91)
    # an old row on the new CUSIP's first day counts
    same_day = FtdIndex([FtdRow("2025-08-05", "91325V108", "UNIT", "UNITI", 5.0),
                         FtdRow("2025-08-05", "912932100", "UNIT", "NEW UNITI", 10.0)])
    assert step_price_ratio(same_day, "UNIT", "91325V108", "912932100") == pytest.approx(2.0)


def test_the_ratio_is_none_when_a_side_has_no_row_under_the_ticker_or_no_price_above_zero():
    ok = _rows(4.91, 8.09)
    assert step_price_ratio(ok, "OTHER", "91325V108", "912932100") is None            # no row under the ticker
    assert step_price_ratio(ok, "UNIT", "99999X999", "912932100") is None             # the old CUSIP has none
    assert step_price_ratio(ok, "UNIT", "91325V108", "99999X999") is None             # nor the new
    assert step_price_ratio(_rows(4.91, 8.09, old_last="2025-08-10"), "UNIT", "91325V108", "912932100") \
        == pytest.approx(8.09 / 4.5)                                                  # the last on or before: 07-01's
    for old, new in [(None, 8.09), (4.91, None), (0.0, 8.09), (4.91, 0.0), (-1.0, 8.09)]:
        assert step_price_ratio(_rows(old, new), "UNIT", "91325V108", "912932100") is None, (old, new)


@pytest.mark.parametrize("ratio,carried", [
    (None, True), (2 / 3, True), (3 / 2, True), (1.0, True), (0.66, False), (1.51, False), (1.65, False),
    (0.25, False), (32.0, False),
])
def test_a_price_carried_over_when_the_ratio_is_inside_the_band_or_unknown(ratio, carried):
    assert price_carried(ratio) is carried
