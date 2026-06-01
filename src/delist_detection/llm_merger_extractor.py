"""LLM-based merger-consideration extractor.

Reads excerpts of an EDGAR merger filing and returns the structured per-share
consideration target shareholders receive at closing (cash leg, stock exchange
ratio, acquirer name/ticker). This is the structural sibling of
``payout_extractor.PayoutExtractor`` — same constructor-injection of the EDGAR
client, same MERGER+cik short-circuit, same ``requests.RequestException →
miss`` degrade-never-raise contract — but it consults an injected LLM client
instead of regex patterns, so it can read mixed cash+stock deals the regex
extractor abstains on.

Scope boundary
--------------
This module extracts only the *consideration legs*. The acquirer's market
PRICE is NOT resolved here: a later integration step joins it from a price
panel and enforces the cash+stock sanity gate. ``to_merger_terms_dict()``
therefore emits ``cash_per_share`` / ``stock_ratio`` / ``acquirer_ticker``
(omitting any that are ``None``) — exactly the shape
``reconstruction.build_dlret_table`` consumes via ``--merger-terms``;
``acquirer_price`` is added downstream.

Miss → drop
-----------
``extract`` returns ``None`` (a "miss") whenever no candidate filing yields a
usable consideration (neither a cash leg nor a stock ratio). Downstream, a miss
leaves the merger's DLRET to abstain/neutral-mark — never a silent zero return.

Caching
-------
Each LLM call is cached on disk keyed by
``{accession}_{model}_{PROMPT_VERSION}.json``. ``PROMPT_VERSION`` is part of
the key, so editing ``SYSTEM_PROMPT`` / ``RESULT_SCHEMA`` (and bumping the
version) cleanly invalidates stale cached extractions rather than silently
reusing them.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .filing_selection import (
    EdgarSubmission,
    announcement_8k,
    closing_8k,
    form_filings,
    parse_date,
)


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MergerTerms:
    """Structured per-share merger consideration extracted from one filing.

    All legs are on a per-TARGET-share basis. ``cash_per_share`` is USD cash;
    ``stock_ratio`` is the number of ACQUIRER shares exchanged per target share.
    ``None`` means the filing did not state that leg (do not infer a zero).
    """

    deal_type: str            # 'cash' | 'stock' | 'cash_and_stock' | 'election' | 'other'
    cash_per_share: float | None
    stock_ratio: float | None
    acquirer_name: str | None
    acquirer_ticker: str | None
    confidence: str           # 'high' | 'medium' | 'low'
    source: str               # '{form}:{accession}'
    quote: str

    def to_merger_terms_dict(self) -> dict:
        """Project to the dict shape ``build_dlret_table`` consumes.

        Emits ``cash_per_share`` / ``stock_ratio`` / ``acquirer_ticker``,
        OMITTING any that are ``None``. ``acquirer_price`` is intentionally
        absent — the integration layer joins it from a price panel.
        """
        out: dict = {}
        if self.cash_per_share is not None:
            out["cash_per_share"] = self.cash_per_share
        if self.stock_ratio is not None:
            out["stock_ratio"] = self.stock_ratio
        if self.acquirer_ticker is not None:
            out["acquirer_ticker"] = self.acquirer_ticker
        return out


# --------------------------------------------------------------------------- #
# Prompt constants — calibration will iterate these. Bump PROMPT_VERSION on edit
# so the disk cache key changes and stale extractions are not silently reused.
# --------------------------------------------------------------------------- #

PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """\
You are a precise M&A-filing extraction engine. You read excerpts of a merger \
filing for a TARGET company and return ONLY the per-share consideration that \
target shareholders receive at closing, as a JSON object.

Report everything on a PER-TARGET-SHARE basis. Follow these rules exactly:

- cash_per_share: the USD cash amount paid per target share. null if the deal \
pays no cash.
- stock_ratio: the exchange ratio — the number of ACQUIRER shares issued per \
target share. null if the deal is all-cash.
- acquirer_name: the name of the buyer (the acquiring company) exactly as \
written in the filing. null if not stated.
- acquirer_ticker: the buyer's primary US-exchange stock ticker symbol. Use the \
ticker the filing states if present (e.g. "CVS Health Corporation (NYSE: CVS)" → \
"CVS"); otherwise supply the well-known ticker for the named acquiring company \
from your own knowledge (e.g. "CVS Health" → "CVS", "AbbVie Inc." → "ABBV", \
"Salesforce" → "CRM"). Return null ONLY if the acquirer is unnamed or you do \
not know its ticker. Give the parent/listed company's ticker, not a subsidiary's.
- deal_type: classify the consideration as one of:
    "cash"            all-cash,
    "stock"           all-stock (exchange ratio only),
    "cash_and_stock"  a fixed mix of cash AND stock per share,
    "election"        shareholders ELECT cash OR stock (possibly with proration),
    "other"           anything else / unclear.
  For an "election" deal, report the stated standard or illustrative per-share \
