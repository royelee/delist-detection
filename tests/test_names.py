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
