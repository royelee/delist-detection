import pytest

from delist_detection.names import description_matches, name_tokens, names_agree


def test_tokens_keep_three_letter_words_and_drop_legal_suffixes():
    assert name_tokens("SUNPOWER CORP.") == {"SUNPOWER"}
    assert name_tokens("Far Peak Acquisition Corp") == {"FAR", "PEAK", "ACQUISITION"}
    assert name_tokens("FOREST OIL CORP") == {"FOREST", "OIL"}
    assert name_tokens("BABCOCK AND WILCOX") == {"BABCOCK", "WILCOX"}
    assert name_tokens("LEAP WIRELESS INTL INC") == {"LEAP", "WIRELESS"}


def test_agreement_needs_two_shared_words_unless_a_name_has_one():
    assert names_agree("HALYARD HEALTH INC", "Halyard Health, Inc.")
    assert names_agree("SUNPOWER CORP.", "SunPower Inc.")               # one-word names: one shared word
    assert names_agree("XTO ENERGY INC", "XTO ENERGY INC")
    assert not names_agree("HEALTHPEAK PROPERTIES INC", "Far Peak Acquisition Corp")
    assert not names_agree("SUNPOWER CORP.", "Complete Solaria, Inc.")
    assert not names_agree("FOREST OIL CORP", "Forest City Enterprises Inc")   # FST
    assert not names_agree("LEAP WIRELESS INTL INC", "Ribbit LEAP, Ltd.")      # LEAP
    assert not names_agree("XTO ENERGY INC", "ABC Energy Inc")
    assert not names_agree("", "Anything")


def test_a_possessive_apostrophe_does_not_split_a_word():
    """EDGAR writes "Macy's, Inc." and "DILLARD'S, INC.", the snapshots MACYS and
    DILLARDS: the apostrophe (straight or curly) is dropped, not a word break."""
    assert name_tokens("Macy's, Inc.") == {"MACYS", "MACY"}
    assert name_tokens("DILLARD’S, INC.") == {"DILLARDS", "DILLARD"}
    assert names_agree("MACYS INC", "Macy's, Inc.")
    assert names_agree("DILLARDS INC CLASS A", "DILLARD'S, INC.")
    assert names_agree("O'REILLY AUTOMOTIVE INC", "OREILLY AUTOMOTIVE INC")
    assert names_agree("LOWE'S COMPANIES INC", "LOWES COMPANIES INC")


def test_an_apostrophe_word_matches_both_the_joined_and_the_split_spelling():
    """Snapshots write O'Reilly as OREILLY, O REILLY and O'REILLY, and Frank's
    as FRANK S: a word with an apostrophe gives both the joined form (OREILLY,
    MACYS, FRANKS) and the split one (REILLY; MACY; FRANK), so each spelling
    matches either."""
    assert names_agree("MACY'S, INC.", "MACYS INC")
    assert names_agree("O'REILLY AUTOMOTIVE INC", "O REILLY AUTOMOTIVE INC")
    assert names_agree("O'REILLY AUTOMOTIVE INC", "OREILLY AUTOMOTIVE INC")
    assert names_agree("Frank's International N.V.", "FRANK S INTERNATIONAL NV")
    assert names_agree("Frank's International N.V.", "FRANKS INTERNATIONAL NV")
    assert name_tokens("O'Reilly Automotive") == {"OREILLY", "REILLY", "AUTOMOTIVE"}


def test_a_possessive_word_counts_once_toward_the_words_needed():
    """"Wendy's Co" is one word (WENDYS or WENDY), not two: it needs one shared
    word, as a one-word name does. Before, its two spellings raised the need to
    two and it no longer agreed with "WENDYS ARBYS GROUP INC"."""
    assert names_agree("WENDYS ARBYS GROUP INC", "Wendy's Co")
    assert names_agree("MACYS RETAIL HOLDINGS INC", "Macy's, Inc.")
    assert names_agree("O'REILLY AUTOMOTIVE INC", "O REILLY AUTOMOTIVE INC")
    assert names_agree("O'REILLY AUTOMOTIVE INC", "OREILLY AUTOMOTIVE INC")
    assert names_agree("Frank's International N.V.", "FRANK S INTERNATIONAL NV")
    assert names_agree("Frank's International N.V.", "FRANKS INTERNATIONAL NV")
    # two words on each side still need two shared words, a possessive counted once
    assert not names_agree("Macy's Foods Inc", "MACYS RETAIL HOLDINGS INC")
    assert not names_agree("MACY MACYS FOODS", "Macy's Retail Holdings")


