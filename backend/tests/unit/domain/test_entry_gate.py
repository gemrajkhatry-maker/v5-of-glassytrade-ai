"""Contract tests for entry_gate.py — pure quant functions, no mocks needed."""

import pytest
from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook, OrderBookLevel, AggressivePrint
from app.domain.fabio_ai.services.entry_gates.three_align import (
    three_align_check,
    cluster_aggressive_prints,
)
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import (
    check_confirmation_bundle,
    compute_atr,
)
from app.domain.fabio_ai.services.entry_gates.signal_builder import (
    build_entry_signal,
    sl_from_aggressive_print,
)
from app.domain.fabio_ai.services.entry_gates.grading import (
    compute_grade_score,
    check_vwap_bias,
)
from app.domain.trading.models.enums import SetupType, SignalType, Source


def _tick(close=100, volume=500, delta=100, high=None, low=None, vwap=0):
    h = high or close * 1.01
    l = low or close * 0.99
    return OHLC(time="2026-01-01T00:00:00Z", open=close, high=h, low=l,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(market_state="BALANCED", poc=100, vah=105, val=95, lvns=(), hvns=(),
         aggression=0.5, session_vwap=0, aggressive_prints=(), cvd_slope=0.0):
    return AMTResult(
        market_state=market_state, poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=lvns, hvns=hvns, aggression=aggression,
        session_vwap=session_vwap, aggressive_prints=aggressive_prints,
        cvd_slope=cvd_slope,
    )


class TestThreeAlignCheck:
    def test_passes_when_all_align(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=500, delta=200)  # near POC, high vol+delta
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick)[0] is True

    def test_fails_zero_poc(self):
        data = [_tick() for _ in range(30)]
        tick = _tick()
        amt = _amt(poc=0, vah=0, val=0)
        assert three_align_check(data, amt, tick)[0] is False

    def test_fails_not_near_level(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=110, volume=500, delta=200)  # not near any level
        amt = _amt(poc=100, vah=105, val=95)
        assert three_align_check(data, amt, tick)[0] is False

    def test_passes_near_lvn(self):
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=98, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95, lvns=(98.0,))
        assert three_align_check(data, amt, tick)[0] is True


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

    def test_signal_contains_trade_thesis_metadata(self):
        tick = _tick(close=95, vwap=99)
        amt = _amt(poc=100, vah=105, val=95, session_vwap=99, aggression=0.8, cvd_slope=0.5)
        ai = {"rationale": "value reclaim", "confidence": "High"}
        sig = build_entry_signal(
            "LONG",
            tick,
            amt,
            ai,
            SetupType.MEAN_REVERSION,
            session_context="NSE_PRIMARY",
        )

        thesis = sig.metadata["trade_thesis"]
        assert thesis["market_state"] == "BALANCED"
        assert thesis["location_type"] == "VAL"
        assert thesis["aggression_trigger"] in {"DELTA_EXPANSION", "CVD_EXPANSION", "DELTA_PRESSURE"}
        assert thesis["session_context"] == "NSE_PRIMARY"
        assert thesis["invalidation_level"] == sig.stop_loss


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


# ---- VWAP Bias Tests ----

