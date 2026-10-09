"""Sub-plan 5f's real terms cases (tests/terms_cases.py over tests/fixtures/terms/): the payout gate and the payout
rule over each case's own prompt-v3 answer, regex read, last close and acquirer price give the contract's value
fields of its diagnosis truth row (a number to 6 significant figures; `*` not scored), and its basket's legs.
FWLT's price ticker (AMFW: the LLM names Amec Foster Wheeler without one, and the run holds no line of it) and
LGFB's second leg (the truth's 1/15 is Starz's consolidation after the closing) are the two known misses (both
residual). TRH's truth row leaves cash_currency blank where the Form 25-NSE notice's $14.22 is USD (the controller's
truth file, not the library's: the third known miss)."""
from __future__ import annotations

import pytest

import terms_cases as tc

MISSES = {("BBG000BK1FD3_2014-12-04", "price_ticker"), ("BBG00FFJY867_2025-05-17", "leg2.ratio"),
          ("BBG000C4FB79_wave2-r1", "cash_currency")}


def _same(truth: str, got: str) -> bool:
    if truth == "*":
        return True
    try:
        return f"{float(truth):.6g}" == f"{float(got):.6g}"
    except ValueError:
        return truth == got


def _mismatches(case_id: str) -> set[tuple[str, str]]:
    c, got = tc.DATA["cases"][case_id], tc.outcome(case_id)
    bad = {(case_id, k) for k in tc.VALUE_FIELDS if not _same(c["truth"][k], got[k])}
    want = c["truth_legs"]
    if want or got["legs"]:
        if len(want) != len(got["legs"]):
            bad.add((case_id, "legs"))
        for w, (ratio, ticker) in zip(want, got["legs"]):
            if not _same(w["ratio"], ratio):
                bad.add((case_id, f"leg{w['leg']}.ratio"))
            if not _same(w["price_ticker"], ticker):
                bad.add((case_id, f"leg{w['leg']}.price_ticker"))
    return bad


@pytest.mark.parametrize("case_id", sorted(tc.DATA["cases"]), ids=lambda c: tc.DATA["cases"][c]["note"].split(":")[0])
def test_a_case_publishes_its_truth_value_fields(case_id):
    assert _mismatches(case_id) == {m for m in MISSES if m[0] == case_id}


def test_the_currency_comes_from_each_cases_own_read():
    """R5: THI's C$65.50 is CAD (its LLM quote), ADCT's regex "$12.75" USD; a stock-only package has none."""
    assert tc.outcome("BBG000BB2N27_2014-12-25")["cash_currency"] == "CAD"
    assert tc.DATA["cases"]["BBG000BB5HV5_2010-12-19"]["regex"]["currency"] == "USD"
    assert tc.outcome("BBG000BTMDX4_2012-04-06")["cash_currency"] == ""


def test_the_cad_package_is_published_but_never_gated():
    """THI: the gate cannot compare C$65.50 + 0.8025 QSR with a USD close, so its terms are skipped (the contract's
    `skipped`), never passed on an unconverted sum as before 5f."""
    from delist_detection.terms.payout_gate import DEFAULT_TOL, gate_payouts
    from delist_detection.outputs.store import DelistingKey
    c = tc.DATA["cases"]["BBG000BB2N27_2014-12-25"]
    key = DelistingKey(c["sec_id"], c["delist_date"])
    g = gate_payouts([key], {}, {}, {}, {key: tc.terms("BBG000BB2N27_2014-12-25")}, {c["sec_id"]: c["last_close"]},
                     {}, lambda t, k: c["acquirer_price"], DEFAULT_TOL)
    assert g.merged_terms == {} and g.flags[key] == ("terms_gate_skipped:CAD",)
