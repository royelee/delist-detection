"""The ticker of a stock leg the LLM names by a defined term and gives no ticker for (sub-plan 5f fix: SHAW 2013's
"CB&I", HBI 2025's "Gildan", CLP 2013's "MAA", PARA 2025's "Paramount Skydance Corporation").

A stock leg whose acquirer has no ticker loses its price (`terms_gate_failed:no_acq_ticker`), though the filing names
the company in full. The ticker is found, in order, by

1. the name: the acquirer name the answer gives, expanded through the filing's own defined terms
   (`exchange_terms.defined_terms`: "CB&I" is "Chicago Bridge & Iron Company N.V."); a name of one word the filing
   does not define ("Orange") is no name to search by;
2. the issuer: SEC's name index (`cik_lookup.CikNameIndex`) lists the companies whose names start with it, and the
   one whose EDGAR names (current and former) agree with it, that had filed by the last trade day and is not the
   target, is the issuer (none or several tie: no answer);
3. its ticker: the tickers its EDGAR record lists (`submissions`), else (a company that has since gone: CBI) the
   symbol the fails-to-deliver rows of the price date name it under (`symbol_in_rows`).

Pure apart from the callables it is given; every read goes through the run's own clients, a failed one is the
caller's `DegradedWatch`, never an answer."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import date

from .acquirer_line import _shared_words, _words, issuer_fits
from .evidence import edgar_names
from .exchange_terms import defined_terms
from .ftd import FtdRow, is_trading_symbol
from .identifiers import normalize_ticker
from .names import description_names, names_agree

MAX_HITS = 12      # index matches per query whose submissions are read: a longer list names no one company
_LEGAL = re.compile(r"[\s,.]+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|l\.?p|n\.?v|s\.?a|"
                    r"ag|se|holdings?|group)\.?$", re.I)


def clean(name: str) -> str:
    """A defined term's name without the stray parenthesis or comma its sentence leaves on it."""
    return re.sub(r"\s+", " ", (name or "").replace("(", " ").replace(")", " ")).strip(" ,;")


def names_to_search(name: str, text: str) -> list[str]:
    """The acquirer's names to look up: its defined term's full name, then the name as the answer gives it when it
    has two words or more (one word is a name any company shares: "Orange" is France's, not Coca-Cola's) or the
    filing defined it."""
    full = clean(defined_terms(text).get(name.strip(), "")) if text and name else ""
    given = clean(name)
    out = [full] if full else []
    if given and (full or len(given.split()) >= 2) and given not in out:
        out.append(given)
    return out


def queries(names: Iterable[str]) -> list[str]:
    """Each name, then the name without its trailing legal words ("Chicago Bridge & Iron Company N.V." finds
    "CHICAGO BRIDGE & IRON CO N V" by "Chicago Bridge & Iron"), the longest first."""
    out: list[str] = []
    for name in names:
        q = clean(name)
        while q and q not in out:
            out.append(q)
            q = _LEGAL.sub("", q).strip(" ,.")
    return out


def _closeness(name: str, edgar: str) -> tuple[int, int]:
    """How near an EDGAR name is to the name looked up: the words of `name` it shares, then (negated) the words of
    its own that `name` lacks ("CHICAGO BRIDGE & IRON CO (DELAWARE)" is farther from "Chicago Bridge & Iron
    Company N.V." than "CHICAGO BRIDGE & IRON CO N V")."""
    shared = _shared_words(name, edgar)
    return shared, -(len(_words(edgar)) - _shared_words(edgar, name))


def issuer_cik(index, subs: Callable[[int], object], first_filed: Callable[[int], date | None],
               names: Sequence[str], last: date, *, target_cik: int | None) -> tuple[int, tuple[str, ...]] | None:
    """The one issuer SEC's name index lists under `names` (`queries`) that is not the target, had filed by `last` and
    whose EDGAR names agree with a name, with those EDGAR names; the exact-name matches of a query first, then its
    prefix matches (never more than MAX_HITS companies; only entries whose index name agrees with a name have their
    submissions read). The issuer whose name is nearest (`_closeness`) wins; a tie is no answer."""
    scored: dict[int, tuple[tuple[int, int], tuple[str, ...]]] = {}
    for q in queries(names):
        exact, prefix = index.split_search(q)
        for hits in (exact, prefix):
            ciks = list(dict.fromkeys(h.cik for h in hits if any(names_agree(n, h.name) for n in names)))
            if not ciks or len(ciks) > MAX_HITS:
                continue
            for cik in ciks:
                if cik == target_cik or cik in scored:
                    continue
                if not any(issuer_fits(subs, first_filed, cik, n, last) for n in names):
                    continue
                sub = subs(cik)
                own = edgar_names(sub) if isinstance(sub, dict) else ()
                scored[cik] = (max((_closeness(n, e) for n in names for e in own if names_agree(n, e)),
                                   default=(0, 0)), own)
            if scored:
                break
        if scored:
            break
    if not scored:
        return None
    best = sorted(scored.items(), key=lambda kv: kv[1][0], reverse=True)
    if len(best) > 1 and best[1][1][0] == best[0][1][0]:
        return None
    return best[0][0], best[0][1][1]


def listed_ticker(sub: object) -> str:
    """The first ticker EDGAR lists for the issuer today, "" for none."""
    tickers = sub.get("tickers") if isinstance(sub, dict) else None
    return normalize_ticker(tickers[0]) if tickers else ""


def symbol_in_rows(rows: Iterable[FtdRow], names: Sequence[str]) -> str:
    """The trading symbol most of the rows whose description names one of `names` carry ("" for none): a company
    EDGAR no longer lists is still in the fails files under its symbol (CBI)."""
    seen = Counter(r.symbol for r in rows if is_trading_symbol(r.symbol)
                   and any(description_names(r.description, n) for n in names))
    return seen.most_common(1)[0][0] if seen else ""


def acquirer_ticker(name: str, text: str, *, index, subs: Callable[[int], object],
                    first_filed: Callable[[int], date | None], rows: Callable[[], Iterable[FtdRow]],
                    last: date, target_cik: int | None) -> str:
    """The ticker of the stock leg's acquirer, "" when none can be named (see the module docstring). `rows` is read
    only when EDGAR lists no ticker for the issuer."""
    names = names_to_search(name, text)
    if not names or index is None:
        return ""
    got = issuer_cik(index, subs, first_filed, names, last, target_cik=target_cik)
    if got is None:
        return ""
    cik, own = got
    return listed_ticker(subs(cik)) or normalize_ticker(symbol_in_rows(rows(), [*own, *names]) or "")
