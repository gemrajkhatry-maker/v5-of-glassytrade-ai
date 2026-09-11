from quant.amt.dto import amt_result_to_dto
from quant.contracts.value_objects import AMTResult


def test_amt_dto_exposes_leg_lvn_availability_and_provenance():
    result = AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        leg_lvns=(100.5,),
        leg_profile=(),
        leg_profile_source="CANDLE_DISTRIBUTED",
        leg_bucket_count=5,
        leg_lvn_unavailable_reason="",
    )
    dto = amt_result_to_dto(result)
    assert dto["legProfileSource"] == "CANDLE_DISTRIBUTED"
    assert dto["legBucketCount"] == 5
    assert dto["legLvnAvailable"] is True
    assert dto["legLvnUnavailableReason"] == ""


def test_empty_leg_lvn_is_truthful_no_lvn():
    result = AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        leg_profile_source="CANDLE_DISTRIBUTED",
        leg_bucket_count=2,
        leg_lvn_unavailable_reason="INSUFFICIENT_BUCKETS",
    )
    dto = amt_result_to_dto(result)
    assert dto["legLvnAvailable"] is False
    assert dto["legLvnUnavailableReason"] == "INSUFFICIENT_BUCKETS"
