from delist_detection.classifier import DelistRecord
from delist_detection.crsp_codes import CrspBucket
from delist_detection.payout_extractor import PayoutExtractor, PayoutResult


class _StubEdgar:
    """Serves no filings and no text — used to test short-circuits."""
    def recent_filings(self, cik):
        return []
    def fetch_filing_text(self, cik, accession, primary_doc):
        return ""


def _rec(bucket, cik=111):
    return DelistRecord(
        ticker="X", cik=cik, observed_delist_date="2024-01-15",
        crsp_code=231, bucket=bucket, confidence="high", reason="", evidence={},
    )


def test_non_merger_returns_none():
    ext = PayoutExtractor(_StubEdgar())
    res = ext.extract(_rec(CrspBucket.COMPLIANCE_FAILURE))
    assert res == PayoutResult(None, "none", "none", "", "")


def test_merger_no_cik_returns_none():
    ext = PayoutExtractor(_StubEdgar())
    res = ext.extract(_rec(CrspBucket.MERGER, cik=None))
    assert res.value is None
    assert res.confidence == "none"


from delist_detection.payout_extractor import _match_payout, _passes_sanity


def test_match_in_cash_family_altr():
    text = ("each share ... were converted into the right to receive "
            "$113.00 in cash, without interest (the Merger Consideration). "
            "amount in cash equal to $1,618.7928 ($113.00 multiplied by ...)")
    val, quote = _match_payout(text)
    assert val == 113.00
    assert "113.00" in quote


def test_match_in_cash_family_atvi():
    text = "was cancelled and automatically converted into the right to receive $95.00 in cash (the Merger Consideration)"
    val, _ = _match_payout(text)
    assert val == 95.00


def test_match_per_share_family():
    text = "holders received $42.50 per share in cash at closing"
    val, _ = _match_payout(text)
    assert val == 42.50


def test_match_four_decimal_trap_not_truncated():
    # $1,618.7928 must NOT be read as 1618.79; the only real per-share is 12.00
    text = "$1,618.7928 was the note payoff; shares received $12.00 in cash"
    val, _ = _match_payout(text)
    assert val == 12.00


def test_match_modal_value_wins():
    text = ("$113.00 in cash ... $113.00 in cash ... $113.00 in cash ... "
            "an alternate $112.00 in cash")
    val, _ = _match_payout(text)
    assert val == 113.00


def test_match_comma_thousands():
    text = "right to receive $1,250.00 in cash per share"
    val, _ = _match_payout(text)
    assert val == 1250.00


def test_no_match_returns_none():
    val, quote = _match_payout("this filing mentions no cash consideration")
    assert val is None and quote == ""


def test_match_skips_par_value_clause():
    # "par value $0.01 per share" must NOT be read as a $0.01 payout.
    text = ("Class A common stock, par value $0.01 per share, was converted "
            "into the right to receive $65.47 in cash")
    val, _ = _match_payout(text)
    assert val == 65.47


def test_match_par_value_only_returns_none():
    text = "common stock, par value $0.01 per share (no consideration stated)"
    val, quote = _match_payout(text)
    assert val is None and quote == ""


def test_match_amount_in_cash_equal_to_skx():
    # SKX / 3G Capital 2025 phrasing.
    text = ("Class A Common Stock, par value $0.001 per share, was converted into "
            "the right to receive (a) an amount in cash equal to $63.00, without "
            "interest thereon")
    val, _ = _match_payout(text)
    assert val == 63.00


def test_match_purchase_price_per_company_share_rcpt():
    # RCPT / Celgene 2015 tender-offer phrasing.
    text = ("the Company's common stock, par value $0.001 (the Common Stock), for a "
            "purchase price of $232.00 per Company Share, net to the seller in cash")
    val, _ = _match_payout(text)
    assert val == 232.00


def test_match_without_interest_anchor_ppd():
    text = "shall be converted into an amount in cash equal to $47.50, without interest and less applicable taxes"
    val, _ = _match_payout(text)
    assert val == 47.50


def test_match_skips_dividend_clause():
    # all-stock deal proxies mention cash dividends; not the payout.
    text = "the board declared a quarterly cash dividend of $0.50 per share of Civitas common stock"
    val, quote = _match_payout(text)
    assert val is None and quote == ""


def test_match_skips_special_dividend():
    text = "a special cash dividend of $2.00 per share of Mr. Cooper common stock"
    val, _ = _match_payout(text)
    assert val is None


def test_match_skips_rounding_boilerplate():
    text = "the exchange ratio (in all cases rounded to the nearest $0.25 per share) shall apply"
    val, _ = _match_payout(text)
    assert val is None


def test_match_skips_in_excess_of():
    text = "holders of a note in excess of $0.50 per share of the acquirer"
    val, _ = _match_payout(text)
    assert val is None


