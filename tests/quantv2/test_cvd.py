from quantv2.cvd import CVDTracker


def test_velocity_and_divergence():
    t = CVDTracker()
    for d in (10, 10, 10, 10, 10, 10, -5, -5, -5, -5):  # price pushed up while cvd stalls/falls
        t.on_delta(float(d))
    # brief pinned cvd == 30.0 but the tuple sums 6*10 + 4*(-5) = 40; adjusted (v1 cvd is a plain cumulative sum)
    assert t.cvd == 40.0
    assert t.velocity < 0
    assert t.divergence("UP", lookback=6) == "BEARISH_FALLING"
    up = CVDTracker()
    for d in (5, 5, 5, 5, 5):
        up.on_delta(float(d))
    assert up.divergence("UP", lookback=6) == "BULLISH_RISING"


def test_velocity_is_ema3_minus_ema9_of_delta():
    t = CVDTracker()
    for _ in range(12):
        t.on_delta(5.0)
    assert t.cvd == 60.0
    assert t.velocity == 0.0  # constant deltas: both EMAs sit exactly on 5.0


def test_divergence_none_and_down():
    t = CVDTracker()
    for d in (10, 10, 10, 10):
        t.on_delta(float(d))
    assert t.divergence("UP", lookback=6) == "BULLISH_RISING"
    assert t.divergence("SIDEWAYS", lookback=6) == "NONE"
    fresh = CVDTracker()
    assert fresh.divergence("UP", lookback=6) == "NONE"
    assert fresh.cvd == 0.0
    assert fresh.velocity == 0.0
