"""Pure rules for turning OpenFIGI answers into one US composite FIGI.

A composite FIGI groups one security's venue lines within a country; the US
composite is the library's sec_id. Acceptance never relies on Bloomberg's
current name alone, because Bloomberg renames a dead line to its acquirer.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .names import names_agree
from .observations import normalize_ticker

US_EXCH = frozenset({"US", "UN", "UW", "UQ", "UR", "UA", "UP", "UF", "UV", "PQ", "UB", "UC", "UM", "UX",
                     "UD", "UT", "UL", "UI", "UO", "UU", "VJ", "VK", "VY"})
_SIDELINE = re.compile(r"WHEN[- ]ISSUED|\bW/I\b|\b144A\b|\bNAV\b", re.I)
_FUND_TYPES = {"open-end fund", "mutual fund", "money market"}
_LEGAL = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "LLC", "PLC",
          "DE", "NEW", "THE", "HOLDINGS", "HOLDING", "GROUP", "LP", "L", "P", "SA", "NV", "AG"}


@dataclass(frozen=True)
class FigiCandidate:
    composite: str
    name: str
    ticker: str
    security_type: str
    rows: tuple[dict, ...]


def _is_sideline(r: dict) -> bool:
    ticker = (r.get("ticker") or "").upper()
    return (bool(_SIDELINE.search(r.get("name") or ""))
            or (r.get("securityType") or "").lower() in _FUND_TYPES
            or (r.get("securityType2") or "").lower() in {"mutual fund", "when issued"}
            or ticker.endswith((" WI", "/WI", " W/I")))


def us_candidates(rows: Iterable[dict]) -> list[FigiCandidate]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        comp = r.get("compositeFIGI")
        if comp:
            groups.setdefault(comp, []).append(r)
    out: list[FigiCandidate] = []
    for comp, rs in groups.items():
        us = next((r for r in rs if r.get("exchCode") == "US"), None)
        if us is None and not any(r.get("exchCode") in US_EXCH for r in rs):
            continue
        rep = us or next((r for r in rs if r.get("exchCode") in US_EXCH), None)
        if _is_sideline(rep):
            continue
        out.append(FigiCandidate(comp, rep.get("name") or "", normalize_ticker(rep.get("ticker") or ""),
                                 rep.get("securityType") or "", tuple(rs)))
    return out


def _carries(c: FigiCandidate, ticker: str) -> bool:
    return any(normalize_ticker(r.get("ticker") or "") == ticker for r in c.rows)


def accept(cands: Sequence[FigiCandidate], *, ticker: str, names: Sequence[str],
           via_cusip: bool) -> FigiCandidate | None:
    t = normalize_ticker(ticker)
    names = [n for n in names if n]
    if via_cusip:
        if len(cands) == 1:
            return cands[0]
        with_t = [c for c in cands if _carries(c, t)]
        return with_t[0] if len(with_t) == 1 else None
    exact = [c for c in cands
             if any(normalize_ticker(r.get("ticker") or "") == t
                    and any(names_agree(r.get("name") or "", n) for n in names) for r in c.rows)]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    plain = [c for c in cands if _carries(c, t) and any(names_agree(c.name, n) for n in names)]
    return plain[0] if len(plain) == 1 else None


def share_class_from_name(name: str | None) -> str:
    s = (name or "").upper().strip()
    m = re.search(r"\bCL(?:ASS)?\s*-?\s*([A-Z])\b", s)
    if m:
        return f"CLASS {m.group(1)}"
    m = re.search(r"\bSER(?:IES)?\s*-?\s*([A-Z0-9])\b", s)
    if m:
        return f"SERIES {m.group(1)}"
    m = re.search(r"-([A-Z])$", s)
    if m:
        return f"CLASS {m.group(1)}"
    return "COMMON"


def class_letter(share_class: str | None) -> str | None:
    m = re.fullmatch(r"(?:CLASS|SERIES)\s+([A-Z0-9])", (share_class or "").upper().strip())
    return m.group(1) if m else None


def placeholder_id(cik: int, share_class: str | None) -> str:
    cls = re.sub(r"[^A-Z0-9]+", "-", (share_class or "COMMON").upper()).strip("-") or "COMMON"
    return f"CIK{int(cik)}-{cls}"


def is_placeholder(sec_id: str) -> bool:
    return sec_id.startswith("CIK")


def bloomberg_ticker(ticker: str) -> str:
    return normalize_ticker(ticker).replace("-", "/")


def filter_query(name: str) -> str:
    words = re.findall(r"[A-Z0-9&']+", (name or "").upper())
    return " ".join(w for w in words if w not in _LEGAL)


def security_kind(security_type: str | None, name: str | None = None) -> str:
    st = (security_type or "").lower()
    nm = (name or "").upper()
    if "preferred" in st or " PREFERRED" in nm:
        return "preferred"
    if st in {"etp", "closed-end fund", "open-end fund", "unit inv tst", "mutual fund"} or "fund" in st \
            or re.search(r"\bETF\b|\bETN\b", nm):
        return "fund"
    if "warrant" in st or re.search(r"\bWARRANTS?\b", nm):
        return "warrant"
    if "right" in st or re.search(r"\bRIGHTS\b", nm):
        return "right"
    if st.startswith("unit") or re.search(r"\bUNITS\b", nm):
        return "unit"
    if any(k in st for k in ("note", "bond", "debt")) or re.search(r"\bNOTES? DUE\b|\bDEBENTURES?\b", nm):
        return "debt"
    return "common"
