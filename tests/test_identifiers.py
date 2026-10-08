"""The identifiers leaf (architecture step 13) at its interface: each ticker spelling, the placeholder sec_id, and each
reader of a share class, one per kind of text, with the real cases the code cites."""
import pytest

from delist_detection.identifiers import (
    CLASS_MODIFIERS, answer_class_letter, bare_ticker, bloomberg_ticker, class_letter, class_of, class_suffix,
    description_class_letter, descriptions_class_letter, figi_class_letter, is_placeholder, name_class_letter,
    normalize_ticker, placeholder_id, prose_class_letters, regular_way, share_class_from_name, strip_class_words,
)

# --- ticker spellings ---------------------------------------------------------------------------------------------


def test_normalize_ticker():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_ticker("BF/A") == "BF-A"
    assert normalize_ticker("BRK B") == "BRK-B"
    assert normalize_ticker("AET") == "AET"
    assert normalize_ticker("LGF.B") == "LGF-B"        # Lions Gate's class B, as the gate asks it (step 12)
    assert normalize_ticker("") == "" and normalize_ticker(None) == ""


def test_regular_way_strips_a_when_issued_suffix_and_nothing_else():
    assert [regular_way(t) for t in ("EHAB-WI", "EHAB WI", "ehab.wi", "EHAB W/I", "AWI", "BF-B", "WI")] == [
        "EHAB", "EHAB", "EHAB", "EHAB", "AWI", "BF-B", "WI"]


def test_openfigis_spelling_puts_the_class_after_a_slash():
    assert bloomberg_ticker("BF-A") == "BF/A"
    assert bloomberg_ticker("aet") == "AET"
    assert bloomberg_ticker("BRK.B") == "BRK/B"


def test_the_fails_files_spell_a_class_ticker_without_its_separator():
    """BRKB and LGFB: the fails files' (and the snapshots') spelling of Berkshire's and Lions Gate's class B."""
    assert [bare_ticker(t) for t in ("BRK-B", "LGF-B", "BF-B", "AET")] == ["BRKB", "LGFB", "BFB", "AET"]
    assert bare_ticker("YRCW") + "D" == "YRCWD"        # a post-split symbol is the bare spelling with D appended


def test_a_one_letter_class_tickers_base_and_letter():
    """UAC-C is a snapshot's spelling of Under Armour's class C, which the fails files list whole as UAC (5h)."""
    assert class_suffix("UAC-C") == ("UAC", "C")
    assert class_suffix("BRK-B") == ("BRK", "B")
    assert class_suffix("LGF-B") == ("LGF", "B")
    assert [class_suffix(t) for t in ("GOOGL", "EHAB-WI", "BRKB", "BRK-B1", "")] == [None] * 5


# --- the placeholder sec_id ---------------------------------------------------------------------------------------


def test_share_class_and_placeholders():
    assert placeholder_id(1122304, None) == "CIK1122304-COMMON"
    assert placeholder_id(14693, "CLASS A") == "CIK14693-CLASS-A"
    assert is_placeholder("CIK1-COMMON") and not is_placeholder("BBG000FJLFX8")


def test_a_placeholder_is_built_from_a_class_code_only():
    assert placeholder_id(1, "SERIES A") == "CIK1-SERIES-A"
    assert placeholder_id(1, share_class_from_name("BERKSHIRE HATHAWAY INC CLASS B")) == "CIK1-CLASS-B"
    with pytest.raises(ValueError):
        placeholder_id(1, "Class A Common Stock")


# --- a security's name --------------------------------------------------------------------------------------------


def test_the_class_code_a_name_states():
    assert share_class_from_name("ALPHABET INC-CL C") == "CLASS C"
    assert share_class_from_name("META PLATFORMS INC-CLASS A") == "CLASS A"
    assert share_class_from_name("DISCOVERY INC-A") == "CLASS A"
    assert share_class_from_name("LIBERTY BROADBAND-SER C") == "SERIES C"
    assert share_class_from_name("CLOROX CO") == "COMMON"
    assert share_class_from_name(None) == "COMMON"
    # real observed names: Lennar's class B, Berkshire's class B; Liberty Capital's tracking stock (LCAPA) states
    # no class in its name, and Under Armour's "A" sits inside the name, not after it
    assert share_class_from_name("LENNAR CORP. CL B") == "CLASS B"
    assert share_class_from_name("BERKSHIRE HATHAWAY INC CLASS B") == "CLASS B"
    assert share_class_from_name("LIBERTY CAPITAL") == "COMMON"
    assert share_class_from_name("UNDER ARMOUR A INC") == "COMMON"


def test_a_class_codes_letter():
    assert class_letter("SERIES C") == "C" and class_letter("CLASS A") == "A" and class_letter("COMMON") is None
    assert class_letter(None) is None and class_letter("Class A Common Stock") is None


def test_the_class_letter_a_name_states():
    """The letter is what counts: "CLASS A" and "SERIES A" are one class (LMCA's real names); a name with no class
    is unknown, not a class of its own."""
    assert name_class_letter("GOOGLE INC CLASS C") == "C"
    assert name_class_letter("LIBERTY MEDIA CORP CLASS A") == name_class_letter("LIBERTY MEDIA CORP SERIES A") == "A"
    assert name_class_letter("VIACOM INC CLASS B") == "B"
    assert name_class_letter("DISCOVERY INC-A") == "A"
    assert name_class_letter("GOOGLE INC") is None and name_class_letter(None) is None


