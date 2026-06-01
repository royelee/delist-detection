"""Extract per-share cash merger consideration from EDGAR filings.

Tiered: closing 8-K (Item 2.01) → announcement 8-K (Item 1.01) →
DEFM14A → PREM14A. First tier yielding a sanity-passing value wins.
A miss returns PayoutResult(None, 'none', ...), which the BMP pipeline
treats as neutral-mark — i.e. a miss is zero-regression.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .filing_selection import (
    announcement_8k,
    closing_8k,
    form_filings,
    parse_date,
)


@dataclass(frozen=True)
class PayoutResult:
    value: float | None
    confidence: str            # 'high' | 'medium' | 'low' | 'none'
    source: str                # '8K_2.01' | '8K_1.01' | 'DEFM14A' | 'PRE14A' | 'none'
    accession: str
    quote: str

    @classmethod
    def none(cls) -> "PayoutResult":
        return cls(None, "none", "none", "", "")


_NONE = PayoutResult.none()


_ABS_MIN, _ABS_MAX = 0.01, 10000.00

# Ordered patterns; group 1 is the dollar value. The (?!\d) guard prevents
# matching a 2-decimal truncation of a 4-decimal figure (e.g. $1,618.7928).
# Phrasings observed across real closing 8-Ks / proxies: "right to receive
# $X in cash" (ALTR/ATVI), "amount in cash equal to $X, without interest"
# (SKX/PPD), "purchase price of $X per Company Share" (RCPT tender offer),
# "$X per share", "merger/cash consideration of $X".
# Each entry is (pattern, weak). The operative signal of a *cash* payout is the
# phrase "in cash". STRONG patterns embed it (or "cash consideration"); they are
# trusted outright. WEAK patterns ("merger consideration of $X", bare "$X per
# share", "purchase price of $X") also appear in all-stock-deal proxies — for
# dividends, DCF valuation ranges, and implied-value-of-stock figures — so they
# only count when an "in cash" phrase follows within _CASH_WINDOW chars. Bare
# "cash" is NOT enough (it matches "discounted cash flow").
_PATTERNS = [
    (re.compile(r"(?:right to receive|receive)\s+\$\s*([\d,]+\.\d{2})(?!\d)\s+in\s+cash", re.I), False),
    (re.compile(r"in\s+cash\s+equal\s+to\s+\$\s*([\d,]+\.\d{2})(?!\d)", re.I), False),
    (re.compile(r"\$\s*([\d,]+\.\d{2})(?!\d)\s+in\s+cash(?:,?\s+without\s+interest)?", re.I), False),
    (re.compile(r"cash\s+consideration\s+of\s+\$\s*([\d,]+\.\d{2})(?!\d)", re.I), False),
    (re.compile(r"merger\s+consideration\s+of\s+\$\s*([\d,]+\.\d{2})(?!\d)", re.I), True),
    (re.compile(r"(?:purchase\s+price|price\s+per\s+share)\s+of\s+\$\s*([\d,]+\.\d{2})(?!\d)", re.I), True),
    (re.compile(r"\$\s*([\d,]+\.\d{2})(?!\d)\s+(?:net\s+)?per\s+(?:[A-Za-z]+\s+){0,2}share", re.I), True),
]
_CASH_WINDOW = 50
_CASH_ANCHOR = re.compile(r"in\s+cash", re.I)


# A dollar-per-share match is NOT a merger payout when the preceding context
# is one of these clauses (par value boilerplate, dividends, rounding rules,
# option exercise prices, break/termination fees, escrow holdbacks). Common in
# all-stock-deal proxies and merger agreements, which still quote small cash
# figures — left unguarded they inject a catastrophic fake -99%. Window kept at
# 30: widening it makes "par value $0.0001 per share, ... for $24.00 per Share"
# falsely collide with the par-value cue (real all-cash tenders ARIA/AZPN).
_NEG_CONTEXT = re.compile(
    r"par\s+value|dividend|rounded|nearest|in\s+excess\s+of|exercise\s+price|"
    r"less\s+than|greater\s+than|fee|escrow|termination",
    re.I,
)
_NEG_WINDOW = 30

# Convertible-note redemption / make-whole figures are quoted "per $1,000
# principal amount" and are NOT the per-share equity consideration. They can be
# large ($1,000-$4,000) and carry "in cash", so guard a window on BOTH sides.
_NOTE_CONTEXT = re.compile(
    r"per\s+\$?\s*1,?000|principal\s+amount|convertible\s+notes?|indenture|make-?whole",
    re.I,
)
_NOTE_WINDOW = 80

# Mixed cash+STOCK consideration ("$X in cash and 0.68 of a share of common
# stock") is OUT OF SCOPE: emitting only the cash leg badly understates the real
# (cash+stock) payout, so these become misses. Detect a STOCK co-consideration
# leg joined to the cash by "and"/"plus".
# Precision rules learned from real filings:
#   * The stock leg carries a NUMERIC ratio ("and 0.68 of a share", "plus one
#     share"). Requiring a ratio token between the and/plus and the equity word
#     avoids false positives like TCO's "$43.00 in cash (...); and (ii) each
#     share of Series B Preferred Stock" (a separate class, no ratio) and LNKD's
#     "and the terms of the merger agreement".
#   * CVRs are EXCLUDED here on purpose: a cash+CVR deal (e.g. APLS $41.00 + a
#     contingent CVR) has a real cash floor we DO want, so it is not "mixed".
_MIXED_EQUITY = (
    r"(?:shares?|stock|ADSs?|ordinary\s+shares?|common\s+shares?|"
    r"fraction\s+of\s+(?:a|one)\s+share)"
)
_MIXED_RATIO = r"(?:\d+(?:\.\d+)?|one|an?)"
# co-consideration AFTER the cash: "...in cash and/plus <ratio> ... <equity>".
_MIXED_AFTER = re.compile(
    r"\b(?:and|plus)\b[^.;:]{0,30}?\b" + _MIXED_RATIO + r"\b"
    r"(?:\s+[\w,'’\-]+){0,7}?\s+" + _MIXED_EQUITY + r"\b",
    re.I,
)
# co-consideration BEFORE the cash: "<equity> and/plus $X in cash" — the equity
# word and the join must sit immediately before the cash (no .;: between). A
# lettered list marker may sit between the join and the cash, e.g. an election
# "(a) 0.2192 shares of HNI common stock ... and (b) $7.20 in cash".
_MIXED_BEFORE = re.compile(
    _MIXED_EQUITY + r"\b[^.;:]{0,18}?\b(?:and|plus)\s*(?:\([a-z]\)\s*)?$", re.I)
_MIXED_WINDOW = 80


def _passes_sanity(value: float, last_close: float | None) -> bool:
    if not (_ABS_MIN <= value <= _ABS_MAX):
        return False
    if last_close is not None and last_close > 0:
        if value < 0.05 * last_close or value > 20.0 * last_close:
            return False
    return True


def _collect(
    text: str, last_close: float | None, allow_weak: bool
) -> tuple[dict[float, int], dict[float, int], dict[float, str]]:
    """Scan text for per-share cash figures. Return (counts, mixed, quotes).

    counts[val] = total clean matches; mixed[val] = how many of those co-occur
    with a stock leg ("and/plus <ratio> shares"); quotes[val] = a sample snippet.
    """
    counts: dict[float, int] = {}
    mixed: dict[float, int] = {}
    quotes: dict[float, str] = {}
    for pat, weak in _PATTERNS:
        if weak and not allow_weak:
            continue
        for m in pat.finditer(text):
            # Skip dividend / par-value / rounding / option / fee / escrow
            # boilerplate in the before-window.
            if _NEG_CONTEXT.search(text[max(0, m.start() - _NEG_WINDOW):m.start()]):
                continue
            # Skip convertible-note redemption figures ("$X per $1,000 ...").
            if _NOTE_CONTEXT.search(text[max(0, m.start() - _NOTE_WINDOW):m.end() + _NOTE_WINDOW]):
                continue
            # Weak patterns only count with an "in cash" phrase after the match.
            if weak and not _CASH_ANCHOR.search(text[m.end():m.end() + _CASH_WINDOW]):
                continue
            try:
                val = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if not _passes_sanity(val, last_close):
                continue
            counts[val] = counts.get(val, 0) + 1
            after = text[m.end():m.end() + _MIXED_WINDOW]
            before = text[max(0, m.start() - _MIXED_WINDOW):m.start()]
            if _MIXED_AFTER.search(after) or _MIXED_BEFORE.search(before):
                mixed[val] = mixed.get(val, 0) + 1
            if val not in quotes:
                lo = max(0, m.start() - 40)
                quotes[val] = text[lo:m.end() + 40].strip()
    return counts, mixed, quotes


def _select(
    counts: dict[float, int], mixed: dict[float, int]
) -> tuple[float | None, bool]:
    """Pick the payout value, or signal a mixed deal.

    Returns (value, mixed_deal). value is None when there is no match OR the deal
    is mixed cash+stock; mixed_deal is True only in the latter case so the caller
    can stop tier fall-through (an intermediate all-cash bid in a later filing
    must not override a mixed closing deal — e.g. PMCS).
    """
    if not counts:
        return None, False
    # Modal value: real consideration is repeated many times, noise once or
    # twice. On a count tie, prefer the larger value — the per-share consideration
    # outranks small contingent legs (e.g. a CVR cap) that share "in cash" wording.
    best = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    # Mixed (cash+stock) deal — OUT OF SCOPE — if the DOMINANT cash figure is
    # itself a stock leg, or any cash figure is stated as a stock leg twice.
    if (mixed.get(best, 0) and 2 * mixed[best] >= counts[best]) or \
       any(mc >= 2 for mc in mixed.values()):
        return None, True
    return best, False


def _match_payout(
    text: str, last_close: float | None = None, allow_weak: bool = True
) -> tuple[float | None, str]:
    """Return (modal sanity-passing value, ~120-char quote) or (None, '').

    allow_weak gates the bare "$X per share" / "purchase price" / "merger
    consideration of $X" patterns. Enable for clean merger-event 8-Ks; disable
    for multi-page proxies, where those phrasings also cover dividends, DCF
    valuation ranges, and mixed-consideration tables.
    """
    counts, mixed, quotes = _collect(text, last_close, allow_weak)
    val, _mixed_deal = _select(counts, mixed)
    return (val, quotes[val]) if val is not None else (None, "")


class PayoutExtractor:
    def __init__(self, edgar) -> None:
        self.edgar = edgar

    def extract(self, record: DelistRecord, last_close: float | None = None) -> PayoutResult:
        if record.bucket != CrspBucket.MERGER or record.cik is None:
            return _NONE
        # The EDGAR client makes live HTTP calls (recent_filings, fetch_filing_text)
        # that can raise on a transport error or non-404 5xx (raise_for_status).
        # A network failure must degrade to a miss (neutral-mark = zero regression),
        # never propagate — the README documents extract() with no try/except.
        try:
            return self._extract(record, last_close)
        except requests.RequestException:
            return _NONE

    def _extract(self, record: DelistRecord, last_close: float | None) -> PayoutResult:
        filings = self.edgar.recent_filings(record.cik)
        if not filings:
            return _NONE
        delist = parse_date(record.observed_delist_date or "")

        # allow_weak: bare per-share / purchase-price / merger-consideration
        # patterns are trustworthy in clean merger-event 8-Ks but noisy in
        # multi-page proxies, so they are disabled for the DEFM14A/PREM14A tiers.
        tiers = [
            ("8K_2.01", "high", True, closing_8k(filings, delist)),
            ("8K_1.01", "medium", True, announcement_8k(filings, delist)),
            ("DEFM14A", "medium", False, form_filings(filings, "DEFM14A", delist)),
            ("PRE14A", "low", False, form_filings(filings, "PREM14A", delist)),
        ]
        for source, conf, allow_weak, candidates in tiers:
            for f in candidates:
                text = self.edgar.fetch_filing_text(record.cik, f.accession, f.primary_doc)
                if not text:
                    continue
                counts, mixed, quotes = _collect(text, last_close, allow_weak)
                val, mixed_deal = _select(counts, mixed)
                # A filing that establishes a mixed cash+stock deal settles the
                # ticker: abstain rather than fall through to a later filing that
                # may quote an intermediate all-cash bid (e.g. PMCS) or a cash
                # election leg.
                if mixed_deal:
                    return _NONE
                if val is not None:
                    return PayoutResult(val, conf, source, f.accession, quotes[val][:160])
        return _NONE
