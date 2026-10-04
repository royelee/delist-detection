"""line_follow: a security's line across a CUSIP or ticker change (sub-plan 5a; rulings R1, R2). Pure, synthetic
rows; tests/test_line_follow_cases.py runs the same functions over real cached cases."""
from datetime import date, timedelta

import pytest

from delist_detection import line_follow as lf
from delist_detection.edgar import EdgarSubmission
from delist_detection.figi_resolution import us_candidates
from delist_detection.ftd import FtdIndex, FtdRow
from delist_detection.observations import TickerEra
from delist_detection.security_master import SWITCH_DAYS, Security


def _rows(symbol, cusip, desc, start, n, *, step=1, prices=None):
    """`n` fails rows from ISO `start`, one every `step` calendar days on weekdays, prices changing each row."""
    out, day = [], date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            p = prices[len(out)] if prices else 10.0 + len(out) * 0.1
            out.append(FtdRow(day.isoformat(), cusip, symbol, desc, p))
        day += timedelta(days=step)
    return out


OLD = _rows("RS", "11111A101", "REVERSE SPLIT CO", "2012-08-01", 40)      # last row 2012-09-25


def _steps(rows, cusips=("11111A101",), tickers=("RS",), **kw):
    return lf.candidate_steps("BBGRS", list(cusips), set(tickers), FtdIndex(rows), **kw)


def test_a_reverse_split_is_a_switch_dated_by_its_first_day_zzzz_row():
    new = [FtdRow("2012-09-26", "11111A200", "RSZZZZ", "REVERSE SPLIT CO NEW", 0.01),
           *_rows("RS", "11111A200", "REVERSE SPLIT CO NEW", "2012-09-27", 5)]
    [st] = _steps(OLD + new)
    assert (st.kind, st.old_cusip, st.new_cusip, st.symbol, st.old_last, st.first) == (
        lf.SWITCH, "11111A101", "11111A200", "RS", "2012-09-25", "2012-09-26")
    assert st.descriptions == ("REVERSE SPLIT CO NEW",)


def test_a_rename_on_the_same_cusip_is_a_new_symbol():
    [st] = _steps(OLD + _rows("RSNW", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5))
    assert (st.kind, st.new_cusip, st.symbol, st.first) == (lf.NEW_SYMBOL, "11111A101", "RSNW", "2012-09-26")


def test_a_post_split_d_spelling_finds_the_switch_and_the_plain_ticker_names_it():
    """YRCW 2010: the new CUSIP trades as YRCWD for its first weeks, then as YRCW."""
    new = _rows("RSD", "11111A200", "REVERSE SPLIT CO", "2012-09-26", 12) + \
        _rows("RS", "11111A200", "REVERSE SPLIT CO", "2012-10-15", 5)
    [st] = _steps(OLD + new)
    assert (st.kind, st.symbol, st.first) == (lf.SWITCH, "RS", "2012-09-26")


def test_a_switch_is_timed_from_the_settling_tail_not_the_last_row():
    """SLE 2012: the old CUSIP fails at one price for 13 trading days after its last trade."""
    tail = [FtdRow(d, "11111A101", "RS", "REVERSE SPLIT CO", 9.0) for d in
            ("2012-09-26", "2012-09-27", "2012-09-28", "2012-10-01", "2012-10-02", "2012-10-03", "2012-10-04",
             "2012-10-05", "2012-10-08", "2012-10-09", "2012-10-10", "2012-10-11", "2012-10-12")]
    new = _rows("RSB", "22222B101", "REVERSE SPLIT CO", "2012-09-27", 5)
    [st] = _steps(OLD + tail + new, extra_symbols={"RSB"})
    assert (st.old_last, st.first, st.symbol) == ("2012-09-26", "2012-09-27", "RSB")


def test_a_new_cusip_too_long_after_the_old_line_is_no_step():
    """GOCO 2023: eight months between the old CUSIP's last row and the new one's first."""
    assert _steps(OLD + _rows("RS", "11111A200", "REVERSE SPLIT CO", "2013-05-01", 5)) == []


def test_an_old_cusip_that_trades_on_under_an_otc_symbol_takes_no_later_switch_or_symbol():
    """VRM 2025: after the bankruptcy the old CUSIP trades as VRMMQ, and the reorganized company's new CUSIP takes
    the ticker; neither is a step of the old line."""
    otc = _rows("RSXYQ", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 30)
    relist = _rows("RS", "11111A200", "REVERSE SPLIT CO", "2012-10-01", 5)
    assert _steps(OLD + otc + relist) == []


