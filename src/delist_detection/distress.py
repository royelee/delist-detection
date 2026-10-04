"""Distress endings (sub-plan 5g, spec 2026-10-03-diagnosis-truth-fixes section 3 "5g"): the facts a drop or a
bankruptcy ending needs beyond its classification, read from the security's own fails rows and from the filings
around its last trade. Pure: texts and rows in, facts out.

- `otc_symbol_from_fails`, `otc_symbol_from_text`: the symbol of the first off-exchange print an `otc_print`
  ending is valued at (decision 11). The security's own CUSIP's fails rows after the last trade say it first (the
  first other symbol, or the exchange symbol when it keeps trading under it); else the 8-K item 3.01 notice's
  "will trade on the OTC ... under the symbol X"; else it is unknown and the contract publishes it blank, never an
  exchange symbol the security left (GPOR, GTX and SPNV were reused by other securities).
- `price_only`: the exchange's stated reason for the removal is a price deficiency and nothing else (CRSP 552, drop
  reason `price`). A market-capitalization, equity, distribution, back-door-listing or filing standard keeps
  `guidelines` (RHD, SPNV, FST, MDRX).
- `substitutes_new_shares`, `plan_ratio`: a Form 25 filed because a bankruptcy plan put new shares in the class's
  place (ruling R6), and the plan's new shares per old share: the notice's stated ratio (SDRL's 0.0037345), else the
  plan 8-K's two counts, the old shares outstanding and the new shares the old holders received (WOLF's
  1,306,896 / 156,479,390).
- `liquidating`: an 8-K that announces a liquidating distribution, a liquidating trust or a plan of liquidation or
  dissolution (EQC 2025: a voluntary delisting during the liquidation is a liquidation, not a transfer)."""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .ftd import FtdRow, is_trading_symbol

OTC_SYMBOL_DAYS = 30        # an other symbol counts this many days after the last trade (the census's latest: 19)
OTC_SETTLE_DAYS = 10        # fails under the exchange symbol later than this, at changing prices: it kept trading


@dataclass(frozen=True)
class DistressTerms:
    """What the contract publishes for one drop or bankruptcy ending beyond its delistings.csv row (stage 9e):
    `otc_symbol` the symbol of its first off-exchange print ("" when unknown); `plan_ratio` a bankruptcy plan's new
    shares per old share as read (R6: the ending is valued by the stock rule on the new line), with `plan_ticker`
    the new line's ticker and `plan_source` where the ratio was read."""
    otc_symbol: str = ""
    plan_ratio: str = ""
    plan_ticker: str = ""
    plan_source: str = ""


def _letters(symbol: str) -> bool:
    return any(ch.isalpha() for ch in symbol or "")


def otc_symbol_from_fails(rows: Iterable[FtdRow], ticker: str, last_trade: date) -> str | None:
    """The symbol of the first off-exchange print, from the fails rows of the security's own CUSIPs (`rows`) dated
    after its last trade: `ticker` (its exchange symbol on that day) when the rows under it before any other symbol
    run past OTC_SETTLE_DAYS at two or more prices (it kept trading under it: LKSD, MDRX); else the first other
    trading symbol within OTC_SYMBOL_DAYS (GPORQ, WFTIF before WFTIQ); else None: the rows say nothing (fails
    settling at the last close for a few days: SIVB, CNB)."""
    lo, hi = last_trade.isoformat(), (last_trade + timedelta(days=OTC_SYMBOL_DAYS)).isoformat()
    later = sorted((r for r in rows if lo < r.date <= hi and is_trading_symbol(r.symbol) and _letters(r.symbol)),
                   key=lambda r: (r.date, r.symbol))
    other = next((r for r in later if r.symbol != ticker), None)
    own = [r for r in later if r.symbol == ticker and (other is None or r.date < other.date)]
    settle = (last_trade + timedelta(days=OTC_SETTLE_DAYS)).isoformat()
    if any(r.date > settle for r in own) and len({r.price for r in own if r.price is not None}) >= 2:
        return ticker
    return other.symbol if other is not None else None


_SENTENCE = re.compile(r"(?<=[.;!?])[”\"']?\s+(?=[(“\"A-Z])")
_OTC_VENUE = re.compile(r"\bOTC|over[- ]the[- ]counter|pink\s+(?:sheets?|open\s+market|market)|bulletin\s+board|"
                        r"expert\s+market|grey\s+market", re.I)
_SYMBOL = re.compile(r"symbol\s*(?:of\s*)?[(“\"']*\s*([A-Z]{1,6})\b(?![a-z])")
_OTHER_CLASS = re.compile(r"warrants?\b|preferred|depositary|\bnotes?\b|debentures?|\brights?\b|\bunits?\b", re.I)
_COMMON = re.compile(r"common|ordinary\s+shares|class\s+a\b", re.I)
_NOT_SYMBOLS = frozenset({"OTC", "OTCQB", "OTCQX", "OTCBB", "NYSE", "NASDAQ", "AMEX", "PINK", "SEC"})


def otc_symbol_from_text(text: str) -> str:
    """The symbol an 8-K item 3.01 notice says the common trades under off the exchange: the first sentence that
    names an OTC venue and a symbol, and is not about another class only (WeWork's warrants), else ""."""
    for sentence in _SENTENCE.split(text or ""):
        if not _OTC_VENUE.search(sentence):
            continue
        if _OTHER_CLASS.search(sentence) and not _COMMON.search(sentence):
            continue
        m = _SYMBOL.search(sentence)
        if m and m.group(1) not in _NOT_SYMBOLS:
            return m.group(1)
    return ""


