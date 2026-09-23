"""Unit tests for acceptance_rejection — acceptance/rejection at VA boundaries."""


from quant.amt.market.acceptance_rejection import ARResult, AcceptanceRejectionEngine
from quant.contracts.value_objects import OHLC


def _candle(t, o, h, lo, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time=t, open=o, high=h, low=lo, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


class TestAcceptanceRejectionEngine:
    def test_initial_update_returns_flags_false(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        assert isinstance(result, ARResult)
        assert result.acceptance_above is False
        assert result.acceptance_below is False

    def test_dict_like_access(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        assert result["acceptance_above"] is False
        assert "acceptance_below" in result
        assert result.get("rejection_at_high") is False
        assert result.get("missing_key", "default") == "default"

    def test_acceptance_above_vah(self):
        engine = AcceptanceRejectionEngine(time_threshold=100.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        result = engine.update(_candle("2024-01-01T09:17:00+00:00", 106, 107, 105.5, 106.5, v=2000), 105.0, 95.0, 1000.0)
        assert result.acceptance_above is True

    def test_acceptance_below_val(self):
        engine = AcceptanceRejectionEngine(time_threshold=100.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        result = engine.update(_candle("2024-01-01T09:17:00+00:00", 94, 95, 93, 93.5, v=2000), 105.0, 95.0, 1000.0)
        assert result.acceptance_below is True

    def test_acceptance_tracks_only_the_current_close_side(self):
        engine = AcceptanceRejectionEngine(time_threshold=50.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)

        above = engine.update(
            _candle("2024-01-01T09:17:00+00:00", 106, 107, 105.5, 106.5, v=2000),
            105.0, 95.0, 1000.0,
        )
        assert above.acceptance_above is True
        assert above.acceptance_below is False

        below = engine.update(
            _candle("2024-01-01T09:18:00+00:00", 94, 94.5, 93, 93.5, v=2000),
            105.0, 95.0, 1000.0,
        )
        assert below.acceptance_above is False
        assert below.acceptance_below is True

        inside = engine.update(
            _candle("2024-01-01T09:19:00+00:00", 100, 101, 99, 100, v=2000),
            105.0, 95.0, 1000.0,
        )
        assert inside.acceptance_above is False
        assert inside.acceptance_below is False

    def test_rejection_at_high(self):
        engine = AcceptanceRejectionEngine()
        # Wicks above VAH with volume spike, close back below
        result = engine.update(
            _candle("2024-01-01T09:15:00+00:00", 104.5, 105.3, 104.0, 104.8, v=2000), 105.0, 95.0, 1000.0
        )
        assert result.rejection_at_high is True

    def test_rejection_at_low(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(
            _candle("2024-01-01T09:15:00+00:00", 95.6, 96.0, 94.8, 95.5, v=2000), 105.0, 95.0, 1000.0
        )
        assert result.rejection_at_low is True

    def test_liquidity_sweep_high(self):
        engine = AcceptanceRejectionEngine()
        result = engine.update(
            _candle("2024-01-01T09:15:00+00:00", 104.5, 105.6, 104.0, 104.6, v=2000), 105.0, 95.0, 1000.0
        )
        assert result.liquidity_sweep == "SWEEP_HIGH"

    def test_no_double_credit_within_single_bar(self):
        """Regression: analyzer called update() twice per bar, crediting the 60s fallback twice."""
        engine = AcceptanceRejectionEngine(time_threshold=120.0)
        # Same candle/timestamp handed to update() twice (what analyzer.analyze() did).
        # Candle sweeps VAH (high 105.6 > vah 105.0, close back below) so sweep/rejection
        # flags are non-trivially computed and must survive the repeat.
        c = _candle("2024-01-01T09:15:00+00:00", 104.5, 105.6, 104.0, 104.6, v=2000)
        s1 = engine.update(c, 105.0, 95.0, 1000.0)
        acc_after_1 = engine._time_above_vah
        s2 = engine.update(c, 105.0, 95.0, 1000.0)
        acc_after_2 = engine._time_above_vah
        assert acc_after_2 == acc_after_1, "same-bar repeat must add zero time credit"
        assert s2.liquidity_sweep == s1.liquidity_sweep == "SWEEP_HIGH"
        assert s2.rejection_at_high == s1.rejection_at_high
        assert s2.rejection_at_low == s1.rejection_at_low
        assert s2.acceptance_above == s1.acceptance_above
        # ponytail fall-through: duration=0 kills velocity via its own duration>0 guard
        assert s2.price_velocity == 0.0

    def test_reset_clears_state(self):
        engine = AcceptanceRejectionEngine(time_threshold=100.0)
        engine.update(_candle("2024-01-01T09:15:00+00:00", 100, 101, 99, 100), 105.0, 95.0, 1000.0)
        engine.update(_candle("2024-01-01T09:17:00+00:00", 106, 107, 105.5, 106.5, v=2000), 105.0, 95.0, 1000.0)
        engine.reset()
        result = engine.update(_candle("2024-01-01T09:19:00+00:00", 106, 107, 105.5, 106.5, v=2000), 105.0, 95.0, 1000.0)
        assert result.acceptance_above is False


def test_dto_price_velocity_nonzero_for_real_bar():
    """Regression: live bars consumed the SECOND A/R update (dt=0 → velocity
    0), so the emitted priceVelocity was always zero. The analyzer must carry
    the FIRST pass (real bar-to-bar duration) through to the result."""
    from quant.amt.analyzer import AMTAnalyzer

    candles = []
    for m in range(0, 45, 5):
        t = f"2026-01-01T09:{15 + m:02d}:00Z"
        o = 100.0 + m * 0.5
        c = o + 2.0
        candles.append(OHLC(time=t, open=o, high=c + 1.0, low=o - 1.0,
                            close=c, volume=1000, vwap=(o + c) / 2,
                            taker_buy_volume=600.0, delta=100.0))
    result = AMTAnalyzer().analyze(candles)
    assert result.price_velocity > 0.0