@pytest.mark.parametrize("symbol", ["RSCOQ", "RSCOF", "RSQ", "RSXXXX", "RSZZZZ", "P105PS", "RS-WI"])
def test_no_otc_deleted_unassigned_or_cusip_tail_symbol_is_a_new_symbol(symbol):
    assert _steps(OLD + _rows(symbol, "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5)) == []


def test_an_adrs_five_letter_otc_symbol_ending_in_y_is_no_new_symbol():
    """ABCDY: an ADR's OTC symbol. `is_otc_symbol` names it; `candidate_steps` takes no step from it."""
    assert lf.is_otc_symbol("ABCDY", {"RS"}) and not lf.is_otc_symbol("ABCD", {"RS"})
    assert _steps(OLD + _rows("ABCDY", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5)) == []


def test_a_cusip_another_security_holds_is_never_a_step():
    """WLL 2017: the new CUSIP is already another security's line of the run."""
    new = _rows("RS", "11111A200", "REVERSE SPLIT CO NEW", "2012-09-26", 5)
    assert _steps(OLD + new, holders={"11111A200": {"BBGOTHER"}}) == []
    assert len(_steps(OLD + new, holders={"11111A200": {"BBGRS"}})) == 1


def test_a_shared_cusip_takes_no_new_symbol():
    """SPW 2015: another security of the run holds the same CUSIP; a new symbol of it is that security's."""
    assert _steps(OLD + _rows("RSNW", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 5),
                  holders={"11111A101": {"BBGRS", "BBGSPXC"}}) == []


def test_a_spin_off_on_a_new_cusip_while_the_old_one_trades_on_is_only_a_new_symbol():
    """GOOG 2014: the class C CUSIP takes GOOG while the old CUSIP goes on as GOOGL."""
    on = _rows("RSL", "11111A101", "REVERSE SPLIT CO", "2012-09-26", 30)
    spun = _rows("RS", "11111A706", "REVERSE SPLIT CO CL C", "2012-09-26", 5)
    [st] = _steps(OLD + on + spun)
    assert (st.kind, st.symbol) == (lf.NEW_SYMBOL, "RSL")


def test_of_several_new_cusips_under_the_issuers_tickers_the_shortest_symbol_is_the_common():
    """SNH 2020: DHC's common, and its notes DHCNI and DHCNL, all began on the rename."""
    new = (_rows("DHC", "25525P107", "DIVERSIFIED HEALTHCARE TRUST C", "2012-09-26", 5)
           + _rows("DHCNI", "25525P206", "DIVERSIFIED HEALTHCARE TRUST 5", "2012-09-26", 5)
           + _rows("DHCNL", "25525P305", "DIVERSIFIED HEALTHCARE TRUST 6", "2012-09-26", 5))
    [st] = _steps(OLD + new, extra_symbols={"DHC", "DHCNI", "DHCNL"})
    assert (st.new_cusip, st.symbol) == ("25525P107", "DHC")


def test_two_new_cusips_under_equal_symbols_are_no_step():
    new = (_rows("RSA", "11111A200", "REVERSE SPLIT CO", "2012-09-26", 5)
           + _rows("RSB", "11111A309", "REVERSE SPLIT CO", "2012-09-26", 5))
    assert _steps(OLD + new, extra_symbols={"RSA", "RSB"}) == []


def test_a_cusip_the_8k_text_names_is_a_switch_under_whatever_symbol_it_trades():
    """LIZ 2012: "the CUSIP number changed to 316645100 and the new trading symbol ... is FNP"."""
    [st] = _steps(OLD + _rows("FNP", "316645100", "FIFTH & PACIFIC COMPANIES, INC", "2012-09-26", 5),
                  extra_cusips={"316645100"})
    assert (st.kind, st.new_cusip, st.symbol) == (lf.SWITCH, "316645100", "FNP")


def test_the_8k_text_sources():
    text = ("the CUSIP number changed to 316645100 and the new trading symbol for the common stock is FNP. "
            "Separately, the company will trade under the ticker symbol “CHX”. Old CUSIP No. 53815P108.")
    assert lf.text_symbols([text]) == {"FNP", "CHX"}
    assert lf.text_cusips([text]) == {"316645100", "53815P108"}
    assert lf.text_cusips(["CUSIP number 123456789"]) == set()           # its check digit fails
    assert lf.text_symbols(["Trading Symbol(s) Name of each exchange on which registered"]) == set()
    assert lf.cusip_check_digit_ok("037833100") and not lf.cusip_check_digit_ok("037833101")


# --- corroborate: what the issuer's filings say about a step (R1) ---

def _f(form, filed, items="", report="", acc=None):
    return EdgarSubmission(acc or f"{form}-{filed}", form, filed, report, items, "d.htm")


STEP = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2012-09-25", "2012-09-26",
                   ("REVERSE SPLIT CO NEW",))
SUB = {"name": "Reverse Split Co", "formerNames": []}
LATER_10Q = _f("10-Q", "2012-11-08", report="2012-09-30")


def _corr(step=STEP, filings=(), sub=SUB, share_class="COMMON", texts=None, listed=False, as_of=date(2026, 9, 25),
          other=None):
    texts = texts or {}
    return lf.corroborate(step, filings=list(filings), sub=sub, share_class=share_class,
                          text_of=lambda f: texts.get(f.accession, ""), listed_now=lambda: listed, as_of=as_of,
                          other_registrant=lambda: other)


def test_an_8k_item_5_03_states_a_switch():
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03,9.01"), LATER_10Q]) == ("8-K 5.03,9.01 2012-09-24", "")


def test_an_edgar_rename_states_a_switch():
    sub = {"name": "Reverse Split Co", "formerNames": [{"name": "Old Split Co", "from": "2001-01-01T00:00:00.000Z",
                                                       "to": "2012-09-20T00:00:00.000Z"}]}
    assert _corr(filings=[LATER_10Q], sub=sub) == ("renamed from Old Split Co 2012-09-20", "")


def test_an_8k_text_stating_a_reverse_split_states_a_switch():
    """DYN 2010: no item 5.03; the 8-K text says the reverse split took effect."""
    k = _f("8-K", "2012-09-25", "8.01", acc="K1")
    assert _corr(filings=[k, LATER_10Q], texts={"K1": "a one-for-eight reverse stock split"}) == (
        "8-K text 2012-09-25", "")


def test_no_filing_stating_the_switch_refuses_it():
    assert _corr(filings=[LATER_10Q]) == ("", "no_filing")


def test_a_bankruptcy_8k_refuses_the_step():
    """UAL 2006: the plan cancelled the old shares; the new CUSIP is the reorganized company's."""
    assert _corr(filings=[_f("8-K", "2012-05-01", "1.03"), _f("8-K", "2012-09-24", "5.03"), LATER_10Q]) == (
        "", "bankruptcy")


def test_a_registrant_that_merged_out_refuses_the_step():
    """UNIT 2025: the old registrant filed a Form 15 and no periodic report for a later period. BXS 2017: a 10-Q
    filed after the step, for the quarter before it, is no sign the registrant carried on."""
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03"), _f("15-12G", "2012-09-27")]) == ("", "merged_out")
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03"), _f("10-Q", "2012-10-10", report="2012-06-30")]) == (
        "", "merged_out")


