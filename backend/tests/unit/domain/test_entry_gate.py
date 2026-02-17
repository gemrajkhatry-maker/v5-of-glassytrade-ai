"""Contract tests for entry_gate.py — pure quant functions, no mocks needed."""

import pytest
from app.domain.fabio_ai.services.entry_gate import (
    three_align_check,
    check_confirmation_bundle,
    check_volatility_filter,
    compute_atr,
    build_entry_signal,
    sl_from_aggressive_print,
)
from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook, OrderBookLevel, AggressivePrint
from app.domain.trading.models.enums import SetupType, SignalType, Source


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(market_state="BALANCED", poc=100, vah=105, val=95, lvns=(), hvns=(),
         aggression=0.5, session_vwap=0, aggressive_prints=()):
    return AMTResult(
        market_state=market_state, poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=lvns, hvns=hvns, aggression=aggression,
        session_vwap=session_vwap, aggressive_prints=aggressive_prints,
    )


class TestThreeAlignCheck:
    def test_passes_when_all_align(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=500, delta=200)  # near POC, high vol+delta
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick) is True

    def test_fails_zero_poc(self):
        data = [_tick() for _ in range(30)]
        tick = _tick()
        amt = _amt(poc=0, vah=0, val=0)
        assert three_align_check(data, amt, tick) is False

    def test_fails_not_near_level(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=102.5, volume=500, delta=200)  # not near any level
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick) is False

    def test_passes_near_lvn(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=98, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95, lvns=(98.0,))
        assert three_align_check(data, amt, tick) is True


class TestConfirmationBundle:
    def test_requires_20_bars(self):
        data = [_tick() for _ in range(10)]
        assert check_confirmation_bundle(data, _tick()) is False

    def test_passes_with_strong_volume_and_delta(self):
        data = [_tick(volume=100, delta=5) for _ in range(30)]
        tick = _tick(volume=500, delta=200)  # 5x volume, 40% delta ratio
        assert check_confirmation_bundle(data, tick) is True

    def test_fails_with_weak_signals(self):
        data = [_tick(volume=100, delta=5) for _ in range(30)]
        tick = _tick(volume=100, delta=5)  # no impulse, low delta ratio
        assert check_confirmation_bundle(data, tick) is False


class TestVolatilityFilter:
    def test_blocks_zero_volume(self):
        assert check_volatility_filter([], _tick(volume=0)) is True

    def test_passes_normal_volume(self):
        assert check_volatility_filter([], _tick(volume=100)) is False

    def test_blocks_extreme_atr(self):
        normal = [_tick(high=101, low=99) for _ in range(20)]
        # Last 5 bars with huge range
        for i in range(-5, 0):
            normal[i] = _tick(high=110, low=90)
        assert check_volatility_filter(normal, _tick()) is True


class TestComputeATR:
    def test_basic(self):
        data = [_tick(high=110, low=90) for _ in range(20)]
        assert compute_atr(data, 14) == pytest.approx(20.0)

    def test_insufficient_data(self):
        assert compute_atr([_tick()], 14) == 0.0


class TestBuildEntrySignal:
    def test_long_trend_signal(self):
        tick = _tick(close=100, vwap=99)
        amt = _amt(poc=100, vah=105, val=95, session_vwap=99)
        ai = {"rationale": "test reason", "confidence": "High"}
        sig = build_entry_signal("LONG", tick, amt, ai, SetupType.TREND_MODEL)
        assert sig.type == SignalType.BUY
        assert sig.source == Source.LLM
        assert sig.stop_loss < sig.price < sig.take_profit
        assert sig.metadata["allow_trail"] is True

    def test_short_mean_reversion_signal(self):
        tick = _tick(close=105, vwap=100)
        amt = _amt(poc=100, vah=105, val=95, session_vwap=100)
        ai = {"rationale": "test", "confidence": "Medium"}
        sig = build_entry_signal("SHORT", tick, amt, ai, SetupType.MEAN_REVERSION)
        assert sig.type == SignalType.SELL
        assert sig.metadata["allow_trail"] is False


class TestSLFromAggressivePrint:
    def test_long_uses_sell_print(self):
        tick = _tick(close=100)
        ap = AggressivePrint(price=99.6, time="t", volume=500, delta=-200, side="SELL")
        amt = _amt(aggressive_prints=(ap,))
        sl = sl_from_aggressive_print(amt, tick, is_buy=True, buffer=0.1)
        assert sl == pytest.approx(99.5)

    def test_no_prints_returns_none(self):
        amt = _amt(aggressive_prints=())
        assert sl_from_aggressive_print(amt, _tick(), True, 0.1) is None

    def test_ignores_distant_prints(self):
        tick = _tick(close=100)
        ap = AggressivePrint(price=90, time="t", volume=500, delta=-200, side="SELL")
        amt = _amt(aggressive_prints=(ap,))
        assert sl_from_aggressive_print(amt, tick, True, 0.1) is None
