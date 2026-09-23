# src/delist_detection/pipeline.py
"""End-to-end run: observations -> security master and delistings (spec §8).

Everything is computed first and written last, so a refusal or a bad override
file never leaves a half-written output over the previous complete one.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .crsp_codes import CrspBucket
from .delistings import DelistingEvent, DelistingFinder, ReviewItem, SecurityContext
from .edgar import EdgarBlocked
from .figi_resolution import FigiCandidate, accept, share_class_from_name, us_candidates
from .form25 import SecurityRef, exchange_label
from .ftd import FtdIndex
from .listing_status import listed_today
from .names import names_agree
from .observations import ObservationIndex, TickerEra, eras_by_key, normalize_ticker, observation_conflicts
from .openfigi import OpenFigiBlocked
from .payout_gate import DEFAULT_TOL, gate_payouts
from .reconstruction import _lookup, build_delistings_table, delisting_row, unmatched_override_keys
from .security_master import (
    FigiResolver, Range, Security, build_securities, era_cusips, era_last_seen, ranges_from_sightings, refine_eras,
)
from .store import write_tables

FTD_START = date(2004, 1, 1)


@dataclass
class Clients:
    edgar: Any
    resolver: Any
    classifier: Any
    figi: Any
    ftd_client: Any
    midas: Any = None
    halts: Any = None
    payout_extractor: Any = None
    llm_extractor: Any = None


@dataclass
class Overrides:
    last_trade_closes: dict = field(default_factory=dict)
    merger_terms: dict = field(default_factory=dict)
    recoveries: dict = field(default_factory=dict)


@dataclass
class RunSummary:
    counts: dict[str, int]
    buckets: dict[str, int]
    figi_sources: dict[str, int]
    review_flags: dict[str, int]


def _stderr(*parts) -> None:
    print(*parts, file=sys.stderr, flush=True)


def _d(s: str) -> date:
    return date.fromisoformat(s)


def successor_from_8k12b(search: Callable, figi, *, name: str, day: date, exclude_cik: int,
                         share_class: str = "COMMON") -> tuple[int, FigiCandidate, str] | None:
    """The successor issuer that filed an 8-K12B naming `name` around `day`,
    resolved to the US composite FIGI whose share class matches the
    predecessor's `share_class`.

    A display name looks like ``"Alphabet Inc.  (GOOGL, GOOG)  (CIK
    0001652044)"``: the tickers are the parenthetical immediately before the
    trailing ``(CIK ...)`` — never the first parenthetical in the string,
    which can be part of the company's own legal name (``"Banco Santander
    (Brasil) S.A.  (BSBR)  (CIK 0001471119)"`` carries the ticker ``BSBR``,
    not ``Brasil``). Each of those tickers is resolved through OpenFIGI; a
    resolved candidate is kept only when its name agrees
    (`names.names_agree`) with the successor's own EDGAR name — the text
    before that ticker parenthetical, exactly as EDGAR's full-text search
    recorded it, so no extra network call is needed to confirm it. Among the
    agreeing candidates, the one whose share class (`share_class_from_name`)
    equals the predecessor's is picked; if the predecessor is plain common
    and exactly one candidate agrees on name, that one is taken even without
    an exact class match. Otherwise returns None (the caller leaves
    `successor_unknown` set rather than guess). A display name with no
    ticker parenthetical yields no candidates and makes no OpenFIGI request.

    Returns `(cik, candidate, filing_date)`.
    """
    hits = search(f'"{name}"', "8-K12B,8-K12G3", day - timedelta(days=30), day + timedelta(days=60))
    for h in hits:
        src = h.get("_source", h)
        filing_date = src.get("file_date") or src.get("filing_date") or ""
        for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
            cik = int(cik_s)
            if cik == exclude_cik:
                continue
            m = re.search(r"\(([^()]*)\)\s*\(CIK\s+\d+\)\s*$", disp)
            if not m:
                continue
            tickers = [normalize_ticker(t) for t in m.group(1).split(",") if t.strip()]
            if not tickers or figi is None:
                continue
            edgar_name = disp[: m.start()].strip()
            candidates: list[FigiCandidate] = []
            for t in tickers:
                ans = figi.map([{"idType": "TICKER", "idValue": t.replace("-", "/")}])[0]
                candidates += us_candidates(ans.get("data") or [])
            agreeing = [c for c in candidates if names_agree(c.name, edgar_name)]
            if not agreeing:
                continue
            class_matches = [c for c in agreeing if share_class_from_name(c.name) == share_class]
            if len(class_matches) == 1:
                return cik, class_matches[0], filing_date
            if share_class == "COMMON" and len(agreeing) == 1:
                return cik, agreeing[0], filing_date
    return None


_CLASS_WORDS = re.compile(r"\b(?:CL(?:ASS)?|SER(?:IES)?)\s*-?\s*[A-Z0-9]\b|-[A-Z]$", re.I)
_STATE_TAG = re.compile(r"\s*/[A-Z]+/?\s*$")        # EDGAR's "AETNA INC /PA/", "ALLEGHANY CORP /DE"


def successor_search_name(edgar, cik: int | None, observed_name: str | None) -> str:
    """The predecessor's name as an 8-K12B would print it: the issuer's EDGAR
    name from its submissions JSON without EDGAR's state tag ("Google Inc."),
    else the observation name without its class words ("GOOGLE INC CLASS A"
    -> "GOOGLE INC")."""
    sub = edgar.submissions(cik) if cik is not None else None
    name = (sub.get("name") or "").strip() if isinstance(sub, dict) else ""
    if name:
        return _STATE_TAG.sub("", name).strip()
    return re.sub(r"\s+", " ", _CLASS_WORDS.sub(" ", observed_name or "")).strip(" -")


def _issuer_exchange_for_ticker(edgar, cik: int | None, ticker: str) -> str | None:
    """The exchange EDGAR's own submissions JSON records for `ticker` (the
    parallel `tickers`/`exchanges` arrays), mapped to the table's exchange
    names; None when the issuer, the ticker, or its exchange entry is
    missing. Reads the submissions JSON the finder already cached — no new
    source."""
    if cik is None:
        return None
    sub = edgar.submissions(cik)
    if not isinstance(sub, dict):
        return None
    tickers = sub.get("tickers") or []
    exchanges = sub.get("exchanges") or []
    want = normalize_ticker(ticker)
    for t, x in zip(tickers, exchanges):
        if normalize_ticker(t) == want and x:
            return exchange_label(x) or None
    return None


def _overlaps(a: dict, b: dict) -> bool:
    a_to = a["valid_to"] or "9999-12-31"
    b_to = b["valid_to"] or "9999-12-31"
    return a["valid_from"] <= b_to and b["valid_from"] <= a_to


def _ticker_range_review(th_rows: list[dict]) -> list[ReviewItem]:
    """Flag, without changing, two `ticker_history` problems (spec 8.5):
    (a) one security's own ranges overlapping (`ticker_range_overlap`), and
    (b) one ticker mapping to two different securities on the same day
    (`ticker_shared`). Each violation names both ranges in its reason."""
    out: list[ReviewItem] = []

    by_sec: dict[str, list[dict]] = defaultdict(list)
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in th_rows:
        by_sec[r["sec_id"]].append(r)
        by_ticker[r["ticker"]].append(r)

    def _name(r: dict) -> str:
        return f"{r['ticker']} {r['valid_from']}..{r['valid_to'] or ''}"

    for sid, rows in by_sec.items():
        rs = sorted(rows, key=lambda r: r["valid_from"])
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _overlaps(rs[i], rs[j]):
                    out.append(ReviewItem(sid, rs[i]["ticker"], None, "ticker_range_overlap",
                                          f"{_name(rs[i])} overlaps {_name(rs[j])}"))

    for ticker, rows in by_ticker.items():
        rs = sorted(rows, key=lambda r: r["valid_from"])
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if rs[i]["sec_id"] == rs[j]["sec_id"] or not _overlaps(rs[i], rs[j]):
                    continue
                out.append(ReviewItem(rs[i]["sec_id"], ticker, None, "ticker_shared",
                                      f"{_name(rs[i])} ({rs[i]['sec_id']}) overlaps "
                                      f"{_name(rs[j])} ({rs[j]['sec_id']})"))
    return out


TICKER_CONFIRM_DAYS = 30        # an era's ticker counts as confirmed by an FTD row this close to its span


def _unconfirmed_review(eras: list[TickerEra], ftd: FtdIndex, resolutions: dict,
                        ciks: dict) -> list[ReviewItem]:
    """A `ticker_unconfirmed` review row for each era from 2004 on (the start of
    SEC fails-to-deliver data) with no FTD row under its ticker within
    `TICKER_CONFIRM_DAYS` of its first and last observation: the SEC data never
    shows that ticker then, as when a snapshot carries a ticker adopted later
    (APTV in 2012-2013, when Delphi traded as DLPH)."""
    out: list[ReviewItem] = []
    for e in eras:
        if _d(e.last) < FTD_START:
            continue
        lo = max(FTD_START, _d(e.first) - timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
        hi = (_d(e.last) + timedelta(days=TICKER_CONFIRM_DAYS)).isoformat()
        if ftd.by_symbol(e.ticker, lo, hi):
            continue
        out.append(ReviewItem(resolutions[e.key].sec_id or "", e.ticker, ciks.get(e.key), "ticker_unconfirmed",
                              f"{e.key} {e.name or ''}: no fails-to-deliver row under {e.ticker} "
                              f"from {lo} to {hi}", last_seen=e.last))
    return out


def _conflict_review(eras: list[TickerEra], resolutions: dict) -> list[ReviewItem]:
    """One `observation_conflict:<date>` review row per ticker seen under two or
    more names on one date (a snapshot source backfilled today's ticker: CB is
    both ACE LTD and CHUBB CORP in 2012-2014). The reason names each name with
    its era and the security that era resolved to. The date is in the flag so
    each (ticker, date) keeps its own row under review.csv's key."""
    out: list[ReviewItem] = []
    for ticker, day, names in observation_conflicts(o for e in eras for o in e.observations):
        seen = [f"{o.name} ({e.key} -> {resolutions[e.key].sec_id or 'unresolved'})"
                for e in eras if e.ticker == ticker for o in e.observations if o.as_of == day and o.name]
        out.append(ReviewItem("", ticker, None, f"observation_conflict:{day}",
                              f"{ticker} seen on {day} under {len(names)} names: " + "; ".join(dict.fromkeys(seen)),
                              last_seen=day))
    return out


