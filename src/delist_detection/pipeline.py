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
from .figi_resolution import accept, us_candidates
from .form25 import SecurityRef
from .ftd import FtdIndex
from .listing_status import listed_today
from .observations import ObservationIndex, normalize_ticker
from .payout_gate import DEFAULT_TOL, gate_payouts
from .reconstruction import _lookup, build_delistings_table, delisting_row, unmatched_override_keys
from .security_master import (
    FigiResolver, Security, build_securities, era_cusips, era_last_seen, ranges_from_sightings,
)
from .store import table_path, write_table

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


def successor_from_8k12b(search: Callable, figi, *, name: str, day: date,
                         exclude_cik: int) -> tuple[int, str] | None:
    """The successor issuer that filed an 8-K12B naming `name` around `day`."""
    hits = search(f'"{name}"', "8-K12B,8-K12G3", day - timedelta(days=30), day + timedelta(days=60))
    for h in hits:
        src = h.get("_source", h)
        for cik_s, disp in zip(src.get("ciks") or [], src.get("display_names") or []):
            cik = int(cik_s)
            if cik == exclude_cik:
                continue
            m = re.search(r"\(([A-Z0-9.\-]+)(?:,|\))", disp)
            if m:
                return cik, normalize_ticker(m.group(1))
    return None


def _sightings(sec: Security, ftd: FtdIndex, cusips: list[str]) -> list[tuple[str, str, str]]:
    out = [(o.as_of, o.ticker, "observation") for e in sec.eras for o in e.observations]
    for c in cusips:
        out += [(r.date, r.symbol, "ftd") for r in ftd.by_cusip(c)]
    return sorted(set(out))


