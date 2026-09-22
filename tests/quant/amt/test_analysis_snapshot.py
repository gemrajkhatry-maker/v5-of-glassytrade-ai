from quant.amt.snapshot import analysis_snapshot_from_result, derive_stacked_imbalance
from quant.contracts.value_objects import AMTResult, FootprintCandle, FootprintLevel


def test_snapshot_carries_result_and_asof_time():
    result = AMTResult(market_state="BALANCED", poc=100.0, value_area_high=101.0, value_area_low=99.0)
    snap = analysis_snapshot_from_result(result, asof_time="2026-09-22T10:00:00+05:30")
    assert snap.result is result
    assert snap.asof_time == "2026-09-22T10:00:00+05:30"


def test_derive_stacked_imbalance_falls_back_to_prior_candle_when_forming_empty():
    stacked_levels = tuple(
        FootprintLevel(price=100.0 + i, bid=1, ask=10, delta=9, imbalance=True, stacked=True)
        for i in range(3)
    )
    flat_levels = tuple(
        FootprintLevel(price=200.0 + i, bid=5, ask=5, delta=0, imbalance=False, stacked=False)
        for i in range(3)
    )
    fps = {
        "t1": FootprintCandle(time="t1", levels=stacked_levels, poc_price=101.0, total_delta=27.0, step_price=1.0),
        "t2": FootprintCandle(time="t2", levels=flat_levels, poc_price=201.0, total_delta=0.0, step_price=1.0),
    }
    direction, mag, lo, hi = derive_stacked_imbalance(fps)
    assert direction == "BUY"
    assert mag >= 3
    assert lo <= hi


def test_derive_stacked_imbalance_matches_three_buy_stack():
    levels = tuple(
        FootprintLevel(price=100.0 + i, bid=1, ask=10, delta=9, imbalance=True, stacked=True)
        for i in range(3)
    )
    fps = {"t1": FootprintCandle(time="t1", levels=levels, poc_price=101.0, total_delta=27.0, step_price=1.0)}
    direction, mag, lo, hi = derive_stacked_imbalance(fps)
    assert direction == "BUY"
    assert mag >= 3
    assert lo <= hi


def test_snapshot_fills_stacked_fields_from_result_footprints():
    levels = tuple(
        FootprintLevel(price=100.0 + i, bid=1, ask=10, delta=9, imbalance=True, stacked=True)
        for i in range(3)
    )
    fps = {"t1": FootprintCandle(time="t1", levels=levels, poc_price=101.0, total_delta=27.0, step_price=1.0)}
    result = AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        footprints=fps,
    )
    snap = analysis_snapshot_from_result(result, asof_time="2026-09-22T10:00:00+05:30")
    assert snap.stacked_imbalance_direction == "BUY"
    assert snap.stacked_imbalance_magnitude >= 3
    assert snap.stacked_imbalance_low <= snap.stacked_imbalance_high
