import delist_detection.ticker_resolver as tr
from delist_detection.classifier import DelistClassifier
from delist_detection.edgar import EdgarSubmission
from delist_detection.ticker_resolver import TickerResolver

# Read at import, before the autouse fixture in conftest.py replaces it.
_REAL_EFTS_LOOKUP = TickerResolver._efts_lookup


class _Edgar:
    """Companies by CIK; name search answers by name prefix."""
    def __init__(self, companies, atom, tickers=None):
        self.companies = companies      # cik -> (name, formerNames, filings)
        self.atom = atom                # name prefix -> cik
        self.tickers = tickers or {}    # SEC's current ticker map
    def company_tickers(self):
        return self.tickers
    def submissions(self, cik, fresh_after=None):
        c = self.companies.get(int(cik))
        return {"name": c[0], "formerNames": c[1], "sic": ""} if c else {"__not_found__": True}
    def recent_filings(self, cik):
        c = self.companies.get(int(cik))
        return list(c[2]) if c else []
    def company_search_atom(self, company, form_type="25-NSE"):
        for prefix, cik in self.atom.items():
            if company.upper().startswith(prefix):
                return [{"cik": cik, "name": None, "form": "", "filing_date": ""}]
        return []
    def fetch_filing_text(self, *a):
        return ""


def _f(acc, form, d):
    return EdgarSubmission(acc, form, d, "", "", "x.htm")


def _real_efts(monkeypatch, hits):
    """Run the real _efts_lookup over these EFTS hits (no network)."""
    class _Resp:
        status_code = 200

        def json(self):
            return {"hits": {"hits": hits}}

    monkeypatch.setattr(TickerResolver, "_efts_lookup", _REAL_EFTS_LOOKUP)
    monkeypatch.setattr(tr.requests, "get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(tr, "_throttle", lambda: None)


def _hit(*pairs):
    return {"_source": {"ciks": [c for c, _ in pairs], "display_names": [n for _, n in pairs]}}


AVANOS = (1606498, ("AVANOS MEDICAL, INC.",
                    [{"name": "Halyard Health, Inc.", "from": "2014-06-02T04:00:00.000Z",
                      "to": "2018-06-28T04:00:00.000Z"}],
                    [_f("K1", "10-K", "2018-02-23"), _f("E1", "8-K", "2018-07-02")]))
FAST = (1815737, ("FAST Acquisition Corp.", [], [_f("S1", "S-1", "2020-08-01"), _f("F1", "25-NSE", "2022-08-26")]))
CITY = (38067, ("FOREST CITY REALTY TRUST", [], [_f("C1", "10-K", "2018-02-27"), _f("C2", "25-NSE", "2018-12-10")]))


def test_a_member_name_finds_a_renamed_company_that_filed_no_form25():
    e = _Edgar(dict([AVANOS]), {"HALYARD": 1606498})
    r = TickerResolver(e, member_names=lambda t, d=None: "HALYARD HEALTH INC")
    assert r.resolve("HYH", "2018-06-29").cik == 1606498


def test_without_a_member_name_the_loose_form25_check_still_applies():
    e = _Edgar(dict([AVANOS]), {"HALYARD": 1606498})
    r = TickerResolver(e, name_lookup=lambda t, d=None: "HALYARD HEALTH INC")
    assert r.resolve("HYH", "2018-06-29").cik is None


def test_a_frozen_tail_member_is_accepted_through_its_old_form25():
    xto = (868809, ("XTO ENERGY INC", [], [_f("X1", "8-K", "2010-06-25"), _f("X2", "25-NSE", "2010-06-28"),
                                          _f("X3", "15-12B", "2010-07-08")]))
    r = TickerResolver(_Edgar(dict([xto]), {"XTO": 868809}), member_names=lambda t, d=None: "XTO ENERGY INC")
    assert r.resolve("XTO", "2013-02-07").cik == 868809


def test_a_long_dead_member_is_not_accepted_for_a_later_event():
    dead = (765258, ("IMCLONE SYSTEMS INC", [], [_f("I1", "10-K", "2008-03-01")]))
    r = TickerResolver(_Edgar(dict([dead]), {"IMCLONE": 765258}),
                       member_names=lambda t, d=None: "IMCLONE SYSTEMS INC")
    assert r.resolve("IMCL", "2018-10-05").cik is None


def test_the_date_anchored_efts_hit_beats_the_member_name(monkeypatch):
    # FST: the vendor series is FAST Acquisition Corp; the member was Forest Oil.
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (1815737, "FAST Acquisition Corp. (FST)", False))
    r = TickerResolver(_Edgar(dict([FAST, CITY]), {"FOREST": 38067}),
                       member_names=lambda t, d=None: "FOREST OIL CORP")
    res = r.resolve("FST", "2022-08-25")
    assert (res.cik, res.source) == (1815737, "efts_name_mismatch")


