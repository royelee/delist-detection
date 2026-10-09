"""own_shares: the own-share reading, one per ending (architecture step 7b; sub-plan 5c's R1, spec 5c rules 1 and 6).
At the interface: `Reader.ending` and what an `OwnShares` answers, over an EDGAR double and the issuer-role cases'
recorded texts (tests/fixtures/issuer_role/); the statement reader's own tests are tests/test_exchange_terms.py."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from delist_detection.endings import own_shares as O
from delist_detection.outputs.reconstruction import DelistRecord
from delist_detection.vocabulary.crsp_codes import CrspBucket
from delist_detection.endings.delistings import Delisting
from delist_detection.sources.edgar import EdgarSubmission
from delist_detection.filings.form25 import parse_form25
from delist_detection.identity.issuer_record import IssuerRecord
from delist_detection.endings.last_trade import LastTrade
from delist_detection.sources.sec_stats import SEC_STATS
from tests import issuer_role_cases as ic

CIK, DAY = 1, date(2017, 9, 1)


def _8k(acc, filed, items="2.01,3.03", form="8-K"):
    return EdgarSubmission(acc, form, filed, "", items, "d.htm")


def _exchange(target):
    return f"Each share of the Company's common stock was converted into one share of {target} common stock."


class Edgar:
    """The registrant (CIK 1, `name`, `former` names with their spans) and its 8-Ks (`filings`, `texts`); EDGAR's
    ticker file (`tickers`) and other registrants' first filings (`first`). `read` lists the texts read; `fail` makes
    each text read fail."""

    def __init__(self, filings=(), texts=None, *, name="ACME CORP", former=(), tickers=None, first=None, fail=False):
        self.filings, self.texts, self.name, self.former = list(filings), texts or {}, name, list(former)
        self.tickers, self.first, self.fail, self.read = tickers or {}, first or {}, fail, []

    def recent_filings(self, cik):
        if int(cik) == CIK:
            return self.filings
        day = self.first.get(int(cik))
        return [_8k("first", day, items="")] if day else []

    def submissions(self, cik, **kw):
        return {"name": self.name, "formerNames": self.former}

    def fetch_filing_text(self, cik, accession, primary_doc):
        self.read.append(accession)
        if self.fail:
            SEC_STATS.degraded("failed_request")
            return ""
        return self.texts.get(accession, "")

    def company_tickers(self):
        return self.tickers


def _reading(edgar, *, share_class="COMMON", name="ACME CORP", day=DAY, form25=None):
    return O.Reader(edgar, IssuerRecord(edgar)).ending(CIK, share_class=share_class, name=name, day=day,
                                                       form25=form25)


# --- what it reads -------------------------------------------------------------------------------------------------

def test_it_reads_the_8ks_around_its_day_in_filing_order_then_the_notice():
    filings = [_8k("late", "2017-09-12"), _8k("b", "2017-09-04"), _8k("a", "2017-08-29"), _8k("early", "2017-08-28"),
               _8k("k", "2017-09-02", form="10-Q")]
    texts = {"a": "A", "b": "B", "late": "L", "early": "E"}
    own = _reading(Edgar(filings, texts), form25=SimpleNamespace(notice_text="NOTICE"))
    assert [f.accession for f in own.filings] == ["a", "b"]           # [day - 3, day + 10], 8-Ks only
    assert own.texts == ["A", "B", "NOTICE"]


def test_the_real_oke_reading_ends_with_its_form25_notice():
    """ONEOK 2026: the 8-Ks around 2026-09-09, then the NYSE notice that names the new CUSIP."""
    edgar = ic.FixtureEdgar()
    raw = ic.EDGAR["raws"]["0000876661-26-000770"]
    f25 = parse_form25(raw, accession="0000876661-26-000770", form="25-NSE", filing_date="2026-09-18")
    own = O.Reader(edgar, IssuerRecord(edgar)).ending(1039684, share_class="COMMON", name="ONEOK INC",
                                                      day=date(2026, 9, 9), form25=f25)
    assert own.texts[-1] == f25.notice_text and "0001193125-26-387972" in edgar.texts_read
    assert own.one_for_one and own.target_issuer() == O.SAME_ISSUER


def test_a_form25_given_as_its_filing_is_read_only_when_the_notice_is_asked():
    sub = _8k("f25", "2017-09-01", items="", form="25-NSE")
    edgar = Edgar([_8k("a", "2017-09-01")], {"a": "nothing here"})
    edgar.fetch_filing_raw = lambda cik, acc: edgar.read.append(f"raw:{acc}") or ""
    own = _reading(edgar, form25=sub)
    assert edgar.read == []
    assert own.notice == "" and edgar.read == ["raw:f25"]


def test_nothing_is_read_until_a_caller_asks_and_then_once():
    edgar = Edgar([_8k("a", "2017-09-01")], {"a": _exchange("Holdco")})
    own = _reading(edgar)
    assert edgar.read == [] and not own.stated
    assert own.one_for_one and own.stated and edgar.read == ["a"]
    assert own.statement is own.statement and own.registrant_statement is not None and edgar.read == ["a"]


def test_the_names_are_those_in_force_before_the_day_then_the_securitys():
    """Schering-Plough became "Merck & Co." the day of the merger: before it, it is read by its old name."""
    sub = {"name": "MERCK & CO., INC.", "formerNames": [{"name": "SCHERING PLOUGH CORP", "from": "1994-01-01",
                                                          "to": "2009-11-03"}]}
    assert O.registrant_names(sub, date(2009, 11, 4), "SCHERING PLOUGH CORP") == ["SCHERING PLOUGH CORP",
                                                                                  "SCHERING PLOUGH CORP"]
    edgar = Edgar(name="MERCK & CO., INC.", former=sub["formerNames"])
    own = _reading(edgar, name="SCHERING PLOUGH CORP", day=date(2009, 11, 4))
    assert own.edgar_names == ["SCHERING PLOUGH CORP"] and own.names == ["SCHERING PLOUGH CORP"] * 2


def test_sbgi_is_read_by_its_figi_class_not_by_its_truncated_name():
    """SBGI 2023: the name "SINCLAIR BROADCAST GROUP INC CLASS" lost its letter; the statement is of the Class A
    shares, so only the security's share class reads it (stage 8b took it; stage 5 reads it the same way now)."""
    def reading(share_class):
        edgar = ic.FixtureEdgar()
        return O.Reader(edgar, IssuerRecord(edgar)).ending(912752, share_class=share_class,
                                                           name="SINCLAIR BROADCAST GROUP INC CLASS",
                                                           day=date(2023, 5, 31))
    own = reading("CLASS A")
    assert own.one_for_one and "Sinclair, Inc." in own.statement.target_names
    assert reading("COMMON").statement is None