def _ticker_on(sig: list[tuple[str, str, str]]) -> Callable[[str], str | None]:
    def f(day: str) -> str | None:
        before = [t for d, t, _ in sig if d <= day]
        if before:
            return before[-1]
        return sig[0][1] if sig else None
    return f


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
    era_by_key = {e.key: e for e in eras}
    log(f"{len(eras)} ticker eras")

    if not eras:
        raise ValueError("no observations to process")

    # 1. FTD rows for the eras' tickers (first: they date each era's real last sighting)
    lo = max(FTD_START, min(_d(e.first) for e in eras) - timedelta(days=30))
    hi = min(date.today(), max(_d(e.last) for e in eras) + timedelta(days=400))
    ftd = FtdIndex.load(clients.ftd_client, lo, hi, symbols={e.ticker for e in eras},
                        cusips={c for e in eras for c in e.cusips})

    # 2. issuer CIK per era, resolved at the era's last sighting: index snapshots can
    # be months apart, and the resolver's Form 25 search is anchored on this date.
    ciks = {e.key: clients.resolver.resolve(e.ticker, era_last_seen(e, ftd)).cik for e in eras}

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
    log(f"{len(securities)} securities; FIGI sources "
        f"{dict(Counter(s.figi_source for s in securities.values()))}")

    # 4. each security's CUSIPs over its whole life
    sec_cusips = {sid: list(dict.fromkeys(cusips[e.key][0] for e in s.eras if cusips[e.key]))
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
        listed[s.sec_id] = listed_today(clients.figi, s.sec_id, edgar=clients.edgar, cik=s.issuer_cik)
        sig = sightings[s.sec_id]
        sibs = siblings.get(s.issuer_cik) or [SecurityRef(s.sec_id, s.share_class, s.kind)]
        # sec_id -> (first sighting, last sighting) for every security sharing this
        # issuer CIK, from the same sightings built above; a sibling with no
        # sightings gets no entry (the finder treats it as alive at every filing).
        spans: dict[str, tuple[str, str]] = {}
        for ref in sibs:
            sib_sig = sightings.get(ref.sec_id)
            if sib_sig:
                spans[ref.sec_id] = (sib_sig[0][0], sib_sig[-1][0])
        ctx = SecurityContext(
            security=s,
            siblings=sibs,
            ticker_on=_ticker_on(sig),
            last_seen=_own_last_seen(s, sig),
            seen_after=lambda day, sig=sig: any(d > day for d, _, _ in sig),
            listed_today=listed[s.sec_id],
            expected_name=s.eras[-1].name if s.eras else None,
            sibling_spans=spans,
        )
        evs, rv = finder.find(ctx)
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

    # 7. last-trade closes
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
        cusip = next((c for c in sec_cusips.get(e.sec_id, [])), None)
        got = (ftd.close_after(e.last_trade.day, cusip=cusip) if cusip else None) \
            or ftd.close_after(e.last_trade.day, symbol=e.ticker)
        if got is None:
            e.record.evidence["flags"].append("no_last_close")
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
        if clients.payout_extractor is not None:
            payouts_raw[key] = clients.payout_extractor.extract(e.record, last_close=closes.get(key))
        if clients.llm_extractor is not None:
            t = clients.llm_extractor.extract(e.record)
            if t is not None:
                llm_terms[key] = t
    trade_day = {(e.sec_id, e.delist_date): e.last_trade.day for e in events}
    acq_symbols = {normalize_ticker(t.acquirer_ticker) for t in llm_terms.values() if t.acquirer_ticker}
    acq_symbols |= {normalize_ticker(v["acquirer_ticker"]) for v in overrides.merger_terms.values()
                    if v.get("acquirer_ticker")}
    if acq_symbols:
        days = [d for d in trade_day.values() if d]
        if days:
            ftd.extend(clients.ftd_client, min(days) - timedelta(days=10), max(days) + timedelta(days=10),
                       symbols=acq_symbols)
    by_delist_date = {dd: day for (_, dd), day in trade_day.items()}

    def acquirer_price(ticker: str, delist_date: str | None) -> float | None:
        day = by_delist_date.get(delist_date)
        got = ftd.close_after(day, symbol=ticker) if day and ticker else None
        return got[0] if got else None

    regex = {k: pr for k, pr in payouts_raw.items() if pr is not None and pr.value is not None}
    gated = gate_payouts(
        [(e.sec_id, e.delist_date) for e in mergers],
        {k: pr.value for k, pr in regex.items()}, {k: pr.source for k, pr in regex.items()},
        {k: pr.confidence for k, pr in regex.items()}, llm_terms, closes, overrides.merger_terms,
        acquirer_price, tol,
    )
    added: dict[str, Security] = {}
    acquirer_ids: dict[tuple[str, str], str] = {}
    for key, terms in gated.merged_terms.items():
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
        if cand.composite not in securities and cand.composite not in added:
            added[cand.composite] = Security(cand.composite, None, "COMMON", cand.name, cand.security_type,
                                             False, "cusip")
            sightings[cand.composite] = sorted({(r.date, r.symbol, "ftd") for r in rows})

    # 9. successors after a FIGI change
    # (search: EDGAR full-text search; wire the real one in default_clients via clients.edgar)
    successor_search = getattr(clients.edgar, "full_text_search", None)
    for e in events:
        if "successor_unknown" not in e.flags or successor_search is None:
            continue
        name = securities[e.sec_id].name
        day = e.last_trade.day or _d(e.delist_date)
        hit = successor_from_8k12b(successor_search, clients.figi, name=name, day=day, exclude_cik=e.cik)
        if hit is None:
            continue
        s_cik, s_ticker = hit
        ans = clients.figi.map([{"idType": "TICKER", "idValue": s_ticker.replace("-", "/")}])[0]
        cands = us_candidates(ans.get("data") or [])
        cand = cands[0] if len(cands) == 1 else None
        if cand is None:
            continue
        e.record.successor_sec_id = cand.composite
        e.record.evidence["flags"] = [f for f in e.record.evidence["flags"] if f != "successor_unknown"]
        if cand.composite not in securities and cand.composite not in added:
            added[cand.composite] = Security(cand.composite, s_cik, "COMMON", cand.name, cand.security_type,
                                             False, "ticker")
            sightings[cand.composite] = [(day.isoformat(), s_ticker, "ftd")]

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
    for sid, s in list(securities.items()) + list(added.items()):
        sig = sightings.get(sid, [])
        fe = final.get(sid)
        is_listed = bool(listed.get(sid))
        end = None
        if fe is not None and not is_listed and fe.last_trade.day is not None:
            end = fe.last_trade.day.isoformat()
        clipped = [x for x in sig if end is None or x[0] <= end]
        for rg in ranges_from_sightings(clipped, end=end, open_ended=is_listed):
            exch = fe.exchange if (fe is not None and end is not None and rg.valid_to == end) else None
            th_rows.append({"sec_id": sid, "ticker": rg.value, "exchange": exch, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})
        cus = [(r.date, r.cusip, "ftd") for c in sec_cusips.get(sid, []) for r in ftd.by_cusip(c)]
        cus += [(o.as_of, o.cusip, "observation") for e in s.eras for o in e.observations if o.cusip]
        cus = [x for x in cus if end is None or x[0] <= end]
        for rg in ranges_from_sightings(cus, end=end, open_ended=is_listed):
            ch_rows.append({"sec_id": sid, "cusip": rg.value, "valid_from": rg.valid_from,
                            "valid_to": rg.valid_to, "source": rg.source})

    payout_rows = []
    for key, pr in payouts_raw.items():
        value = gated.payouts.get(key)
        payout_rows.append({"sec_id": key[0], "delist_date": key[1], "ticker": ev_by_key[key].ticker,
                            "payout_per_share": value, "confidence": gated.confidences.get(key, "none"),
                            "source": gated.sources.get(key, "none"),
                            "accession": (pr.accession if pr and value is not None else None)})

    # 11. write
    counts = {
        "securities": write_table("securities", [s.row() for s in securities.values()] +
                                  [s.row() for s in added.values()], table_path(out_dir, "securities")),
        "ticker_history": write_table("ticker_history", th_rows, table_path(out_dir, "ticker_history")),
        "cusip_history": write_table("cusip_history", ch_rows, table_path(out_dir, "cusip_history")),
        "delistings": write_table("delistings", delisting_rows, table_path(out_dir, "delistings")),
        "payouts": write_table("payouts", payout_rows, table_path(out_dir, "payouts")),
        "review": write_table("review", review_rows, table_path(out_dir, "review")),
    }
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
