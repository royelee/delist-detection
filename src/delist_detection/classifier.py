"""Classify a delisting into a CRSP-style code from EDGAR filings.

Pipeline per ticker:
    1. Resolve CIK
    2. Pull all submissions
    3. Find Form 25 or 25-NSE near the observed delisting date (±30 days)
    4. Find 8-K within ±10 days; parse `items` for the fingerprint
    5. Find Form 15-12G / 15-12B / 15-15D for deregistration confirmation
    6. Apply fingerprint rules → CRSP code + confidence
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from .crsp_codes import CrspBucket, bucket_for_code
from .edgar import EdgarClient, EdgarSubmission
from .evidence import (
    bankruptcy_8ks,
    filed_operating_between,
    item_text,
    mentions_bankruptcy,
    renamed_near,
    says_listing_transfer,
    still_operating,
)
from .ticker_resolver import TickerResolver


DELIST_FORMS = {"25", "25-NSE"}
DEREG_FORMS = {"15-12G", "15-12B", "15-15D"}

# 8-K item code fingerprints (numeric strings as EDGAR emits them).
MERGER_ITEMS = {"2.01", "5.01"}
COMPLIANCE_ITEMS = {"3.01"}
LIQUIDATION_ITEMS = {"2.04"}
DEFAULT_LOOKBACK_DAYS = 30
EIGHT_K_WINDOW_DAYS = 14
EIGHT_K_BACKSCAN_DAYS = 120  # how far back to scan for an announcement 8-K

FORM25_AFTER_DAYS = 45       # a Form 25 filed after the vendor's last trade
FORM25_TAIL_DAYS = 45        # beyond this, an earlier Form 25 means a frozen vendor tail
FORM25_MAX_BEFORE_DAYS = 1500
M_A_ITEMS = {"2.01", "5.01", "3.03"}


@dataclass
class DelistRecord:
    ticker: str
    cik: int | None
    observed_delist_date: str | None
    crsp_code: int | None
    bucket: CrspBucket
    confidence: str            # 'high' | 'medium' | 'low' | 'none'
    reason: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bucket"] = self.bucket.value
        return d


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _near(d1: date | None, d2: date | None, days: int) -> bool:
    if d1 is None or d2 is None:
        return False
    return abs((d1 - d2).days) <= days


class DelistClassifier:
    def __init__(
        self,
        edgar: EdgarClient,
        resolver: TickerResolver,
        asset_type_lookup: "callable[..., str | None] | None" = None,
        name_hint_lookup: "callable[..., str | None] | None" = None,
    ) -> None:
        self.edgar = edgar
        self.resolver = resolver
        self.asset_type_lookup = asset_type_lookup or (lambda *a, **kw: None)
        self.name_hint_lookup = name_hint_lookup or (lambda *a, **kw: None)

    def _detect_continued_filings(
        self, filings: list[EdgarSubmission], delist_date: date
    ) -> bool:
        """True if the company kept filing periodic reports >180d after delist.

        Indicates exchange-transfer (OTC continuation) rather than a true exit.
        """
        cutoff = delist_date + timedelta(days=180)
        for f in filings:
            if f.form not in {"10-K", "10-Q", "20-F", "40-F"}:
                continue
            try:
                fd = datetime.strptime(f.filing_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if fd > cutoff:
                return True
        return False

    def _detect_delinquent_filer(
        self, filings: list[EdgarSubmission], delist_date: date
    ) -> bool:
        """True if the company filed NT 10-K / NT 10-Q in the year before delist."""
        lo = delist_date - timedelta(days=365)
        for f in filings:
            if f.form not in {"NT 10-K", "NT 10-Q", "NT-NSAR"}:
                continue
            try:
                fd = datetime.strptime(f.filing_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if lo <= fd <= delist_date:
                return True
        return False

    def _pick_delist_filing(
        self,
        filings: list[EdgarSubmission],
        observed: date | None,
        cik: int | None = None,
    ) -> tuple[EdgarSubmission | None, int | None]:
        cands = [f for f in filings if f.form in DELIST_FORMS]
        if not cands:
            return None, None
        if observed is None:
            return max(cands, key=lambda f: f.filing_date), None
        best = None
        for c in cands:
            fd = _parse_date(c.filing_date)
            if fd is None:
                continue
            gap = (observed - fd).days            # > 0: Form 25 before the last trade
            if gap < -FORM25_AFTER_DAYS or gap > FORM25_MAX_BEFORE_DAYS:
                continue
            if gap > FORM25_TAIL_DAYS:
                near = self._pick_8k_near(filings, fd) or self._backscan_for_fingerprint_8k(filings, fd)
                merger_anchor = near is not None and bool(near.item_set & M_A_ITEMS)
                if not merger_anchor and filed_operating_between(filings, fd, observed):
                    continue                      # an older, different event (SKLZ 2021, LBRDA 2015)
            if best is None or abs(gap) < abs(best[1]):
                best = (c, gap)
        return (best[0], best[1]) if best else (None, None)

    def _pick_8k_near(
        self, filings: list[EdgarSubmission], anchor: date
    ) -> EdgarSubmission | None:
        candidates: list[tuple[int, EdgarSubmission]] = []
        for f in filings:
            if f.form != "8-K":
                continue
            fd = _parse_date(f.report_date) or _parse_date(f.filing_date)
            if fd is None:
                continue
            delta = abs((fd - anchor).days)
            if delta <= EIGHT_K_WINDOW_DAYS:
                candidates.append((delta, f))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _backscan_for_fingerprint_8k(
        self, filings: list[EdgarSubmission], anchor: date
    ) -> EdgarSubmission | None:
        """Walk older 8-Ks looking for the merger or compliance fingerprint.

        Some delistings are announced months before the Form 25 is filed
        (the Form 25 is filed *after* deal close, but Item 2.01 is filed
        at close, and Item 1.01 may appear at signing). We sweep up to
        EIGHT_K_BACKSCAN_DAYS before the anchor to find the most diagnostic
        8-K.
        """
        diagnostic: tuple[int, int, EdgarSubmission] | None = None  # (score, delta, sub)
        for f in filings:
            if f.form != "8-K":
                continue
            fd = _parse_date(f.report_date) or _parse_date(f.filing_date)
            if fd is None:
                continue
            delta_days = (anchor - fd).days
            if delta_days < 0 or delta_days > EIGHT_K_BACKSCAN_DAYS:
                continue
            items = f.item_set
            if {"2.01", "3.01", "5.01"}.issubset(items):
                score = 100
            elif {"2.01", "5.01"}.issubset(items):
                score = 80
            elif {"2.01", "3.01"}.issubset(items):
                score = 70
            elif "3.01" in items:
                score = 40
            elif "2.04" in items and "3.01" in items:
                score = 60
            else:
                continue
            if diagnostic is None or score > diagnostic[0] or (
                score == diagnostic[0] and delta_days < diagnostic[1]
            ):
                diagnostic = (score, delta_days, f)
        return diagnostic[2] if diagnostic else None

    def _pick_dereg(
        self, filings: list[EdgarSubmission], anchor: date | None
    ) -> EdgarSubmission | None:
        candidates = [f for f in filings if f.form in DEREG_FORMS]
        if not candidates:
            return None
        if anchor is None:
            return max(candidates, key=lambda f: f.filing_date)
        scored: list[tuple[int, EdgarSubmission]] = []
        for c in candidates:
            fd = _parse_date(c.filing_date)
            if fd is None:
                continue
            scored.append((abs((fd - anchor).days), c))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0])
        return scored[0][1]

    def _confirmed_bankruptcy(self, cik, filings, on):
        """First 1.03 8-K in the window whose text mentions a bankruptcy. An empty
        text (fetch miss) counts as confirmed: the tag is SEC's own metadata."""
        for f in bankruptcy_8ks(filings, on):
            text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
            if not text or mentions_bankruptcy(text):
                return f
        return None

    def _rename_or_transfer(self, cik, filings, observed):
        """A rename around the delisting date, or a 3.01 notice that reads as a
        listing transfer rather than a deficiency, while the company keeps
        reporting results: an exchange transfer, not a compliance failure."""
        sub = self.edgar.submissions(cik)
        if not isinstance(sub, dict):
            return None
        old = renamed_near(sub, observed)
        transfer = False
        for f in filings:
            d = _parse_date(f.filing_date)
            if f.form.startswith("8-K") and "3.01" in f.item_set and d and abs((d - observed).days) <= 30:
                text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
                transfer = transfer or says_listing_transfer(item_text(text, "3.01"))
        if (old or transfer) and still_operating(filings, observed):
            why = f"renamed from {old!r}" if old else "3.01 notice announces a listing transfer"
            return f"Ticker change / listing transfer: {why}; company still reports results"
        return None

    def _effective_items(self, cik, f, flags):
        """The 8-K's item set with an unconfirmed 1.03 tag stripped.

        A 1.03 (Bankruptcy or Receivership) tag whose filing text doesn't
        mention a bankruptcy is a mis-tag (e.g. a merger 8-K); don't let it
        force a LIQUIDATION classification via `_classify_items`.
        """
        items = set(f.item_set)
        if "1.03" in items:
            text = self.edgar.fetch_filing_text(cik, f.accession, f.primary_doc)
            if text and not mentions_bankruptcy(text):
                items.discard("1.03")
                if "bankruptcy_tag_unconfirmed" not in flags:
                    flags.append("bankruptcy_tag_unconfirmed")
        return items

    def _classify_items(self, items: set[str]) -> tuple[int | None, str]:
        """Map an 8-K item set to a CRSP DLSTCD-style code.

        Items table (relevant to delistings):
            1.02 — Termination of a Material Definitive Agreement
            1.03 — Bankruptcy or Receivership                         → 470
            2.01 — Completion of Acquisition / Disposition of Assets  → M&A signal
            2.04 — Acceleration of Direct Financial Obligation        → distress
            3.01 — Notice of Delisting                                → compliance/M&A
            3.03 — Material Modification to Rights of Holders         → M&A context
            5.01 — Changes in Control of Registrant                   → M&A signal
            5.03 — Amendments to Articles of Incorporation            → merger-into
        """
        has_103 = "1.03" in items
        has_201 = "2.01" in items
        has_204 = "2.04" in items
        has_301 = "3.01" in items
        has_501 = "5.01" in items
        has_503 = "5.03" in items
        has_303 = "3.03" in items
        control = has_501 and (has_201 or has_301 or has_303)

        if has_103:
            return 470, "Bankruptcy (8-K item 1.03)"
        if has_201 and has_301 and has_501:
            return 231, "M&A 2.01+3.01+5.01 (acquired by external acquirer)"
        if has_201 and has_501:
            return 233, "M&A 2.01+5.01 (subsidiary buyback / parent acquisition)"
        if control:
            return 231, "M&A change in control (5.01) with delisting/rights change, closing 8-K without 2.01"
        if has_201 and has_301:
            return 200, "M&A 2.01+3.01 (acquisition with delisting)"
        if has_204 and has_301:
            return 470, "3.01 + 2.04 without a change in control (distress/Ch.11 lead-in)"
        if has_301:
            return 570, "Compliance failure (3.01 alone, no M&A indicators)"
        return None, "No conclusive 8-K items"

    def classify_ticker(
        self,
        ticker: str,
        observed_delist_date: str | None = None,
    ) -> DelistRecord:
        observed = _parse_date(observed_delist_date) if observed_delist_date else None

        # Asset-type short-circuit: ETFs, notes, warrants, units, rights all
        # land in CRSP 600 EXPIRATION (scheduled end / not an equity event).
        # We also pattern-match the AV company name for cases where the
        # asset_type column is "Stock" but the name reveals the security
        # (notes, warrants, ETF, rights).
        atype = (self.asset_type_lookup(ticker, observed_delist_date) or "").strip().lower()
        name_hint = (self.name_hint_lookup(ticker, observed_delist_date) or "").lower()
        non_equity = atype in {
            "warrant", "unit", "right", "rights", "warrants", "units",
            "etf", "etn", "note", "notes", "preferred", "preferreds",
            "adr depositary", "depositary",
        }
        if not non_equity and name_hint:
            for kw in (" etf", " etn", " notes due", " note due",
                       " tradeable rights", " rights ", " warrants",
                       " trust units", " preferred"):
                if kw in name_hint:
                    non_equity = True
                    atype = atype or "name-hint"
                    break
        if non_equity:
            return DelistRecord(
                ticker=ticker.upper(),
                cik=None,
                observed_delist_date=observed_delist_date,
                crsp_code=600,
                bucket=CrspBucket.EXPIRATION,
                confidence="high",
                reason=f"Non-equity security (asset_type='{atype}', name='{name_hint[:60]}')",
                evidence={"asset_type": atype, "name_hint": name_hint},
            )

        resolution = self.resolver.resolve(ticker, observed_delist_date)

        if resolution.cik is None:
            return DelistRecord(
                ticker=ticker.upper(),
                cik=None,
                observed_delist_date=observed_delist_date,
                crsp_code=None,
                bucket=CrspBucket.UNKNOWN,
                confidence="none",
                reason="No CIK found for ticker (likely never SEC-registered or pre-EDGAR)",
                evidence={"resolution_source": resolution.source},
            )

        flags: list[str] = []
        if resolution.source == "company_tickers":
            flags.append("resolved_by_current_ticker_map")
        expected = self.resolver._expected_name(ticker.upper(), observed_delist_date)
        if expected and observed:
            _, agrees = self.resolver._fits_date(resolution.cik, observed_delist_date, expected)
            if not agrees:
                flags.append("member_name_mismatch")

        filings = self.edgar.recent_filings(resolution.cik)
        if not filings:
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=None,
                bucket=CrspBucket.UNKNOWN,
                confidence="none",
                reason="EDGAR returned no submissions for CIK",
                evidence={"resolution_source": resolution.source, "name": resolution.name,
                          "flags": flags},
            )

        delist_filing, gap = self._pick_delist_filing(filings, observed, resolution.cik)
        if gap is not None and gap > FORM25_TAIL_DAYS:
            flags.append(f"frozen_tail:{gap}")
        dereg = self._pick_dereg(filings, observed)
        evidence: dict = {
            "resolution_source": resolution.source,
            "name": resolution.name,
            "delist_filing": asdict(delist_filing) if delist_filing else None,
            "dereg_filing": asdict(dereg) if dereg else None,
            "anchor_gap_days": gap,
            "flags": flags,
        }

        # SEC-revoked: explicit Order of Suspension/Revocation by the SEC.
        # The submissions JSON marks these with form code 'REVOKED'.
        for f in filings:
            if f.form == "REVOKED":
                return DelistRecord(
                    ticker=ticker.upper(),
                    cik=resolution.cik,
                    observed_delist_date=observed_delist_date,
                    crsp_code=573,
                    bucket=CrspBucket.COMPLIANCE_FAILURE,
                    confidence="high",
                    reason=f"SEC REVOKED registration filed {f.filing_date}",
                    evidence={**evidence, "revoked_filing": asdict(f)},
                )

        # A confirmed bankruptcy on record beats everything below, including a
        # company that kept filing after emerging from Chapter 11 with the same
        # CIK (Oasis Petroleum): the old equity was still cancelled at emergence.
        if observed:
            bk = self._confirmed_bankruptcy(resolution.cik, filings, observed)
            if bk is not None:
                return DelistRecord(
                    ticker=ticker.upper(), cik=resolution.cik,
                    observed_delist_date=observed_delist_date, crsp_code=470,
                    bucket=CrspBucket.LIQUIDATION, confidence="high",
                    reason=f"Bankruptcy (8-K item 1.03 filed {bk.filing_date})",
                    evidence={**evidence, "bankruptcy_8k": asdict(bk)},
                )

        # A rename or a 3.01 "transfer the listing" notice, with the company
        # still reporting results afterward, is an exchange transfer — not a
        # compliance failure. Checked before the Form-25-driven branches so a
        # frozen Form 25 tail (e.g. an old SPAC-merger Form 25) can't hide it.
        if observed:
            why = self._rename_or_transfer(resolution.cik, filings, observed)
            if why:
                return DelistRecord(
                    ticker=ticker.upper(), cik=resolution.cik,
                    observed_delist_date=observed_delist_date, crsp_code=304,
                    bucket=CrspBucket.EXCHANGE_TRANSFER, confidence="high",
                    reason=why, evidence=evidence,
                )

        # Exchange-transfer override is the strongest single signal —
        # check it BEFORE the Form-25-or-not branches.
        if observed and self._detect_continued_filings(filings, observed):
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=304,
                bucket=CrspBucket.EXCHANGE_TRANSFER,
                confidence="medium",
                reason="Continued 10-K/Q filings >180d after delist (moved to OTC or spun off)",
                evidence=evidence,
            )

        if delist_filing is None:
            # No Form 25 found. Use 8-K-only logic centered on observed date.
            if observed is None:
                return DelistRecord(
                    ticker=ticker.upper(),
                    cik=resolution.cik,
                    observed_delist_date=observed_delist_date,
                    crsp_code=None,
                    bucket=CrspBucket.UNKNOWN,
                    confidence="low",
                    reason="No Form 25 and no observed date to anchor 8-K search",
                    evidence=evidence,
                )
            eightk = self._pick_8k_near(filings, observed)
            evidence["anchor_8k"] = asdict(eightk) if eightk else None
            if eightk is None:
                return DelistRecord(
                    ticker=ticker.upper(),
                    cik=resolution.cik,
                    observed_delist_date=observed_delist_date,
                    crsp_code=None,
                    bucket=CrspBucket.UNKNOWN,
                    confidence="low",
                    reason="No Form 25 and no 8-K near observed delist date",
                    evidence=evidence,
                )
            code, reason = self._classify_items(self._effective_items(resolution.cik, eightk, flags))
            if code is None:
                # Form 15 present but no 8-K signal — went voluntarily deregistered.
                if dereg is not None:
                    return DelistRecord(
                        ticker=ticker.upper(),
                        cik=resolution.cik,
                        observed_delist_date=observed_delist_date,
                        crsp_code=573,
                        bucket=CrspBucket.COMPLIANCE_FAILURE,
                        confidence="medium",
                        reason="Form 15 deregistration without merger 8-K (voluntary or SEC action)",
                        evidence=evidence,
                    )
                return DelistRecord(
                    ticker=ticker.upper(),
                    cik=resolution.cik,
                    observed_delist_date=observed_delist_date,
                    crsp_code=None,
                    bucket=CrspBucket.UNKNOWN,
                    confidence="low",
                    reason=reason,
                    evidence=evidence,
                )
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=code,
                bucket=bucket_for_code(code),
                confidence="medium",
                reason=reason + " (no Form 25 anchor, 8-K-only)",
                evidence=evidence,
            )

        anchor = _parse_date(delist_filing.filing_date) or observed
        eightk = self._pick_8k_near(filings, anchor) if anchor else None
        if eightk is None or self._classify_items(self._effective_items(resolution.cik, eightk, flags))[0] is None:
            back = self._backscan_for_fingerprint_8k(filings, anchor) if anchor else None
            if back is not None:
                eightk = back
        evidence["anchor_8k"] = asdict(eightk) if eightk else None

        if eightk is None:
            # Form 25 present but no nearby 8-K. If a Form 15 was also filed,
            # treat as voluntary deregistration / liquidation rather than
            # compliance failure (which assigns -100% to forward returns).
            if dereg is not None:
                return DelistRecord(
                    ticker=ticker.upper(),
                    cik=resolution.cik,
                    observed_delist_date=observed_delist_date,
                    crsp_code=400,
                    bucket=CrspBucket.LIQUIDATION,
                    confidence="medium",
                    reason="Form 25 + Form 15, no merger 8-K: voluntary dereg / liquidation",
                    evidence=evidence,
                )
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=570,
                bucket=CrspBucket.COMPLIANCE_FAILURE,
                confidence="medium",
                reason="Form 25 present, no 8-K within window (defaulting to exchange action)",
                evidence=evidence,
            )

        code, reason = self._classify_items(self._effective_items(resolution.cik, eightk, flags))

        if code is None:
            if dereg is not None:
                return DelistRecord(
                    ticker=ticker.upper(),
                    cik=resolution.cik,
                    observed_delist_date=observed_delist_date,
                    crsp_code=400,
                    bucket=CrspBucket.LIQUIDATION,
                    confidence="medium",
                    reason="Form 25 + Form 15, 8-K without M&A items: liquidation/voluntary dereg",
                    evidence=evidence,
                )
            return DelistRecord(
                ticker=ticker.upper(),
                cik=resolution.cik,
                observed_delist_date=observed_delist_date,
                crsp_code=570,
                bucket=CrspBucket.COMPLIANCE_FAILURE,
                confidence="low",
                reason="Form 25 present with 8-K having no conclusive items; default compliance",
                evidence=evidence,
            )

        # Delinquent-filer upgrade: a 570 with NT 10-K/Q in the prior year
        # is more specifically a 580 (delinquent in filings).
        if code == 570 and observed and self._detect_delinquent_filer(filings, observed):
            code = 580
            reason = reason + " + NT 10-K/Q in prior year (delinquent filer 580)"

        conf = "high" if dereg is not None else "medium"
        return DelistRecord(
            ticker=ticker.upper(),
            cik=resolution.cik,
            observed_delist_date=observed_delist_date,
            crsp_code=code,
            bucket=bucket_for_code(code),
            confidence=conf,
            reason=reason,
            evidence=evidence,
        )

    def classify_many(
        self, items: Iterable[tuple[str, str | None]]
    ) -> list[DelistRecord]:
        return [self.classify_ticker(t, d) for t, d in items]
