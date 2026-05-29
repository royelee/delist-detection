"""Resolve a (ticker, as_of_date) pair to a CIK.

SEC's company_tickers.json only lists *currently* registered tickers, so it
misses anything already deregistered. For those we fall back to EDGAR's
full-text search (efts.sec.gov), which indexes historical filings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests

from .edgar import EdgarClient, DEFAULT_UA, _throttle


@dataclass
class TickerResolution:
    ticker: str
    cik: int | None
    name: str | None
    source: str  # 'company_tickers' | 'efts' | 'manual' | 'rename' | None


class TickerResolver:
    def __init__(
        self,
        edgar: EdgarClient,
        rename_map: dict[str, str] | None = None,
        manual_overrides: dict[str, int] | None = None,
        cache_path: Path | str | None = None,
        name_lookup: "callable[..., str | None] | None" = None,
    ) -> None:
        self.edgar = edgar
        self.rename_map = {k.upper(): v.upper() for k, v in (rename_map or {}).items()}
        self.manual_overrides = {k.upper(): int(v) for k, v in (manual_overrides or {}).items()}
        self.cache_path = Path(cache_path) if cache_path else None
        self.name_lookup = name_lookup or (lambda *a, **kw: None)
        self._memo: dict[str, TickerResolution] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                raw = json.loads(self.cache_path.read_text())
                for t, d in raw.items():
                    self._memo[t] = TickerResolution(**d)
            except (json.JSONDecodeError, TypeError):
                pass
        self._companies: dict[str, dict] | None = None

    def _ensure_companies(self) -> dict[str, dict]:
        if self._companies is None:
            self._companies = self.edgar.company_tickers()
        return self._companies

    def _persist(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps({t: r.__dict__ for t, r in self._memo.items()}, indent=2)
        )

    # CIKs of US exchanges — these file Form 25-NSEs *on behalf of* the issuer,
    # so they appear in every delisting filing's CIK array. Always skip them.
    EXCHANGE_CIKS: set[int] = {
        1354457,   # Nasdaq Stock Market LLC
        1067442,   # New York Stock Exchange LLC
        1102740,   # NYSE Arca (Pacific Exchange)
        1019028,   # NYSE American / NYSE MKT (formerly AMEX)
        1192304,   # NYSE Chicago
        1133219,   # BATS / CBOE BZX
        1466168,   # CBOE Exchange Inc
        1605448,   # Investors Exchange (IEX)
        1283699,   # NYSE National
        1106974,   # Boston Stock Exchange / NSX (legacy)
    }

    def _efts_pre_delist_frequency_ranked(
        self, ticker: str, observed_date: str, top_n: int = 5
    ) -> list[tuple[int, str]]:
        """Frequency-rank CIKs filing 8-Ks in the 90 days before the delist.

        Useful when Form 25 doesn't contain the ticker text. A target company
        usually files many 8-Ks (and a definitive proxy) in the months leading
        up to its acquisition. The acquirer also files some, but the target
        normally outnumbers it in 8-Ks where the ticker is mentioned.
        """
        try:
            d = datetime.strptime(observed_date, "%Y-%m-%d").date()
        except ValueError:
            return []
        lo = (d - timedelta(days=120)).isoformat()
        hi = (d - timedelta(days=1)).isoformat()
        url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q=%22{ticker}%22&forms=8-K"
            f"&dateRange=custom&startdt={lo}&enddt={hi}"
        )
        try:
            _throttle()
            resp = requests.get(
                url,
                headers={"User-Agent": DEFAULT_UA, "Accept": "application/json"},
                timeout=30,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            return []
        hits = data.get("hits", {}).get("hits", [])
        counts: dict[int, tuple[int, str]] = {}
        token_re = re.compile(rf"\(\s*{re.escape(ticker.upper())}\s*\)")
        for h in hits:
            src = h.get("_source", {})
            ciks = src.get("ciks") or []
            names = src.get("display_names") or []
            for nm, cik in zip(names, ciks):
                c = int(cik)
                if c in self.EXCHANGE_CIKS:
                    continue
                weight = 3 if token_re.search(nm.upper()) else 1
                cur_count, cur_name = counts.get(c, (0, nm))
                counts[c] = (cur_count + weight, cur_name)
        if not counts:
            return []
        ranked = sorted(counts.items(), key=lambda kv: -kv[1][0])[:top_n]
        return [(c, nm) for c, (_, nm) in ranked]

    @staticmethod
    def _name_variants(name: str) -> list[str]:
        """Generate likely EDGAR-equivalent company-name search variants.

        EDGAR's `cgi-bin/browse-edgar?company=` does prefix-style matching, so
        a name like 'MERRILL LYNCH CO INC' must be queried as just
        'MERRILL LYNCH' to match the registered name 'MERRILL LYNCH & CO INC'.
        We try the full name, several stripped versions, and the leading two
        meaningful tokens.
        """
        if not name:
            return []
        n = name.strip()
        # Normalize punctuation
        cleaned = re.sub(r"[.,'’]", "", n).strip()
        no_amp = cleaned.replace("&", " ").strip()
        no_amp = re.sub(r"\s+", " ", no_amp)
        variants: list[str] = []
        seen: set[str] = set()

        def add(v: str) -> None:
            v = v.strip()
            if v and v.upper() not in seen:
                seen.add(v.upper())
                variants.append(v)

        add(n)
        add(cleaned)
        add(no_amp)
        # Strip trailing suffixes
        suffix_re = re.compile(
            r"\s+(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS|"
            r"GROUP|INTERNATIONAL|TRUST|LLC|LP|LLP|HOLDING|HOLDINGS)\.?\s*$",
            re.IGNORECASE,
        )
        cur = no_amp
        for _ in range(3):
            new = suffix_re.sub("", cur).strip()
            if new == cur:
                break
            add(new)
            cur = new
        # Take leading 1-3 tokens, alphabetic only — but skip very-common
        # first tokens that would over-match (THE, NEW, FIRST, etc.).
        tokens = [tok for tok in re.split(r"[\s\-/]+", no_amp)
                  if re.match(r"^[A-Za-z][A-Za-z0-9'’]*$", tok)]
        SHORT_GENERICS = {"THE", "NEW", "FIRST", "SECOND", "GENERAL", "AMERICAN",
                          "NATIONAL", "INTERNATIONAL", "WORLD", "UNITED",
                          "BANK", "TRUST"}
        if len(tokens) >= 2:
            add(" ".join(tokens[:2]))
        if len(tokens) >= 3:
            add(" ".join(tokens[:3]))
        if tokens and len(tokens[0]) >= 5 and tokens[0].upper() not in SHORT_GENERICS:
            add(tokens[0])
        return variants

    def _name_search(
        self, ticker: str, observed_date: str | None
    ) -> tuple[int | None, str | None]:
        """Resolve via Alpha Vantage name → EDGAR company search.

        Collects ALL hits across name variants and forms, then picks the
        best (cik, name) by:
          1. preferring CIKs whose name shares 4+ char tokens with AV name;
          2. then preferring hits with `filing_date` closest to observed_date;
          3. else taking the first non-exchange CIK.
        """
        nm = self.name_lookup(ticker, observed_date)
        if not nm:
            return None, None
        variants = self._name_variants(nm)
        try:
            target_d = datetime.strptime(observed_date, "%Y-%m-%d").date() if observed_date else None
        except ValueError:
            target_d = None

        # Gather candidates: list of (cik, hit_name, date_delta_days_or_None)
        candidates: list[tuple[int, str | None, int | None]] = []
        for variant in variants:
            for form in ("25-NSE", "25", "15-12G", ""):
                try:
                    hits = self.edgar.company_search_atom(variant, form_type=form)
                except Exception:
                    hits = []
                for h in hits:
                    cik = int(h["cik"])
                    if cik in self.EXCHANGE_CIKS:
                        continue
                    fd_str = h.get("filing_date") or ""
                    delta: int | None = None
                    if target_d and fd_str:
                        try:
                            fd = datetime.strptime(fd_str, "%Y-%m-%d").date()
                            delta = abs((fd - target_d).days)
                        except ValueError:
                            delta = None
                    candidates.append((cik, h.get("name"), delta))
                if hits:
                    break  # one form-class per variant is enough

        if not candidates:
            return None, None

        # Score each candidate: name-token overlap with AV name, then date proximity
        target_tokens = {tok for tok in re.findall(r"[A-Z]{4,}", nm.upper())
                         if tok not in {"CORP", "CORPORATION", "INC", "COMPANY",
                                         "HOLDINGS", "LTD", "LIMITED", "GROUP",
                                         "INTERNATIONAL", "TRUST", "PARTNERS",
                                         "FUND", "BANK", "BANCORP", "BANCSHARES"}}
        best: tuple[int, int, int, str | None] | None = None
        # higher score = better. score order: (name_score, -delta_penalty, -cik_index)
        for cand_cik, cand_name, delta in candidates:
            name_score = 0
            if cand_name:
                cand_tokens = set(re.findall(r"[A-Z]{4,}", cand_name.upper()))
                name_score = len(target_tokens & cand_tokens)
            # delta bonus: capped at 540 (else uninformative)
            if delta is None:
                date_penalty = 1000
            else:
                date_penalty = min(delta, 9999)
            tup = (name_score, -date_penalty, -len(candidates) if best is None else 0, cand_cik, cand_name)
            cur_key = (tup[0], tup[1])
            if best is None or cur_key > (best[0], best[1]):
                best = (name_score, -date_penalty, cand_cik, cand_name)
        if best is None:
            return None, None
        return best[2], best[3] or nm

    def _name_match_score(self, cik: int, ticker_name: str) -> int:
        """Token-overlap score between AV name and the CIK's EDGAR names.

        Score is the number of shared 4+ char alphabetic tokens between the
        AV-provided company name and the EDGAR conformed/former names.
        Used as a soft validator — a candidate from frequency search whose
        EDGAR name shares zero meaningful tokens with the AV name is almost
        certainly the wrong company.
        """
        try:
            sub = self.edgar.submissions(cik)
        except Exception:
            return 0
        if not isinstance(sub, dict):
            return 0
        names = [sub.get("name", "")] + [
            x.get("name", "") for x in sub.get("formerNames", []) if isinstance(x, dict)
        ]
        candidate_tokens: set[str] = set()
        for n in names:
            for tok in re.findall(r"[A-Z]{4,}", n.upper()):
                if tok not in {"CORP", "CORPORATION", "INC", "COMPANY", "HOLDINGS",
                                "LTD", "LIMITED", "GROUP", "INTERNATIONAL", "TRUST",
                                "PARTNERS", "FUND", "BANK", "BANCORP", "BANCSHARES"}:
                    candidate_tokens.add(tok)
        target_tokens: set[str] = set()
        for tok in re.findall(r"[A-Z]{4,}", ticker_name.upper()):
            if tok not in {"CORP", "CORPORATION", "INC", "COMPANY", "HOLDINGS",
                           "LTD", "LIMITED", "GROUP", "INTERNATIONAL", "TRUST",
                           "PARTNERS", "FUND", "BANK", "BANCORP", "BANCSHARES"}:
                target_tokens.add(tok)
        return len(candidate_tokens & target_tokens)

    def _validate_cik(self, cik: int, observed_date: str, strict: bool = True) -> bool:
        """Confirm the candidate CIK matches a target-of-delisting profile.

        Loose mode: just need a Form 25 or Form 15 within ±540 days of delist.
        Strict mode: additionally requires NO 10-K / 10-Q / 20-F filed in the
            window [observed+90, observed+5y]. The strict check rejects the
            *acquirer* (who keeps filing) when the candidate came from a
            frequency rank. It's too aggressive for true targets that keep
            filing because of leftover registered debt (Merrill post-BofA).
        """
        try:
            d = datetime.strptime(observed_date, "%Y-%m-%d").date()
        except ValueError:
            return True
        try:
            subs = self.edgar.recent_filings(cik)
        except Exception:
            return False

        has_delist_form = False
        no_post_cutoff = d + timedelta(days=90)
        post_horizon = d + timedelta(days=365 * 5)
        for f in subs:
            try:
                fd = datetime.strptime(f.filing_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if f.form in {"25", "25-NSE", "15-12G", "15-12B", "15-15D"}:
                if abs((fd - d).days) <= 540:
                    has_delist_form = True
            if strict and f.form in {"10-K", "10-Q", "20-F", "40-F"}:
                if no_post_cutoff < fd < post_horizon:
                    return False
        return has_delist_form

    def _efts_lookup(
        self, ticker: str, observed_date: str | None = None
    ) -> tuple[int | None, str | None]:
        """EDGAR full-text search fallback, anchored on the delisting filings.

        Strategy: search for the ticker only within Form 25 / 25-NSE / 15-*
        filings in a ±90 day window around the observed delist date, and
        accept the match only when the *exact* ticker token appears in the
        display_name (e.g. as ``(ACME)``) — never substring-match a longer
        word like ``ACMECORP`` against ``ACME``.

        When ``observed_date`` is None we still issue a delist-form-only
        query without a date range, which is far less ambiguous than the
        original 8-K-included query.
        """
        ticker_u = ticker.upper()
        forms = "25-NSE,25,15-12G,15-12B,15-15D"
        params = [f"q=%22{ticker_u}%22", f"forms={forms}"]
        if observed_date:
            try:
                d = datetime.strptime(observed_date, "%Y-%m-%d").date()
                lo = (d - timedelta(days=90)).isoformat()
                hi = (d + timedelta(days=90)).isoformat()
                params += [f"dateRange=custom", f"startdt={lo}", f"enddt={hi}"]
            except ValueError:
                pass
        url = "https://efts.sec.gov/LATEST/search-index?" + "&".join(params)
        try:
            _throttle()
            resp = requests.get(
                url,
                headers={"User-Agent": DEFAULT_UA, "Accept": "application/json"},
                timeout=30,
            )
            if resp.status_code != 200:
                return None, None
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            return None, None
        hits = data.get("hits", {}).get("hits", [])
        token_re = re.compile(rf"\(\s*{re.escape(ticker_u)}\s*\)")

        # First pass: exact (TICKER) match anywhere in display_names.
        for h in hits:
            src = h.get("_source", {})
            ciks = src.get("ciks") or []
            names = src.get("display_names") or []
            for nm, cik in zip(names, ciks):
                if token_re.search(nm.upper()) and int(cik) not in self.EXCHANGE_CIKS:
                    return int(cik), nm

        # Second pass: only safe when we narrowed by date AND restricted to
        # delisting forms — then the issuer is the first non-exchange CIK
        # in the most recent hit.
        if observed_date:
            for h in hits:
                src = h.get("_source", {})
                ciks = src.get("ciks") or []
                names = src.get("display_names") or []
                for nm, cik in zip(names, ciks):
                    c = int(cik)
                    if c in self.EXCHANGE_CIKS:
                        continue
                    return c, nm
        return None, None

    def resolve(self, ticker: str, observed_date: str | None = None) -> TickerResolution:
        t = ticker.upper().strip()
        cache_key = f"{t}|{observed_date or ''}"

        # Manual overrides always beat the cache — they're the truth.
        if t in self.manual_overrides:
            res = TickerResolution(ticker=t, cik=self.manual_overrides[t], name=None, source="manual")
            self._memo[cache_key] = res
            self._persist()
            return res

        if cache_key in self._memo:
            return self._memo[cache_key]

        renamed = self.rename_map.get(t)
        if renamed and renamed != t:
            inner = self.resolve(renamed, observed_date)
            res = TickerResolution(ticker=t, cik=inner.cik, name=inner.name, source="rename")
            self._memo[cache_key] = res
            self._persist()
            return res

        companies = self._ensure_companies()
        if t in companies:
            row = companies[t]
            res = TickerResolution(
                ticker=t,
                cik=int(row["cik_str"]),
                name=row.get("title"),
                source="company_tickers",
            )
            self._memo[cache_key] = res
            self._persist()
            return res

        cik: int | None = None
        name: str | None = None
        source = "none"
        av_name = self.name_lookup(t, observed_date)

        # Tier 1: EFTS Form 25 + date — most precise when it returns a hit.
        # Use loose validation: a name in EFTS Form-25 results is already
        # tightly date-anchored.
        c0, n0 = self._efts_lookup(t, observed_date)
        if c0 is not None:
            if not observed_date or self._validate_cik(c0, observed_date, strict=False):
                cik, name, source = c0, n0, "efts"

        # Tier 2: AV name → EDGAR company-name search. Loose validation:
        # name-match plus a real Form 25 in the window is strong evidence.
        if cik is None:
            c1, n1 = self._name_search(t, observed_date)
            if c1 is not None and (not observed_date or self._validate_cik(c1, observed_date, strict=False)):
                cik, name, source = c1, n1, "name_search"

        # Tier 3: 8-K frequency rank — strict validation (must reject the
        # acquirer, who keeps filing 10-Qs).
        if cik is None and observed_date:
            ranked = self._efts_pre_delist_frequency_ranked(t, observed_date)
            best: tuple[int, int, int, str] | None = None
            for rank, (cand_cik, cand_name) in enumerate(ranked):
                if not self._validate_cik(cand_cik, observed_date, strict=True):
                    continue
                score = self._name_match_score(cand_cik, av_name) if av_name else 0
                inv_rank = -rank
                cur = (score, inv_rank, cand_cik, cand_name)
                if best is None or cur > best:
                    best = cur
            if best is not None:
                cik, name, source = best[2], best[3], "efts_frequency"
            elif ranked:
                source = "rejected_validation"

        res = TickerResolution(ticker=t, cik=cik, name=name, source=source)
        self._memo[cache_key] = res
        self._persist()
        return res

    def resolve_many(
        self, items: Iterable[tuple[str, str | None]]
    ) -> dict[str, TickerResolution]:
        return {t: self.resolve(t, d) for t, d in items}
