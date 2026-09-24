from delist_detection.names import name_tokens, names_agree


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
