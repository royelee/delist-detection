"""Sub-plan 5e's real cases through the run's own stage 8 (tests/acquirer_gate_cases.py): each merger's acquirer
security, its price ticker and the payout gate's verdict. The expected values are the diagnosis truth's price_sec_id
and price_ticker ("" where the truth leaves the security open and the run has no line for it), and for the guards
the committed run's own."""
import pytest

from acquirer_gate_cases import DATA, outcome, payouts

# sec_id: (price_sec_id, price_ticker, gate, priced_by)
EXPECTED = {
    # the acquirer renamed or re-CUSIPed at the closing: the issuer's new line, priced on the price date
    "BBG000BDXVW8": ("BBG000M65M61", "UAL", "passed", "line"),        # CAL: UAUA -> UAL
    "BBG000BSD7C2": ("BBG000BW8S60", "RTX", "passed", "line"),        # RTN: UTX -> RTX after the spin-offs
    "BBG000BSGQN5": ("BBG000BTFDR9", "CAA", "passed", "line"),        # RYL: SPF -> CAA, by the resolver
    "BBG000DQV8M1": ("BBG000BDB3H1", "GEN", "passed", "line"),        # MIR: RRI -> GEN
    "BBG000BYD720": ("BBG00GSNPM07", "JHG", "passed", "line"),        # JNS: JHG's $1.00 first row skipped
    "BBG000FVQ434": ("BBG006G063F9", "INFO", "passed", "line"),       # IHS: INFO's $0.01 first row skipped
    "BBG00K7K2XZ0": ("BBG006GNSZW5", "LBRDK", "passed", "line"),      # GLIBA: Series C, not the LLM's LBRDA
    # no ticker in the terms: the issuer by the acquirer name
    "BBG000BN53G7": ("BBG000PXGT62", "SGI", "passed", "line"),        # LEG: Somnigroup
    "BBG000K3T8L8": ("BBG00H433CR2", "EVRG", "passed", "line"),       # GXP: Monarch Energy Holding (Evergy)
    "BBG01HLM8W28": ("BBG01KJQM3Y8", "SIRI", "passed", "line"),       # LSXMA: New Sirius
    # the terms' ticker's holder: OpenFIGI has no answer for its CUSIP
    "BBG000BJCFP1": ("BBG000BNHSP9", "LUK", "passed", "ticker"),      # JEF
    "BBG000C070N2": ("BBG000BT0093", "SIRI", "passed", "ticker"),     # XMSR
    # an election's default package (cash and stock) settles the gate
    "BBG000BGFLL5": ("BBG000C1FB75", "ICE", "passed", "ticker"),      # NYX
    "BBG000BJVZF7": ("BBG000FH8PX5", "ACT", "passed", "ticker"),      # FRX
    "BBG000DBVBY4": ("BBG000BLZRJ2", "MS", "passed", "ticker"),       # EV
    "BBG000C3HNW5": ("BBG000F61RJ8", "ACM", "passed", "ticker"),      # URS
    "BBG000PTXBV3": ("BBG000BJFJ98", "NLY", "passed", "ticker"),      # HTS
    "CIK230463-COMMON": ("BBG000NDZ417", "PXP", "passed", "ticker"),  # PPP, before the run's fails window
    "BBG000FJJW82": ("BBG000CKJ0P3", "LIFE", "passed", "ticker"),     # ABI: the row the price is read from is LIFE's
    "BBG000BTN971": ("", "ETP", "passed", "ticker"),                  # SUN: no line of ETP's issuer in the run
    # the price ticker is the line's symbol on the price date
    "BBG000BLPBL5": ("BBG000BG8M31", "EQR", "passed", "ticker"),      # AVB: Vivmark only from 2026-08-19
    # the line found, the gate still fails: it is doing its job
    "BBG0069FL5L5": ("BBG000FVXD63", "RRC", "failed", ""),            # MRD: a stale last close
    "BBG0077VS2C0": ("BBG000BV5627", "QXO", "failed", ""),            # BLD: a prorated package
    "BBG000C0NY96": ("BBG000BFK8Y6", "TCF", "failed", ""),            # TCF: the last close is the acquirer's (5d)
    # guards: unchanged from the committed run
    "BBG000BRZBT3": ("BBG000BJ2VQ6", "ESV", "passed", "ticker"),      # RDC: never repriced on the new CUSIP
    "BBG000BWMX63": ("BBG000BTJS47", "SAN", "passed", "ticker"),      # WBS: the acquirer the run adds
    "BBG000R23VW8": ("BBG00ZXBJ153", "MRVL", "passed", "ticker"),     # IPHI: new Marvell, not old Marvell's holder
    "BBG000JXRXK2": ("", "SAN", "failed", ""),                        # SOV: SAN was Santander Chile's in 2009
    "BBG000BJ27C4": ("BBG000BHGDH5", "DUK", "passed", "ticker"),      # PGN
    # the ticker's rows are another line of the same issuer: stage 8a's line stands (the review's TWC, VIA, STRZA)
    "BBG000H89QJ6": ("BBG000VPGNR2", "CHTR", "passed", "line"),       # TWC: New Charter, not old Charter's rows
    "BBG000DHM3H8": ("BBG000BWDFD4", "VIACA", "passed", "line"),      # VIA: the quote's Class A, priced on class A
    "BBG000DHSPT0": ("BBG000C496P7", "VIAC", "passed", "ticker"),     # VIA-B: the target's own class B
    "BBG000PCNTM2": ("BBG00FFJY867", "LGFB", "passed", "line"),       # STRZA: Lions Gate's class B on a new CUSIP
}


