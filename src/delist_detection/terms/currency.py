"""The currency a filing states for a cash amount (ruling R5, sub-plan 5f): "$" and "US$" are USD, "C$" and
"Cdn$" are CAD, and so on. The library publishes the currency as the filing states it and never converts; a
blank is "the filing does not say" (never inferred from where the company is based). Pure."""
from __future__ import annotations

import re

USD = "USD"
# the letters a filing writes straight before "$"
_DOLLAR_PREFIXES = {"US": "USD", "U.S.": "USD", "C": "CAD", "CA": "CAD", "CAN": "CAD", "CDN": "CAD",
                    "A": "AUD", "AU": "AUD", "NZ": "NZD", "HK": "HKD", "S": "SGD"}
_SIGNS = {"€": "EUR", "£": "GBP", "¥": "JPY"}
_CODES = frozenset({"USD", "CAD", "AUD", "NZD", "HKD", "SGD", "EUR", "GBP", "JPY", "CHF", "SEK", "NOK", "DKK"})
_PREFIX = re.compile(r"(?<![A-Za-z])((?:U\.S\.)|[A-Za-z]{1,3})$")


def prefix_currency(text: str, dollar_at: int) -> str:
    """The currency of the "$" at `dollar_at` in `text`: the letters written straight before it ("C$65.50" is
    CAD), else USD; letters that name no currency the library knows give "" (not stated in a form it reads)."""
    m = _PREFIX.search(text[max(0, dollar_at - 5):dollar_at])
    if m is None:
        return USD
    token = m.group(1)
    return _DOLLAR_PREFIXES.get(token if token == "U.S." else token.upper(), "")


def normalize(code: object) -> str:
    """An LLM's currency answer as an ISO 4217 code ("$"/"US$" -> USD, "C$" -> CAD), "" when it is none or not a
    code the library knows."""
    if not isinstance(code, str):
        return ""
    c = code.strip()
    if not c or c.lower() in ("null", "none", "n/a"):
        return ""
    if c in _SIGNS:
        return _SIGNS[c]
    if c.endswith("$"):
        return prefix_currency(c, len(c) - 1)
    c = c.upper()
    return c if c in _CODES else ""


def _spellings(amount: float) -> list[str]:
    out = [f"{amount:,.2f}", f"{amount:.2f}"]
    if amount == int(amount):
        out += [f"{int(amount):,}", f"{int(amount)}"]
    out += [f"{amount:,.4f}".rstrip("0").rstrip("."), f"{amount:g}"]
    return list(dict.fromkeys(out))


def stated_currency(text: str, amount: float | None, *, explicit_only: bool = False) -> str:
    """The currency `text` writes next to `amount` ("C$65.50", "$23.00", "€12.00", "USD 4.11"), "" when the text
    does not state the amount with a currency. The first statement wins. `explicit_only`: a bare "$" (no letters
    before it) states none ("CAD $65.50" says CAD in its words, which no "$" overrides)."""
    if not text or amount is None:
        return ""
    for spelled in _spellings(float(amount)):
        for m in re.finditer(r"(?<![\d.,])" + re.escape(spelled) + r"(?![\d]|[.,]\d)", text):
            j = m.start()
            while j > 0 and text[j - 1].isspace():
                j -= 1
            if j > 0 and text[j - 1] == "$":
                if explicit_only and _PREFIX.search(text[max(0, j - 6):j - 1]) is None:
                    continue
                return prefix_currency(text, j - 1)
            if j > 0 and text[j - 1] in _SIGNS:
                return _SIGNS[text[j - 1]]
            code = re.search(r"\b([A-Z]{3})$", text[max(0, j - 4):j])
            if code and code.group(1) in _CODES:
                return code.group(1)
    return ""
