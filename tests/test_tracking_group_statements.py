"""exchange_terms.own_exchange over tracking-stock groups (batch 3 gate, FNFV 2017 and LCAPA 2011): the registrant's
statement of what a group's shares became, read for a security whose class code is the plain COMMON. The real 8-K
texts (tests/fixtures/own_shares/texts.json) come from the local EDGAR caches."""
from __future__ import annotations

import json
from pathlib import Path

from delist_detection.endings import exchange_terms as X

TEXTS = json.loads((Path(__file__).parent / "fixtures" / "own_shares" / "texts.json").read_text())
FNF_8K, LIBERTY_8K = TEXTS["0001104659-17-069547"], TEXTS["0001104659-11-053828"]
LIBERTY = ["LIBERTY MEDIA CORP"]


def test_a_groups_security_reads_the_statement_of_its_own_group_not_another_groups():
    """LCAPA 2011: 'Liberty Capital' (a placeholder with the plain class COMMON) takes the Series A Liberty Capital
    statement of the Liberty Media 8-K, one share for one share of Splitco's, not the Liberty Starz one."""
    own = X.own_exchange([LIBERTY_8K], names=[*LIBERTY, "LIBERTY CAPITAL"], class_letter="",
                         security_name="LIBERTY CAPITAL", issuer_names=LIBERTY)
    assert own is not None and own.one_for_one and "Liberty Capital" in own.target
    assert "Starz" not in own.target and "Splitco" in " ".join(own.target_names)


def test_the_other_group_reads_its_own_statement():
    own = X.own_exchange([LIBERTY_8K], names=[*LIBERTY, "LIBERTY STARZ"], class_letter="",
                         security_name="LIBERTY STARZ", issuer_names=LIBERTY)
    assert own is not None and "Liberty Starz" in own.target


def test_without_the_securitys_group_name_a_lettered_statement_is_still_no_plain_commons():
    """A plain COMMON with no group of its own in its name takes no lettered statement (as before)."""
    assert X.own_exchange([LIBERTY_8K], names=["LIBERTY MEDIA CORP", "ACME CORP"], class_letter="",
                          security_name="ACME CORP", issuer_names=LIBERTY) is None
    assert X.own_exchange([LIBERTY_8K], names=LIBERTY, class_letter="") is None


def test_a_redemption_of_a_tracking_group_for_the_new_issuers_shares_is_read():
    """FNFV 2017: 'redemption on a per share basis of each outstanding share of FNFV common stock for one share of
    Cannae common stock', no cash but in lieu of fractions."""
    own = X.own_exchange([FNF_8K], names=["Fidelity National Financial, Inc.", "FNFV GROUP INC"], class_letter="")
    assert own is not None and own.one_for_one
    assert "Cannae" in own.target_names


# --- the target is the registrant's former subsidiary, whose name the registrant itself carried until the split ---

def test_a_target_the_filing_calls_the_registrants_subsidiary_is_another_entity_than_the_registrants_old_name():
    """LCAPA 2011: Liberty Media Corporation (the registrant, renamed Liberty Interactive that day) split off its
    subsidiary Liberty Media Corporation ('Splitco', formerly Liberty CapStarz): the same name, a new issuer."""
    own = X.own_exchange([LIBERTY_8K], names=[*LIBERTY, "LIBERTY CAPITAL"], class_letter="",
                         security_name="LIBERTY CAPITAL", issuer_names=LIBERTY)
    assert "Liberty Media Corporation" in own.target_names and own.target_subsidiary


def test_a_split_offs_target_is_the_registrants_former_subsidiary():
    """FNFV 2017: 'its former wholly-owned subsidiary Cannae Holdings, Inc. ("Cannae")'."""
    own = X.own_exchange([FNF_8K], names=["Fidelity National Financial, Inc.", "FNFV GROUP INC"], class_letter="")
    assert own.target_subsidiary
    plain = X.own_exchange(["Each share of the Company's common stock was converted into one share of Holdco common "
                            "stock. Holdco Inc., a Delaware corporation (\"Holdco\")."], names=["Acme Corp"],
                           class_letter="")
    assert plain is not None and not plain.target_subsidiary
