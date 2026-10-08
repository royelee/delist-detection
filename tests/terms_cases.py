"""Sub-plan 5f's real terms cases, replayed offline: tests/fixtures/terms/cases.json (built once from the local caches
and a run's tables by scripts/build_terms_fixtures.py) holds each case's merger ending (last trade, last close, the
acquirer price and security the run found), the prompt-v3 LLM answer the run read for it and the regex payout read.
`outcome(case_id)` runs the payout gate (`payout_gate.gate_payouts`) and the payout rule (`payout_rule.value_fields`)
over them, as stages 8 and 10g do, and gives the contract's value fields."""
from __future__ import annotations

import json
from pathlib import Path

from delist_detection.edgar import EdgarSubmission
from delist_detection.llm_merger_extractor import LLMMergerTermsExtractor, base_reading, states_no_package
from delist_detection.payout_gate import DEFAULT_TOL, gate_payouts
from delist_detection.dlret import MergerInputs
from delist_detection.payout_rule import basket_legs, value_fields
from delist_detection.reconstruction import for_delisting
from delist_detection.store import DelistingKey, format_cell
from lifecycle_tables import ending

FIX = Path(__file__).parent / "fixtures" / "terms"
DATA = json.loads((FIX / "cases.json").read_text())
VALUE_FIELDS = ("value_rule", "cash_per_share", "cash_currency", "stock_ratio", "price_ticker")


def terms(case_id: str):
    c = DATA["cases"][case_id]
    if c["llm"] is None:
        return None
    f = EdgarSubmission(accession=c["filing"]["accession"], form=c["filing"]["form"], filing_date="",
                        report_date="", items="", primary_doc="")
    t = LLMMergerTermsExtractor._to_terms(c["llm"], f)
    if t is not None and states_no_package(t):         # as the extractor does: the earlier prompt's reading stands
        t = base_reading(t, LLMMergerTermsExtractor._to_terms(c.get("legacy"), f)) or t
    return t


def outcome(case_id: str) -> dict[str, str]:
    """The contract's value fields of the case's ending (strings, as the contract writes them), and `legs`: the
    payout_legs.csv rows' (ratio, ticker)."""
    c = DATA["cases"][case_id]
    key = DelistingKey(c["sec_id"], c["delist_date"])
    t, regex, close = terms(case_id), c["regex"], c["last_close"]
    g = gate_payouts([key], {key: regex["value"]} if regex else {}, {key: regex["source"]} if regex else {},
                     {key: regex["confidence"]} if regex else {}, {key: t} if t is not None else {},
                     {c["sec_id"]: close} if close is not None else {}, {},
                     lambda ticker, k: c["acquirer_price"], DEFAULT_TOL)
    merged = for_delisting(g.merged_terms, key) or {}
    cash = merged.get("cash_per_share", g.payouts.get(key))
    row = ending(c["sec_id"], c["delist_date"], ltd=c["last_trade_date"], method="",
                 last_trade_close=format_cell(close), payout_per_share=format_cell(cash),
                 stock_ratio=format_cell(merged.get("stock_ratio")),
                 acquirer_ticker=merged.get("acquirer_ticker") or "", payout_source=g.sources.get(key, ""),
                 flags=";".join(g.flags.get(key, ())), acquirer_sec_id=c["acquirer_sec_id"])
    inputs = MergerInputs(llm=t, raw_value=regex["value"] if regex else None,
                          raw_source=regex["source"] if regex else "",
                          raw_currency=regex["currency"] if regex else "", acquirer_sec_id=c["acquirer_sec_id"],
                          price_ticker=c["price_ticker"])
    f = value_fields(row, c["published_last_trade_date"], inputs)
    out = {k: format_cell(f[k]) for k in VALUE_FIELDS}
    out["legs"] = [(format_cell(r["ratio"]), r["price_ticker"])
                   for r in basket_legs(row, c["published_last_trade_date"], inputs)]
    return out
