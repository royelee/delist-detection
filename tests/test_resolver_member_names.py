from delist_detection.edgar import EdgarSubmission
from delist_detection.ticker_resolver import TickerResolver


class _Edgar:
    """Companies by CIK; name search answers by name prefix."""
    def __init__(self, companies, atom):
        self.companies = companies      # cik -> (name, formerNames, filings)
        self.atom = atom                # name prefix -> cik
    def company_tickers(self):
        return {}
    def submissions(self, cik):
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


AVANOS = (1606498, ("AVANOS MEDICAL, INC.",
                    [{"name": "Halyard Health, Inc.", "from": "2014-06-02T04:00:00.000Z",
                      "to": "2018-06-28T04:00:00.000Z"}],
                    [_f("K1", "10-K", "2018-02-23"), _f("E1", "8-K", "2018-07-02")]))


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
    fast = (1815737, ("FAST Acquisition Corp.", [], [_f("S1", "S-1", "2020-08-01"), _f("F1", "25-NSE", "2022-08-26")]))
    city = (38067, ("FOREST CITY REALTY TRUST", [], [_f("C1", "10-K", "2018-02-27"), _f("C2", "25-NSE", "2018-12-10")]))
    monkeypatch.setattr(TickerResolver, "_efts_lookup",
                        lambda self, t, d=None, **kw: (1815737, "FAST Acquisition Corp. (FST)"))
    r = TickerResolver(_Edgar(dict([fast, city]), {"FOREST": 38067}),
                       member_names=lambda t, d=None: "FOREST OIL CORP")
    assert r.resolve("FST", "2022-08-25").cik == 1815737


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

def test_the_efts_second_pass_keeps_only_a_hit_whose_name_agrees(monkeypatch):
    # tests/golden.py replays this rule over captured hits; this pins the real method.
    import delist_detection.ticker_resolver as tr
    monkeypatch.undo()                                   # the real _efts_lookup, with requests stubbed
    hits = [{"_source": {"ciks": ["1354457", "1829426"],
                         "display_names": ["Nasdaq Stock Market LLC  (CIK 0001354457)",
                                           "Far Peak Acquisition Corp  (CIK 0001829426)"]}},
            {"_source": {"ciks": ["765880"],
                         "display_names": ["HEALTHPEAK PROPERTIES, INC.  (DOC)  (CIK 0000765880)"]}}]

    class _Resp:
        status_code = 200
        def json(self):
            return {"hits": {"hits": hits}}
    monkeypatch.setattr(tr.requests, "get", lambda *a, **kw: _Resp())
    monkeypatch.setattr(tr, "_throttle", lambda: None)
    r = TickerResolver(_Edgar({}, {}))
    assert r._efts_lookup("PEAK", "2023-02-13", expected_name="HEALTHPEAK PROPERTIES INC")[0] == 765880
    assert r._efts_lookup("PEAK", "2023-02-13") == (None, None)
    assert r._efts_lookup("PEAK", "2023-02-13", expected_name="SOMETHING ELSE INC") == (None, None)
    hits[0]["_source"]["display_names"][1] = "Far Peak Acquisition Corp  (PEAK)  (CIK 0001829426)"
    assert r._efts_lookup("PEAK", "2023-02-13")[0] == 1829426      # first pass: the ticker token decides