def test_the_classifier_flags_a_kept_first_pass_hit_under_another_name(monkeypatch):
    _real_efts(monkeypatch, [_hit(("1815737", "FAST Acquisition Corp.  (FST)  (CIK 0001815737)"))])
    e = _Edgar(dict([FAST, CITY]), {"FOREST": 38067})
    r = TickerResolver(e, member_names=lambda t, d=None: "FOREST OIL CORP")
    rec = DelistClassifier(e, r).classify_ticker("FST", "2022-08-25")
    assert rec.cik == 1815737
    assert rec.evidence["resolution_source"] == "efts_name_mismatch"
    assert rec.evidence["flags"] == ["member_name_mismatch", "spac"]


def test_the_member_name_tier_runs_before_the_frequency_rank(monkeypatch):
    # LC with SEC's current ticker map: EFTS finds nothing; frequency rank would pick Comstock.
    lc = (1409970, ("Happen, Inc.", [{"name": "LendingClub Corp", "from": "2007-08-15T04:00:00.000Z",
                                      "to": "2026-06-18T04:00:00.000Z"}],
                    [_f("L1", "10-Q", "2026-05-05"), _f("L2", "25", "2026-06-18")]))
    comstock = (1299969, ("COMSTOCK INC", [], [_f("M1", "10-K", "2026-03-01")]))
    monkeypatch.setattr(TickerResolver, "_efts_pre_delist_frequency_ranked",
                        lambda self, t, d, top_n=5: [(1299969, "Comstock Inc"), (1409970, "LendingClub")])
    r = TickerResolver(_Edgar(dict([lc, comstock]), {"LENDINGCLUB": 1409970}),
                       member_names=lambda t, d=None: "LENDINGCLUB CORP")
    assert r.resolve("LC", "2026-06-01").cik == 1409970


def test_the_efts_second_pass_prefers_an_agreeing_name_and_falls_back_to_the_first(monkeypatch):
    hits = [_hit(("1354457", "Nasdaq Stock Market LLC  (CIK 0001354457)"),
                 ("1829426", "Far Peak Acquisition Corp  (CIK 0001829426)")),
            _hit(("765880", "HEALTHPEAK PROPERTIES, INC.  (DOC)  (CIK 0000765880)"))]
    _real_efts(monkeypatch, hits)
    r = TickerResolver(_Edgar({}, {}))
    assert r._efts_lookup("PEAK", "2023-02-13", expected_name="HEALTHPEAK PROPERTIES INC") == \
        (765880, "HEALTHPEAK PROPERTIES, INC.  (DOC)  (CIK 0000765880)", False)
    assert r._efts_lookup("PEAK", "2023-02-13") == (None, None, False)          # no name: no second pass
    assert r._efts_lookup("PEAK", "2023-02-13", expected_name="SOMETHING ELSE INC") == \
        (1829426, "Far Peak Acquisition Corp  (CIK 0001829426)", True)          # the fallback
    hits[0]["_source"]["display_names"][1] = "Far Peak Acquisition Corp  (PEAK)  (CIK 0001829426)"
    # first pass: the ticker token decides, whatever the expected name says
    cik, _, fallback = r._efts_lookup("PEAK", "2023-02-13", expected_name="SOMETHING ELSE INC")
    assert (cik, fallback) == (1829426, False)