# Real SEC fails-to-deliver descriptions (as SEC truncates them) against the era's
# observed names and its issuer's EDGAR names, current and former.
@pytest.mark.parametrize("description, names", [
    # controls: the right CUSIP of each, and it keeps it
    ("APPLE INC;COM NPV", ["APPLE INC"]),
    ("JOHNSON AND JOHNSON", ["JOHNSON & JOHNSON"]),
    ("MICROSOFT CORP;COM USD0.000012", ["MICROSOFT CORP"]),
    ("EXXON MOBIL CORPORATION", ["EXXON MOBIL CORP"]),
    ("DELL TECHNOLOGIES INC COM CL C", ["DELL TECHNOLOGIES INC CLASS C"]),
    ("DOW INC COM", ["DOW INC"]),
    ("FOX CORP CL A (DE)", ["FOX CORP CLASS A"]),
    ("GOOGLE INC;COM USD0.001 CL'A'", ["GOOGLE INC"]),
    ("MONDELEZ INTL INC;COM USD0.01", ["MONDELEZ INTERNATIONAL INC CLASS A"]),
    ("ALTRIA GROUP,INC.", ["ALTRIA GROUP INC"]),
    ("LUMEN TECHNOLOGIES, INC. (LA)", ["LUMEN TECHNOLOGIES INC"]),
    ("CLIFFS NATURAL RES;COM STK USD", ["CLEVELAND CLIFFS INC"]),
    # a description that lags a rename, or a snapshot that backfilled the later
    # name: the issuer's former EDGAR name carries it
    ("SEATTLE GENETICS INC", ["SEAGEN INC", "Seagen Inc.", "SEATTLE GENETICS INC /WA"]),
    ("COACH INC.", ["TAPESTRY INC", "TAPESTRY, INC.", "COACH INC"]),
    ("CORRECTIONS CORP OF AMER (NEW)", ["CORECIVIC CORP", "CoreCivic, Inc.", "CORRECTIONS CORP OF AMERICA"]),
    ("WABTEC (COMMON)", ["WESTINGHOUSE AIR BRAKE TECHNOLOGIE", "WESTINGHOUSE AIR BRAKE TECHNOLOGIES CORP",
                         "WABTEC CORP"]),
    ("IAC INC. COM", ["PEOPLE", "People Inc", "IAC Inc.", "IAC/InterActiveCorp"]),
    # a word written short
    ("GEN ELEC CO COM NEW (NY)", ["GENERAL ELECTRIC"]),
    ("MP MATLS CORP COM", ["MP MATERIALS CORP CLASS A"]),
    ("APTAGROUP INC", ["APTARGROUP INC"]),
    ("SS&C TECH HLDGS INC COM STK (D", ["SS&C TECHNOLOGIES HOLDINGS INC."]),
    # a plural S one side leaves out
    ("HANESBRANDS INC COM STK", ["HANESBRAND INC"]),
    # words run together, one way or the other
    ("MC DERMOTT INTL", ["MCDERMOTT INTL INC"]),
    ("MARKET  AXESS HOLDINGS, INC.", ["MARKETAXESS HOLDINGS INC"]),
    ("BORGWARNER INC", ["BORG WARNER INC"]),
    # nothing to compare: no word left on one side
    ("3M COMPANY;COM USD0.01", ["3M CO"]),
    ("HP INC COM STK (DE)", ["HP INC", "HEWLETT PACKARD CO"]),
    ("RH COM(DE)", ["RH", "Restoration Hardware Holdings Inc"]),
    # ... also when the state or country after the "(" is a word ("IRE")
    ("XL GROUP PLC ORDINARY SHS (IRE", ["XL GROUP PLC", "XL GROUP LTD", "XL CAPITAL LTD", "EXEL LTD"]),
])
def test_a_fails_description_matches_its_own_company(description, names):
    assert description_matches(description, names)


@pytest.mark.parametrize("description, names", [
    # code review 2026-09-25: another company's rows under a stale or backfilled era's ticker
    ("COMPANIA CERVECER UNIDAS ADS(5", ["CLEAR CHANNEL COMM INC", "iHeartCommunications, Inc.",
                                        "CLEAR CHANNEL COMMUNICATIONS INC"]),
    ("STANTEC INC. COM", ["STATION CASINOS INC"]),
    ("SILVERCORP METALS INC COM (CAN", ["SERVICEMASTER CO", "SERVICEMASTER CO, LLC"]),
    ("AVIVA PLC ADR REP 2 ORD SHS (G", ["AVAYA INC", "LUCENT EN CORP"]),
    # Eversource's later name must not reach EnergySolutions through ENERGY
    ("ENERGYSOLUTIONS INC. COM", ["NORTHEAST UTILITIES", "EVERSOURCE ENERGY", "NORTHEAST UTILITIES SYSTEM"]),
    ("ACCRETIVE HEALTH, INC COMMON S", ["ARMOR HOLDINGS INC", "AMERICAN BODY ARMOR & EQUIPMENT INC"]),
    ("THOMSON REUTERS CORP", ["TRIAD HOSPITALS INC", "TRIAD HOSPITALS LLC"]),
    ("FIRST TRUST STRATEGIC HIGH INC", ["FEDERATED HERMES INC CLASS B", "FEDERATED HERMES, INC.",
                                        "FEDERATED INVESTORS INC /PA/"]),
    ("ELEMENTS BG SMALL CAP ETN 08/1", ["BEAR STEARNS COS INC", "BEAR STEARNS COMPANIES INC"]),
    ("NOCERA INC", ["NEWS CORP. CL A", "TWENTY-FIRST CENTURY FOX, INC.", "NEWS CORP"]),
    ("SHELTON GTR CHINA FD SH BEN IN", ["TRUIST FINANCIAL CORP", "BB&T CORP", "SOUTHERN NATIONAL CORP /NC/"]),
    ("CYTTA CORP NEW COM STK (NV)", ["CYTYC CORP"]),
])
def test_a_fails_description_of_another_company_does_not_match(description, names):
    assert not description_matches(description, names)
