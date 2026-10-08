"""What a filing says the registrant's own shares became (sub-plan 5c; spec 2026-10-03-diagnosis-truth-fixes, ruling
R1: a continuation is one new share per old share and no cash in the exchange). Pure: the statement reader.

An 8-K that reports a merger, a holding-company reorganization, a reclassification or a split-off states the
conversion: "each outstanding share of Baker Hughes common stock was converted into the right to receive one share
of BHGE's Class A common stock", "each share of SBG's Class A common stock ... was exchanged on a one-for-one basis
for an equivalent share of New Sinclair's Class A common stock", "the holders of outstanding shares of DIRECTV Group
common stock received one share of DIRECTV Class A common stock for each share". `statements` reads every such
statement of one filing; `own_exchange` keeps those about the security's own shares -- the subject's first party is
the registrant (an EDGAR name it carried before the event, a defined term that stands for one, "Old"/"Legacy" before
it, "the Company", "its", "our") and the class is the security's -- and says what they became: the ratio, whether
cash was paid in the exchange (par values, cash in lieu of fractional shares and a special dividend are not
consideration: operator ruling 2026-10-04), the target clause, the names it carries and the class letter it names. A
distribution (the holders kept their shares: a record date, "for every four shares") is no exchange. What a statement
means for its holders is its own: one for one (R1's shape, `one_share_no_cash`), a split factor (`split_factor`),
a changed stake (rule 6).

Two other roles a registrant can have in such a filing, for the end-of-era resolver's rule 1: `acquires` (another
party's shares became the registrant's -- Mirant into RRI Energy, Catalyst into SXC -- or the registrant issued its
shares to the other party under the merger agreement: Forest Oil to Sabine) and `distributes` (its holders received
another company's shares and kept theirs: News Corp's 2013 separation). Which texts, names and class one ending's
statement is read in and against is `own_shares`' choice (the own-share reading).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .identifiers import CLASS_MODIFIERS, prose_class_letters

_QUOTES = str.maketrans({"“": '"', "”": '"', "’": "'", "‘": "'", " ": " "})
_NUMBER_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}
# "one (1) share", "one-tenth (0.1) of a share": the number in parentheses is the reading
_WORD_NUMBER = re.compile(r"\b(?:one|two|three|four|five|one-(?:half|third|quarter|tenth))\s*\((\d*\.?\d+)\)", re.I)
_SAME_NUMBER = re.compile(r"^(?:an?\s+(?:equal|like|equivalent|identical)\s+number\s+of|the\s+same\s+number\s+of"
                          r"|an?\s+equivalent|an?)$", re.I)
_ENUMERATOR = re.compile(r"\(\s*(?:[ivx]{1,4}|\d{1,2}|[a-h])\s*\)")       # "(i)", "(ii)", "(1)", "(a)"
_SENTENCE_END = re.compile(r"(?<!\bInc)(?<!\bCorp)(?<!\bCo)(?<!\bLtd)(?<!\bNo)(?<!\bU\.S)(?<!\bN\.V)(?<!\bS\.A)"
                           r"(?<!\bL\.P)(?<!\bplc)(?<!\bMr)(?<!\bMs)(?<!\bJr)[.;]\s+(?=[A-Z•\"])|\s•\s|\x00")
# a legal suffix's period ends the sentence when a sentence starter follows ("... of Newco plc. Holders of ...")
_SUFFIX_END = re.compile(r"\b(Inc|Corp|Co|Ltd|plc|N\.V|S\.A|L\.P)\.\s+(?=(?:Each|The|Holders?|At|In|On|Upon|Pursuant|As|"
                         r"Following|Immediately|Prior|After|Item|All|Any|This|These|It|Its|Under|Such|Subject|For|"
                         r"Effective|Also|Additionally|Except|When|If|Thereafter|Then|Parent|Newco|Holdco)\b)")
_BREAK = "\x00"
_PAREN = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
_DEFINED = re.compile(r'\(\s*(?:the\s+|each,?\s+an?\s+)?"\s*([^"()]{1,40}?)\s*"\s*(?:,[^()]{0,40})?\)')
# 'Howard Hughes Holdings Inc., a Delaware corporation and direct wholly owned subsidiary of the Company ("Holdco")':
# the appositive between a name and its defined term
_APPOSITIVE = re.compile(r",\s+an?\s+(?:(?:newly[- ]formed|direct|indirect|wholly[- ]owned|[A-Z][a-z]+)\s+){0,4}"
                         r"(?:corporation|company|limited\s+liability\s+company|public\s+limited|subsidiary|entity|"
                         r"holding)", re.I)
_QTY = (r"(?P<qty>one|two|three|1(?:\.0+)?|\d*\.\d+|\d+|an?\s+(?:equal|like|equivalent|identical)\s+number\s+of"
        r"|the\s+same\s+number\s+of|an?\s+equivalent|an?)")
_SHARE = (r"(?:\s+of\s+an?)?(?:\s+(?:validly[- ]issued|fully[- ]paid|non-?assessable|newly[- ]issued|new|and|,))*"
          r"\s*(?:(?:common|ordinary)\s+)?(?:shares?|ADSs?|American\s+Depositary\s+Shares?)\b")
# the consideration: "into one share", "for an equivalent share", "received 1.11130 shares", "receiving one share"
_CONSIDERATION = re.compile(r"\b(?P<lead>into|for|receiv(?:e|ed|es|ing))\s+(?:the\s+right\s+to\s+receive\s+)?"
                            + _QTY + _SHARE, re.I)
_BASIS = re.compile(r"on\s+a\s+one[- ](?:for|to)[- ]one\s+basis|share[- ]for[- ]share", re.I)
_VERB = re.compile(r"convert|exchang|reclassif|redeem|redemption|receiv", re.I)
_FOR_EACH = re.compile(r"\bfor\s+each\s+(?:outstanding\s+|issued\s+and\s+outstanding\s+)?(?:share|shares)\s+of\s+",
                       re.I)
_FOR_EVERY = re.compile(r"\bfor\s+every\s+\w+\s+shares?\s+of\s+(?P<subj>[^;.]{0,160})", re.I)
_DISTRIBUTION = re.compile(r"\bRecord\s+Date\b|\bholders?\s+of\s+record\b|\bof\s+record\s+(?:as\s+of|on|at)\b"
                           r"|\b(?:the\s+)?Distribution\b|\bdistributed\b|\bpro\s+rata\b|\bfor\s+every\b")
# a statement with a conversion verb is an exchange: "holders of record" and "distributed" (the paying agent) do not
# make it a distribution
_STRONG_VERB = re.compile(r"convert|exchang|reclassif|redeem|redemption", re.I)
_DISTRIBUTION_STRONG = re.compile(r"\bRecord\s+Date\b|\b(?:the\s+)?Distribution\b|\bpro\s+rata\b|\bfor\s+every\b")
_SHARES_OF = re.compile(r"\b(?:shares?|stock)\s+of\s+", re.I)
_EACH = re.compile(r"\beach\s+", re.I)
# a subject that is not the class's public shares: an award, another security, a merger subsidiary's shares, the
# shares an insider rolled over (Continental Resources 2022: "the Rollover Shares owned by the Hamm Family")
_NOT_SHARES = re.compile(r"\b(?:options?|restricted|awards?|warrants?|preferred|RSUs?|units?|debentures?|notes?|"
                         r"convertible|rights?|exchangeable|Merger\s+Sub\w*|Purchaser|Rollover)\b", re.I)
# a cash consideration: "converted into the right to receive $74.28 in cash"
# or the defined price ("the Per Share Merger Consideration", "the Offer Price"), "cash in an amount equal to $", "cash
# consideration of $"
_CASH_CONSIDERATION = re.compile(r"\b(?:into|for)\s+(?:the\s+right\s+to\s+receive\s+)?(?:(?:an\s+amount\s+(?:in\s+cash\s+)?"
                                 r"equal\s+to\s+|cash\s+(?:in\s+an\s+amount\s+equal\s+to|consideration\s+of)\s+)?"
                                 r"(?:US)?\$\s?\d[\d.,]*|the\s+(?:Per\s+Share\s+)?(?:Merger|Offer)\s+"
                                 r"(?:Consideration|Price)\b)", re.I)
_PAR = re.compile(r"(?:,\s*)?(?:with(?:out)?\s+)?(?:no\s+)?(?:a\s+)?(?:par|nominal)\s+value(?:\s+of)?"
                  r"(?:\s+(?:US)?\$\s?[\d.,]+(?:\s+\d/\d)?)?(?:\s+per\s+share)?"
                  r"|(?:US)?\$\s?[\d.,]+\s+(?:par|nominal)\s+value(?:\s+per\s+share)?", re.I)
_LIEU = re.compile(r"(?:with\s+|and\s+|plus\s+)?(?:any\s+)?cash\s+(?:being\s+)?(?:paid\s+|payment\s+|payable\s+)?"
                   r"(?:to\s+[^;]{0,60}?)?in\s+lieu\s+of\s+(?:any\s+|issuing\s+)?fraction\w*(?:\s+(?:of\s+a\s+)?shares?)?"
                   r"|in\s+lieu\s+of\s+(?:any\s+)?fraction\w*(?:\s+shares?)?", re.I)
# "and a special one-time cash dividend of $17.50": a dividend, never consideration (operator ruling 2026-10-04)
_DIVIDEND_LEG = re.compile(r"(?:,?\s*(?:and|plus)\s+)?(?:an?|the)\s+(?:one-time\s+)?special\s+(?:one-time\s+)?"
                           r"(?:cash\s+)?dividend"
                           r"(?:\s+(?:of|in\s+the\s+amount\s+of|equal\s+to))?\s+(?:US)?\$\s?[\d.,]+(?:\s+per\s+share)?",
                           re.I)
_CASH = re.compile(r"\$\s?\d|\bin\s+cash\b|\bcash\s+(?:consideration|payment|amount)\b|\b(?:and|plus)\s+cash\b", re.I)
_CASH_FOR_SHARE = re.compile(r"\breceiv\w*\s+(?:cash\s+in\s+the\s+amount\s+of\s+)?(?:an\s+amount\s+in\s+cash\s+"
                             r"(?:equal\s+to\s+)?)?\$\s?[\d.,]+[^;]{0,80}?\bfor\s+each\s+share\s+of\s+"
                             r"(?P<subj>[^;]{0,120})", re.I)
_SPECIAL_DIVIDEND = re.compile(r"special\s+(?:one-time\s+)?(?:cash\s+)?dividend[^.;]{0,80}?\$\s?(\d[\d,]*(?:\.\d+)?)"
                               r"|\$\s?(\d[\d,]*(?:\.\d+)?)\s+per\s+share[^.;]{0,40}?special\s+(?:one-time\s+)?"
                               r"(?:cash\s+)?dividend", re.I)
# Forest Oil 2014: "the Company issued an aggregate of 79,241,916 Common Shares ... to Sabine Investor Holdings ...
# pursuant to the Amended Merger Agreement"
_ISSUED = re.compile(r"\bthe\s+Company\s+issued\s+(?:an\s+aggregate\s+of\s+)?[\d,]+\s+(?:\w+\s+){0,3}shares\b[^.;]{0,240}?"
                     r"\b(?:Merger|Combination|Contribution|Exchange)\s+Agreement\b", re.I)
_TOP_UP = re.compile(r"\bTop-?\s?Up\b", re.I)
# a second leg after the first: "and 0.25 of a share of Series A Liberty Live common stock", "and one contingent value
# right", "and one-half of one warrant"
_EXTRA_LEG = re.compile(r"\b(?:and|plus)\s+(?:an?|one|two|three|\d[\d.,]*|one-(?:half|third|quarter|tenth))\s+"
                        r"(?:of\s+(?:an?\s+|one\s+)?)?(?:[\w-]+\s+){0,3}?(?:shares?|warrants?|rights?|units?|CVRs?)\b",
                        re.I)
# A target clause ends where the sentence goes on to something else
_TARGET_END = re.compile(r",?\s+(?:having|effective|which|that|with|subject|pursuant|and|plus|as|in\s+accordance)\b|;",
                         re.I)
_CAP_RUN = re.compile(r"[A-Z][A-Za-z0-9&'.-]*(?:\s+(?:of\s+|&\s+)?[A-Z][A-Za-z0-9&'.-]*)*")
_CLASS_WORDS = {"CLASS", "SERIES", "COMMON", "STOCK", "SHARE", "SHARES", "ORDINARY", "PREFERRED", "VOTING",
                "NON-VOTING", "CAPITAL", "SPECIAL", "ADS", "ADSS", "AMERICAN", "DEPOSITARY", "EFFECTIVE", "TIME",
                "UNITS", "UNIT"}
_NOT_PARTIES = {"THE", "THE COMPANY", "COMPANY", "EACH", "UPON", "AT", "PURSUANT", "IN", "AS", "ON", "ALL", "ANY",
                "MERGER", "EFFECTIVE TIME", "CLOSING"}
_NEW_TERM = re.compile(r"^(?:New|Holdco|Parent|Successor)\b")
_OLD_TERM = re.compile(r"^(?:Old|Legacy|Former|Predecessor)\s+")
_OWN_PRONOUN = re.compile(r"\b(?:the\s+Company|Company's|our|its|we)\b", re.I)
_OWN_SKIP = {"THE", "NEW", "OLD", "INC", "CORP", "CO", "COMPANY", "HOLDINGS", "GROUP", "LTD", "PLC", "NV", "LLC",
             "SA", "AG", "SE", "LP", "TRUST", "INTERNATIONAL", "AMERICAN", "UNITED", "NATIONAL", "FIRST", "GENERAL",
             "ENERGY", "FINANCIAL", "CLASS", "COMMON", "SERIES", "STOCK"}


@dataclass(frozen=True)
class Statement:
    """One conversion statement of a filing: each share of `subject` became `ratio` shares of `target`, with cash
    or not; `distribution` when its holders kept their shares (a record date, "for every", "the Distribution")."""
    ratio: float
    cash: bool
    subject: str
    target: str
    sentence: str
    subject_letters: frozenset[str] = frozenset()
    target_letter: str = ""
    distribution: bool = False


@dataclass(frozen=True)
class OwnExchange:
    """What the security's own shares became (module docstring): `ratio` shares per share, cash in the exchange or
    not, the target clause, the names it carries (defined terms expanded: "Holdco" is "Howard Hughes Holdings
    Inc."), the class letter it names (the security's own for "the corresponding series"), whether it names the
    registrant itself (a reclassification into another class of the same issuer), the sentence, whether several
    own-share statements disagree (`ambiguous`) and the special dividends the filings name (never consideration)."""
    ratio: float
    cash: bool
    target: str
    target_names: tuple[str, ...]
    target_letter: str
    target_own: bool
    sentence: str
    ambiguous: bool = False
    special_dividends: tuple[float, ...] = ()
    extra_leg: bool = False

    @property
    def one_for_one(self) -> bool:
        """One share per share, no cash, one reading, and no second leg of shares, rights, warrants, units or CVRs
        (R1: only one security comes back)."""
        return one_share_no_cash(self.ratio, self.cash) and not self.ambiguous and not self.extra_leg

    @property
    def split(self) -> bool:
        """The ratio is a split factor (`split_factor`): the holders keep their stake in more or fewer shares."""
        return split_factor(self.ratio)

    @property
    def stake_changed(self) -> bool:
        """One reading whose holders got another ratio than one or a split factor, or cash: a merger, whatever
        registers the successor (spec 5c rule 6, sub-plan 5f: CHTR 2016's 0.9042 New Charter; SIRI 2024's 0.1 New
        Sirius is a consolidation)."""
        return not self.ambiguous and (self.cash or not self.split)


SPLIT_FACTOR_MAX = 100     # a split or consolidation factor n (or 1/n) is a whole number up to this


def one_share_no_cash(ratio: float | None, cash) -> bool:
    """R1's shape: one share per share and no cash (`cash` a flag or an amount; a ratio within 1e-9 of one)."""
    return ratio is not None and abs(ratio - 1.0) <= 1e-9 and not cash


def split_factor(ratio: float) -> bool:
    """Whether `ratio` shares per share is a split or a consolidation: n or 1/n for a whole n up to
    SPLIT_FACTOR_MAX, 1 included. The holders keep their stake (rule 6's guard, SIRI 2024's 0.1; stage 9g's ratio
    doubt, `continuation_evidence.ratio_doubt`)."""
    if ratio <= 0:
        return False
    n = ratio if ratio >= 1 else 1 / ratio
    return round(n) <= SPLIT_FACTOR_MAX and abs(n - round(n)) < 1e-6


def normalize(text: str) -> str:
    """One line, straight quotes, "one (1)" as "1" and "one-tenth (0.1)" as "0.1"."""
    t = re.sub(r"\s+", " ", (text or "").translate(_QUOTES))
    return _WORD_NUMBER.sub(r"\1", t)


def defined_terms(text: str) -> dict[str, str]:
    """A filing's defined terms and the names they stand for: 'Howard Hughes Holdings Inc., a Delaware corporation
    ... ("Holdco")' gives {"Holdco": "Howard Hughes Holdings Inc."}; the name is the run of capitalized words right
    before the parenthesis (or before its appositive), with a legal suffix after a comma ("Sinclair Broadcast
    Group, Inc.")."""
    out: dict[str, str] = {}
    t = normalize(text)
    for m in _DEFINED.finditer(t):
        alias = m.group(1).strip()
        before = t[max(0, m.start() - 200):m.start()].rstrip(" ,")
        appositive = list(_APPOSITIVE.finditer(before))
        if appositive:
            before = before[:appositive[-1].start()].rstrip(" ,")
        runs = list(_CAP_RUN.finditer(before))
        if not runs or runs[-1].end() < len(before) - 2:
            continue
        name = runs[-1].group(0).strip()
        if len(runs) > 1 and re.fullmatch(r"(?:Inc|Corp|Co|Ltd|LLC|L\.P|N\.V|plc|S\.A)\.?", name):
            name = before[runs[-2].start():].strip()
        if name and alias.upper() != "COMPANY" and name != alias:
            out.setdefault(alias, name)
    return out


def _qty(s: str) -> float | None:
    s = s.strip().lower()
    if s in _NUMBER_WORDS:
        return _NUMBER_WORDS[s]
    if _SAME_NUMBER.match(s):
        return 1.0
    try:
        return float(s)
    except ValueError:
        return None


def _clauses(text: str) -> list[tuple[str, str]]:
    """(clause, its sentence) for every clause of a normalized text: sentences split at their ends, then at their
    enumerators ("(i)", "(2)")."""
    text = _SUFFIX_END.sub(lambda m: m.group(1) + "." + _BREAK, text)
    return [(c, s) for s in _SENTENCE_END.split(text) for c in _ENUMERATOR.split(s) if c.strip()]


def _subject_phrase(before: str) -> str:
    """The subject phrase: what follows the last "shares of"/"stock of" before the consideration ("each share of the
    Company's Class A common stock ..."), else what follows the last "each" ("each Mylan Share issued ...")."""
    hits = list(_SHARES_OF.finditer(before))
    if hits:
        return before[hits[-1].end():]
    hits = list(_EACH.finditer(before))
    return before[hits[-1].end():] if hits else before[-200:]


def _distribution(sentence: str, verb_context: str) -> bool:
    """Whether the holders kept their shares: a record date, "for every", "the Distribution"; "holders of record" or
    "distributed" alone do not make it one when a conversion verb states the statement."""
    return bool((_DISTRIBUTION_STRONG if _STRONG_VERB.search(verb_context) else _DISTRIBUTION).search(sentence))


def statements(text: str) -> list[Statement]:
    """Every conversion statement of one filing's text (module docstring), parentheticals set aside."""
    out: list[Statement] = []
    for clause, sentence in _clauses(normalize(text)):
        bare = re.sub(r"\s+", " ", _PAREN.sub(" ", clause))
        shares = list(_CONSIDERATION.finditer(bare))
        cash_only = [c for c in _CASH_CONSIDERATION.finditer(bare)
                     if not any(s.start() <= c.start() < s.end() for s in shares)]
        matches = sorted(shares + cash_only, key=lambda m: m.start())
        prev = 0
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(bare)
            rest, before, prev = bare[m.end():end], bare[prev:m.start()], m.end()
            if m.re is _CASH_CONSIDERATION:          # "converted into the right to receive $74.28 in cash"
                if _VERB.search(before[-160:]):
                    subject = _subject_phrase(before)
                    out.append(Statement(0.0, True, subject.strip(" ,"), "", sentence,
                                         frozenset(prose_class_letters(subject)), "",
                                         _distribution(sentence, before[-160:])))
                continue
            ratio = _qty(m.group("qty"))
            if ratio is None:
                continue
            each = _FOR_EACH.search(rest)
            if m.group("lead").lower().startswith("receiv") and each is not None:
                subject, target = rest[each.end():][:160], rest[:each.start()]   # "received N of T for each of S"
            else:
                subject, target = _subject_phrase(before), rest
            if not _VERB.search(before[-160:] + " " + m.group("lead")):
                continue
            consideration = _DIVIDEND_LEG.sub(" ", _LIEU.sub(" ", _PAR.sub(" ", m.group(0) + target)))
            letters = prose_class_letters(target)
            out.append(Statement(ratio, bool(_CASH.search(consideration)), subject.strip(" ,"), target.strip(" ,"),
                                 sentence, frozenset(prose_class_letters(subject)), letters[0] if letters else "",
                                 _distribution(sentence, before[-160:] + " " + m.group("lead"))))
    return out


def own_words(names: Iterable[str]) -> set[str]:
    """The words that name the registrant: each name's first word that is not a filler or a legal suffix (two
    letters or more: "SXC", "BJ"), and its first two such words joined ("LIONS GATE" is LIONSGATE). A later word
    of the name ("HEALTH" in "SXC Health Solutions") is too common to name it."""
    words: set[str] = set()
    for n in names:
        toks = [w for w in re.findall(r"[A-Z0-9][A-Z0-9&'-]*", (n or "").upper().replace("'S", "").replace(".", ""))
                if w not in _OWN_SKIP]
        if toks and len(toks[0]) >= 2:
            words.add(toks[0])
        if len(toks) >= 2:
            words.add(toks[0] + toks[1])
    return words


def _names_own(phrase: str, own: set[str]) -> bool:
    """A phrase names the registrant: one of its words, possessive or plural ("Walgreens", "SBG's"), not after "New"
    ("New Lionsgate" is another company than "Old Lionsgate")."""
    up = phrase.upper()
    for w in own:
        for m in re.finditer(rf"(?<![A-Z0-9]){re.escape(w)}(?:S|'S)?(?![A-Z0-9])", up):
            if not re.search(r"\bNEW\s+$", up[max(0, m.start() - 6):m.start()]):
                return True
    return False


def parties(phrase: str) -> list[str]:
    """The capitalized names a phrase carries, class words dropped ("BHGE's Class A common stock" -> ["BHGE"])."""
    out = []
    for m in _CAP_RUN.finditer(phrase):
        words = [w for w in m.group(0).replace("'s", "").split()
                 if w.upper().strip(".,") not in _CLASS_WORDS and not re.fullmatch(r"[A-Z]-?\d?", w)]
        name = " ".join(words).strip(" ,.")
        if name and name.upper() not in _NOT_PARTIES:
            out.append(name)
    return out


def _first_party_own(head: str, own: set[str]) -> bool | None:
    """Whose shares a subject is: True for the registrant ("the Company's", "its", one of its words, "Old"/"Legacy"
    before one), False when its first named party is another ("Liberty Media's ... Liberty SiriusXM common stock"),
    None when it names nobody."""
    names = parties(head)
    pronoun = _OWN_PRONOUN.search(head)
    if not names:
        return True if pronoun else None
    first = re.sub(r"^(?:Old|Legacy|Former|Predecessor)\s+", "", names[0])
    if pronoun and pronoun.start() < head.find(names[0]):
        return True
    return _names_own(first, own)


def _class_ok(st: Statement, letter: str | None, class_words: Sequence[str]) -> bool:
    """The subject is the security's class: no letter, or the security's (`letter` None: any class); and it names
    each word that sets the security's class apart ("Class A Special"), and none the security lacks."""
    if letter is None:
        return True
    if letter and st.subject_letters and letter not in st.subject_letters:
        return False
    if not letter and len(st.subject_letters) == 1:
        return False
    head = st.subject[:120].upper()
    mods = {w.upper() for w in class_words}
    return all((w in head) == (w in mods) for w in CLASS_MODIFIERS)


def _terms_and_own(texts: Sequence[str], names: Sequence[str]) -> tuple[dict[str, str], set[str]]:
    terms: dict[str, str] = {}
    for t in texts:
        for k, v in defined_terms(t).items():
            terms.setdefault(k, v)
    own = own_words(names)
    # a defined term that stands for the registrant ("SBG", "Old CCOH": also without its "Old")
    aliases = [k for k, v in terms.items() if _names_own(v, own) and not _NEW_TERM.match(k)]
    own |= {k.upper() for k in aliases} | {_OLD_TERM.sub("", k).upper() for k in aliases}
    return terms, own


def own_statements(texts: Iterable[str], *, names: Sequence[str], class_letter: str | None = "",
                   class_words: Sequence[str] = ()) -> list[Statement]:
    """The exchange statements of `texts` (not distributions) about the security's own shares (module docstring)."""
    texts = [normalize(t) for t in texts if t]
    _, own = _terms_and_own(texts, names)
    out = []
    for t in texts:
        for st in statements(t):
            head = st.subject[:120]
            if st.distribution or _NOT_SHARES.search(head):
                continue
            if _first_party_own(head, own) is not False and _class_ok(st, class_letter, class_words):
                if _first_party_own(head, own) is None and not _OWN_PRONOUN.search(st.sentence) \
                        and not _names_own(st.sentence, own):
                    continue
                out.append(st)
    return out


def _cash_for_class(texts: Iterable[str], own: set[str], letter: str | None) -> bool:
    """A filing pays cash for each share of the security's class ("each holder of the Company's Class A common
    stock is entitled to receive cash in the amount of $28.00 for each share of Class A Common Stock held")."""
    for t in texts:
        for m in _CASH_FOR_SHARE.finditer(t):
            subj = re.split(r"\s+(?:held|and|or)\b|[,;(]", m.group("subj"), maxsplit=1)[0]
            letters = set(prose_class_letters(subj))
            if letter and letters and letter not in letters:
                continue
            if not letter and letters:
                continue
            if _first_party_own(subj, own) is not False:
                return True
    return False


def own_exchange(texts: Iterable[str], *, names: Sequence[str], class_letter: str | None = "",
                 class_words: Sequence[str] = ()) -> OwnExchange | None:
    """What the security's own shares became (module docstring): `names` the registrant's names before the event
    (`own_shares.registrant_names`), `class_letter` its class letter ("" for a plain common, None for any class),
    `class_words` the words that set its class apart (`identifiers.class_of`). None when no filing states it."""
    texts = [normalize(t) for t in texts if t]
    found = own_statements(texts, names=names, class_letter=class_letter, class_words=class_words)
    if not found:
        return None
    terms, own = _terms_and_own(texts, names)
    st = found[0]
    named = _PAR.sub(" ", st.target)
    cut = _TARGET_END.search(named)
    named = named[:cut.start()] if cut else named
    target_names: list[str] = []
    for p in parties(named):
        target_names.append(p)
        target_names += [v for k, v in terms.items() if k.upper() == p.upper() or k.upper() in p.upper().split()]
    letters = prose_class_letters(named)
    letter = letters[0] if letters else (class_letter or "" if re.search(
        r"corresponding\s+(?:series|class)", st.target, re.I) else "")
    rest = _PAR.sub(" ", st.target)[cut.start():] if cut else ""
    extra = bool(_EXTRA_LEG.search(rest))
    target_own = bool(_OWN_PRONOUN.search(named)) or not parties(named)
    dividends = sorted({float((m.group(1) or m.group(2)).replace(",", ""))
                        for t in texts for m in _SPECIAL_DIVIDEND.finditer(t)})
    return OwnExchange(st.ratio, st.cash or _cash_for_class(texts, own, class_letter), st.target,
                       tuple(dict.fromkeys(target_names)), letter, target_own, st.sentence,
                       len({(s.ratio, s.cash) for s in found}) > 1, tuple(dividends), extra)


def acquires(texts: Iterable[str], *, names: Sequence[str]) -> str:
    """The sentence in which another party's shares became the registrant's ("each outstanding share of common stock
    of Mirant was converted into the right to receive 2.835 ... shares of our common stock") or the registrant
    issued its shares to the other party under the merger agreement (Forest Oil 2014), else ""."""
    texts = [normalize(t) for t in texts if t]
    _, own = _terms_and_own(texts, names)
    for t in texts:
        for st in statements(t):
            head = st.subject[:120]
            if st.distribution or _NOT_SHARES.search(head) or _first_party_own(head, own) is not False:
                continue
            target = st.target[:160]
            cut = _TARGET_END.search(target)
            target = target[:cut.start()] if cut else target
            if re.search(r"\b(?:our|its)\b|\bthe\s+Company\b", target) or (
                    _names_own(target, own) and not re.search(r"\bNew\s", target)):
                return st.sentence[:300]
        for m in _ISSUED.finditer(t):
            if not _TOP_UP.search(m.group(0)):      # the top-up option's shares are the offer's, not a merger issue
                return t[m.start():m.end()][:300]
    return ""


def distributes(texts: Iterable[str], *, names: Sequence[str]) -> str:
    """The sentence in which the registrant's holders received another company's shares and kept their own ("one
    share of News Corp Class A common stock for every four shares of the Company's Class A common stock held"),
    else ""."""
    texts = [normalize(t) for t in texts if t]
    _, own = _terms_and_own(texts, names)
    for t in texts:
        for m in _FOR_EVERY.finditer(t):
            subj = m.group("subj")[:120]
            if _first_party_own(subj, own):
                return t[max(0, m.start() - 200):m.end()][:300]
    return ""
