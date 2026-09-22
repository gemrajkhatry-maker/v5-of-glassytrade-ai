from quant.amt.profile.leg_lvn import resolve_leg_lvn
from quant.amt.snapshot import analysis_snapshot_from_result
from quant.contracts.value_objects import AMTResult


def test_resolve_leg_lvn_reads_amt_result_leg_lvns():
    result = AMTResult(
        market_state="BALANCED", poc=100.0, value_area_high=101.0, value_area_low=99.0,
        leg_lvns=(99.0, 101.5),
    )
    resolved = resolve_leg_lvn(result, 101.0)
    assert resolved.available is True
    assert resolved.level == 101.5
    assert resolved.source == "leg_lvns"


def test_resolve_leg_lvn_reads_snapshot_result_leg_lvns():
    result = AMTResult(
        market_state="BALANCED", poc=100.0, value_area_high=101.0, value_area_low=99.0,
        leg_lvns=(100.5,),
    )
    snap = analysis_snapshot_from_result(result, asof_time="t")
    resolved = resolve_leg_lvn(snap, 101.0)
    assert resolved.available is True
    assert resolved.level == 100.5


def test_resolve_leg_lvn_prefers_nearest_positive_plural_level():
    result = resolve_leg_lvn({"legLvns": [-1.0, 99.0, 101.5]}, 101.0)
    assert result.available is True
    assert result.level == 101.5
    assert result.source == "legLvns"


def test_resolve_leg_lvn_ignores_the_legacy_singular_key():
    """The DTO only ever emits ``legLvns``; ``legLvn`` is not a producer key."""
    result = resolve_leg_lvn({"legLvn": 99.5}, 100.0)
    assert result.available is False
    assert result.level == 0.0
    assert result.reason == "NO_LVN"


def test_resolve_leg_lvn_reports_unavailable_without_a_level():
    result = resolve_leg_lvn({}, 100.0)
    assert result.available is False
    assert result.level == 0.0
    assert result.reason == "NO_LVN"


def test_retest_tolerance_is_at_least_tick_and_bounded_by_leg_range():
    from quant.amt.profile.leg_lvn import leg_lvn_retest_tolerance
    value = leg_lvn_retest_tolerance(tick_size=0.05, bucket_width=1.0, leg_range=20.0)
    assert value >= 0.05
    assert value <= 20.0 * 0.25


def test_retest_tolerance_rejects_missing_dimensions_safely():
    from quant.amt.profile.leg_lvn import leg_lvn_retest_tolerance
    assert leg_lvn_retest_tolerance(0.05, 0.0, 0.0) == 0.1
