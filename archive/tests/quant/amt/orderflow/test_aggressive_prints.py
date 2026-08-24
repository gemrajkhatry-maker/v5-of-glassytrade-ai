"""TDD test suite for aggressive prints / volume bubbles — ported from backend.

Tests the detection algorithm, delta directionality filter, expiry,
EMA variance warm-up, and print registry.
"""

import pytest
from quant.amt import compute as mc
from quant.amt.orderflow.aggressive_prints import (
    compute_aggression_sigma,
    find_aggressive_prints,
    AggressivePrintRegistry,
    AggressivePrintConfig,
)
from quant.contracts.value_objects import OHLC, AggressivePrint


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
    return [
        _candle(
            volume=volume,
            delta=delta,
            time=f"2026-02-25T{10 + (base_time + i) // 60:02d}:{(base_time + i) % 60:02d}:00",
        )
        for i in range(n)
    ]


# ─── aggression_sigma() ───────────────────────────────────────────


class TestAggressionSigma:
    def test_returns_zero_for_short_data(self):
        assert mc.aggression_sigma(100, [50, 60, 70], 20) == 0.0

    def test_returns_zero_for_zero_volume(self):
        vols = [100.0] * 20
        assert mc.aggression_sigma(0, vols, 20) == 0.0

    def test_normal_volume_low_sigma(self):
        vols = [
            80, 120, 95, 110, 85, 130, 100, 115, 90, 105,
            88, 112, 97, 108, 92, 118, 103, 95, 110, 85,
            120, 100, 115, 90, 108, 92, 105, 98, 112, 88,
        ]
        sigma = mc.aggression_sigma(120, vols, 20)
        assert sigma < 2.0

    def test_spike_volume_high_sigma(self):
        vols = [
            80, 120, 95, 110, 85, 130, 100, 115, 90, 105,
            88, 112, 97, 108, 92, 118, 103, 95, 110, 85,
            120, 100, 115, 90, 108, 92, 105, 98, 112, 88,
        ]
        sigma = mc.aggression_sigma(500, vols, 20)
        assert sigma >= 2.5

    def test_warm_up_no_inflated_sigma(self):
        vols = [80, 120, 95, 110, 85, 130, 100, 115, 90, 105, 88, 112, 97, 108, 92]
        sigma = mc.aggression_sigma(200, vols, 20)
        assert sigma < 8.0

    def test_compute_aggression_sigma_matches(self):
        vols = [80, 120, 95, 110, 85, 130, 100, 115, 90, 105, 88, 112, 97, 108, 92]
        data = [
            _candle(volume=v, delta=v * 0.1, time=f"2026-02-25T{10 + i // 60:02d}:{i % 60:02d}:00")
            for i, v in enumerate(vols)
        ]
        spike = _candle(volume=500.0, delta=250.0, time="2026-02-25T11:00:00")
        assert compute_aggression_sigma(spike, data) == pytest.approx(
            mc.aggression_sigma(500.0, [float(v.volume) for v in data], 20)
        )


# ─── Delta directionality threshold ───────────────────────────────


class TestDeltaDirectionalityThreshold:
    def _make_data_with_spike(self, spike_delta_ratio: float) -> list[OHLC]:
        data = _candles(60, volume=100, delta=10)
        spike_vol = 500.0
        spike_delta = spike_vol * spike_delta_ratio
        data.append(
            _candle(volume=spike_vol, delta=spike_delta, time="2026-02-25T11:00:00")
        )
        return data

    def test_low_delta_ratio_rejected(self):
        data = self._make_data_with_spike(0.10)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_medium_delta_ratio_rejected(self):
        data = self._make_data_with_spike(0.30)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_high_delta_ratio_accepted(self):
        data = self._make_data_with_spike(0.50)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1
        assert prints[-1].side == "BUY"

    def test_exactly_at_threshold(self):
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
        data[30] = _candle(volume=500, delta=250, time=data[30].time)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1
        assert prints[0].side == "BUY"

    def test_rejects_spike_with_balanced_delta(self):
        data = _candles(60, volume=100, delta=10)
        data[30] = _candle(volume=500, delta=75, time=data[30].time)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_incremental_expires_old_prints(self):
        data = _candles(60, volume=100, delta=10)
        data[55] = _candle(volume=500, delta=300, time=data[55].time)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1

        for i in range(35):
            data.append(_candle(volume=100, delta=10, time=f"2026-02-25T12:{i:02d}:00"))
            prints = find_aggressive_prints(
                data, previous_prints=prints, previous_data_len=len(data) - 1
            )

        assert len(prints) == 0

    def test_full_rebuild_also_expires(self):
        data = _candles(60, volume=100, delta=10)
        data[10] = _candle(volume=500, delta=300, time=data[10].time)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0

    def test_incremental_matches_full_rebuild(self):
        data = _candles(60, volume=100, delta=10)
        data[55] = _candle(volume=500, delta=300, time=data[55].time)

        full = find_aggressive_prints(data)

        inc = find_aggressive_prints(data[:-1])
        inc = find_aggressive_prints(
            data, previous_prints=inc, previous_data_len=len(data) - 1
        )

        assert len(full) == len(inc)


# ─── EMA Variance Warm-Up ────────────────────────────────────────


class TestEMAVarianceWarmUp:
    def test_no_spurious_prints_first_20_candles(self):
        volumes = [
            80, 120, 95, 110, 85, 130, 100, 115, 90, 105,
            88, 112, 97, 108, 92, 118, 103, 95, 110, 85,
            120, 100, 115, 90, 108,
        ]
        data = [
            _candle(
                volume=v,
                delta=v * 0.1,
                time=f"2026-02-25T{10 + i // 60:02d}:{i % 60:02d}:00",
            )
            for i, v in enumerate(volumes)
        ]
        data[20] = _candle(volume=135, delta=50, time=data[20].time)
        prints = find_aggressive_prints(data)
        assert len(prints) == 0


# ─── AggressivePrintRegistry ─────────────────────────────────────


class TestAggressivePrintRegistry:
    def test_register_deduplicates_by_time(self):
        registry = AggressivePrintRegistry()
        prints = [
            AggressivePrint(price=100.0, time="t1", side="BUY", volume=100, delta=50),
            AggressivePrint(price=101.0, time="t1", side="SELL", volume=100, delta=-50),
            AggressivePrint(price=102.0, time="t2", side="BUY", volume=100, delta=50),
        ]
        registry.register(prints)
        registry.register(prints)
        assert len(registry.prints) == 3

    def test_get_retests(self):
        registry = AggressivePrintRegistry(proximity_pct=0.001)
        registry.register([
            AggressivePrint(price=100.0, time="t1", side="BUY", volume=100, delta=50),
            AggressivePrint(price=200.0, time="t2", side="SELL", volume=100, delta=-50),
        ])
        retests = registry.get_retests(100.05)
        assert len(retests) == 1
        assert retests[0].price == 100.0

    def test_clear(self):
        registry = AggressivePrintRegistry()
        registry.register([
            AggressivePrint(price=100.0, time="t1", side="BUY", volume=100, delta=50)
        ])
        registry.clear()
        assert registry.prints == []
