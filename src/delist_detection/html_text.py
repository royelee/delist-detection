"""Filing HTML as plain text: what the EDGAR client caches for a filing's text
(`EdgarClient.fetch_filing_text`) and what Form 25 parsing reads."""
from __future__ import annotations

import html
import re


def strip_html(raw: str) -> str:
    """Strip <script>/<style>/tags, unescape entities, collapse whitespace."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()