@pytest.mark.parametrize("form", ["10-QSB", "10-KSB", "10-KSB40", "10-K405", "10-QT", "10-KT"])
def test_a_small_business_or_older_periodic_report_carries_the_registrant_on(form):
    """2006: an issuer that files only a 10-QSB (or another periodic form) for a period after the step carries on."""
    step = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2006-09-25", "2006-09-26",
                       ("REVERSE SPLIT CO NEW",))
    f = [_f("8-K", "2006-09-24", "5.03"), _f(form, "2007-02-14", report="2006-12-31")]
    assert _corr(step, filings=f) == ("8-K 5.03 2006-09-24", "")


@pytest.mark.parametrize("filed, refused", [("2012-03-30", True), ("2012-03-29", False),   # first - 180, first - 181
                                            ("2012-10-26", True), ("2012-10-27", False)])  # first + 30, first + 31
def test_an_8k_item_1_03_refuses_a_step_only_within_its_window(filed, refused):
    f = [_f("8-K", filed, "1.03"), _f("8-K", "2012-09-24", "5.03"), LATER_10Q]
    assert _corr(filings=f) == (("", "bankruptcy") if refused else ("8-K 5.03 2012-09-24", ""))


def test_the_registrants_own_successor_registration_carries_it_on():
    assert _corr(filings=[_f("8-K12B", "2012-09-26")]) == ("8-K12B 2012-09-26", "")