def test_the_registrant_statement_leaves_the_exchanges_notice_out():
    """Actavis 2013: the NYSE notice reads Warner Chilcott's 0.160 as the class's; the registrant's 8-Ks state none."""
    notice = SimpleNamespace(notice_text="Each share of the Company's common stock was converted into 0.160 of a "
                                         "share of Actavis plc.")
    own = _reading(Edgar([_8k("a", "2017-09-01")], {"a": "The merger closed."}), form25=notice)
    assert own.statement.ratio == 0.16 and own.registrant_statement is None


def test_a_failed_read_marks_the_reading_degraded_and_keeps_nothing_as_a_fact():
    own = _reading(Edgar([_8k("a", "2017-09-01")], {"a": _exchange("Holdco")}, fail=True))
    assert own.statement is None and own.degraded
    assert not _reading(Edgar([_8k("a", "2017-09-01")], {"a": _exchange("Holdco")})).degraded


# --- what it answers -----------------------------------------------------------------------------------------------

def test_the_name_tie():
    """A ticker of two letters or more that is a word of a target name ("BHGE's Class A common stock"), or a target
    name that agrees with one of the candidate's names; a blank name ties nothing."""
    st = _reading(Edgar([_8k("a", "2017-09-01")], {"a": _exchange("BHGE's Class A")})).statement
    assert O.names_target(st, [], {"BHGE"}) and not O.names_target(st, [], {"B"})
    hh = _reading(Edgar([_8k("a", "2017-09-01")], {"a": _exchange("Howard Hughes Holdings Inc.")})).statement
    assert O.names_target(hh, ["HOWARD HUGHES HOLDINGS INC."]) and not O.names_target(hh, ["BAKER HUGHES CO", ""])


@pytest.mark.parametrize("age,new", [(548, True), (O.NEW_ISSUER_DAYS, True), (O.NEW_ISSUER_DAYS + 1, False)],
                         ids=["DowDuPont", "limit", "past"])
def test_a_new_issuer_first_filed_at_most_new_issuer_days_before(age, new):
    assert O.new_issuer(DAY - timedelta(days=age), DAY) is new
    assert not O.new_issuer(None, DAY)


@pytest.mark.parametrize("target,whom", [
    ("Holdco", O.NEW_ISSUER),            # a registrant of another CIK first filed 2017-03-01: a new holding company
    ("Oldco", ""),                       # first filed 1995: an existing acquirer (LVNTA into GCI Liberty)
    ("Nobody", ""),                      # in no ticker file
    ("Predecessor", O.SAME_ISSUER),      # a name the registrant itself carried ("Legacy ONEOK" into "ONEOK")
    ("its Class A", O.SAME_ISSUER),      # a reclassification (Clearway 2026)
])
def test_whom_the_target_names(target, whom):
    """Stage 5's R1 (sub-plan 5c): a one-for-one exchange is a continuation only into the same issuer or a new one."""
    edgar = Edgar([_8k("a", "2017-09-01")], {"a": _exchange(target)}, name="Predecessor Corp",
                  tickers={"HOLD": {"cik_str": 2, "ticker": "HOLD", "title": "Holdco Inc."},
                           "OLD": {"cik_str": 3, "ticker": "OLD", "title": "Oldco Inc."}},
                  first={2: "2017-03-01", 3: "1995-03-01"})
    own = _reading(edgar, name="PREDECESSOR CORP")
    assert own.one_for_one and own.target_issuer() == whom


