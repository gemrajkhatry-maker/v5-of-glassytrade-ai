"""TDD test suite for aggressive prints / volume bubbles.

Tests the detection algorithm, delta directionality filter, expiry,
EMA variance warm-up, and SL placement from aggressive prints.
"""

import pytest
from app.domain.fabio_ai.services import mlx_compute as mc
from app.domain.fabio_ai.services.amt_analyzer import (
    find_aggressive_prints,
    AMTConfig,
)
from app.domain.fabio_ai.services.entry_gates.signal_builder import sl_from_aggressive_print
from app.domain.trading.models.value_objects import OHLC, AggressivePrint, AMTResult


def _candle(
    price: float = 100.0,
    volume: float = 100.0,
    delta: float = 0.0,
    time: str = "2026-02-25T10:00:00",
) -> OHLC:
    return OHLC(
        time=time,
        open=price,
        high=price + 0.5,
        low=price - 0.5,
        close=price,
        volume=volume,
        vwap=price,
        delta=delta,
    )


def _candles(
    n: int, volume: float = 100.0, delta: float = 10.0, base_time: int = 0
) -> list[OHLC]:
    """Generate n candles with consistent volume."""
    return [
        _candle(
            volume=volume,
            delta=delta,
            time=f"2026-02-25T{10 + (base_time + i) // 60:02d}:{(base_time + i) % 60:02d}:00",
        )
        for i in range(n)
    ]


def _amt_result_with_prints(prints: list[AggressivePrint]) -> AMTResult:
    """Minimal AMTResult with aggressive prints."""
    return AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=101.0,
        value_area_low=99.0,
        lvns=(),
        hvns=(),
        aggressive_prints=tuple(prints),
        aggression=0.0,
        signal=None,
        setup=None,
        session_vwap=100.0,
    )


# ─── aggression_sigma() ───────────────────────────────────────────


class TestAggressionSigma:
    def test_returns_zero_for_short_data(self):
        assert mc.aggression_sigma(100, [50, 60, 70], 20) == 0.0

    def test_returns_zero_for_zero_volume(self):
        vols = [100.0] * 20
        assert mc.aggression_sigma(0, vols, 20) == 0.0

    def test_normal_volume_low_sigma(self):
        # Realistic volume with ~20% natural variation
        vols = [
            80,
            120,
            95,
            110,
            85,
            130,
            100,
            115,
            90,
            105,
            88,
            112,
            97,
            108,
            92,
            118,
            103,
            95,
            110,
            85,
            120,
            100,
            115,
            90,
            108,
            92,
            105,
            98,
            112,
            88,
        ]
        sigma = mc.aggression_sigma(120, vols, 20)  # volume near mean
        assert sigma < 2.0

    def test_spike_volume_high_sigma(self):
        # Same realistic volumes, but 5x spike
        vols = [
            80,
            120,
            95,
            110,
            85,
            130,
            100,
            115,
            90,
            105,
            88,
            112,
            97,
            108,
            92,
            118,
            103,
            95,
            110,
            85,
            120,
            100,
            115,
            90,
            108,
            92,
            105,
            98,
            112,
            88,
        ]
        sigma = mc.aggression_sigma(500, vols, 20)
        assert sigma >= 2.5

    def test_warm_up_no_inflated_sigma(self):
        """After fix: seeded variance prevents inflated z-scores on early candles."""
        # Realistic variation — a 2x spike should NOT be wildly inflated
        vols = [80, 120, 95, 110, 85, 130, 100, 115, 90, 105, 88, 112, 97, 108, 92]
        sigma = mc.aggression_sigma(200, vols, 20)
        # With proper variance seeding + std floor, 2x volume should stay reasonable
        assert sigma < 8.0  # Sanity: shouldn't be wildly inflated (was 100+ before fix)


# ─── Delta directionality threshold ───────────────────────────────


class TestDeltaDirectionalityThreshold:
    """Tests that the 40% delta ratio filter rejects near-balanced candles."""

    def _make_data_with_spike(self, spike_delta_ratio: float) -> list[OHLC]:
        """Create 60 normal candles + 1 spike with given delta ratio."""
        data = _candles(60, volume=100, delta=10)
        spike_vol = 500.0
        spike_delta = spike_vol * spike_delta_ratio
        data.append(
            _candle(volume=spike_vol, delta=spike_delta, time="2026-02-25T11:00:00")
        )
        return data

    def test_low_delta_ratio_rejected(self):
        """10% delta ratio = near-balanced → NOT flagged."""
        data = self._make_data_with_spike(0.10)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_medium_delta_ratio_rejected(self):
        """30% delta ratio → NOT flagged (below 40% threshold)."""
        data = self._make_data_with_spike(0.30)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_high_delta_ratio_accepted(self):
        """50% delta ratio → flagged."""
        data = self._make_data_with_spike(0.50)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1
        assert prints[-1].side == "BUY"

    def test_exactly_at_threshold(self):
        """40% delta ratio → flagged (threshold is >=)."""
        data = self._make_data_with_spike(0.40)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1


# ─── find_aggressive_prints() ────────────────────────────────────


