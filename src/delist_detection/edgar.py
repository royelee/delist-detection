"""Thin EDGAR client. Handles SEC fair-access throttling and on-disk caching.

SEC requires a descriptive User-Agent and ≤10 req/sec from a single IP. We cap
at 8 req/sec and cache every JSON payload, so repeated runs cost nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


SEC_HOST = "https://data.sec.gov"
WWW_SEC_HOST = "https://www.sec.gov"
# SEC requires a descriptive User-Agent with a contact. Override via the
# EDGAR_USER_AGENT env var; the default carries a non-personal noreply contact.
DEFAULT_UA = os.environ.get(
    "EDGAR_USER_AGENT", "delist_detection/0.1 (royelee@users.noreply.github.com)"
)

_RATE_LOCK = threading.Lock()
_LAST_CALL: list[float] = [0.0]
_MIN_INTERVAL = 1.0 / 8.0


def _strip_html(raw: str) -> str:
    """Strip <script>/<style>/tags, unescape entities, collapse whitespace."""
    import html as _html
    import re as _re

    t = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    t = _re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = _re.sub(r"\s+", " ", t)
    return t.strip()


def _throttle() -> None:
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()


@dataclass
class EdgarSubmission:
    """One row from the recent-filings table on submissions.json."""

    accession: str
    form: str
    filing_date: str       # YYYY-MM-DD
    report_date: str       # YYYY-MM-DD or ''
    items: str             # comma-separated 8-K item codes (may be '')
    primary_doc: str

    @property
    def item_set(self) -> set[str]:
        return {x.strip() for x in self.items.split(",") if x.strip()}


class EdgarClient:
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str = DEFAULT_UA,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json", "Host": "data.sec.gov"}
        )

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.json"

    def _get_json(self, url: str, *, refresh: bool = False) -> Any:
        cp = self._cache_path(url)
        if cp.exists() and not refresh:
            try:
                return json.loads(cp.read_text())
            except json.JSONDecodeError:
                cp.unlink(missing_ok=True)

        _throttle()
        host = "data.sec.gov" if url.startswith(SEC_HOST) else "www.sec.gov"
        headers = {**self.session.headers, "Host": host}
        resp = self.session.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            cp.write_text(json.dumps({"__not_found__": True, "url": url}))
            return {"__not_found__": True, "url": url}
        resp.raise_for_status()
        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = {"__raw__": resp.text, "url": url}
        cp.write_text(json.dumps(data))
        return data

    def company_tickers(self) -> dict[str, dict[str, Any]]:
        """Master ticker→CIK map. ~10k entries; refresh weekly is enough.

        Returns dict keyed by uppercase ticker.
        """
        url = f"{WWW_SEC_HOST}/files/company_tickers.json"
        raw = self._get_json(url)
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(raw, dict):
            return out
        for v in raw.values():
            if not isinstance(v, dict):
                continue
            t = str(v.get("ticker", "")).upper()
            if t:
                out[t] = v
        return out

    def company_search_atom(self, company: str, form_type: str = "25-NSE") -> list[dict[str, Any]]:
        """Search EDGAR by company name; return [{cik, name, form, date}, ...].

        Uses the cgi-bin/browse-edgar ATOM endpoint. The ATOM XML has a
        single <company-info> block (top match) and an <entry> per filing.
        We return the top company's CIK along with any matching filings.
        """
        url = (
            f"{WWW_SEC_HOST}/cgi-bin/browse-edgar?action=getcompany"
            f"&company={requests.utils.quote(company)}&type={form_type}"
            "&dateb=&owner=include&count=10&output=atom"
        )
        _throttle()
        try:
            resp = self.session.get(
                url,
                headers={**self.session.headers, "Host": "www.sec.gov", "Accept": "application/atom+xml,text/xml"},
                timeout=30,
            )
            if resp.status_code != 200:
                return []
        except requests.RequestException:
            return []
        text = resp.text
        # Quick-and-dirty XML extraction; the document is tiny and well-formed.
        import re as _re
        out: list[dict[str, Any]] = []
        ci_cik = _re.search(r"<cik>\s*(\d+)\s*</cik>", text)
        ci_name = _re.search(r"<conformed-name>(.*?)</conformed-name>", text)
        company_cik = int(ci_cik.group(1)) if ci_cik else None
        company_name = ci_name.group(1) if ci_name else None
        if company_cik is None:
            return []
        entries = _re.findall(
            r"<entry>(.*?)</entry>", text, flags=_re.DOTALL
        )
        for e in entries:
            fd = _re.search(r"<filing-date>(\d{4}-\d{2}-\d{2})</filing-date>", e)
            ft = _re.search(r"<filing-type>([^<]+)</filing-type>", e)
            out.append({
                "cik": company_cik,
                "name": company_name,
                "form": ft.group(1) if ft else "",
                "filing_date": fd.group(1) if fd else "",
            })
        if not entries:
            out.append({"cik": company_cik, "name": company_name, "form": "", "filing_date": ""})
        return out

    def submissions(self, cik: int | str) -> dict[str, Any]:
        cik_str = str(int(cik)).zfill(10)
        url = f"{SEC_HOST}/submissions/CIK{cik_str}.json"
        return self._get_json(url)

    def fetch_filing_text(self, cik: int | str, accession: str, primary_doc: str) -> str:
        """Fetch a filing's primary document, return stripped plain text.

        Cached as utf-8 under cache/edgar/text/{accession_no_dashes}.txt.
        Returns '' on empty primary_doc, 404, or network error so callers can
        fall through to the next tier. A 404 is cached as a sticky miss;
        transient non-200s are not cached so a later run retries.
        """
        # An empty primary_doc would resolve to the directory-listing URL, which
        # returns 200 and a useless file index — never fetch it (FIX 7).
        if not primary_doc:
            return ""
        acc_nodash = accession.replace("-", "")
        text_dir = self.cache_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        cp = text_dir / f"{acc_nodash}.txt"
        if cp.exists():
            return cp.read_text(encoding="utf-8")
        url = (
            f"{WWW_SEC_HOST}/Archives/edgar/data/{int(cik)}/"
            f"{acc_nodash}/{primary_doc}"
        )
        _throttle()
        try:
            resp = self.session.get(
                url,
                headers={**self.session.headers, "Host": "www.sec.gov", "Accept": "text/html,*/*"},
                timeout=30,
            )
        except requests.RequestException:
            return ""
        if resp.status_code != 200:
            # Only a 404 is a stable "not found" worth caching as a sticky miss.
            # Cache other non-200s (429/503/etc.) would turn a transient outage
            # into a permanent empty result, so leave the cache untouched (FIX 6).
            if resp.status_code == 404:
                cp.write_text("", encoding="utf-8")
            return ""
        text = _strip_html(resp.text)
        cp.write_text(text, encoding="utf-8")
        return text

    def recent_filings(self, cik: int | str) -> list[EdgarSubmission]:
        sub = self.submissions(cik)
        if not isinstance(sub, dict) or sub.get("__not_found__"):
            return []
        recent = sub.get("filings", {}).get("recent", {})
        n = len(recent.get("accessionNumber", []))
        out: list[EdgarSubmission] = []
        for i in range(n):
            out.append(
                EdgarSubmission(
                    accession=recent["accessionNumber"][i],
                    form=recent["form"][i],
                    filing_date=recent.get("filingDate", [""] * n)[i],
                    report_date=recent.get("reportDate", [""] * n)[i],
                    items=recent.get("items", [""] * n)[i],
                    primary_doc=recent.get("primaryDocument", [""] * n)[i],
                )
            )
        # also pull historical files (paginated chunks of older filings)
        for fchunk in sub.get("filings", {}).get("files", []):
            url = f"{SEC_HOST}/submissions/{fchunk['name']}"
            data = self._get_json(url)
            if not isinstance(data, dict) or data.get("__not_found__"):
                continue
            n = len(data.get("accessionNumber", []))
            for i in range(n):
                out.append(
                    EdgarSubmission(
                        accession=data["accessionNumber"][i],
                        form=data["form"][i],
                        filing_date=data.get("filingDate", [""] * n)[i],
                        report_date=data.get("reportDate", [""] * n)[i],
                        items=data.get("items", [""] * n)[i],
                        primary_doc=data.get("primaryDocument", [""] * n)[i],
                    )
                )
        return out