def _merge_review_rows(rows: list[dict]) -> list[dict]:
    """Collapse rows that share `(sec_id, delist_date, ticker, review_flags)`
    into one, joining their distinct `reason`s with `"; "`. Every other field
    keeps its first non-empty value."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in rows:
        key = (r.get("sec_id"), r.get("delist_date"), r.get("ticker"), r.get("review_flags"))
        if key not in merged:
            merged[key] = dict(r)
            order.append(key)
            continue
        existing = merged[key]
        reasons = [x for x in (existing.get("reason") or "").split("; ") if x]
        new_reason = r.get("reason") or ""
        if new_reason and new_reason not in reasons:
            reasons.append(new_reason)
        existing["reason"] = "; ".join(reasons)
        for k, v in r.items():
            if k == "reason":
                continue
            if not existing.get(k) and v:
                existing[k] = v
    return [merged[k] for k in order]


def _sightings(sec: Security, ftd: FtdIndex, cusips: list[str]) -> list[tuple[str, str, str]]:
    """Dated `(day, ticker, source)` sightings of the security: its observations
    and the FTD rows of its CUSIPs. A ticker spelled with or without separators
    ("BF-B" / "BFB": snapshots write both, FTD keys rows by the separator form)
    is written one way per security: a spelling it was observed under, the one
    with a separator first. So Hubbell's merged class keeps "HUBB" while class
    B, observed as "HUB-B" and "HUBB", is "HUB-B"."""
    out = [(o.as_of, o.ticker, "observation") for e in sec.eras for o in e.observations]
    for c in cusips:
        out += [(r.date, r.symbol, "ftd") for r in ftd.by_cusip(c)]
    label: dict[str, str] = {}
    for t in sorted({o.ticker for e in sec.eras for o in e.observations}, key=lambda t: ("-" not in t, t)):
        label.setdefault(t.replace("-", ""), t)
    return sorted({(d, label.get(t.replace("-", ""), t), s) for d, t, s in out})


def _cusip_sightings(sec: Security, ftd: FtdIndex, cusips: list[str]) -> list[tuple[str, str, str]]:
    """Dated `(day, cusip, source)` sightings of the security's CUSIPs: the FTD
    rows of each CUSIP that resolved to it, and the CUSIPs its observations carry."""
    out = [(r.date, r.cusip, "ftd") for c in cusips for r in ftd.by_cusip(c)]
    out += [(o.as_of, o.cusip, "observation") for e in sec.eras for o in e.observations if o.cusip]
    return sorted(set(out))


def _close_on(ftd: FtdIndex, cusip_ranges: list[Range], day: date,
              symbol: str) -> tuple[float, str, bool] | None:
    """The close of `day` (FTD rows of the next trading days, see
    `FtdIndex.close_after`), looked up by the CUSIP whose range holds `day`,
    then by `symbol`."""
    d = day.isoformat()
    cusip = next((r.value for r in cusip_ranges if r.valid_from <= d and (r.valid_to is None or d <= r.valid_to)),
                 None)
    return (ftd.close_after(day, cusip=cusip) if cusip else None) or ftd.close_after(day, symbol=symbol)


def _close_through(ftd: FtdIndex, cusip_ranges: list[Range], day: date, symbol: str) -> tuple[float, str] | None:
    """When no row follows `day`: the latest close known on it (`FtdIndex.close_through`,
    a row dated on or a few trading days before `day`), by the CUSIP whose range
    holds `day`, then by `symbol`."""
    d = day.isoformat()
    cusip = next((r.value for r in cusip_ranges if r.valid_from <= d and (r.valid_to is None or d <= r.valid_to)),
                 None)
    return (ftd.close_through(day, cusip=cusip) if cusip else None) or ftd.close_through(day, symbol=symbol)


def _ticker_on(sig: list[tuple[str, str, str]]) -> Callable[[str], str | None]:
    def f(day: str) -> str | None:
        before = [t for d, t, _ in sig if d <= day]
        if before:
            return before[-1]
        return sig[0][1] if sig else None
    return f


def _resolution_source(sec: Security, cik_res: dict) -> str:
    """The resolver tier ("cik_map", "manual", "company_tickers", ...) that
    found the security's issuer CIK: that of its latest era with a CIK, the
    same era `build_securities` takes `issuer_cik` from; "security_master"
    when none has one."""
    for e in reversed(sec.eras):
        r = cik_res.get(e.key)
        if r is not None and r.cik is not None:
            return r.source or "security_master"
    return "security_master"


def _own_last_seen(sec: Security, sig: list[tuple[str, str, str]]) -> str:
    """The latest sighting under one of the security's own era tickers, else
    the latest era end date.

    FTD rows found by CUSIP include a post-delisting OTC tail under another
    symbol (e.g. a bankrupt XYZ trading as XYZQ), which would otherwise push
    `last_seen` past the real delisting and misdate a fallback delisting.
    """
    own = {e.ticker for e in sec.eras}
    dates = [d for d, t, _ in sig if t in own]
    return dates[-1] if dates else max(e.last for e in sec.eras)


def run(index: ObservationIndex, clients: Clients, overrides: Overrides, *, out_dir: Path,
        tol: float = DEFAULT_TOL, limit: int | None = None, log: Callable = _stderr) -> RunSummary:
    eras = index.eras()
    if limit:
        eras = eras[:limit]
    log(f"{len(eras)} ticker eras")

    if not eras:
        raise ValueError("no observations to process")

    # 1. FTD rows for the eras' tickers (first: they date each era's real last sighting),
    # then split the observation eras further on that evidence (a CUSIP switch, or a
    # gap no FTD row bridges). Every later step works on the refined eras.
    lo = max(FTD_START, min(_d(e.first) for e in eras) - timedelta(days=30))
    hi = min(date.today(), max(_d(e.last) for e in eras) + timedelta(days=400))
    class_names: dict[str, list[str]] = defaultdict(list)     # BF-B's names: checks FTD's "BFB" rows
    for e in eras:
        if "-" in e.ticker:
            class_names[e.ticker] += e.names
    ftd = FtdIndex.load(clients.ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips}, names=class_names)
    eras = refine_eras(eras, ftd)
    era_by_key = eras_by_key(eras)               # raises on a duplicate key: an era is never dropped
    log(f"{len(eras)} eras after the FTD split")

    # 2. issuer CIK per era, resolved at the era's last sighting: index snapshots can
    # be months apart, and the resolver's Form 25 search is anchored on this date.
    # The resolver tier that found it (cik_map, manual, company_tickers, ...) is kept
    # for the delisting rows' resolution_source.
    cik_res = {e.key: clients.resolver.resolve(e.ticker, era_last_seen(e, ftd)) for e in eras}
    ciks = {k: r.cik for k, r in cik_res.items()}

    # 3. FIGI per era -> securities
    cusips = {e.key: era_cusips(e, ftd) for e in eras}
    resolutions = FigiResolver(clients.figi).resolve_many(eras, ciks=ciks, cusips=cusips)
    securities = build_securities(resolutions, era_by_key, ciks)
    review: list[ReviewItem] = []
    for key, res in resolutions.items():
        era = era_by_key[key]
        for flag in res.flags:
            review.append(ReviewItem(res.sec_id or "", era.ticker, ciks.get(key), flag,
                                     f"{era.key} {era.name or ''}".strip(), last_seen=era.last))
    review += _conflict_review(eras, resolutions)
    review += _unconfirmed_review(eras, ftd, resolutions, ciks)
    log(f"{len(securities)} securities; FIGI sources "
        f"{dict(Counter(s.figi_source for s in securities.values()))}")

    # 4. each security's CUSIPs over its whole life: every CUSIP of each of its eras
    # that resolved to its FIGI (a reverse split's old and new CUSIP both)
    sec_cusips = {sid: list(dict.fromkeys(c for e in s.eras for c in resolutions[e.key].cusips))
                  for sid, s in securities.items()}
    ftd.extend(clients.ftd_client, lo, date.today(), cusips={c for v in sec_cusips.values() for c in v})

    # 5. delistings
    siblings: dict[int, list[SecurityRef]] = defaultdict(list)
    for s in securities.values():
        if s.issuer_cik is not None:
            siblings[s.issuer_cik].append(SecurityRef(s.sec_id, s.share_class, s.kind))
    finder = DelistingFinder(clients.edgar, clients.classifier, midas=clients.midas, halts=clients.halts)
    events: list[DelistingEvent] = []
    listed: dict[str, bool | None] = {}
    sightings = {sid: _sightings(s, ftd, sec_cusips[sid]) for sid, s in securities.items()}
    for i, s in enumerate(sorted(securities.values(), key=lambda s: s.sec_id), 1):
        sig = sightings[s.sec_id]
        own_last_seen = _own_last_seen(s, sig)
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind)]
        # sec_id -> (first sighting, last own-ticker sighting) for every security
        # sharing this issuer CIK, from the same sightings built above; a sibling
        # with no sightings gets no entry (the finder treats it as alive at every
        # filing). The end reuses _own_last_seen so a sibling's post-delisting OTC
        # tail under another symbol can't extend its life past its real death.
        spans: dict[str, tuple[str, str]] = {}
        for ref in sibs:
            sib_sig = sightings.get(ref.sec_id)
            if not sib_sig:
                continue
            sib_sec = securities.get(ref.sec_id)
            span_end = _own_last_seen(sib_sec, sib_sig) if sib_sec is not None else sib_sig[-1][0]
            spans[ref.sec_id] = (sib_sig[0][0], span_end)
        try:
            # listed_today lives inside the try too: a FIGI/EDGAR error there
            # must become a reviewable row for this one security, not abort
            # the whole overnight run.
            listed[s.sec_id] = listed_today(clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik)
            ctx = SecurityContext(
                security=s,
                siblings=sibs,
                ticker_on=_ticker_on(sig),
                last_seen=own_last_seen,
                seen_after=lambda day, sig=sig: any(d > day for d, _, _ in sig),
                listed_today=listed[s.sec_id],
                expected_name=s.eras[-1].name if s.eras else None,
                sibling_spans=spans,
                resolution_source=_resolution_source(s, cik_res),
                ftd_seen_after=lambda day, sig=sig, own={e.ticker for e in s.eras}: any(
                    d > day for d, t, src in sig if src == "ftd" and t in own),
                tickers_between=lambda lo, hi, sig=sig: list(dict.fromkeys(t for d, t, _ in sig if lo <= d <= hi)),
            )
            evs, rv = finder.find(ctx)
        except (EdgarBlocked, OpenFigiBlocked):
            raise
        except Exception as exc:  # an overnight run must survive one bad security
            log(f"[{i}/{len(securities)}] {s.sec_id}: ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(s.sec_id, s.eras[-1].ticker if s.eras else "", s.issuer_cik, "error",
                                     f"{type(exc).__name__}: {exc}", last_seen=own_last_seen))
            continue
        events += evs
        review += rv
        if i % 50 == 0:
            log(f"[{i}/{len(securities)}] securities searched; {len(events)} delistings so far")

    # 6. every override must name a delisting
    keys = [(e.sec_id, e.delist_date) for e in events]
    bad = []
    for name, m in (("--last-trade-closes", overrides.last_trade_closes),
                    ("--merger-terms", overrides.merger_terms), ("--recoveries", overrides.recoveries)):
        bad += [f"{name}: {k}" for k in unmatched_override_keys(m, keys)]
    if bad:
        raise ValueError("override rows that match no delisting: " + "; ".join(map(str, bad)))

    # 7. last-trade closes. The FTD rows were loaded from the eras' first sighting
    # on; a delisting whose last trade came earlier (a stale snapshot listed the
    # security after it was gone) needs the rows around that day first.
    early = [e for e in events if e.last_trade.day is not None and FTD_START <= e.last_trade.day < lo]
    if early:
        days = [e.last_trade.day for e in early]
        ftd.extend(clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                   symbols={e.ticker for e in early},
                   cusips={c for e in early for c in sec_cusips.get(e.sec_id, [])})
    closes: dict[tuple[str, str], float] = {}
    for e in events:
        key = (e.sec_id, e.delist_date)
        given = _lookup(overrides.last_trade_closes, e.sec_id, e.delist_date)
        if given is not None:
            closes[key] = given
            continue
        if e.last_trade.day is None:
            e.record.evidence["flags"].append("no_last_close")
            continue
        sec = securities[e.sec_id]
        cusip_ranges = ranges_from_sightings(_cusip_sightings(sec, ftd, sec_cusips.get(e.sec_id, [])),
                                             end=None, open_ended=True)
        got = _close_on(ftd, cusip_ranges, e.last_trade.day, e.ticker)
        if got is None:
            # Fails stop once trading stops, so no row may follow the last trade
            # day: look back a few rows (spec §16), flagged as an earlier close.
            back = _close_through(ftd, cusip_ranges, e.last_trade.day, e.ticker)
            if back is None:
                e.record.evidence["flags"].append("no_last_close")
            else:
                closes[key] = back[0]
                e.record.evidence["flags"].append("ftd_close_prior_day")
            continue
        price, _, lagged = got
        closes[key] = price
        if lagged:
            e.record.evidence["flags"].append("ftd_close_lagged")

    # 8. merger payouts, LLM terms, acquirer prices and securities
    payouts_raw, llm_terms = {}, {}
    mergers = [e for e in events if e.record.bucket is CrspBucket.MERGER]
    for e in mergers:
        key = (e.sec_id, e.delist_date)
        try:
            if clients.payout_extractor is not None:
                payouts_raw[key] = clients.payout_extractor.extract(e.record, last_close=closes.get(key))
            if clients.llm_extractor is not None:
                t = clients.llm_extractor.extract(e.record)
                if t is not None:
                    llm_terms[key] = t
        except (EdgarBlocked, OpenFigiBlocked):
            raise
        except Exception as exc:  # an overnight run must survive one bad extraction
            log(f"{e.sec_id} {e.delist_date}: payout extraction ERROR {type(exc).__name__}: {exc}")
            review.append(ReviewItem(e.sec_id, e.ticker, e.cik, "error", f"{type(exc).__name__}: {exc}",
                                     delist_date=e.delist_date))
    trade_day = {(e.sec_id, e.delist_date): e.last_trade.day for e in events}
    acq_symbols = {normalize_ticker(t.acquirer_ticker) for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in overrides.merger_terms.values()
                    if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                       symbols=acq_symbols)

    lagged_acquirer: set[tuple[str, str | None]] = set()

    def acquirer_price(ticker: str, key: tuple[str, str | None]) -> float | None:
        # Priced on THAT merger's own last-trade day: many mergers can share a
        # delist_date, so a plain date->day map would misprice one with another's.
        day = trade_day.get(key)
        got = ftd.close_after(day, symbol=ticker) if day and ticker else None
        if got is None:
            return None
        if got[2]:
            lagged_acquirer.add(key)
        return got[0]

    regex = {k: pr for k, pr in payouts_raw.items() if pr is not None and pr.value is not None}
    gated = gate_payouts(
        [(e.sec_id, e.delist_date) for e in mergers],
        {k: pr.value for k, pr in regex.items()}, {k: pr.source for k, pr in regex.items()},
        {k: pr.confidence for k, pr in regex.items()}, llm_terms, closes, overrides.merger_terms,
        acquirer_price, tol,
    )
    for e in mergers:
        # A lagged FTD close (no row on the next trading day) may carry an OTC or
        # stale price: flag the delisting when that price made it into its terms.
        terms = _lookup(gated.merged_terms, e.sec_id, e.delist_date)
        if (e.sec_id, e.delist_date) in lagged_acquirer and terms and terms.get("acquirer_price") is not None:
            e.record.evidence["flags"].append("acquirer_close_lagged")
    added: dict[str, Security] = {}
    added_meta: dict[str, dict] = {}
    acquirer_ids: dict[tuple[str, str], str] = {}
    for e in mergers:
        key = (e.sec_id, e.delist_date)
        terms = _lookup(gated.merged_terms, e.sec_id, e.delist_date)
        if not terms:
            continue
        acq = normalize_ticker(terms.get("acquirer_ticker") or "")
        day = trade_day.get(key)
        if not acq or day is None:
            continue
        rows = ftd.by_symbol(acq, (day - timedelta(days=10)).isoformat(), (day + timedelta(days=10)).isoformat())
        cusip = Counter(r.cusip for r in rows).most_common(1)
        if not cusip:
            continue
        ans = clients.figi.map([{"idType": "ID_CUSIP", "idValue": cusip[0][0], "includeUnlistedEquities": True}])[0]
        cand = accept(us_candidates(ans.get("data") or []), ticker=acq, names=[], via_cusip=True)
        if cand is None:
            continue
        acquirer_ids[key] = cand.composite
        if cand.composite not in securities:
            if cand.composite not in added:
                acq_cik = clients.resolver.resolve(acq, day.isoformat()).cik
                added[cand.composite] = Security(cand.composite, acq_cik, share_class_from_name(cand.name),
                                                 cand.name, cand.security_type, False, "cusip")
                added_meta[cand.composite] = {"kind": "acquirer", "ticker": acq, "rows": [], "fallback_day": day}
            # Union every merger's FTD window for this acquirer: several mergers
            # can name the same acquirer, and its ticker_history row must span
            # all of them, not just the first one processed.
            added_meta[cand.composite]["rows"] = added_meta[cand.composite]["rows"] + list(rows)

    # 9. successors after a FIGI change
    # (search: EDGAR full-text search; wire the real one in default_clients via clients.edgar)
    successor_search = getattr(clients.edgar, "full_text_search", None)
    for e in events:
        if "successor_unknown" not in e.flags or successor_search is None:
            continue
        predecessor = securities[e.sec_id]
        day = e.last_trade.day or _d(e.delist_date)
        name = successor_search_name(clients.edgar, e.cik, predecessor.name)
        hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day,
                                   exclude_cik=e.cik, share_class=predecessor.share_class)
        if hit is None:
            continue
        s_cik, cand, filing_date = hit
        e.record.successor_sec_id = cand.composite
        e.record.evidence["flags"] = [f for f in e.record.evidence["flags"] if f != "successor_unknown"]
        if cand.composite not in securities and cand.composite not in added:
            added[cand.composite] = Security(cand.composite, s_cik, share_class_from_name(cand.name), cand.name,
                                             cand.security_type, False, "ticker")
            # A same-ticker successor (a holding-company reorg) must not overlap
            # the predecessor's own ticker_history row, even when its 8-K12B was
            # filed before the predecessor's actual last trade: clamp valid_from
            # to no earlier than the day after that last trade (or delist_date
            # when the last trade day is unknown).
            not_before = ((e.last_trade.day or _d(e.delist_date)) + timedelta(days=1)).isoformat()
            fd = filing_date or day.isoformat()
            added_meta[cand.composite] = {"kind": "successor", "ticker": cand.ticker,
                                          "filing_date": max(fd, not_before)}

    # 10. rows
    table = build_delistings_table(
        [e.record for e in events], last_trade_closes=closes, payouts=gated.payouts,
        exchanges={(e.sec_id, e.delist_date): e.exchange for e in events},
        merger_terms=gated.merged_terms, recovery_ratios=overrides.recoveries,
        payout_sources=gated.sources, payout_confidences=gated.confidences, payout_flags=gated.flags,
    )
    ev_by_key = {(e.sec_id, e.delist_date): e for e in events}
    delisting_rows, review_rows = [], []
    for enr in table:
        e = ev_by_key[(enr.sec_id, enr.delist_date)]
        pr = payouts_raw.get((e.sec_id, e.delist_date))
        delisting_rows.append(delisting_row(
            enr, exchange=e.exchange or None,
            last_trade_date=e.last_trade.day.isoformat() if e.last_trade.day else None,
            last_trade_date_source=e.last_trade.source or None,
            successor_sec_id=e.record.successor_sec_id,
            acquirer_sec_id=acquirer_ids.get((e.sec_id, e.delist_date)),
            raw_payout_per_share=pr.value if pr else None, raw_payout_source=pr.source if pr else None,
            raw_payout_confidence=pr.confidence if pr else None,
        ))
        if enr.review_flags:
            ak = (enr.evidence or {}).get("anchor_8k") or {}
            review_rows.append({"sec_id": enr.sec_id, "delist_date": enr.delist_date, "ticker": enr.ticker,
                                "cik": enr.cik, "bucket": enr.bucket.value,
                                "dlret": delisting_rows[-1]["dlret"], "review_flags": ";".join(enr.review_flags),
                                "reason": enr.reason, "anchor_8k": ak.get("items")})
    for r in review:
        review_rows.append({"sec_id": r.sec_id, "delist_date": r.delist_date, "ticker": r.ticker, "cik": r.cik,
                            "review_flags": r.flag, "reason": r.reason, "last_seen": r.last_seen})

    th_rows, ch_rows = [], []
    final = {}
    for e in sorted(events, key=lambda e: e.delist_date):
        final[e.sec_id] = e
    for sid, s in securities.items():
        sig = sightings.get(sid, [])
        fe = final.get(sid)
        is_listed = bool(listed.get(sid))
        end = None
        if fe is not None and not is_listed:
            # A last-trade day we couldn't confirm still clips the ranges at the
            # delisting date -- an unclipped range would otherwise run past a
            # security's real end.
            end = fe.last_trade.day.isoformat() if fe.last_trade.day is not None else fe.delist_date
        clipped = [x for x in sig if end is None or x[0] <= end]
        for rg in ranges_from_sightings(clipped, end=end, open_ended=is_listed):
            if fe is not None and end is not None and rg.valid_to == end:
                exch = fe.exchange
            elif rg.valid_to is None:
                # An open (listed-today) row: pull the exchange from the issuer's
                # own EDGAR submissions JSON (already cached by the finder).
                exch = _issuer_exchange_for_ticker(clients.edgar, s.issuer_cik, rg.value)
            else:
                exch = None
            th_rows.append({"sec_id": sid, "ticker": rg.value, "exchange": exch, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})
        cus = [x for x in _cusip_sightings(s, ftd, sec_cusips.get(sid, [])) if end is None or x[0] <= end]
        for rg in ranges_from_sightings(cus, end=end, open_ended=is_listed):
            ch_rows.append({"sec_id": sid, "cusip": rg.value, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})

    # Added (acquirer/successor) securities get one row each, built directly:
    # ranges_from_sightings' filter that drops single-value FTD sightings would
    # otherwise silently drop a successor's lone 8-K12B-dated sighting.
    for sid, s in added.items():
        listed[sid] = listed_today(clients.figi, sid, edgar=clients.edgar, cik=s.issuer_cik)
        is_listed = bool(listed[sid])
        meta = added_meta[sid]
        if meta["kind"] == "acquirer":
            rows = meta["rows"]
            dates = sorted(r.date for r in rows) if rows else []
            valid_from = dates[0] if dates else meta["fallback_day"].isoformat()
            valid_to = None if is_listed else (dates[-1] if dates else valid_from)
            source = "ftd"
        else:  # successor
            fd = meta["filing_date"]
            valid_from = fd
            valid_to = None if is_listed else fd
            source = "edgar_8k"
        exch = _issuer_exchange_for_ticker(clients.edgar, s.issuer_cik, meta["ticker"]) if is_listed else None
        th_rows.append({"sec_id": sid, "ticker": meta["ticker"], "exchange": exch, "valid_from": valid_from,
                        "valid_to": valid_to, "source": source})

    for item in _ticker_range_review(th_rows):
        review_rows.append({"sec_id": item.sec_id, "delist_date": item.delist_date, "ticker": item.ticker,
                            "cik": item.cik, "review_flags": item.flag, "reason": item.reason,
                            "last_seen": item.last_seen})

    payout_rows = []
    for key, pr in payouts_raw.items():
        value = gated.payouts.get(key)
        source = gated.sources.get(key, "none")
        # Restore the old CLI's provenance rule: an LLM-sourced payout cites the
        # LLM filing's accession (its regex accession, if any, is often blank or
        # belongs to a different filing tier).
        if source.startswith("llm"):
            t = llm_terms.get(key)
            accession = t.source.partition(":")[2] if t is not None else None
        else:
            accession = pr.accession if pr and value is not None else None
        payout_rows.append({"sec_id": key[0], "delist_date": key[1], "ticker": ev_by_key[key].ticker,
                            "payout_per_share": value, "confidence": gated.confidences.get(key, "none"),
                            "source": source, "accession": accession})

    review_rows = _merge_review_rows(review_rows)

    # 11. write -- all six tables formatted and written to temp files first,
    # renamed into place together, so a later table's failure never leaves an
    # earlier table's new file sitting over the previous complete one.
    counts = write_tables(out_dir, {
        "securities": [s.row() for s in securities.values()] + [s.row() for s in added.values()],
        "ticker_history": th_rows,
        "cusip_history": ch_rows,
        "delistings": delisting_rows,
        "payouts": payout_rows,
        "review": review_rows,
    })
    flags = Counter(f.split(":", 1)[0] for r in review_rows for f in (r.get("review_flags") or "").split(";") if f)
    return RunSummary(counts, dict(Counter(e.record.bucket.value for e in events)),
                      dict(Counter(s.figi_source for s in securities.values())), dict(flags))


def default_clients(index: ObservationIndex, *, cache_dir: Path, rename_map: dict | None = None,
                    manual_overrides: dict | None = None, extract_payouts: bool = True,
                    extract_llm: bool = False, llm_model: str | None = None, use_midas: bool = True,
                    use_halts: bool = True) -> Clients:
    from .classifier import DelistClassifier
    from .edgar import EdgarClient
    from .ftd import FtdClient
    from .midas import MidasClient
    from .nasdaq_halts import NasdaqHaltClient
    from .openfigi import OpenFigiClient, resolve_api_key
    from .payout_extractor import PayoutExtractor
    from .ticker_resolver import TickerResolver

    edgar = EdgarClient(cache_dir=cache_dir / "edgar")
    resolver = TickerResolver(edgar, rename_map=rename_map,
                              manual_overrides={k: v for k, v in (manual_overrides or {}).items() if v > 0},
                              cache_path=cache_dir / "ticker_resolution.json",
                              member_names=index.name_on, cik_map=index.cik_pin_on)
    llm = None
    if extract_llm:
        from .llm_client import default_llm_client
        from .llm_merger_extractor import LLMMergerTermsExtractor
        llm = LLMMergerTermsExtractor(edgar, default_llm_client(llm_model), cache_dir=cache_dir / "llm")
    return Clients(
        edgar=edgar, resolver=resolver, classifier=DelistClassifier(edgar, resolver),
        figi=OpenFigiClient(cache_dir / "openfigi", resolve_api_key()),
        ftd_client=FtdClient(cache_dir / "sec_data" / "ftd"),
        midas=MidasClient(cache_dir / "sec_data" / "midas") if use_midas else None,
        halts=NasdaqHaltClient(cache_dir / "nasdaq_halts") if use_halts else None,
        payout_extractor=PayoutExtractor(edgar) if extract_payouts else None,
        llm_extractor=llm,
    )