def test_bare_per_share_without_cash_rejected():
    # A "$X per share" with no 'cash' nearby (e.g. a DCF valuation table) is noise.
    text = "the discounted cash flow analysis implied a value of $648.00 per share for the company"
    val, _ = _match_payout(text)
    assert val != 648.00


def test_purchase_price_without_cash_rejected():
    text = "an enterprise value of $145.33 per share under the comparable companies method"
    val, _ = _match_payout(text)
    assert val != 145.33


def test_match_skips_convertible_note_redemption():
    # X / US Steel: note make-whole figure, not the $55 equity consideration.
    text = ("holders of the Convertible Notes will be entitled to receive $4,116.15 "
            "in cash per $1,000 principal amount of the Notes; each share was "
            "converted into the right to receive $55.00 in cash")
    val, _ = _match_payout(text)
    assert val == 55.00


def test_match_note_only_returns_none():
    text = "the make-whole amount is expected to be $1,017.62 in cash per $1,000 principal amount of the Notes"
    val, _ = _match_payout(text)
    assert val is None


def test_dividend_guard_does_not_block_real_payout():
    # A dividend mention elsewhere must not suppress the real consideration.
    text = ("paid a quarterly dividend of $0.50 per share last year; at closing each "
            "share was converted into the right to receive $84.00 in cash")
    val, _ = _match_payout(text)
    assert val == 84.00


# --- FIX 1: mixed cash+stock deals must NOT emit only the cash leg --------

def test_match_mixed_cash_stock_ann_returns_none():
    # ANN / Ascena: cash + fraction of a share of common stock → out of scope.
    text = ("the right to receive (i) $37.34 in cash and (ii) 0.68 of a share "
            "of common stock")
    val, quote = _match_payout(text)
    assert val is None and quote == ""


def test_match_mixed_cash_stock_cov_returns_none():
    # COV / Medtronic: cash + fraction of an ordinary share.
    text = ("the right to receive $35.19 in cash and 0.956 of a newly issued "
            "New Medtronic ordinary share")
    val, _ = _match_payout(text)
    assert val is None


def test_match_mixed_cash_stock_fdo_returns_none():
    # FDO / Dollar Tree: cash + shares of common stock.
    text = "$59.60 in cash and 0.2484 shares of Dollar Tree common stock"
    val, _ = _match_payout(text)
    assert val is None


def test_match_mixed_cash_stock_hnt_returns_none():
    # HNT / Centene: cash + fraction of one share.
    text = "$28.25 in cash and 0.622 of one share of Centene's common stock"
    val, _ = _match_payout(text)
    assert val is None


def test_match_mixed_stock_before_cash_af_returns_none():
    # AF / Astoria: equity co-consideration BEFORE the cash leg.
    text = "common stock plus $0.50 in cash for each share of Astoria"
    val, _ = _match_payout(text)
    assert val is None


def test_match_mixed_cash_plus_stock_omx_returns_none():
    # OMX / Office Depot: cash + one share via "plus".
    text = "$5.25 in cash plus one share of Office Depot common stock"
    val, _ = _match_payout(text)
    assert val is None


def test_match_pure_cash_with_trailing_and_altr():
    # ALTR: "and" followed by non-equity boilerplate → still pure cash.
    text = ("right to receive $113.00 in cash, without interest (the Merger "
            "Consideration). Pursuant to the Merger Agreement...")
    val, _ = _match_payout(text)
    assert val == 113.00


def test_match_pure_cash_and_terms_clause_lnkd():
    # LNKD: "and the terms of the merger agreement" is not an equity token.
    text = ("$196.00 per share in cash and the terms of the merger agreement "
            "offer the best value")
    val, _ = _match_payout(text)
    assert val == 196.00


def test_match_pure_cash_without_interest_skx_not_flagged_mixed():
    # SKX: "without interest thereon" must not count as co-consideration.
    text = "an amount in cash equal to $63.00, without interest thereon"
    val, _ = _match_payout(text)
    assert val == 63.00


# --- cash + contingent CVR: take the cash floor, do NOT treat as mixed -----

def test_match_cash_plus_cvr_takes_cash_floor_apls():
    # APLS: $41.00 cash tender + a contingent CVR capped at $4.00. The CVR is
    # not a stock leg, so the deal is not "mixed"; the real per-share cash floor
    # ($41.00) must win over the small CVR figure ($4.00).
    text = ("$41.00 per Share, net to the seller in cash, without interest, plus "
            "one contingent value right representing up to an aggregate of $4.00 "
            "in cash. $41.00 per Share in cash is payable at closing.")
    val, _ = _match_payout(text)
    assert val == 41.00