class TestCheckVWAPBias:
    def test_long_below_vwap_warning(self):
        from app.domain.fabio_ai.services.entry_gates.grading import check_vwap_bias
        result = check_vwap_bias("LONG", price=98.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_short_above_vwap_warning(self):
        from app.domain.fabio_ai.services.entry_gates.grading import check_vwap_bias
        result = check_vwap_bias("SHORT", price=102.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_long_at_vwap_2sigma_overextended(self):
        from app.domain.fabio_ai.services.entry_gates.grading import check_vwap_bias
        result = check_vwap_bias("LONG", price=104.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["overextended"] is True

    def test_short_at_vwap_minus_2sigma_overextended(self):
        from app.domain.fabio_ai.services.entry_gates.grading import check_vwap_bias
        result = check_vwap_bias("SHORT", price=96.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["overextended"] is True

    def test_long_above_vwap_no_warning(self):
        from app.domain.fabio_ai.services.entry_gates.grading import check_vwap_bias
        result = check_vwap_bias("LONG", price=101.0, vwap=100.0, vwap_upper_2=104.0, vwap_lower_2=96.0)
        assert result["warning"] is False
        assert result["overextended"] is False

    def test_ignores_distant_prints(self):
        tick = _tick(close=100)
        ap = AggressivePrint(price=90, time="t", volume=500, delta=-200, side="SELL")
        amt = _amt(aggressive_prints=(ap,))
        assert sl_from_aggressive_print(amt, tick, True, 0.1) is None


# ---- Aggressive Prints as Structural Levels (Tasks 12-13) ----

class TestClusterAggressivePrints:
    def test_merges_nearby(self):
        """Prints within 0.1% of each other merge into VWAP of cluster."""
        from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints
        prints = (
            AggressivePrint(price=100.0, time="t", volume=300, delta=100, side="BUY"),
            AggressivePrint(price=100.05, time="t", volume=200, delta=50, side="BUY"),
        )
        result = cluster_aggressive_prints(prints)
        assert len(result) == 1
        # VWAP = (100*300 + 100.05*200) / 500 = 100.02
        assert result[0] == pytest.approx(100.02)

    def test_separate_far(self):
        """Prints far apart stay as separate clusters."""
        from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints
        prints = (
            AggressivePrint(price=100.0, time="t", volume=300, delta=100, side="BUY"),
            AggressivePrint(price=105.0, time="t", volume=200, delta=50, side="BUY"),
        )
        result = cluster_aggressive_prints(prints)
        assert len(result) == 2

    def test_cap_at_5(self):
        """More than 5 clusters returns only top 5 by volume."""
        from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints
        # 7 prints far apart -> 7 clusters, capped to 5
        prints = tuple(
            AggressivePrint(price=100.0 + i * 10, time="t", volume=(i + 1) * 100, delta=50, side="BUY")
            for i in range(7)
        )
        result = cluster_aggressive_prints(prints)
        assert len(result) == 5

    def test_empty(self):
        """Empty tuple returns empty list."""
        from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints
        assert cluster_aggressive_prints(()) == []


class TestThreeAlignAggressiveLevels:
    def test_near_aggressive_level(self):
        """Price near an aggressive print cluster level counts as near level."""
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        # tick at 110 is NOT near POC=100/VAH=105/VAL=95, but IS near aggressive level 110
        tick = _tick(close=110, volume=500, delta=200)
        amt = _amt(poc=100, vah=105, val=95)
        # Without aggressive levels, this fails (existing test confirms)
        assert three_align_check(data, amt, tick)[0] is False
        # With aggressive level at 110, it should pass
        assert three_align_check(data, amt, tick, aggressive_levels=[110])[0] is True

# ---- Imbalance Alignment Tests (Task 21) ----

class TestImbalanceAlignment:
    def test_aligned_long_buy_imbalances(self):
        """LONG + mostly BUY imbalances -> +1."""
        from app.domain.fabio_ai.services.entry_gates.grading import check_imbalance_alignment
        from app.domain.trading.models.value_objects import StackedImbalance
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="BUY", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 1

    def test_opposing_long_sell_imbalances(self):
        """LONG + mostly SELL imbalances -> -2."""
        from app.domain.fabio_ai.services.entry_gates.grading import check_imbalance_alignment
        from app.domain.trading.models.value_objects import StackedImbalance
        imbalances = [
            StackedImbalance(direction="SELL", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="SELL", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == -2

    def test_empty_imbalances(self):
        """No imbalances -> 0."""
        from app.domain.fabio_ai.services.entry_gates.grading import check_imbalance_alignment
        assert check_imbalance_alignment("LONG", []) == 0

    def test_mixed_equal_imbalances(self):
        """Equal BUY and SELL -> 0."""
        from app.domain.fabio_ai.services.entry_gates.grading import check_imbalance_alignment
        from app.domain.trading.models.value_objects import StackedImbalance
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="SELL", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
        ]
        assert check_imbalance_alignment("LONG", imbalances) == 0

    def test_short_aligned_with_sell(self):
        """SHORT + mostly SELL imbalances -> +1."""
        from app.domain.fabio_ai.services.entry_gates.grading import check_imbalance_alignment
        from app.domain.trading.models.value_objects import StackedImbalance
        imbalances = [
            StackedImbalance(direction="SELL", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
            StackedImbalance(direction="SELL", price_low=100, price_high=102, magnitude=4, candle_time="t2"),
            StackedImbalance(direction="BUY", price_low=98, price_high=100, magnitude=2, candle_time="t3"),
        ]
        assert check_imbalance_alignment("SHORT", imbalances) == 1

    def test_short_opposing_buy_imbalances(self):
        """SHORT + mostly BUY imbalances -> -2."""
        from app.domain.fabio_ai.services.entry_gates.grading import check_imbalance_alignment
        from app.domain.trading.models.value_objects import StackedImbalance
        imbalances = [
            StackedImbalance(direction="BUY", price_low=99, price_high=101, magnitude=3, candle_time="t1"),
        ]
        assert check_imbalance_alignment("SHORT", imbalances) == -2


    def test_existing_levels_still_work(self):
        """Existing VAH/VAL/POC/HVN near-level detection still works with aggressive_levels=None."""
        data = [_tick(close=100, volume=200, delta=80) for _ in range(30)]
        tick = _tick(close=100, volume=500, delta=200)  # near POC
        amt = _amt(poc=100, vah=105, val=95)
        # Should pass without aggressive_levels (backward compatible)
        assert three_align_check(data, amt, tick, aggressive_levels=None)[0] is True

# ---- CVD Hard Gate Tests ----

class TestCVDHardGate:
    def test_long_extreme_bearish_cvd_blocked(self):
        from app.domain.fabio_ai.services.entry_gates.grading import compute_grade_score
        tick = _tick(close=100)
        # CVD heavily opposing the LONG direction
        amt = _amt(poc=100, vah=105, val=95, cvd_slope=-55.0)
        score = compute_grade_score(direction="LONG", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
        assert score == -10
        
    def test_short_extreme_bullish_cvd_blocked(self):
        from app.domain.fabio_ai.services.entry_gates.grading import compute_grade_score
        tick = _tick(close=100)
        # CVD heavily opposing the SHORT direction
        amt = _amt(poc=100, vah=105, val=95, cvd_slope=55.0)
        score = compute_grade_score(direction="SHORT", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
        assert score == -10
        
    def test_normal_cvd_passes_gate(self):
        from app.domain.fabio_ai.services.entry_gates.grading import compute_grade_score
        tick = _tick(close=100)
        # CVD is normal, does not trigger hard gate
        amt = _amt(poc=100, vah=105, val=95, cvd_slope=10.0)
        score = compute_grade_score(direction="LONG", tick=tick, amt_result=amt, setup_type=SetupType.TREND_MODEL)
        assert score != -10