def test_a_special_dividend_is_no_consideration():
    """KRFT 2015: the $16.50 the 8-K calls a special cash dividend is not cash in the exchange (operator ruling
    2026-10-04); other cash is."""
    text = _exchange("Kraft Heinz") + " Holders also received a special cash dividend of $16.50 per share."
    own = _reading(Edgar([_8k("a", "2017-09-01")], {"a": text}))
    assert own.statement.special_dividends == (16.5,)
    assert own.consideration(16.5) is None and own.consideration(16.0) == 16.0 and own.consideration(None) is None


def test_rule_1_reads_the_deal_8ks_too():
    """RRI Energy 2010: the 8-K that reports the 5.01 says Mirant's shares became the registrant's; it was filed
    outside the day's window, so only the deal's own day reads it. A statement about the registrant's own shares of
    any class means it did not survive."""
    acquirer = ("At the effective time, each outstanding share of common stock of Mirant was converted into the right "
                "to receive 2.835 shares of our common stock.")
    filings = [_8k("deal", "2017-07-03", items="5.01")]
    own = _reading(Edgar(filings, {"deal": acquirer}, name="RRI ENERGY INC"), name="RRI ENERGY INC")
    assert own.survived([]) == ""
    assert own.survived([date(2017, 7, 3)]).startswith("At the effective time, each outstanding share of common")
    target = _reading(Edgar(filings, {"deal": acquirer + " Each share of the Company's common stock was converted "
                                                          "into the right to receive $10.00 in cash."}))
    assert target.survived([date(2017, 7, 3)]) == ""
    assert not own.stated                                    # rule 1's read is not the class's statement


# --- one reading per ending ----------------------------------------------------------------------------------------

def _delisting():
    rec = DelistRecord("OLD", CIK, DAY.isoformat(), 304, CrspBucket.EXCHANGE_TRANSFER, "medium", "r", {"flags": []},
                       sec_id="OLD-ID", delist_date="2017-09-11")
    return Delisting("OLD-ID", CIK, "OLD", "2017-09-11", rec, LastTrade(DAY, "midas", ()), None, None, "NYSE")


def test_a_delisting_carries_its_reading_and_a_later_stage_reads_that_one():
    edgar = Edgar([_8k("a", "2017-09-01")], {"a": _exchange("Holdco")})
    reader = O.Reader(edgar, IssuerRecord(edgar))
    d, sec = _delisting(), SimpleNamespace(share_class="COMMON", name="OLD CORP")
    own = O.of(d, reader, sec)
    assert d.own_shares is own and own.day == d.anchor and own.one_for_one
    assert O.of(d, reader, sec) is own and edgar.read == ["a"]


@pytest.mark.parametrize("sec_id,ratio,stake_changed", [("BBG000PYZSR8", 0.9042, True), ("BBG000BT0093", 0.1, False)],
                         ids=["CHTR", "SIRI"])
def test_the_finder_carries_the_reading_rule_6_decided_on(sec_id, ratio, stake_changed):
    """CHTR 2016 is a merger by rule 6 (0.9042 New Charter); SIRI 2024's 0.1 New Sirius is a consolidation. The
    delisting carries the reading the classifier decided on, so stage 9g and the verdict read that ratio."""
    found, _ = ic.find(sec_id, ic.clients())
    own = found[0].own_shares
    assert own is not None and own.statement.ratio == ratio and own.statement.stake_changed is stake_changed
    assert found[0].record.bucket is (CrspBucket.MERGER if stake_changed else CrspBucket.EXCHANGE_TRANSFER)


def test_a_reading_the_classifier_never_asked_is_not_carried():
    """TW 2016: its 8-K items decide a merger; no rule reads its own shares, so stage 8b makes the reading."""
    c = ic.clients()
    found, _ = ic.find("BBG000BBLK04", c)
    assert found[0].own_shares is None
    ic.later("BBG000BBLK04", found, c)
    assert found[0].own_shares is not None and found[0].own_shares.day == found[0].anchor


def test_stages_8b_and_9_read_the_carried_reading():
    """OKE 2026: stage 5's R1 read the holding company's formation; stage 9 links the successor from that reading."""
    c = ic.clients()
    found, _ = ic.find("BBG000BQHGR6", c)
    own = found[0].own_shares
    assert own is not None and own.one_for_one
    ic.later("BBG000BQHGR6", found, c)
    assert found[0].own_shares is own
