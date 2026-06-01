from delist_detection.crsp_codes import CrspBucket, bucket_for_code


def test_known_codes_map_correctly():
    assert bucket_for_code(100) is CrspBucket.ACTIVE
    assert bucket_for_code(231) is CrspBucket.MERGER
    assert bucket_for_code(304) is CrspBucket.EXCHANGE_TRANSFER
    assert bucket_for_code(470) is CrspBucket.LIQUIDATION
    assert bucket_for_code(560) is CrspBucket.COMPLIANCE_FAILURE
    assert bucket_for_code(600) is CrspBucket.EXPIRATION


def test_unknown_or_missing():
    assert bucket_for_code(None) is CrspBucket.UNKNOWN
    assert bucket_for_code(900) is CrspBucket.UNKNOWN


def test_ranges_fall_through_to_correct_bucket():
    # An unspecified 5xx code should still route to compliance-failure.
    assert bucket_for_code(555) is CrspBucket.COMPLIANCE_FAILURE
    # A 2xx without an explicit entry should still be merger.
    assert bucket_for_code(225) is CrspBucket.MERGER


def test_up_migration_codes_are_exchange_transfer_not_compliance():
    # Per Shumway & Warther (1999): only 501 (->NYSE) and 502 (->AMEX/NYSE MKT)
    # are positive up-migrations, NOT performance delistings. They must not land
    # in COMPLIANCE_FAILURE (which would apply a -55% Shumway shock to a good event).
    assert bucket_for_code(501) is CrspBucket.EXCHANGE_TRANSFER
    assert bucket_for_code(502) is CrspBucket.EXCHANGE_TRANSFER
    # 503-519 are performance-related distress delistings per the source — NOT
    # up-migrations — so they must land in COMPLIANCE_FAILURE.
    assert bucket_for_code(505) is CrspBucket.COMPLIANCE_FAILURE
    assert bucket_for_code(517) is CrspBucket.COMPLIANCE_FAILURE


def test_genuine_5xx_still_compliance():
    assert bucket_for_code(500) is CrspBucket.COMPLIANCE_FAILURE
    assert bucket_for_code(520) is CrspBucket.COMPLIANCE_FAILURE
    assert bucket_for_code(555) is CrspBucket.COMPLIANCE_FAILURE