def test_a_recent_step_of_a_line_listed_today_carries_on_before_its_next_report():
    recent = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2026-07-17", "2026-07-20",
                         ("REVERSE SPLIT CO NEW",))
    f = [_f("8-K", "2026-07-20", "5.03")]
    assert _corr(recent, filings=f, listed=True) == ("8-K 5.03 2026-07-20", "")
    assert _corr(recent, filings=f, listed=False) == ("", "merged_out")


def test_another_registrants_successor_filing_refuses_the_step():
    """SBGI 2023: a new holding company (another CIK) registered as the old registrant's successor."""
    assert _corr(filings=[_f("8-K", "2012-09-24", "5.03"), LATER_10Q], other=999) == ("", "other_registrant")


def test_new_rows_named_only_by_a_name_the_issuer_left_behind_refuse_a_switch():
    """New LMCA 2013: the new CUSIP under the ticker is another issuer's; its description matches the old
    issuer's former name only. The names in force from the first new row decide."""
    sub = {"name": "Starz", "formerNames": [{"name": "Liberty Media Corp", "from": "2011-09-01T00:00:00.000Z",
                                             "to": "2012-09-20T00:00:00.000Z"}]}
    step = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A200", "RS", "2012-09-25", "2012-09-26",
                       ("LIBERTY MEDIA CORP DELAWARE CL",))
    assert _corr(step, filings=[_f("8-K", "2012-09-24", "5.03"), LATER_10Q], sub=sub) == ("", "name")


def test_a_class_letter_other_than_the_lines_refuses_a_switch():
    step = lf.LineStep("BBGRS", lf.SWITCH, "11111A101", "11111A706", "RS", "2012-09-25", "2012-09-26",
                       ("REVERSE SPLIT CO CL C",))
    f = [_f("8-K", "2012-09-24", "5.03"), LATER_10Q]
    assert _corr(step, filings=f, share_class="CLASS A") == ("", "class")
    assert _corr(step, filings=f, share_class="COMMON")[1] == ""          # a line with no class letter takes it


def test_a_new_symbol_near_a_suspension_or_form_25_is_an_otc_move():
    """TMA 2008, FST 2014: the same CUSIP under a new symbol after a delisting is the OTC tail, not the line."""
    step = lf.LineStep("BBGRS", lf.NEW_SYMBOL, "11111A101", "11111A101", "RSNW", "2012-09-25", "2012-09-26")
    for filing in (_f("8-K", "2012-09-20", "3.01"), _f("25-NSE", "2012-09-15"), _f("15-12B", "2012-10-05")):
        assert _corr(step, filings=[filing, LATER_10Q]) == ("", "otc_move")
    assert _corr(step, filings=[LATER_10Q]) == ("same CUSIP", "")


def test_name_on_is_the_edgar_name_on_the_day_without_its_state_tag():
    sub = {"name": "Starz", "formerNames": [{"name": "LIBERTY MEDIA CORP /DE/", "from": "2011-09-01T00:00:00.000Z",
                                             "to": "2013-01-11T00:00:00.000Z"}]}
    assert lf.name_on(sub, date(2012, 6, 1)) == "LIBERTY MEDIA CORP"
    assert lf.name_on(sub, date(2014, 1, 1)) == "Starz"
    assert lf.name_on(None, date(2014, 1, 1), "OBSERVED CO") == "OBSERVED CO"


# --- other_registrant: another CIK's 8-K12B/8-K12G3 naming the issuer ---

class _Edgar:
    def __init__(self, listed):
        self.listed = listed

    def submissions(self, cik):
        return {"tickers": self.listed.get(int(cik), []), "exchanges": ["NYSE"] * len(self.listed.get(int(cik), []))}


def _hit(cik, display):
    return {"_source": {"ciks": [f"{cik:010d}"], "display_names": [display], "form": "8-K12B",
                        "file_date": "2012-09-27"}}