class TestFindAggressivePrints:
    def test_empty_data(self):
        assert find_aggressive_prints([]) == []

    def test_short_data_returns_empty(self):
        data = _candles(10)
        assert find_aggressive_prints(data) == []

    def test_detects_spike_with_directional_delta(self):
        data = _candles(60, volume=100, delta=10)
        # Spike: 5x volume, 50% delta ratio
        data[30] = _candle(volume=500, delta=250, time=data[30].time)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1
        assert prints[0].side == "BUY"

    def test_rejects_spike_with_balanced_delta(self):
        """Volume spike but balanced delta (15%) → NOT detected after fix."""
        data = _candles(60, volume=100, delta=10)
        # Spike volume but only 15% delta ratio
        data[30] = _candle(volume=500, delta=75, time=data[30].time)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_incremental_expires_old_prints(self):
        data = _candles(60, volume=100, delta=10)
        # Create a print at candle 55 (within 30-candle window of end)
        data[55] = _candle(volume=500, delta=300, time=data[55].time)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1

        # Add 35 more candles (pushes print beyond 30-candle window)
        for i in range(35):
            data.append(_candle(volume=100, delta=10, time=f"2026-02-25T12:{i:02d}:00"))
            prints = find_aggressive_prints(
                data, previous_prints=prints, previous_data_len=len(data) - 1
            )

        # Old print should be expired
        assert len(prints) == 0

    def test_full_rebuild_also_expires(self):
        """After fix: full rebuild should also apply 30-candle expiry."""
        data = _candles(60, volume=100, delta=10)
        # Print at candle 10 (very old)
        data[10] = _candle(volume=500, delta=300, time=data[10].time)
        prints = find_aggressive_prints(data)
        # Should be expired since candle 10 is >30 candles from end (candle 59)
        assert len(prints) == 0

    def test_incremental_matches_full_rebuild(self):
        """Same input should produce same output regardless of path."""
        data = _candles(60, volume=100, delta=10)
        data[55] = _candle(volume=500, delta=300, time=data[55].time)

        # Full rebuild
        full = find_aggressive_prints(data)

        # Incremental: build up from 59 candles + add last
        inc = find_aggressive_prints(data[:-1])
        inc = find_aggressive_prints(
            data, previous_prints=inc, previous_data_len=len(data) - 1
        )

        assert len(full) == len(inc)


# ─── EMA Variance Warm-Up ────────────────────────────────────────


class TestEMAVarianceWarmUp:
    def test_no_spurious_prints_first_20_candles(self):
        """Candles with natural variation — moderate spike shouldn't trigger."""
        # Create candles with realistic volume variation
        volumes = [
            80,
            120,
            95,
            110,
            85,
            130,
            100,
            115,
            90,
            105,
            88,
            112,
            97,
            108,
            92,
            118,
            103,
            95,
            110,
            85,
            120,
            100,
            115,
            90,
            108,
        ]
        data = [
            _candle(
                volume=v,
                delta=v * 0.1,
                time=f"2026-02-25T{10 + i // 60:02d}:{i % 60:02d}:00",
            )
            for i, v in enumerate(volumes)
        ]
        # Candle 21 with 1.3x avg volume but low delta ratio (below 40% threshold)
        # 50/135 = 0.37, which is below 0.40 threshold - should NOT trigger
        data[20] = _candle(volume=135, delta=50, time=data[20].time)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0


# ─── sl_from_aggressive_print() ──────────────────────────────────


class TestSlFromAggressivePrint:
    def test_picks_nearest_sell_print_for_long(self):
        """For LONG: pick the highest (nearest) SELL print below price."""
        prints = [
            AggressivePrint(price=99.60, time="t1", side="SELL", volume=100, delta=-50),
            AggressivePrint(price=99.70, time="t2", side="SELL", volume=100, delta=-50),
            AggressivePrint(price=99.80, time="t3", side="SELL", volume=100, delta=-50),
        ]
        amt = _amt_result_with_prints(prints)
        tick = _candle(price=100.0)
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl is not None
        # Should pick 99.80 (nearest), not 99.60 (furthest)
        assert sl == pytest.approx(99.80 - 0.1)

    def test_picks_nearest_buy_print_for_short(self):
        """For SHORT: pick the lowest (nearest) BUY print above price."""
        prints = [
            AggressivePrint(price=100.10, time="t1", side="BUY", volume=100, delta=50),
            AggressivePrint(price=100.20, time="t2", side="BUY", volume=100, delta=50),
            AggressivePrint(price=100.40, time="t3", side="BUY", volume=100, delta=50),
        ]
        amt = _amt_result_with_prints(prints)
        tick = _candle(price=100.0)
        sl = sl_from_aggressive_print(amt, tick, is_buy=False, buffer=0.1)
        assert sl is not None
        # Should pick 100.10 (nearest), not 100.40 (furthest)
        assert sl == pytest.approx(100.10 + 0.1)

    def test_returns_none_when_no_opposing_prints(self):
        prints = [
            AggressivePrint(price=101.0, time="t1", side="BUY", volume=100, delta=50),
        ]
        amt = _amt_result_with_prints(prints)
        tick = _candle(price=100.0)
        # Looking for SELL prints below for LONG — none exist
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl is None

    def test_respects_proximity_filter(self):
        """Prints > 0.5% away from price should be ignored."""
        prints = [
            AggressivePrint(price=95.0, time="t1", side="SELL", volume=100, delta=-50),
        ]
        amt = _amt_result_with_prints(prints)
        tick = _candle(price=100.0)  # 95.0 is 5% away, > 0.5% proximity
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl is None