def test_every_case_has_an_expectation():
    assert set(EXPECTED) == set(DATA["cases"])


@pytest.mark.parametrize("sec_id", sorted(EXPECTED))
def test_case(sec_id):
    got = outcome(sec_id)
    assert (got.price_sec_id, got.price_ticker, got.gate, got.priced_by) == EXPECTED[sec_id], DATA["cases"][sec_id]["note"]


def test_the_guards_keep_the_committed_acquirer():
    for sid in ("BBG000BWMX63", "BBG000R23VW8", "BBG000BJ27C4"):
        committed = DATA["cases"][sid]["committed"]
        got = outcome(sid)
        assert (got.price_sec_id, got.price_ticker, got.gate) == (
            committed["price_sec_id"], committed["price_ticker"], committed["terms_gate"])


def test_a_ticker_price_that_passed_is_the_one_kept():
    # RDC: Ensco's close before its consolidation, as the committed run priced it
    got = outcome("BBG000BRZBT3")
    assert got.priced_by == "ticker" and got.acquirer_price == pytest.approx(3.97)


def test_the_resolver_is_asked_on_the_last_trade_day_only():
    """Every ticker lookup is dated: the terms' ticker on the last trade day, never a later day (GEN is Gen Digital
    from 2022; SAN was Santander Chile's in 2009)."""
    for sid in ("BBG000BSGQN5", "BBG000JXRXK2", "BBG000C0NY96"):
        _, e, resolver = payouts(sid)
        assert resolver.asked and all(k.endswith("|" + e.last_trade.day.isoformat()) for k in resolver.asked)


def test_a_line_priced_late_flags_the_acquirer_close_lagged():
    # AVP-like lag: a ticker price is unchanged and flagged as before; a line price two rows late is flagged too
    got = outcome("BBG000BLPBL5")
    assert "acquirer_close_lagged" in got.flags                    # VMRK's first row is 2026-08-19 (unchanged)
    assert "acquirer_close_lagged" not in outcome("BBG000BDXVW8").flags


@pytest.mark.parametrize("sec_id", sorted(EXPECTED))
def test_an_answered_received_close_changes_no_acquirer_and_no_request(sec_id):
    """`--price-answers`: a second run with the received_close answered (at the run's own price, or any price) changes
    values only. The published acquirer and the request's lookup_ticker are those of the first run, so the answer
    still matches its request (CAL, GLIBA) and stage 10g does not refuse it."""
    first = outcome(sec_id)
    for price in (first.acquirer_price or 50.0, 50.0):
        second = outcome(sec_id, answer=(first.price_ticker, price))
        assert (second.price_sec_id, second.price_ticker) == (first.price_sec_id, first.price_ticker), \
            DATA["cases"][sec_id]["note"]
