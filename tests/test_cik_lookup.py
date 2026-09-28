"""SEC's cik-lookup-data.txt as a local name -> CIK index (cik-lookup plan)."""
from pathlib import Path

from delist_detection.cik_lookup import CikNameIndex, normalize_name

EXCERPT = (Path(__file__).parent / "fixtures" / "cik_lookup" / "excerpt.txt").read_text(encoding="latin-1")


def _index():
    return CikNameIndex.from_text(EXCERPT)


def _ciks(hits):
    return [h.cik for h in hits]


def test_normalize_name_drops_case_punctuation_ampersands_and_the_state_tag():
    assert normalize_name("Merrill Lynch & Co., Inc.") == "MERRILL LYNCH CO INC"
    assert normalize_name("JACOBS ENGINEERING GROUP INC /DE/") == "JACOBS ENGINEERING GROUP INC"
    assert normalize_name("MERRILL LYNCH PIERCE FENNER & SMITH INC /NY") == "MERRILL LYNCH PIERCE FENNER SMITH INC"
    assert normalize_name("  'MKTG,   INC.' ") == "MKTG INC"
    assert normalize_name("") == ""


def test_the_excerpt_parses_every_named_line_and_skips_nameless_ones():
    idx = _index()
    assert len(idx) == 27                       # 29 lines, 2 with no name
    (hit,) = idx.search("2I CAPITAL PCC: STRATEGIC FUND I")      # a colon inside the name survives
    assert (hit.cik, hit.name) == (1508295, "2I CAPITAL PCC: STRATEGIC FUND I")


def test_exact_matches_come_before_prefix_matches():
    hits = _index().search("BARNES & NOBLE INC")
    assert _ciks(hits) == [890491]
    exact, prefix = _index().split_search("AMERICREDIT CORP")
    assert (_ciks(exact), _ciks(prefix)) == ([804269], [1037688])


def test_a_prefix_matches_on_a_word_boundary_only():
    """EDGAR's prefix search, on whole words: BARNES finds BARNES & NOBLE and
    BARNES BANCORP, never BARNESANDNOBLE COM."""
    ciks = set(_ciks(_index().search("BARNES")))
    assert {890491, 1634117, 1222169, 2150699} <= ciks and 1069665 not in ciks


def test_a_former_name_finds_the_current_cik():
    """The file is cumulative: Michael Kors' 2018 rename to Capri Holdings keeps
    CIK 1530721 under both names."""
    assert _ciks(_index().search("MICHAEL KORS HOLDINGS LTD")) == [1530721]
    assert _ciks(_index().search("CAPRI HOLDINGS LTD")) == [1530721]


def test_punctuation_and_state_tags_do_not_block_a_match():
    idx = _index()
    assert sorted(set(_ciks(idx.search("Anheuser-Busch Companies Inc")))) == [310569]
    assert sorted(set(_ciks(idx.search("MERRILL LYNCH CO INC")))) == [65100, 735164]
    assert sorted(set(_ciks(idx.search("JACOBS ENGINEERING GROUP")))) == [52988, 878737, 1963960]


def test_an_unknown_or_blank_query_finds_nothing():
    assert _index().search("NO SUCH COMPANY") == [] and _index().search("  ") == []
