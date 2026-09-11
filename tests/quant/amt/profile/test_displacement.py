from types import SimpleNamespace

from quant.amt.profile.displacement import detect_displacement_leg


def test_displacement_leg_prefers_tick_footprint_profile_when_available():
    candles = [SimpleNamespace(open=100, close=101, high=102, low=99, volume=100, delta=10, time=f"t{i}") for i in range(5)]
    footprints = {
        f"t{i}": SimpleNamespace(
            time=f"t{i}",
            levels=(
                SimpleNamespace(price=100.0 + i, bid=10.0, ask=25.0, delta=15.0),
                SimpleNamespace(price=101.0 + i, bid=30.0, ask=10.0, delta=-20.0),
                SimpleNamespace(price=102.0 + i, bid=12.0, ask=28.0, delta=16.0),
            ),
            step_price=1.0,
        ) for i in range(5)
    }
    config = SimpleNamespace(DISPLACEMENT_MULTIPLIER=1.0, LVN_THRESHOLD=0.15,
                             LVN_SMOOTHING=3)
    result = detect_displacement_leg(candles, config, footprints=footprints)
    assert result["profile_source"] == "TICK_FOOTPRINT"
    assert result["bucket_count"] >= 3
