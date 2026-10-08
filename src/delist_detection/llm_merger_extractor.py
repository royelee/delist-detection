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
``reconstruction.build_delistings_table`` consumes via ``--merger-terms``;
``acquirer_price`` is added downstream.

Prompt v3 (sub-plan 5f)
-----------------------
The answer is the PACKAGE one share of the named target security became
(ruling R4: the final prorated package when a filing states it, else the
default, non-election package; never the sum of an election's alternatives),
with the cash's currency as the filing states it (R5), the stock leg's issuer
and class, a stock leg stated as a dollar value (PCYC), and every further
security received (a basket, R3). The candidate filings put the latest
completion documents first: the closing 8-K, an 8-K that reports the closing
without Item 2.01, an amendment filed after the last merger proxy, then the
proxy; a foreign private issuer's 6-K reports close to the delisting come
last. A one-for-one answer the model is not sure of, whose quote states no
number of shares, is passed over for the next candidate
(`unsupported_one_for_one`).

Miss → drop
-----------
``extract`` returns ``None`` (a "miss") whenever no candidate filing yields a
usable consideration (no cash leg and no stock leg). Downstream, a miss
leaves the merger's DLRET to abstain/neutral-mark — never a silent zero return.
A failed LLM call is a miss that counts itself degraded
(``sec_stats.SEC_STATS.degraded("llm_call")``), so the pipeline flags the
delisting ``resolution_degraded``; it is never cached.

Caching
-------
Each LLM call is cached on disk keyed by
``{accession}_{model}_{PROMPT_VERSION}_{ticker}.json``. ``PROMPT_VERSION`` is part of
the key, so editing ``SYSTEM_PROMPT`` / ``RESULT_SCHEMA`` (and bumping the
version) cleanly invalidates stale cached extractions rather than silently
reusing them; the target's ticker is part of it because the user prompt names
the target security (two classes of one issuer can get different terms).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import requests

from .classifier import DelistRecord
from .crsp_codes import CrspBucket
from .atomic_io import clean_orphan_temps, write_atomic
from .currency import normalize as normalize_currency, stated_currency
from .fatal import FATAL
from .filing_selection import (
    EdgarSubmission,
    announcement_8k,
    closing_8k,
    form_filings,
    parse_date,
)
from .observations import normalize_ticker
from .sec_stats import SEC_STATS


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

# What an answer spells out for "no ticker" ("NULL", "None", "N/A", "-": GRUB 2021's terms): no ticker, so a stock leg
# with none is reported as `no_acq_ticker`, never as a price missing for "NULL".
NULL_TICKERS = frozenset({"", "null", "none", "n/a", "n-a", "-"})
# The package bases of a prompt-v3 answer that names its package (sub-plan 5f, ruling R4); `none` states none.
PACKAGE_BASES = frozenset({"final_prorated", "default", "fixed"})


def clean_ticker(ticker: object) -> str:
    """A ticker as an answer gives it, stripped, "" for none (`NULL_TICKERS`)."""
    t = ticker.strip() if isinstance(ticker, str) else ""
    return "" if t.lower() in NULL_TICKERS else t


@dataclass(frozen=True)
class StockLeg:
    """One further security received per target share (ruling R3: a basket's second and later legs)."""
    ratio: float | None
    issuer_name: str = ""
    ticker: str = ""
    share_class: str = ""


_LETTER = re.compile(r"(?i)\s*(?:(?:class|series)\s+)?([A-Z0-9])(?:\s+(?:common|ordinary)\b.*)?\s*")


def leg_class_letter(text: str) -> str:
    """The letter of a share class an answer names ("B", "Class B", "Series C common"), "" for any other text
    ("preferred unit", "common")."""
    m = _LETTER.fullmatch(text or "")
    return m.group(1).upper() if m else ""


@dataclass(frozen=True)
class MergerTerms:
    """Structured per-share merger consideration extracted from one filing: the PACKAGE one target share became at
    the closing (ruling R4: the final prorated package when the filing states it, else the default, non-election
    package, never the sum of an election's alternatives).

    All legs are on a per-TARGET-share basis. ``cash_per_share`` is the cash in ``cash_currency`` (ruling R5: as the
    filing states it, "" when it does not; the library never converts); ``stock_ratio`` is the number of shares of
    the stock leg's issuer (``acquirer_*``: the company whose shares the holders receive) per target share;
    ``stock_value`` a stock leg stated as a dollar value over an averaging price instead of a number of shares
    (PCYC); ``extra_legs`` every further security received (a basket, ruling R3). ``None`` means the filing did not
    state that leg (do not infer a zero).
    """

    deal_type: str            # 'cash' | 'stock' | 'cash_and_stock' | 'election' | 'other'
    cash_per_share: float | None
    stock_ratio: float | None
    acquirer_name: str | None
    acquirer_ticker: str | None
    confidence: str           # 'high' | 'medium' | 'low'
    source: str               # '{form}:{accession}'
    quote: str
    cash_currency: str = ""
    stock_value: float | None = None
    acquirer_share_class: str = ""
    extra_legs: tuple[StockLeg, ...] = ()
    package_basis: str = ""   # 'final_prorated' | 'default' | 'fixed' | 'none' (v3 states no package) | '' (before v3)
    election_note: str = ""
    contingent_note: str = ""
    # an election whose filing states no package for the holders who made no election: the v3 answer states no leg
    # (WSC 2011, THE 2007), so the legs are the earlier prompt's cached either-or reading of the same filing
    # (`LEGACY_VERSION`, which the gate reads as sub-plan 5e did), or the answer is a result only for the holders who
    # elected (`electors_only`, NMX 2008). Either way the row is flagged `election_no_default`
    no_default: bool = False
    # the averaging period the filing names for a stock leg stated as a dollar value, as it words it (PCYC 2015: "ten
    # consecutive trading days ending on and including the second trading day prior to the final expiration date of
    # the offer"), read from the filing's own text; "" when it states none. `payout_rule` names it in `value_formula`
    value_window: str = ""

    def __post_init__(self) -> None:
        # "No ticker" is one rule: a spelled-out null (`NULL_TICKERS`) is no ticker, whoever built the answer
        object.__setattr__(self, "acquirer_ticker", clean_ticker(self.acquirer_ticker) or None)

    # What the answer means, asked of the answer itself (the gate, the payout rule, the price requests and stage 8
    # read these, never the raw fields' shape).

    @property
    def ticker(self) -> str:
        """The stock leg's acquirer ticker as a symbol to look up (normalized), "" for none."""
        return normalize_ticker(self.acquirer_ticker or "")

    @property
    def is_package(self) -> bool:
        """Whether the answer names its package (prompt v3, sub-plan 5f): its cash and stock legs are what one share
        became (ruling R4), an election's included, never its alternatives. An earlier answer's election legs were
        the alternatives, and so are those of a v3 answer that states no package (basis `none`: CBSS 2007's $71.82
        or 2.8 BBVA ADSs): both keep sub-plan 5e's either-or reading."""
        return self.package_basis in PACKAGE_BASES

    @property
    def is_basket(self) -> bool:
        """Two or more securities per target share (ruling R3)."""
        return bool(self.extra_legs) and (self.stock_ratio is not None or self.stock_value is not None)

    @property
    def has_stock(self) -> bool:
        """Whether the package holds any security (a ratio, a dollar-valued leg or a further leg): what the gate and
        the payout rule ask."""
        return bool(self.stock_ratio) or bool(self.stock_value) or bool(self.extra_legs)

    @property
    def stock_leg(self) -> bool:
        """Whether the answer holds a stock leg of its acquirer that the acquirer's close prices: a number of its
        shares or a dollar value of them (PCYC). What stage 8 looks the acquirer up for and what asks a received
        close; a further leg alone (`has_stock`) does not."""
        return bool(self.stock_ratio) or bool(self.stock_value)

    @property
    def skip_reason(self) -> str:
        """Why the payout gate cannot check the answer against a USD close (ruling R5 and R3), "" when it can: the
        cash leg's currency when it is not USD (the library has no FX source), `basket` for two or more securities,
        and `stock_value` for shares stated as a dollar value over an averaging price the library does not have."""
        cur = self.cash_currency or ""
        if self.cash_per_share and cur and cur != "USD":
            return cur
        if self.extra_legs:
            return "basket"
        if self.stock_value and not self.stock_ratio:
            return "stock_value"
        return ""

    @property
    def published(self) -> MergerTerms | None:
        """The legs the contract publishes for this answer as read (the gate did not keep it): its package. An
        answer that states no package (prompt v3 basis `none`, or an earlier prompt's) holds an election's
        alternatives, never the package: only its all-cash alternative is published, else nothing (TRH 2012: the
        stock alternative is no package). None when nothing is left to publish."""
        terms: MergerTerms | None = self
        if self.deal_type == "election" and not self.is_package and not self.no_default:
            terms = replace(self, stock_ratio=None, stock_value=None, extra_legs=()) if self.cash_per_share else None
        return terms if terms is not None and (terms.cash_per_share or terms.has_stock) else None

    def legs(self, main_ticker: str) -> list[tuple[float | None, str, str]]:
        """(ratio, ticker, share class) of each security of the package, the main one first (its ticker as the main
        row would publish it, `main_ticker`). A further leg's ticker is the one its own class trades under: a leg
        that repeats an earlier leg's ticker with another class letter takes the class ticker (CAA 2018's Lennar class
        B under the class A's LEN is LEN-B, as the fails rows spell it), a repeat with no class letter and a preferred
        class (BPYU 2021's "BPY preferred unit", not the common units' BPY) have none, so no price is asked of the
        wrong security."""
        out = [(self.stock_ratio, main_ticker, self.acquirer_share_class or "")]
        letters: dict[str, set[str]] = {main_ticker: {leg_class_letter(self.acquirer_share_class or "")}} \
            if main_ticker else {}
        for leg in self.extra_legs:
            ticker = normalize_ticker(leg.ticker) if leg.ticker else ""
            letter = leg_class_letter(leg.share_class)
            if ticker and "PREFER" in (leg.share_class or "").upper():
                ticker = ""
            elif ticker in letters:
                base = re.sub(r"-[A-Z]$", "", ticker)
                ticker = f"{base}-{letter}" if letter and letter not in letters[ticker] else ""
            if ticker:
                letters.setdefault(ticker, set()).add(letter)
            out.append((leg.ratio, ticker, leg.share_class or ""))
        return out

    def to_merger_terms_dict(self) -> dict:
        """Project to the dict shape ``build_delistings_table`` consumes.

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

PROMPT_VERSION = "v3"
# The prompt version whose cached answers read an election as its alternatives (cash OR stock): the either-or reading
# the gate keeps for an election whose v3 answer states no package. Read from the cache only, never asked again.
LEGACY_VERSION = "v2"

SYSTEM_PROMPT = """\
You are a precise M&A-filing extraction engine. You read excerpts of a filing \
about a merger, acquisition, exchange offer or separation of a TARGET company and \
return, as a JSON object, what ONE share of the target security named in the \
user message became at the closing: its PACKAGE.

Report everything per ONE share of that target security. Mind its class: two \
classes of one company can receive different terms.

Which package to report:
- The consideration actually paid at the closing. In this order of preference: \
the final per-share result the filing states after any proration; else, when \
holders could elect, what a holder who made NO election received (the default, \
"standard" or "mixed" consideration); else the fixed consideration of a deal \
without elections.
- Never add up the alternatives of an election (cash OR stock), and never report \
one elected alternative when a default or a final package is stated.
- If no default is fixed and no final result is stated, report the alternative \
made only of cash and/or shares, with no contingent right; if several, the \
all-cash one.
- Use the latest figures: an amended agreement's terms replace the original's, \
and a closing filing's figures replace a proxy's estimates or headlines.
- Count the shares actually ISSUED or delivered per target share, not figures \
"equivalent to" shares of another company. For American depositary shares, \
report the number of ADSs; ADSs "representing 0.5260 of an ordinary share" (one \
ADS per ordinary share) give 0.5260.
- A special dividend the target pays apart from the merger consideration is NOT \
part of the package. Cash paid at the closing for a security the target \
distributed to its holders as a step of the same transaction IS: when each \
target share was converted into $10.00 in cash and each share of a company the \
target had just distributed to its holders was converted into $5.00 in cash, \
report $15.00.

Fields:
- package_basis: "final_prorated" (the filing states one final per-share result \
that every holder of the class received after proration, for example "each \
share received $16.00 and 0.8998 shares"; the percentages of holders who \
elected cash or stock are not such a result), "default" (what non-electing \
holders received), "fixed" (no election), or "none" (no package can be stated).
- cash_per_share: the cash per target share in the package; null if none.
- cash_currency: the ISO 4217 code of that cash as the filing states it ("$" or \
"US$" is "USD", "C$" is "CAD", "€" is "EUR", "£" is "GBP"); null if there is no \
cash or the filing states no currency.
- stock_ratio: the number of shares (or units, or ADSs) of ONE security received \
per target share in the package; null if no fixed number is stated.
- stock_value_per_share: when the package's shares are stated as a dollar VALUE \
(for example "shares of X with a value of $109.00 based on X's average trading \
price") instead of a fixed number, that value; else null.
- acquirer_name, acquirer_ticker, acquirer_share_class: the issuer of the shares \
in stock_ratio or stock_value_per_share, that is the company whose shares the \
target's holders receive (the buyer, a new holding company, or a company \
separated or spun off to the holders): its full name as the filing gives it \
(not a defined term such as "New CCE" or "Parent" when the filing names the \
company); its primary US-exchange ticker, else its home-exchange ticker (use the \
ticker the filing states, e.g. "CVS Health Corporation (NYSE: CVS)" gives "CVS"; \
otherwise supply the well-known ticker of that company from your own knowledge, \
e.g. "AbbVie Inc." gives "ABBV", and for a new holding company the ticker it \
began trading under; return null ONLY if the company is unnamed or you do not \
know its ticker); and the class received ("A", \
"B", "C", "Series C"; null if not stated). With no stock in the package: the \
buyer's name and ticker, and a null class.
- other_stock_legs: every FURTHER security received per target share in the \
package beyond the one in stock_ratio (for example the second company's shares \
in a separation into two companies), each with its ratio, issuer_name, ticker \
and share_class. Empty when one security or none is received. Do not list \
contingent value rights, warrants or cash for fractional shares here.
- deal_type: "cash", "stock", "cash_and_stock" (a fixed mix), "election" \
(holders could elect cash or stock, possibly prorated), or "other".
- election_note: for an election deal, its alternatives in a few words (for \
example "$44.25 cash or 1.00 ETE unit, prorated"); else "".
- contingent_note: contingent value rights, warrants or other contingent \
consideration in a few words; else "".
- confidence: "high", "medium" or "low".
- quote: a short verbatim snippet (under 200 characters) from the text that \
supports the package, including the cash amount with its currency sign.

Null anything that is not explicitly supported by the text. Do NOT guess. \
Return ONLY the JSON object.\
"""

_LEG_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "ratio": {"type": ["number", "null"]},
        "issuer_name": {"type": "string"},
        "ticker": {"type": ["string", "null"]},
        "share_class": {"type": ["string", "null"]},
    },
    "required": ["ratio", "issuer_name", "ticker", "share_class"],
    "additionalProperties": False,
}

RESULT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "deal_type": {
            "type": "string",
            "enum": ["cash", "stock", "cash_and_stock", "election", "other"],
        },
        "package_basis": {"type": "string", "enum": ["final_prorated", "default", "fixed", "none"]},
        "cash_per_share": {"type": ["number", "null"]},
        "cash_currency": {"type": ["string", "null"]},
        "stock_ratio": {"type": ["number", "null"]},
        "stock_value_per_share": {"type": ["number", "null"]},
        "acquirer_name": {"type": ["string", "null"]},
        "acquirer_ticker": {"type": ["string", "null"]},
        "acquirer_share_class": {"type": ["string", "null"]},
        "other_stock_legs": {"type": "array", "items": _LEG_SCHEMA},
        "election_note": {"type": "string"},
        "contingent_note": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "quote": {"type": "string"},
    },
    "required": [
        "deal_type", "package_basis", "cash_per_share", "cash_currency", "stock_ratio", "stock_value_per_share",
        "acquirer_name", "acquirer_ticker", "acquirer_share_class", "other_stock_legs", "election_note",
        "contingent_note", "confidence", "quote",
    ],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Excerpt selection
# --------------------------------------------------------------------------- #

_EXCERPT_KEYWORDS = [
    "merger consideration", "right to receive", "exchange ratio",
    "shares of", "in cash", "per share", "election", "each share",
    "prorat", "depositary", "non-electing",
]
_EXCERPT_HALF_WINDOW = 1500
_EXCERPT_BUDGET = 30000

# the 8-K items that report a closing when Item 2.01 is absent (FWLT's 3.01 + 5.01), and the window around the
# delisting they are read in
_CLOSING_ITEMS = frozenset({"3.01", "3.03", "5.01"})
_CLOSING_ITEMS_DAYS = 30
# the merger documents an amendment 8-K must follow to be read before them (BOT's 8-K raising 0.35 to 0.375)
_PROXY_FORMS = ("DEFM14A", "DEFM14C", "S-4", "S-4/A", "F-4", "F-4/A", "SC TO-T", "SC TO-I")
_SIX_K_DAYS = (timedelta(days=120), timedelta(days=30))   # a foreign private issuer's 6-K reports around the delisting


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


def _text(x: object) -> str:
    """An LLM string answer, "" for null or the word null."""
    if not isinstance(x, str):
        return ""
    s = x.strip()
    return "" if s.lower() in ("null", "none", "n/a", "n-a", "-") else s


_SHARE_COUNT = re.compile(r"(?i)\b(?:one|1|\d+\.\d+)\b(?:\s*\(\d+\))?[^.;]{0,60}?\b(?:shares?|units?|ADSs?|stock)\b"
                          r"|one-for-one|equal number")


_ELECTORS = re.compile(r"(?i)\bwho\s+(?:validly\s+)?elected\b|\belecting\s+(?:holders|stockholders|shareholders)\b")
_NON_ELECTORS = re.compile(r"(?i)\bno\s+election\b|\bnot\s+(?:to\s+)?(?:make|made|elect)|\bfail(?:ed|s|ure)\s+to\b|"
                           r"\bnon-?elect|\bdeemed\b|\bdefault\b")


def electors_only(deal_type: object, basis: str, quote: str) -> bool:
    """A `final_prorated` election answer whose quote gives the result of the holders who elected (NMX 2008: "stockholders
    who elected to receive stock consideration ... will receive approximately $7.29 in cash and 0.2164 shares") and
    says nothing of what a holder who made no election received. Ruling R4 (2026-10-04): the package is what the
    non-electors received, which such a filing does not state, so the elector class's result stands, flagged
    `election_no_default` (EP 2012's closing 8-K states the non-electors' mixed consideration, which is the package)."""
    return (deal_type == "election" and basis == "final_prorated" and bool(_ELECTORS.search(quote or ""))
            and not _NON_ELECTORS.search(quote or ""))


def states_no_package(terms: MergerTerms) -> bool:
    """An election answer that states no package for the holders who made no election: prompt v3's basis `none`
    (TRH 2012: shares or cash "with a value equal to $61.14": no cash leg, no ratio, only a value), or one election
    class's result (`electors_only`, NMX 2008). A basis-`none` answer that does state a cash leg or a ratio keeps it
    (CYN 2015's $90.057 cash)."""
    return terms.deal_type == "election" and (terms.no_default or (
        terms.package_basis == "none" and terms.cash_per_share is None and terms.stock_ratio is None
        and not terms.extra_legs))


def base_reading(terms: MergerTerms, old: MergerTerms | None) -> MergerTerms | None:
    """R4 (controller ruling 2026-10-04): when the answer states no package for non-electors, the base reading stands,
    the earlier prompt's cached answer for the same filing (`old`), flagged `election_no_default`: TRH's 14.22 and
    0.145 Y, NMX's all-cash 81.16 (the gate's either-or reading). Never one election class's result. None when
    `old` states no leg."""
    if old is None or (old.cash_per_share is None and not old.has_stock):
        return None
    return replace(old, election_note=terms.election_note, no_default=True)


_AVG_WINDOW = re.compile(r"(?i)\baverage\s+(?:sale\s+|trading\s+|closing\s+)?price[^.]{0,220}?\bfor\s+the\s+"
                         r"((?:ten|\d+)\s+(?:consecutive\s+)?(?:trading\s+)?days?[^.;,(“”]{0,160})")


def averaging_window(text: str) -> str:
    """The averaging period a filing words for a share count that depends on an average price ("the volume weighted
    average sale price per share of AbbVie common stock ... for the ten consecutive trading days ending on and
    including the second trading day prior to the final expiration date of the offer"), "" when none is found."""
    m = _AVG_WINDOW.search(re.sub(r"\s+", " ", text or ""))
    return m.group(1).strip() if m else ""


def unsupported_one_for_one(terms: MergerTerms) -> bool:
    """A one-for-one, no-cash answer the model is not sure of (confidence below high) whose quote states no number of
    shares (ATH 2022's "AHL became a direct subsidiary of AGM", read as 1 where holders got 1.149 AGM shares; CHTR
    2016's "New Charter ... trades under CHTR", where they got 0.9042): one share is the guess a reorganization
    invites, so the next candidate filing is read instead (the prompt's "null anything not supported")."""
    return (terms.stock_ratio == 1.0 and not terms.cash_per_share and not terms.extra_legs
            and terms.confidence != "high" and not _SHARE_COUNT.search(terms.quote or ""))


def _sanitize_model(model: str) -> str:
    """Make a model name safe for a filename (``/`` and ``:`` → ``_``)."""
    return model.replace("/", "_").replace(":", "_")


def _sanitize_key(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "_", s)


def _day(f: EdgarSubmission) -> date | None:
    return parse_date(f.report_date) or parse_date(f.filing_date)


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
        Model identifier used in the cache key (it labels the cache, not the
        call). Defaults to the injected ``llm``'s own ``model``, the one it
        calls, so an answer is never filed under another model's name; then
        ``$CHAT_MODEL``, then ``"model"``, for a client that carries none.
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
        self.model = model or getattr(llm, "model", None) or os.environ.get("CHAT_MODEL", "model")
        self.cache_dir = Path(cache_dir)
        self.max_filings = max_filings
        clean_orphan_temps(self.cache_dir)    # a killed run's cut-off answer

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def extract(self, record: DelistRecord, security_name: str = "") -> MergerTerms | None:
        """Return the merger consideration for ``record``, or ``None`` on a miss.

        ``security_name`` (the target security's name, its class with it) is named in the user prompt.
        Short-circuits to ``None`` for non-MERGER buckets or a missing CIK.
        A network error (``requests.RequestException``) degrades to a miss —
        same degrade-never-raise contract as ``PayoutExtractor.extract``.
        """
        if record.bucket is not CrspBucket.MERGER or record.cik is None:
            return None
        try:
            return self._extract(record, security_name)
        except requests.RequestException:
            return None

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _extract(self, record: DelistRecord, security_name: str = "") -> MergerTerms | None:
        filings = self.edgar.recent_filings(record.cik)
        if not filings:
            return None
        delist = parse_date(record.observed_delist_date or "")

        candidates = self._candidates(filings, delist)

        tried = 0
        legless: list[tuple[EdgarSubmission, MergerTerms]] = []
        for f in candidates:
            if tried >= self.max_filings:
                break
            text = self.edgar.fetch_filing_text(record.cik, f.accession, f.primary_doc)
            if not text:
                continue
            tried += 1
            excerpt = self._relevant_excerpts(text)
            try:
                terms = self._llm_extract(excerpt, record, f, security_name)
            except FATAL:
                raise
            except Exception:
                # A single bad LLM call must not abort the whole extraction —
                # fall through to the next candidate filing. It is never cached,
                # and it counts itself degraded: the delisting's terms rested on
                # a failed read. (Network errors on EDGAR are caught one level up
                # and degrade to a miss.)
                SEC_STATS.degraded("llm_call")
                continue
            if terms is None or unsupported_one_for_one(terms):
                continue
            if states_no_package(terms):
                kept = base_reading(terms, self._legacy_terms(f, record))
                if kept is not None:
                    return kept     # the completion filing states no default: a later filing never answers better (TRH)
                if terms.no_default:
                    continue        # one election class's result is never the package: the regex read stands
            if terms.cash_per_share is not None or terms.has_stock:
                return replace(terms, value_window=averaging_window(text)) if terms.stock_value else terms
            if terms.deal_type == "election" and terms.election_note:
                legless.append((f, terms))      # an election whose alternatives it states in a note, with no leg
        # No candidate gave a leg. An election with no stated default (v3 states no package, and the prompt's "null
        # anything not supported" nulls both legs: WSC 2011, THE 2007) keeps the either-or reading the earlier
        # prompt cached for that filing; the payout gate decides whether it reconciles.
        for f, v3 in legless:
            old = self._legacy_terms(f, record)
            if old is not None and (old.cash_per_share is not None or old.has_stock):
                return replace(old, election_note=v3.election_note, no_default=True)
        return None

    def _legacy_terms(self, filing: EdgarSubmission, record: DelistRecord) -> MergerTerms | None:
        """The `LEGACY_VERSION` answer cached for this filing (no ticker in its key), None when there is none."""
        acc_key = filing.accession.replace("-", "")
        path = self.cache_dir / f"{acc_key}_{_sanitize_model(self.model)}_{LEGACY_VERSION}.json"
        try:
            raw = json.loads(path.read_text()) if path.exists() else None
        except (json.JSONDecodeError, OSError):
            return None
        return self._to_terms(raw, filing)

    def _candidates(self, filings, delist) -> list[EdgarSubmission]:
        """Ordered, de-duplicated (by accession) candidate filings, the latest completion documents first:

        closing 8-K (Item 2.01) → an 8-K reporting the closing without 2.01 (3.01, 3.03 or 5.01 within 30 days of
        the delisting) → an announcement 8-K (1.01) filed after the last merger proxy or registration (an
        amendment: its terms replace the proxy's) → DEFM14A → the other announcement 8-Ks → PREM14A → a 6-K
        report around the delisting (a foreign private issuer files no 8-K).
        Later duplicates of an accession already seen are dropped, preserving
        the first (highest-preference) position.
        """
        ordered: list[EdgarSubmission] = []
        ordered += closing_8k(filings, delist)
        ordered += self._closing_without_201(filings, delist)
        announcements = announcement_8k(filings, delist)
        proxies = [d for f in filings if f.form in _PROXY_FORMS and (d := parse_date(f.filing_date))
                   and (delist is None or delist - timedelta(days=730) <= d <= delist)]
        last_proxy = max(proxies, default=None)
        if last_proxy is not None:
            ordered += [f for f in announcements if (d := _day(f)) and d > last_proxy]
        ordered += form_filings(filings, "DEFM14A", delist)
        ordered += announcements
        ordered += form_filings(filings, "PREM14A", delist)
        ordered += self._six_k(filings, delist)

        seen: set[str] = set()
        out: list[EdgarSubmission] = []
        for f in ordered:
            if f.accession in seen:
                continue
            seen.add(f.accession)
            out.append(f)
        return out

    @staticmethod
    def _closing_without_201(filings, delist) -> list[EdgarSubmission]:
        if delist is None:
            return []
        span = timedelta(days=_CLOSING_ITEMS_DAYS)
        out = [f for f in filings if f.form == "8-K" and "2.01" not in f.item_set
               and f.item_set & _CLOSING_ITEMS and (d := _day(f)) and delist - span <= d <= delist + span]
        out.sort(key=lambda f: abs((_day(f) - delist).days))
        return out

    @staticmethod
    def _six_k(filings, delist) -> list[EdgarSubmission]:
        if delist is None:
            return []
        before, after = _SIX_K_DAYS
        out = [f for f in filings if f.form == "6-K" and (d := _day(f)) and delist - before <= d <= delist + after]
        out.sort(key=lambda f: abs((_day(f) - delist).days))
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

    def cache_path(self, filing: EdgarSubmission, record: DelistRecord) -> Path:
        """Where the answer for this filing and this target security is cached."""
        acc_key = filing.accession.replace("-", "")
        return self.cache_dir / (f"{acc_key}_{_sanitize_model(self.model)}_{PROMPT_VERSION}_"
                                 f"{_sanitize_key(record.ticker or 'none')}.json")

    def _llm_extract(
        self, excerpt: str, record: DelistRecord, filing: EdgarSubmission, security_name: str = ""
    ) -> MergerTerms | None:
        """Run (or load a cached) LLM extraction for one filing.

        Cache key: ``cache_path``. On a cache hit the stored dict is reused (no LLM call); otherwise the LLM
        is called and its dict is written to the cache. Returns ``None`` when the
        (cached or fresh) payload is not a usable dict.
        """
        cache_path = self.cache_path(filing, record)

        raw: object
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                raw = None
        else:
            raw = None

        if not isinstance(raw, dict):
            user_prompt = self._user_prompt(excerpt, record, filing, security_name)
            raw = self.llm.extract(SYSTEM_PROMPT, user_prompt, RESULT_SCHEMA)
            if isinstance(raw, dict):
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                write_atomic(cache_path, json.dumps(raw))
            else:
                # an answer that is no JSON object is never cached, so it is asked again on every run: it counts
                # itself degraded, like a failed call, and the delisting's row carries `resolution_degraded`
                SEC_STATS.degraded("llm_call")

        return self._to_terms(raw, filing)

    @staticmethod
    def _user_prompt(excerpt: str, record: DelistRecord, filing: EdgarSubmission | None = None,
                     security_name: str = "") -> str:
        target = f"{security_name} (ticker {record.ticker})" if security_name else f"ticker {record.ticker}"
        filed = f"Filing: {filing.form} filed {filing.filing_date}\n" if filing is not None else ""
        return (
            f"Target company ticker: {record.ticker}\n"
            f"Target security: {target}\n"
            f"Observed delist date: {record.observed_delist_date or 'unknown'}\n"
            f"{filed}\n"
            "Extract the package one share of the target security received, from the filing "
            "excerpt below.\n\n"
            "----- FILING EXCERPT -----\n"
            f"{excerpt}"
        )

    @staticmethod
    def _to_terms(raw: object, filing: EdgarSubmission) -> MergerTerms | None:
        """Convert a raw LLM dict into a ``MergerTerms`` (None if unusable). A cash amount the quote writes with a
        currency takes that currency (the quote is the filing's own text), else the answer's `cash_currency`."""
        if not isinstance(raw, dict):
            return None
        cash = _tolerant_float(raw.get("cash_per_share"))
        quote = raw.get("quote") or ""
        currency = ""
        if cash:
            said = normalize_currency(raw.get("cash_currency"))
            # a bare "$" in the quote never overrides the currency the answer states when that is not USD ("CAD $65.50",
            # "Cdn. $65.50"); an explicit prefix ("C$", "US$", "€", "USD 4.11") does
            currency = (stated_currency(quote, cash, explicit_only=bool(said) and said != "USD") or said)
        basis = str(raw.get("package_basis") or "").strip().lower()
        legs = []
        for leg in raw.get("other_stock_legs") or ():
            if isinstance(leg, dict) and _tolerant_float(leg.get("ratio")):
                legs.append(StockLeg(_tolerant_float(leg.get("ratio")), _text(leg.get("issuer_name")),
                                     _text(leg.get("ticker")), _text(leg.get("share_class"))))
        return MergerTerms(
            deal_type=raw.get("deal_type") or "other",
            cash_per_share=cash,
            stock_ratio=_tolerant_float(raw.get("stock_ratio")),
            acquirer_name=raw.get("acquirer_name"),
            acquirer_ticker=_text(raw.get("acquirer_ticker")) or None,     # "NULL" is no ticker (GRUB 2021)
            confidence=raw.get("confidence") or "low",
            source=f"{filing.form}:{filing.accession}",
            quote=quote,
            cash_currency=currency,
            stock_value=_tolerant_float(raw.get("stock_value_per_share")),
            acquirer_share_class=_text(raw.get("acquirer_share_class")),
            extra_legs=tuple(legs),
            package_basis=basis,
            election_note=_text(raw.get("election_note")),
            contingent_note=_text(raw.get("contingent_note")),
            no_default=electors_only(raw.get("deal_type"), basis, quote),
        )