def test_another_ciks_successor_filing_naming_the_issuer_is_found():
    asked = []

    def search(q, forms, lo, hi):
        asked.append((q, forms, lo, hi))
        return [_hit(1, "Reverse Split Co (RS) (CIK 0000000001)"),
                _hit(2, "Reverse Split Holdings Inc (RSH) (CIK 0000000002)")]
    got = lf.other_registrant(search, _Edgar({}), name="Reverse Split Co", day=date(2012, 9, 26), cik=1,
                              own_tickers={"RS"})
    assert got == 2 and asked == [('"Reverse Split Co"', "8-K12B,8-K12G3", date(2012, 8, 27), date(2012, 11, 25))]


def test_another_listed_issuers_own_filing_that_names_the_issuer_is_not_its_successor():
    """iHeartMedia's 8-K12G3 names its subsidiary Clear Channel Outdoor; IHRT is iHeart's own listed stock."""
    def search(q, forms, lo, hi):
        return [_hit(7, "iHeartMedia, Inc. (IHRT) (CIK 0000000007)")]
    assert lf.other_registrant(search, _Edgar({7: ["IHRT"]}), name="Clear Channel Outdoor Holdings",
                               day=date(2019, 5, 2), cik=1, own_tickers={"CCO"}) is None
    assert lf.other_registrant(None, _Edgar({}), name="X", day=date(2019, 5, 2), cik=1, own_tickers=()) is None


# --- decide: R2 ---

def _cand(composite, name="REVERSE SPLIT CO", ticker="RS"):
    return us_candidates([{"figi": composite, "compositeFIGI": composite, "exchCode": "US", "ticker": ticker,
                           "name": name, "securityType": "Common Stock"}])


def _sec(sec_id, cik=1, share_class="COMMON"):
    return Security(sec_id, cik, share_class, "REVERSE SPLIT CO", "Common Stock", True,
                    "placeholder" if sec_id.startswith("CIK") else "cusip",
                    eras=[TickerEra("RS", "2008-01-16", "2010-06-30")])


def test_decide_follows_r2():
    figi_line, placeholder = _sec("BBGRS"), _sec("CIK1-COMMON")
    new_symbol = lf.LineStep("BBGRS", lf.NEW_SYMBOL, "11111A101", "11111A101", "RSNW", "2012-09-25", "2012-09-26")
    assert lf.decide(new_symbol, figi_line, None, {}).kind == lf.ATTACH
    assert lf.decide(STEP, figi_line, [], {}).kind == lf.ATTACH                              # no US line
    assert lf.decide(STEP, figi_line, _cand("BBGRS"), {}).kind == lf.ATTACH                  # the same composite
    assert lf.decide(STEP, figi_line, None, {}) == lf.Decision(lf.REFUSED, why="unsettled")  # an OpenFIGI error
    assert lf.decide(STEP, figi_line, _cand("BBGX1") + _cand("BBGX2"), {}).why == "unsettled"
    d = lf.decide(STEP, figi_line, _cand("BBGNEW"), {})
    assert (d.kind, d.composite) == (lf.SUCCESSOR, "BBGNEW")
    d = lf.decide(STEP, placeholder, _cand("BBGNEW"), {"BBGNEW": _sec("BBGNEW")})
    assert (d.kind, d.composite) == (lf.FOLD, "BBGNEW")
    assert lf.decide(STEP, placeholder, _cand("BBGNEW"), {"BBGNEW": _sec("BBGNEW", cik=2)}).why == "other_issuer"
    assert lf.decide(STEP, placeholder, _cand("BBGNEW"), {"BBGNEW": _sec("BBGNEW", share_class="CLASS A")}).why == \
        "class"


def test_composites_reads_an_answer():
    assert lf.composites({"error": "Invalid idValue"}) is None
    assert lf.composites({"warning": "No identifier found."}) == []
    assert [c.composite for c in lf.composites({"data": [{"compositeFIGI": "BBGX", "exchCode": "US", "ticker": "X",
                                                          "name": "X CO"}]})] == ["BBGX"]


# --- the LINE_DAYS window, each bound pinned on its own ---

def _from(symbol, cusip, first, n=5):
    """`n` fails rows on consecutive trading days from the trading day `first`."""
    from delist_detection.trading_calendar import add_trading_days
    return [FtdRow(add_trading_days(date.fromisoformat(first), i).isoformat(), cusip, symbol, "REVERSE SPLIT CO",
                   20.0 + i) for i in range(n)]


def _edge(offset):
    """The trading day `offset` trading days from the old line's settled last row."""
    settled = lf.line_end(["11111A101"], {"RS"}, FtdIndex(OLD)).settled
    return lf._days(settled, offset)