def test_a_name_without_its_class_words():
    """As an 8-K12B prints the predecessor (the successor searches of stages 9 and the handoffs)."""
    assert strip_class_words("GOOGLE INC CLASS A") == "GOOGLE INC"
    assert strip_class_words("ALPHABET INC-CL C") == "ALPHABET INC"
    assert strip_class_words("Liberty Media Corp Series A") == "Liberty Media Corp"
    assert strip_class_words("DISCOVERY INC-A") == "DISCOVERY INC"
    assert strip_class_words("AON PLC CLASS A") == "AON PLC"
    # CAPITAL is a word of Liberty Capital's name, not a class word
    assert strip_class_words("LIBERTY CAPITAL") == "LIBERTY CAPITAL"
    assert strip_class_words(None) == ""


# --- an OpenFIGI name's last letter -------------------------------------------------------------------------------


def test_the_class_letter_an_openfigi_name_ends_with():
    """Sub-plan 5h's rule B: Bloomberg writes the class after a dash and a space (MSG Networks, Starz), which a
    name's own reader does not read."""
    assert [figi_class_letter(n) for n in ("MSG NETWORKS INC- A", "STARZ - A", "GRAHAM HOLDINGS CO-CLASS B",
                                           "HUBBELL INC", "ALPHABET INC-CL A", "WW INTERNATIONAL INC")] == \
        ["A", "A", "B", None, "A", None]
    assert name_class_letter("MSG NETWORKS INC- A") is None and name_class_letter("STARZ - A") is None


# --- a fails-to-deliver description -------------------------------------------------------------------------------


def test_the_class_letter_one_fails_description_names():
    """The fails index's base relabel (UAC-C, 5h) and the line follow's class refusal read one description so."""
    assert description_class_letter("UNDER ARMOUR INC CL C") == "C"
    assert description_class_letter("UNDER ARMOUR INC CLASS C") == "C"
    assert description_class_letter("GREIF, INC. CL-A") == "A"
    assert description_class_letter("SINCLAIR INC CL A") == "A"
    assert description_class_letter("NEWS CORP NEW CL B COM STK (DE") == "B"
    # a series is no class letter here (CELANESE CORPORATION SER A COM), and neither is a letter the name ends with
    assert description_class_letter("CELANESE CORPORATION SER A COM") is None
    assert description_class_letter("LAMAR ADVERTISING CO-A") is None
    assert description_class_letter("HEICO CORP") is None and description_class_letter(None) is None


def test_the_letter_a_securitys_fails_descriptions_name():
    """R2 (5b): SunPower's class A placeholder ("SUNPOWER CORP CL A"); two letters name no one class. Its rule is
    its own: a letter after a space only ("CONTL AIRLINES INC CL-B" names none), and a series counts."""
    assert descriptions_class_letter(["SUNPOWER CORP CL A"]) == "A"
    assert descriptions_class_letter(["LIBERTY INTERACTIVE CORP SER A", "LIBERTY INTERACTIVE CORP"]) == "A"
    assert descriptions_class_letter(["X CORP CLASS A", "X CORP CL B"]) is None
    assert descriptions_class_letter(["SUNPOWER CORP", ""]) is None
    assert descriptions_class_letter(d for d in ["SUNPOWER CORP CL A"]) == "A"     # any iterable
    assert descriptions_class_letter(["CONTL AIRLINES INC CL-B"]) is None
    assert description_class_letter("CONTL AIRLINES INC CL-B") == "B"
    assert descriptions_class_letter(["CELANESE CORPORATION COM STK", "CELANESE CORPORATION SER A COM"]) == "A"


# --- an LLM answer's share class ----------------------------------------------------------------------------------


def test_the_letter_of_the_share_class_an_answer_names():
    """CAA 2018: the Lennar leg's "Class B" (published as LEN-B); BPYU 2021's "BPY preferred unit" names none."""
    assert [answer_class_letter(t) for t in ("B", "Class B", "Series C common", "class a ordinary")] == \
        ["B", "B", "C", "A"]
    assert [answer_class_letter(t) for t in ("preferred unit", "common", "", None)] == ["", "", "", ""]


# --- a filing's prose ---------------------------------------------------------------------------------------------


def test_the_class_letters_a_filings_prose_names():
    """An 8-K's sentence (the own-share reading) and an LLM answer's quote (the acquirer line) are read alike.
    Viacom 2019: both the class converted and the class received are read (class B's own quote names A, so it is
    class A's, VIA-B); GLIBA 2020's Liberty Broadband Series C; CAA 2018's two Lennar classes."""
    assert prose_class_letters("each share of Class A common stock of Viacom was converted automatically into "
                               "0.59625 shares of ViacomCBS Class A Common Stock") == ["A", "A"]
    assert prose_class_letters("0.580 of a share of Liberty Broadband Series C common stock") == ["C"]
    assert prose_class_letters("The Company's stockholders are receiving as Merger consideration 0.885 shares of "
                               "Lennar Class A common stock and 0.0177 shares of Lennar Class B") == ["A", "B"]
    # Envision Healthcare's 2016 merger 8-K (0001193125-16-787541): "Series A-1" is its own series, not series A
    assert prose_class_letters("each share of the Company's 5.250% mandatory convertible preferred stock, Series A-1 "
                               "was converted") == []
    assert prose_class_letters("class b common stock") == [] and prose_class_letters(None) == []


# --- the words that set a class apart -----------------------------------------------------------------------------


def test_the_class_is_the_securitys_share_class_and_the_words_its_name_sets_it_apart_by():
    assert class_of("CLASS A", "COMCAST SPECIAL CORP CLASS A") == ("A", ("SPECIAL",))
    assert class_of("COMMON", "ONEOK INC") == ("", ())
    assert class_of("CLASS B", "LIONS GATE ENTERTAINMENT NON-VOTING") == ("B", ("NON-VOTING",))
    assert CLASS_MODIFIERS == ("SPECIAL", "NON-VOTING", "LIMITED VOTING")