split if the filing gives one; otherwise leave both legs null.
- confidence: your own assessment of the extraction — "high", "medium", or "low".
- quote: a short verbatim snippet (under 200 characters) from the text that \
supports the numbers you report.

Null anything that is not explicitly supported by the text. Do NOT guess. \
Return ONLY the JSON object.\
"""

RESULT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "deal_type": {
            "type": "string",
            "enum": ["cash", "stock", "cash_and_stock", "election", "other"],
        },
        "cash_per_share": {"type": ["number", "null"]},
        "stock_ratio": {"type": ["number", "null"]},
        "acquirer_name": {"type": ["string", "null"]},
        "acquirer_ticker": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "quote": {"type": "string"},
    },
    "required": [
        "deal_type", "cash_per_share", "stock_ratio",
        "acquirer_name", "acquirer_ticker", "confidence", "quote",
    ],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Excerpt selection
# --------------------------------------------------------------------------- #

_EXCERPT_KEYWORDS = [
    "merger consideration", "right to receive", "exchange ratio",
    "shares of", "in cash", "per share", "election", "each share",
]
_EXCERPT_HALF_WINDOW = 1500
_EXCERPT_BUDGET = 30000


def _tolerant_float(x: object) -> float | None:
    """Parse a number from the LLM, tolerating ``$``/``,``/whitespace. None on failure."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.replace("$", "").replace(",", "").strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _sanitize_model(model: str) -> str:
    """Make a model name safe for a filename (``/`` and ``:`` → ``_``)."""
    return model.replace("/", "_").replace(":", "_")


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #

class LLMMergerTermsExtractor:
    """Extract structured merger consideration from EDGAR filings via an LLM.

    Parameters
    ----------
    edgar:
        Injected EDGAR client — ``recent_filings(cik)`` and
        ``fetch_filing_text(cik, accession, primary_doc)``.
    llm:
        Injected duck-typed LLM client — ``extract(system, user, schema) -> dict``.
    model:
        Model identifier used in the cache key. Defaults to ``$CHAT_MODEL`` or
        ``"model"`` when unset (it labels the cache, not the call — the injected
        ``llm`` already knows which model it talks to).
    cache_dir:
        Directory for the per-filing LLM-response cache.
    max_filings:
        Cap on the number of candidate filings whose text is sent to the LLM.
    """

    def __init__(
        self,
        edgar,
        llm,
        *,
        model: str | None = None,
        cache_dir: str | Path = "cache/llm",
        max_filings: int = 3,
    ) -> None:
        self.edgar = edgar
        self.llm = llm
        self.model = model or os.environ.get("CHAT_MODEL", "model")
        self.cache_dir = Path(cache_dir)
        self.max_filings = max_filings

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def extract(self, record: DelistRecord) -> MergerTerms | None:
        """Return the merger consideration for ``record``, or ``None`` on a miss.

        Short-circuits to ``None`` for non-MERGER buckets or a missing CIK.
        A network error (``requests.RequestException``) degrades to a miss —
        same degrade-never-raise contract as ``PayoutExtractor.extract``.
        """
        if record.bucket is not CrspBucket.MERGER or record.cik is None:
            return None
        try:
            return self._extract(record)
        except requests.RequestException:
            return None

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _extract(self, record: DelistRecord) -> MergerTerms | None:
        filings = self.edgar.recent_filings(record.cik)
        if not filings:
            return None
        delist = parse_date(record.observed_delist_date or "")

        candidates = self._candidates(filings, delist)

        tried = 0
        for f in candidates:
            if tried >= self.max_filings:
                break
            text = self.edgar.fetch_filing_text(record.cik, f.accession, f.primary_doc)
            if not text:
                continue
            tried += 1
            excerpt = self._relevant_excerpts(text)
            try:
                terms = self._llm_extract(excerpt, record, f)
            except Exception:
                # A single bad LLM call must not abort the whole extraction —
                # fall through to the next candidate filing. (Network errors are
                # caught one level up and degrade to a miss.)
                continue
            if terms is None:
                continue
            if terms.cash_per_share is not None or terms.stock_ratio is not None:
                return terms
        return None

    def _candidates(self, filings, delist) -> list[EdgarSubmission]:
        """Ordered, de-duplicated (by accession) candidate filings.

        Preference order: closing 8-K → DEFM14A → announcement 8-K → PREM14A.
        Later duplicates of an accession already seen are dropped, preserving
        the first (highest-preference) position.
        """
        ordered: list[EdgarSubmission] = []
        ordered += closing_8k(filings, delist)
        ordered += form_filings(filings, "DEFM14A", delist)
        ordered += announcement_8k(filings, delist)
        ordered += form_filings(filings, "PREM14A", delist)

        seen: set[str] = set()
        out: list[EdgarSubmission] = []
        for f in ordered:
            if f.accession in seen:
                continue
            seen.add(f.accession)
            out.append(f)
        return out

    def _relevant_excerpts(self, text: str) -> str:
        """Window the text around consideration keywords, merging overlaps.

        For each case-insensitive keyword hit take a ±1500-char window; merge
        overlapping windows; concatenate (joined by ``\\n...\\n``) up to a
        ~30000-char budget. Falls back to ``text[:30000]`` when no keyword hits.
        """
        spans: list[tuple[int, int]] = []
        lower = text.lower()
        for kw in _EXCERPT_KEYWORDS:
            start = 0
            while True:
                i = lower.find(kw, start)
                if i == -1:
                    break
                lo = max(0, i - _EXCERPT_HALF_WINDOW)
                hi = min(len(text), i + len(kw) + _EXCERPT_HALF_WINDOW)
                spans.append((lo, hi))
                start = i + 1

        if not spans:
            return text[:_EXCERPT_BUDGET]

        # Merge overlapping / adjacent windows (sorted by start).
        spans.sort()
        merged: list[list[int]] = [list(spans[0])]
        for lo, hi in spans[1:]:
            if lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])

        pieces: list[str] = []
        total = 0
        for lo, hi in merged:
            chunk = text[lo:hi]
            if total + len(chunk) > _EXCERPT_BUDGET:
                chunk = chunk[: _EXCERPT_BUDGET - total]
            pieces.append(chunk)
            total += len(chunk)
            if total >= _EXCERPT_BUDGET:
                break
        return "\n...\n".join(pieces)

    def _llm_extract(
        self, excerpt: str, record: DelistRecord, filing: EdgarSubmission
    ) -> MergerTerms | None:
        """Run (or load a cached) LLM extraction for one filing.

        Cache key: ``{accession_no_dashes}_{sanitized_model}_{PROMPT_VERSION}.json``.
        On a cache hit the stored dict is reused (no LLM call); otherwise the LLM
        is called and its dict is written to the cache. Returns ``None`` when the
        (cached or fresh) payload is not a usable dict.
        """
        acc_key = filing.accession.replace("-", "")
        cache_path = (
            self.cache_dir
            / f"{acc_key}_{_sanitize_model(self.model)}_{PROMPT_VERSION}.json"
        )

        raw: object
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                raw = None
        else:
            raw = None

        if not isinstance(raw, dict):
            user_prompt = self._user_prompt(excerpt, record)
            raw = self.llm.extract(SYSTEM_PROMPT, user_prompt, RESULT_SCHEMA)
            if isinstance(raw, dict):
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(raw))

        return self._to_terms(raw, filing)

    @staticmethod
    def _user_prompt(excerpt: str, record: DelistRecord) -> str:
        return (
            f"Target company ticker: {record.ticker}\n"
            f"Observed delist date: {record.observed_delist_date or 'unknown'}\n\n"
            "Extract the per-target-share merger consideration from the filing "
            "excerpt below.\n\n"
            "----- FILING EXCERPT -----\n"
            f"{excerpt}"
        )

    @staticmethod
    def _to_terms(raw: object, filing: EdgarSubmission) -> MergerTerms | None:
        """Convert a raw LLM dict into a ``MergerTerms`` (None if unusable)."""
        if not isinstance(raw, dict):
            return None
        return MergerTerms(
            deal_type=raw.get("deal_type") or "other",
            cash_per_share=_tolerant_float(raw.get("cash_per_share")),
            stock_ratio=_tolerant_float(raw.get("stock_ratio")),
            acquirer_name=raw.get("acquirer_name"),
            acquirer_ticker=raw.get("acquirer_ticker"),
            confidence=raw.get("confidence") or "low",
            source=f"{filing.form}:{filing.accession}",
            quote=raw.get("quote") or "",
        )
