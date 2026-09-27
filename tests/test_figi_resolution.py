from delist_detection.figi_resolution import (
    FigiCandidate, accept, bloomberg_ticker, class_letter, filter_query, is_placeholder, placeholder_id,
    security_kind, share_class_from_name, us_candidates,
)


def _row(comp, exch, ticker, name, st="Common Stock", figi=None, st2="Common Stock"):
    return {"figi": figi or (comp if exch == "US" else comp + exch), "compositeFIGI": comp, "exchCode": exch,
            "ticker": ticker, "name": name, "securityType": st, "securityType2": st2}


def test_us_candidates_groups_and_filters():
    rows = [
        _row("BBG000FJLFX8", "US", "AET", "AETNA INC"),
        _row("BBG000FJLFX8", "UN", "AET", "AETNA INC"),
        _row("BBG000FGJDG1", "GR", "2675508D", "AETNA INC"),                    # German composite
        _row("BBG00WI00001", "US", "CHNGV", "CHANGE HEALTHCARE-WHEN ISSUED"),     # when-issued line
        _row("BBG00NAV0001", "US", "XCBHX", "SOME FUND NAV", st="Open-End Fund"),
    ]
    cands = us_candidates(rows)
    assert [c.composite for c in cands] == ["BBG000FJLFX8"]
    assert cands[0].name == "AETNA INC" and cands[0].ticker == "AET" and len(cands[0].rows) == 2


def test_accept_via_cusip_needs_no_name():
    renamed = FigiCandidate("BBG000BPVCR1", "MALLINCKRODT ARD LLC", "QCOR", "Common Stock",
                            (_row("BBG000BPVCR1", "US", "QCOR", "MALLINCKRODT ARD LLC"),))
    assert accept([renamed], ticker="QCOR", names=["QUESTCOR PHARMACEUTICALS INC"], via_cusip=True) is renamed
    assert accept([renamed], ticker="QCOR", names=["QUESTCOR PHARMACEUTICALS INC"], via_cusip=False) is None


def test_accept_via_ticker_uses_venue_rows_and_class():
    a = FigiCandidate("BBG009S39JX6", "ALPHABET INC-CL A", "GOOGL", "Common Stock",
                      (_row("BBG009S39JX6", "US", "GOOGL", "ALPHABET INC-CL A"),))
    c = FigiCandidate("BBG009S3NB30", "ALPHABET INC-CL C", "GOOG", "Common Stock",
                      (_row("BBG009S3NB30", "US", "GOOG", "ALPHABET INC-CL C"),))
    assert accept([a, c], ticker="GOOG", names=["ALPHABET INC"], via_cusip=False) is c
    etf = FigiCandidate("BBG01VRMNFB1", "PROSHARES S&P DYNAMIC BUFFER ETP", "FB", "ETP",
                        (_row("BBG01VRMNFB1", "US", "FB", "PROSHARES S&P DYNAMIC BUFFER ETP", st="ETP"),))
    assert accept([etf], ticker="FB", names=["FACEBOOK INC"], via_cusip=False) is None     # recycled ticker


def test_accept_old_name_on_a_venue_row():
    col = FigiCandidate("BBG000BN1XR3", "COLLINS AEROSPACE", "COL", "Common Stock", (
        _row("BBG000BN1XR3", "US", "COL", "COLLINS AEROSPACE"),
        _row("BBG000BN1XR3", "UN", "COL", "ROCKWELL COLLINS INC"),
    ))
    assert accept([col], ticker="COL", names=["ROCKWELL COLLINS INC"], via_cusip=False) is col


def test_share_class_and_placeholders():
    assert share_class_from_name("ALPHABET INC-CL C") == "CLASS C"
    assert share_class_from_name("META PLATFORMS INC-CLASS A") == "CLASS A"
    assert share_class_from_name("DISCOVERY INC-A") == "CLASS A"
    assert share_class_from_name("LIBERTY BROADBAND-SER C") == "SERIES C"
    assert share_class_from_name("CLOROX CO") == "COMMON"
    assert share_class_from_name(None) == "COMMON"
    assert class_letter("SERIES C") == "C" and class_letter("CLASS A") == "A" and class_letter("COMMON") is None
    assert placeholder_id(1122304, None) == "CIK1122304-COMMON"
    assert placeholder_id(14693, "CLASS A") == "CIK14693-CLASS-A"
    assert is_placeholder("CIK1-COMMON") and not is_placeholder("BBG000FJLFX8")


def test_small_helpers():
    assert bloomberg_ticker("BF-A") == "BF/A"
    assert bloomberg_ticker("aet") == "AET"
    assert filter_query("Aaron's Company, Inc.") == "AARON'S"
    assert filter_query("ALLEGHANY CORP /DE") == "ALLEGHANY"
    assert security_kind("Common Stock") == "common"
    assert security_kind("REIT") == "common"
    assert security_kind("ETP") == "fund"
    assert security_kind("Preferred") == "preferred"
    assert security_kind("", "GOLDMAN SACHS 6.125% NOTES DUE 2060") == "debt"
    assert security_kind(None) == "common"


def test_us_candidates_warrants_not_dropped():
    """Warrant lines (ticker ending in -W) should not be dropped as when-issued."""
    rows = [
        _row("BBG000ABC123", "US", "ABC-W", "ABC CORP-CW27", st="Warrant"),
        _row("BBG000DEF456", "US", "ABC WI", "ABC CORP WHEN ISSUED"),  # this should be dropped
    ]
    cands = us_candidates(rows)
    assert len(cands) == 1
    assert cands[0].composite == "BBG000ABC123"
    assert cands[0].ticker == "ABC-W"
    assert cands[0].name == "ABC CORP-CW27"


def test_us_candidates_security_type2_when_issued():
    """securityType2 == 'When Issued' should drop the line when it's the representative."""
    rows = [
        _row("BBG000ABC123", "US", "ABC", "ABC CORP", st2="When Issued"),
    ]
    cands = us_candidates(rows)
    assert len(cands) == 0  # dropped because rep has securityType2="When Issued"


def test_us_candidates_prefers_us_exch_over_rs_zero():
    """When no US row exists, use the first US_EXCH row, not rs[0]."""
    rows = [
        _row("BBG000ABC123", "GR", "ABC", "ABC GMBH"),  # foreign row first
        _row("BBG000ABC123", "UN", "ABC", "ABC CORP"),  # US-traded row second
    ]
    cands = us_candidates(rows)
    assert len(cands) == 1
    assert cands[0].name == "ABC CORP"  # from UN row, not GR row
    assert cands[0].ticker == "ABC"
    assert len(cands[0].rows) == 2  # both rows in the candidate