def test_match_preferred_class_not_flagged_mixed_tco():
    # TCO: common gets all-cash $43.00; a separate Series B Preferred class is
    # described in the next clause ("; and (ii) each share of ... Preferred
    # Stock"). That separate class has no share-ratio, so it must NOT mark the
    # all-cash common consideration as mixed.
    text = ("each share of common stock was converted into the right to receive "
            "$43.00 in cash (the Common Stock Merger Consideration); and (ii) each "
            "share of Series B Preferred Stock shall be treated as set forth")
    val, _ = _match_payout(text)
    assert val == 43.00


def test_match_mixed_deal_with_competing_cash_bid_abstains_pmcs():
    # PMCS: real deal is "$9.22 in cash and 0.0771 shares" (mixed, stated twice);
    # a competing all-cash bid ("$10.50 ... to $11.60 in cash") is mentioned once.
    # The repeated stock leg makes the whole deal mixed → abstain (not $11.60).
    text = ("for $9.22 in cash and 0.0771 of a share of common stock of Microsemi. "
            "The per PMC Share consideration of $9.22 in cash and 0.0771 shares of "
            "Microsemi common stock was set. A prior bid increased from $10.50 in "
            "cash to $11.60 in cash, without interest.")
    val, _ = _match_payout(text, allow_weak=False)
    assert val is None


def test_match_mixed_election_lettered_list_abstains_scs():
    # SCS: cash-or-stock election with a lettered list — "(a) 0.2192 shares of HNI
    # common stock ... and (b) $7.20 in cash" (stated twice). Mixed → abstain.
    text = ("(a) 0.2192 shares of HNI common stock, par value $1.00 per share "
            "(HNI Common Stock), and (b) $7.20 in cash; the mixed election is "
            "(a) 0.2192 shares of HNI common stock and (b) $7.20 in cash.")
    val, _ = _match_payout(text, allow_weak=False)
    assert val is None


def test_match_par_value_far_before_not_suppressed_aria():
    # ARIA: all-cash $24.00 tender. "par value" sits >30 chars before the real
    # $24.00 figure, so the par-value guard (30-char window) must not suppress it.
    text = ("shares of common stock, par value $0.001 per share, of the Company "
            "(the Shares) for $24.00 per Share, net to the seller in cash")
    val, _ = _match_payout(text)
    assert val == 24.00


# --- FIX 3: non-consideration cash phrases (fees / escrow) -----------------

def test_match_skips_termination_fee():
    text = "the Company shall pay a termination fee of $5.00 in cash"
    val, quote = _match_payout(text)
    assert val is None and quote == ""


def test_match_skips_escrow():
    text = "an escrow of $3.00 in cash shall be held by the agent"
    val, _ = _match_payout(text)
    assert val is None


# --- FIX 4: widen neg window so dividend phrasing is caught ----------------

def test_match_skips_dividend_in_the_amount_of():
    # 'dividend' sits well before the '$' — the original target phrasing.
    text = "the Company will pay a dividend in the amount of $0.50 per share"
    val, _ = _match_payout(text)
    assert val is None


def test_sanity_absolute_band():
    assert not _passes_sanity(0.001, None)
    assert not _passes_sanity(20000.0, None)
    assert _passes_sanity(113.0, None)


def test_sanity_relative_band():
    assert not _passes_sanity(2.0, last_close=100.0)      # < 5% of last close
    assert not _passes_sanity(2500.0, last_close=100.0)   # > 20x last close
    assert _passes_sanity(113.0, last_close=111.85)


from delist_detection.edgar import EdgarSubmission


class _FakeEdgarText:
    """recent_filings + fetch_filing_text keyed by accession."""
    def __init__(self, filings, texts):
        self._filings = filings
        self._texts = texts
    def recent_filings(self, cik):
        return list(self._filings)
    def fetch_filing_text(self, cik, accession, primary_doc):
        return self._texts.get(accession, "")


def _merger_rec():
    return DelistRecord(
        ticker="ALTR", cik=1701732, observed_delist_date="2025-03-26",
        crsp_code=231, bucket=CrspBucket.MERGER, confidence="high",
        reason="", evidence={},
    )