def test_a_live_company_of_the_member_name_does_not_replace_the_efts_company(monkeypatch):
    # BWC: EFTS finds only Blue Whale's Form 25; the member name finds Babcock & Wilcox,
    # which kept filing and has no Form 25/15 near the date.
    blue = (1854863, ("Blue Whale Acquisition Corp I", [],
                      [_f("B0", "S-1", "2021-05-13"), _f("B1", "25-NSE", "2023-08-10")]))
    bw = (1630805, ("Babcock & Wilcox Enterprises, Inc.", [],
                    [_f("W0", "10-K", "2023-03-15"), _f("W1", "10-Q", "2023-08-08")]))
    _real_efts(monkeypatch, [_hit(("1854863", "Blue Whale Acquisition Corp I  (CIK 0001854863)"))])
    e = _Edgar(dict([blue, bw]), {"BABCOCK": 1630805})
    r = TickerResolver(e, member_names=lambda t, d=None: "BABCOCK AND WILCOX")
    res = r.resolve("BWC", "2023-08-11")
    assert (res.cik, res.source) == (1854863, "efts_name_mismatch")
    rec = DelistClassifier(e, r).classify_ticker("BWC", "2023-08-11")
    assert "member_name_mismatch" in rec.evidence["flags"]


def test_a_member_company_with_its_own_form25_replaces_the_efts_fallback(monkeypatch):
    # PEAK: EFTS finds only Far Peak; Healthpeak filed its own 25-NSE three days before the date.
    far = (1829426, ("Far Peak Acquisition Corp", [],
                     [_f("P0", "S-1", "2020-10-26"), _f("P1", "25-NSE", "2023-01-05")]))
    hp = (765880, ("HEALTHPEAK PROPERTIES, INC.", [],
                   [_f("H0", "10-K", "2022-02-09"), _f("H1", "25-NSE", "2023-02-10")]))
    _real_efts(monkeypatch, [_hit(("1829426", "Far Peak Acquisition Corp  (CIK 0001829426)"))])
    r = TickerResolver(_Edgar(dict([far, hp]), {"HEALTHPEAK": 765880}),
                       member_names=lambda t, d=None: "HEALTHPEAK PROPERTIES INC")
    res = r.resolve("PEAK", "2023-02-13")
    assert (res.cik, res.source) == (765880, "name_search")


def test_a_member_name_without_usable_words_is_no_expected_name():
    att = (732717, ("AT&T INC.", [], [_f("T0", "10-K", "2020-02-19"), _f("T1", "10-Q", "2023-11-01")]))
    e = _Edgar(dict([att]), {}, tickers={"T": {"cik_str": 732717, "ticker": "T", "title": "AT&T INC."}})
    r = TickerResolver(e, member_names=lambda t, d=None: "AT&T INC.")
    assert r._expected_name("T", "2024-01-02") is None
    res = r.resolve("T", "2024-01-02")
    assert (res.cik, res.source) == (732717, "company_tickers")
    rec = DelistClassifier(e, r).classify_ticker("T", "2024-01-02")
    assert rec.evidence["flags"] == ["resolved_by_current_ticker_map"]


def test_exchange_ciks_include_nyse_llc_and_cboe_bzx():
    assert {876661, 1417835} <= TickerResolver.EXCHANGE_CIKS


def test_the_efts_fallback_skips_the_exchange_that_filed_the_form25(monkeypatch):
    # NYSE LLC and Cboe BZX file Form 25s for their issuers; neither is the company that delisted
    far_peak = "Far Peak Acquisition Corp  (CIK 0001829426)"
    _real_efts(monkeypatch, [_hit(("0000876661", "NEW YORK STOCK EXCHANGE LLC  (CIK 0000876661)"),
                                  ("0001417835", "Cboe BZX Exchange, Inc.  (CIK 0001417835)"),
                                  ("0001829426", far_peak))])
    r = TickerResolver(_Edgar({}, {}))
    assert r._efts_lookup("PEAK", "2023-02-13", expected_name="HEALTHPEAK PROPERTIES") == (1829426, far_peak, True)