@pytest.mark.parametrize("offset, found", [(lf.LINE_DAYS, True), (lf.LINE_DAYS + 1, False),
                                           (-SWITCH_DAYS, True), (-SWITCH_DAYS - 1, False)])
def test_the_window_bounds_a_switch_found_by_symbol(offset, found):
    steps = _steps(OLD + _from("RS", "11111A200", _edge(offset)))
    assert [s.new_cusip for s in steps] == (["11111A200"] if found else [])


@pytest.mark.parametrize("offset, found", [(lf.LINE_DAYS, True), (lf.LINE_DAYS + 1, False),
                                           (-SWITCH_DAYS, True), (-SWITCH_DAYS - 1, False)])
def test_the_window_bounds_a_switch_found_by_its_cusip(offset, found):
    steps = _steps(OLD + _from("XYZ", "316645100", _edge(offset)), extra_cusips={"316645100"})
    assert [s.new_cusip for s in steps] == (["316645100"] if found else [])


# --- the final fix wave ---

def test_a_new_cusip_beside_an_old_line_still_trading_at_changing_prices_is_no_step():
    """CHTR 2026: the issuer's new preferred first trades 7 trading days before the end of the data while the
    common goes on at changing prices; a live line's `last` is the data end, so only the settled row can tell."""
    new = _rows("RSP", "11111A306", "REVERSE SPLIT CO PFD", "2012-09-14", 7)
    assert _steps(OLD + new, extra_symbols={"RSP"}) == []
    near = _rows("RSP", "11111A306", "REVERSE SPLIT CO PFD", "2012-09-20", 4)      # 3 trading days before the end
    assert len(_steps(OLD + near, extra_symbols={"RSP"})) == 1


def test_the_own_ticker_pick_is_made_before_held_cusips_are_dropped():
    """LMCA 2016: the new CUSIP under the line's own ticker is another security's; the leftover under another
    symbol is not the line's."""
    new = (_rows("RS", "11111A200", "REVERSE SPLIT CO", "2012-09-26", 5)
           + _rows("RSB", "11111A309", "REVERSE SPLIT CO B", "2012-09-26", 5))
    assert _steps(OLD + new, extra_symbols={"RSB"}, holders={"11111A200": {"BBGOTHER"}}) == []
    [st] = _steps(OLD + new, extra_symbols={"RSB"}, holders={"11111A309": {"BBGOTHER"}})
    assert st.new_cusip == "11111A200"


@pytest.mark.parametrize("kind", ["Preferred Stock", "Warrant", "Right", "Unit"])
def test_a_candidate_typed_preferred_warrant_right_or_unit_is_refused(kind):
    cand = us_candidates([{"figi": "BBGP", "compositeFIGI": "BBGP", "exchCode": "US", "ticker": "RSP",
                           "name": "REVERSE SPLIT CO", "securityType": kind}])
    assert len(cand) == 1
    d = lf.decide(STEP, _sec("BBGRS"), cand, {})
    assert (d.kind, d.why) == (lf.REFUSED, "type")
    assert lf.decide(STEP, _sec("BBGRS"), _cand("BBGP"), {}).kind == lf.SUCCESSOR      # a common stays a successor


def test_other_registrant_reraises_fatal_and_treats_a_request_failure_as_failed():
    import requests
    from delist_detection.fatal import FATAL

    def hits(exc):
        def search(q, forms, lo, hi):
            raise exc
        return search
    with pytest.raises(FATAL):
        lf.other_registrant(hits(FATAL[0]("blocked")), _Edgar({}), name="X Co", day=date(2012, 9, 26), cik=1,
                            own_tickers=set())

    class Down(_Edgar):
        def submissions(self, cik):
            raise requests.ConnectionError("down")

    def search(q, forms, lo, hi):
        return [_hit(7, "Other Inc (OTH) (CIK 0000000007)")]
    assert lf.other_registrant(search, Down({}), name="X Co", day=date(2012, 9, 26), cik=1,
                               own_tickers=set()) == lf.READ_FAILED
    assert lf.other_registrant(hits(requests.Timeout("slow")), _Edgar({}), name="X Co", day=date(2012, 9, 26),
                               cik=1, own_tickers=set()) == lf.READ_FAILED
    assert _corr(other=lf.READ_FAILED, filings=[_f("8-K", "2012-09-24", "5.03"), LATER_10Q]) == ("", "read_failed")