def test_tier1_closing_8k_high():
    filings = [EdgarSubmission(
        accession="C1", form="8-K", filing_date="2025-03-28",
        report_date="2025-03-26", items="2.01,5.01,3.01", primary_doc="d.htm")]
    texts = {"C1": "converted into the right to receive $113.00 in cash, without interest"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 113.00
    assert res.confidence == "high"
    assert res.source == "8K_2.01"
    assert res.accession == "C1"


def test_tier2_announcement_8k_medium():
    # No 2.01 filing; a 1.01 filing ~60d before delist carries the number.
    filings = [EdgarSubmission(
        accession="A1", form="8-K", filing_date="2025-01-26",
        report_date="2025-01-26", items="1.01,9.01", primary_doc="d.htm")]
    texts = {"A1": "agreed to acquire each share for $95.00 in cash"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 95.00
    assert res.confidence == "medium"
    assert res.source == "8K_1.01"


def test_tier3_defm14a_medium():
    filings = [EdgarSubmission(
        accession="D1", form="DEFM14A", filing_date="2025-02-01",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"D1": "right to receive $80.00 in cash for each share"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 80.00
    assert res.source == "DEFM14A"
    assert res.confidence == "medium"


def test_tier4_prem14a_low():
    filings = [EdgarSubmission(
        accession="P1", form="PREM14A", filing_date="2025-01-10",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"P1": "right to receive $80.00 in cash for each share"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.source == "PRE14A"
    assert res.confidence == "low"


def test_tier1_preferred_over_tier2():
    filings = [
        EdgarSubmission(accession="C1", form="8-K", filing_date="2025-03-28",
            report_date="2025-03-26", items="2.01,5.01", primary_doc="d.htm"),
        EdgarSubmission(accession="A1", form="8-K", filing_date="2025-01-26",
            report_date="2025-01-26", items="1.01", primary_doc="d.htm"),
    ]
    texts = {"C1": "right to receive $113.00 in cash",
             "A1": "for $999.00 in cash"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 113.00 and res.source == "8K_2.01"


def test_proxy_tier_ignores_weak_bare_per_share():
    # A DEFM14A whose only figure is a bare "$X per share ... in cash" (e.g. a
    # dividend or implied stock value) must NOT be trusted — weak patterns are
    # disabled for proxy tiers. No 8-K present, so the result is a miss.
    filings = [EdgarSubmission(
        accession="D1", form="DEFM14A", filing_date="2025-02-01",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"D1": "an implied value of $145.33 per share, payable in cash equivalents of acquirer stock"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    assert ext.extract(_merger_rec()) == PayoutResult.none()


def test_proxy_tier_accepts_strong_in_cash():
    # But a strong "right to receive $X in cash" in a proxy IS trusted.
    filings = [EdgarSubmission(
        accession="D1", form="DEFM14A", filing_date="2025-02-01",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"D1": "each share converted into the right to receive $25.00 in cash, without interest"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res.value == 25.00 and res.source == "DEFM14A"


def test_proxy_tier_ignores_stale_filing():
    # A proxy filed years before the delist (recycled CIK / prior restructuring)
    # must not match. MRO: a 2001 PRE14A vs a 2024 delist.
    filings = [EdgarSubmission(
        accession="OLD", form="PREM14A", filing_date="2001-05-01",
        report_date="", items="", primary_doc="d.htm")]
    texts = {"OLD": "converted into the right to receive $50.00 in cash"}
    rec = DelistRecord(ticker="MRO", cik=101778, observed_delist_date="2024-11-22",
                       crsp_code=231, bucket=CrspBucket.MERGER, confidence="high",
                       reason="", evidence={})
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    assert ext.extract(rec) == PayoutResult.none()


def test_all_tiers_miss_returns_none():
    filings = [EdgarSubmission(
        accession="C1", form="8-K", filing_date="2025-03-28",
        report_date="2025-03-26", items="2.01", primary_doc="d.htm")]
    texts = {"C1": "the deal closed with no dollar figure stated here"}
    ext = PayoutExtractor(_FakeEdgarText(filings, texts))
    res = ext.extract(_merger_rec())
    assert res == PayoutResult.none()


# --- FIX 5: extract() must never raise on a network error ------------------

import requests


class _RaisingEdgar:
    """recent_filings raises a requests error, simulating a 5xx/transport fail."""
    def recent_filings(self, cik):
        raise requests.HTTPError("500 Server Error")
    def fetch_filing_text(self, cik, accession, primary_doc):
        raise requests.HTTPError("500 Server Error")


def test_extract_swallows_requests_error_returns_none():
    ext = PayoutExtractor(_RaisingEdgar())
    res = ext.extract(_merger_rec())
    assert res == PayoutResult.none()


class _RaisingFetchEdgar:
    """recent_filings ok, but fetch_filing_text raises on the network call."""
    def __init__(self, filings):
        self._filings = filings
    def recent_filings(self, cik):
        return list(self._filings)
    def fetch_filing_text(self, cik, accession, primary_doc):
        raise requests.ConnectionError("dropped")


def test_extract_swallows_fetch_error_returns_none():
    filings = [EdgarSubmission(
        accession="C1", form="8-K", filing_date="2025-03-28",
        report_date="2025-03-26", items="2.01", primary_doc="d.htm")]
    ext = PayoutExtractor(_RaisingFetchEdgar(filings))
    res = ext.extract(_merger_rec())
    assert res == PayoutResult.none()