_PRICE = re.compile(r"abnormally\s+low|low\s+(?:selling\s+|trading\s+)?price|price\s+(?:level|criteri)|"
                    r"(?:average\s+)?closing\s+price|(?:below|less\s+than|under)\s+\$\s*1(?:\.00)?\b|"
                    r"bid\s+price|802\.01C|5450\(a\)\(1\)|5550\(a\)\(2\)|1003\(f\)\(v\)", re.I)
_OTHER_STANDARD = re.compile(
    r"market\s+capitali[sz]ation|stockholders.?\s+equity|shareholders.?\s+equity|802\.01[AB]|back[- ]?door|"
    r"102\.01|initial\s+listing|number\s+of\s+(?:public\s+)?(?:round[- ]lot\s+)?(?:holders|shareholders|"
    r"stockholders)|public\s+float|market\s+value\s+of\s+(?:publicly\s+held|listed)|net\s+tangible|"
    r"annual\s+report|10-K|10-Q|periodic\s+report|delinquen|audit\s+committee|\bfees\b|5250\(c\)|5450\(b\)|"
    r"5550\(b\)|5620|5605|1003\(a\)|corporate\s+governance", re.I)


def price_only(text: str) -> bool:
    """Whether `text` (the exchange's removal notice, else the 3.01 notices) cites a price deficiency (an
    abnormally low price, a $1 average close or bid price, NYSE 802.01C, Nasdaq 5450(a)(1)/5550(a)(2)) and no
    other listing standard."""
    return bool(_PRICE.search(text or "")) and not _OTHER_STANDARD.search(text or "")


_SUBSTITUTION = re.compile(r"came\s+to\s+evidence.{0,80}?other\s+securities\s+in\s+substitution", re.I | re.S)
_NEW_SHARES = re.compile(r"\bnew\s+common|[\"“(]new[\"”)]", re.I)
BANKRUPTCY_WORDS = re.compile(r"bankrupt|chapter\s*11|plan\s+of\s+reorganization|emerge[ds]?\s+from|"
                              r"emergence\s+from", re.I)


def substitutes_new_shares(notice: str) -> bool:
    """Whether a Form 25 notice says the class came to evidence other securities (rule 12d2-2(a)(3)) and names new
    shares in its place ("New Common Stock", Wolfspeed's "New", Whiting's "(New)"); a holding company's one-for-one
    names none (APA 2021)."""
    return bool(_SUBSTITUTION.search(notice or "")) and bool(_NEW_SHARES.search(notice or ""))


_RATIO = re.compile(r"ratio\s+of\s+(?:approximately\s+|about\s+)?(\d*\.\d+)\s+(?:shares?\s+of\s+)?(?:the\s+)?new\b",
                    re.I)
_OLD_COUNT = re.compile(r"\b(\d{1,3}(?:,\d{3}){2,})\s+(?:issued\s+and\s+)?outstanding\s+shares\s+of\s+"
                        r"[^.;]{0,80}?common\s+stock", re.I)
_NEW_COUNT = re.compile(r"(?:holders\s+of\s+(?:the\s+)?(?:old\s+common\s+stock|existing\s+(?:common\s+)?"
                        r"(?:equity|stock|shares))|existing\s+equity\s+holders|old\s+equity\s+holders)"
                        r"[^.;]{0,80}?\breceiv\w*[^.;]{0,60}?\b(\d{1,3}(?:,\d{3})+)\s+shares\s+of\s+(?:the\s+)?"
                        r"new\s+common", re.I)
_CONDITIONAL = re.compile(r"\bif\b|reserve|contingen|subject\s+to|warrant", re.I)


def _counts(pattern: re.Pattern, texts: Sequence[str]) -> set[int]:
    out: set[int] = set()
    for text in texts:
        for sentence in _SENTENCE.split(text or ""):
            if _CONDITIONAL.search(sentence):
                continue
            out.update(int(m.group(1).replace(",", "")) for m in pattern.finditer(sentence))
    return out


def plan_ratio(notice: str, plan_texts: Sequence[str]) -> tuple[str, str] | None:
    """The plan's new shares per old share, as (ratio, source): the notice's "exchange ratio of approximately X New
    Common Stock per" as stated (`form25_notice`), else the one count of old shares outstanding and the one count
    of new shares the old holders received that the plan 8-Ks (`plan_texts`) state, outside a condition (a share
    reserve paid if approvals arrive), their quotient to six significant figures (`plan_8k`); else None."""
    m = _RATIO.search(notice or "")
    if m:
        return m.group(1), "form25_notice"
    old, new = _counts(_OLD_COUNT, plan_texts), _counts(_NEW_COUNT, plan_texts)
    if len(old) == 1 and len(new) == 1 and 0 < next(iter(new)) < next(iter(old)):
        return f"{next(iter(new)) / next(iter(old)):.6g}", "plan_8k"
    return None


_LIQUIDATING = re.compile(r"liquidating\s+(?:cash\s+)?distribution|liquidating\s+trust|plan\s+of\s+(?:complete\s+)?"
                          r"(?:liquidation|dissolution)|plan\s+of\s+(?:sale\s+and\s+)?dissolution", re.I)


def liquidating(text: str) -> bool:
    """Whether an 8-K's text announces a liquidating distribution, a liquidating trust or a plan of liquidation or
    dissolution (not a preferred stock's liquidation preference)."""
    return bool(_LIQUIDATING.search(text or ""))
