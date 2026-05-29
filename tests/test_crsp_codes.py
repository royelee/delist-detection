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
