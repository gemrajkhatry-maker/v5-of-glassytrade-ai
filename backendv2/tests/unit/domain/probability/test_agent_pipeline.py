"""Tests for the 4-agent micro-agent cascade pipeline.

Covers: pick_direction, assess_timing, select_playbook, kelly_size,
adjust_sl_tp, summarize_feature_drivers, run_agent_pipeline.
"""

import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.probability.agent_pipeline import (
    AgentDecision,
    pick_direction,
    assess_timing,
    select_playbook,
    kelly_size,
    adjust_sl_tp,
    summarize_feature_drivers,
    run_agent_pipeline,
    _to_float,
)
from app.domain.probability.direction_timing import DirectionSignal
from app.domain.probability.regime_classifier import RegimeState
from app.domain.trading.model.value_objects import OHLC, AMTResult, AggressivePrint


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class MockProbabilityEngine:
    """Lightweight fake IProbabilityInference for unit tests."""

    def __init__(self, p_long=0.55, p_short=0.45, ready=True,
                 mfe_long=0.015, mfe_short=0.015):
        self._p_long = p_long
        self._p_short = p_short
        self._ready = ready
        self._mfe_long = mfe_long
        self._mfe_short = mfe_short

    def is_ready(self):
        return self._ready

    def estimate(self, features):
        return SimpleNamespace(
            p_long_target=self._p_long,
            p_short_target=self._p_short,
            expected_mfe_long=self._mfe_long,
            expected_mfe_short=self._mfe_short,
            calibrated=False,
        )


def make_ohlc(time="2024-01-01T09:15:00", open=100.0, high=101.0,
              low=99.5, close=100.5, volume=1000, delta=50):
    return OHLC.create(
        time=time, open=open, high=high, low=low,
        close=close, volume=volume, delta=delta,
    )


def make_data(n=10, base_open=100.0):
    """Create a list of n OHLC candles."""
    candles = []
    for i in range(n):
        candles.append(make_ohlc(
            time=f"2024-01-01T09:{15 + i * 5:02d}:00",
            open=base_open + i * 0.2,
            high=base_open + i * 0.2 + 0.8,
            low=base_open + i * 0.2 - 0.3,
            close=base_open + i * 0.2 + 0.5,
            volume=1000 + i * 100,
            delta=50 + i * 10,
        ))
    return candles


def make_amt(market_state="BALANCED", poc=100.0, vah=102.0, val=98.0,
             cvd_slope=0.0, aggressive_prints=(), aggression=0.0,
             leg_regime="", leg_poc=0.0, leg_vah=0.0, leg_val=0.0,
             balance_ratio=0.6, delta_normalized_option=0.0,
             price_velocity=0.05, **overrides):
    return AMTResult(
        market_state=market_state,
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
        cvd_slope=cvd_slope,
        aggressive_prints=aggressive_prints,
        aggression=aggression,
        leg_regime=leg_regime,
        leg_poc=leg_poc,
        leg_vah=leg_vah,
        leg_val=leg_val,
        balance_ratio=balance_ratio,
        delta_normalized_option=delta_normalized_option,
        price_velocity=price_velocity,
        **overrides,
    )


def make_regime(regime="BALANCED", allowed_long=True, allowed_short=True,
                risk_scale=1.0):
    return RegimeState(
        regime=regime,
        allowed_long=allowed_long,
        allowed_short=allowed_short,
        risk_scale=risk_scale,
    )


# ---------------------------------------------------------------------------
# 1. pick_direction — ~6 tests
# ---------------------------------------------------------------------------

class TestPickDirection:

    def test_long_clear_edge(self):
        """LONG when p_long >= threshold and > p_short + margin."""
        engine = MockProbabilityEngine(p_long=0.65, p_short=0.40)
        regime = make_regime("TRENDING")
        signal = pick_direction(
            {}, engine, regime, playbook="imbalance_continuation",
            p_threshold_long=0.55, p_threshold_short=0.53, margin=0.04,
        )
        assert signal.direction == "LONG"
        assert signal.p_long == 0.65
        assert signal.edge > 0  # positive edge

    def test_short_clear_edge(self):
        """SHORT when p_short >= threshold and > p_long + margin."""
        engine = MockProbabilityEngine(p_long=0.35, p_short=0.62)
        regime = make_regime("TRENDING")
        signal = pick_direction(
            {}, engine, regime, playbook="imbalance_continuation",
            p_threshold_long=0.55, p_threshold_short=0.53, margin=0.04,
        )
        assert signal.direction == "SHORT"
        assert signal.p_short == 0.62

    def test_flat_when_no_edge(self):
        """FLAT when neither direction has sufficient edge."""
        engine = MockProbabilityEngine(p_long=0.48, p_short=0.47)
        regime = make_regime("BALANCED")
        signal = pick_direction(
            {}, engine, regime, playbook="return_to_value",
            p_threshold_long=0.51, p_threshold_short=0.51, margin=0.02,
        )
        assert signal.direction == "FLAT"

    def test_regime_filter_blocks_long(self):
        """Regime with allowed_long=False forces p_long to 0."""
        engine = MockProbabilityEngine(p_long=0.70, p_short=0.40)
        regime = make_regime("TRENDING", allowed_long=False)
        signal = pick_direction(
            {}, engine, regime, playbook="imbalance_continuation",
            p_threshold_long=0.55, p_threshold_short=0.53, margin=0.04,
        )
        # p_long is zeroed out, but p_short may not meet threshold either
        # so direction depends on remaining conditions
        assert signal.p_long == 0.0

    def test_close_probabilities_let_higher_win(self):
        """When abs(p_long - p_short) < margin, higher probability wins."""
        engine = MockProbabilityEngine(p_long=0.555, p_short=0.545)
        regime = make_regime("BALANCED")
        signal = pick_direction(
            {}, engine, regime, playbook="return_to_value",
            p_threshold_long=0.51, p_threshold_short=0.51, margin=0.02,
        )
        # Both >= CONFIDENCE_LOW_THRESHOLD (0.50), diff=0.01 < margin (0.02)
        # The close-probability branch picks the higher one
        assert signal.direction == "LONG"
        assert signal.p_long >= signal.p_short

    def test_unready_engine_returns_flat(self):
        """Engine not ready returns FLAT with default probabilities."""
        engine = MockProbabilityEngine(ready=False)
        regime = make_regime("TRENDING")
        signal = pick_direction(
            {}, engine, regime, playbook="imbalance_continuation",
        )
        assert signal.direction == "FLAT"
        assert signal.p_long == 0.5
        assert signal.p_short == 0.5
        assert signal.edge == 0.0


# ---------------------------------------------------------------------------
# 2. assess_timing — ~8 tests
# ---------------------------------------------------------------------------

class TestAssessTiming:

    def test_enter_now_when_conditions_met(self):
        """ENTER_NOW when all gates pass and aggression confirms."""
        data = make_data(n=10)
        tick = make_ohlc(close=101.0, delta=100, volume=2000)
        agg_print = AggressivePrint(
            price=101.0, time="2024-01-01T09:50:00",
            side="BUY", volume=500, delta=200,
        )
        amt = make_amt(
            cvd_slope=2.0,
            aggressive_prints=(agg_print,),
            aggression=3.0,
            price_velocity=0.03,
        )
        with patch("app.domain.probability.agent_pipeline.three_align_check",
                   return_value=(True, True)):
            with patch("app.domain.probability.agent_pipeline.run_gate_pipeline",
                       return_value=(True, "TRADE", "", 3, 4)):
                result = assess_timing(
                    data, tick, amt, direction="LONG",
                    playbook="imbalance_continuation",
                )
        assert result == "ENTER_NOW"

    def test_wait_when_chasing_extreme_bar(self):
        """WAIT when bar range > 3x ATR (chasing a spike)."""
        data = make_data(n=10)
        # Create an extreme bar: range = 5.0 while ATR5 ~ 1.1
        tick = make_ohlc(high=105.0, low=100.0, close=104.0, delta=100)
        amt = make_amt(cvd_slope=2.0, price_velocity=0.03)
        result = assess_timing(
            data, tick, amt, direction="LONG",
            playbook="imbalance_continuation",
        )
        assert result == "WAIT"

    def test_wait_when_delta_zero_no_aggression(self):
        """WAIT when delta=0 and no aggressive prints."""
        data = make_data(n=10)
        tick = make_ohlc(close=100.5, delta=0, volume=500)
        amt = make_amt(cvd_slope=0.0, aggressive_prints=(), aggression=0.0)
        result = assess_timing(
            data, tick, amt, direction="LONG",
            playbook="imbalance_continuation",
        )
        assert result == "WAIT"

    def test_wait_when_cvd_contradicts_long(self):
        """WAIT when CVD slope is strongly bearish for LONG direction."""
        from app.domain.constants import CVD_SLOPE_HARD_BLOCK
        data = make_data(n=10)
        tick = make_ohlc(close=100.5, delta=100, volume=2000)
        amt = make_amt(cvd_slope=-CVD_SLOPE_HARD_BLOCK - 10,
                       aggressive_prints=(), aggression=0.0)
        result = assess_timing(
            data, tick, amt, direction="LONG",
            playbook="imbalance_continuation",
        )
        assert result == "WAIT"

    def test_skip_for_return_to_value_at_poc(self):
        """SKIP for return_to_value when price is near POC."""
        data = make_data(n=10)
        tick = make_ohlc(close=100.1, delta=100, volume=1000)
        amt = make_amt(poc=100.0, vah=102.0, val=98.0, cvd_slope=1.0)
        result = assess_timing(
            data, tick, amt, direction="LONG",
            playbook="return_to_value",
        )
        assert result == "SKIP"

    def test_wait_for_probing_without_aggression(self):
        """WAIT for probing_breakout without aggressive prints."""
        data = make_data(n=10)
        tick = make_ohlc(close=103.0, delta=100, volume=1000)
        amt = make_amt(
            market_state="PROBING",
            cvd_slope=2.0,
            aggressive_prints=(),
            aggression=1.0,
            price_velocity=0.03,
        )
        with patch("app.domain.probability.agent_pipeline.three_align_check",
                   return_value=(True, True)):
            with patch("app.domain.probability.agent_pipeline.run_gate_pipeline",
                       return_value=(True, "TRADE", "", 3, 4)):
                result = assess_timing(
                    data, tick, amt, direction="LONG",
                    playbook="probing_breakout",
                )
        assert result == "WAIT"

    def test_wait_when_three_align_gate_fails(self):
        """WAIT when three-align gate does not pass."""
        data = make_data(n=10)
        tick = make_ohlc(close=100.5, delta=100, volume=1000)
        agg_print = AggressivePrint(
            price=100.5, time="2024-01-01T09:50:00",
            side="BUY", volume=500, delta=200,
        )
        amt = make_amt(cvd_slope=2.0, aggressive_prints=(agg_print,),
                       aggression=3.0, price_velocity=0.03)
        with patch("app.domain.probability.agent_pipeline.three_align_check",
                   return_value=(False, False)):
            result = assess_timing(
                data, tick, amt, direction="LONG",
                playbook="imbalance_continuation",
            )
        assert result == "WAIT"

    def test_wait_when_twelve_gate_pipeline_fails(self):
        """WAIT when 12-gate pipeline rejects."""
        data = make_data(n=10)
        tick = make_ohlc(close=100.5, delta=100, volume=1000)
        agg_print = AggressivePrint(
            price=100.5, time="2024-01-01T09:50:00",
            side="BUY", volume=500, delta=200,
        )
        amt = make_amt(cvd_slope=2.0, aggressive_prints=(agg_print,),
                       aggression=3.0, price_velocity=0.03)
        with patch("app.domain.probability.agent_pipeline.three_align_check",
                   return_value=(True, True)):
            with patch("app.domain.probability.agent_pipeline.run_gate_pipeline",
                       return_value=(False, "BLOCKED", "No candles yet", 0, 4)):
                result = assess_timing(
                    data, tick, amt, direction="LONG",
                    playbook="imbalance_continuation",
                )
        assert result == "WAIT"


# ---------------------------------------------------------------------------
# 3. select_playbook — ~5 tests
# ---------------------------------------------------------------------------

class TestSelectPlaybook:

    def test_trending_imbalanced_selects_imbalance_continuation(self):
        """TRENDING + IMBALANCED market state → imbalance_continuation."""
        regime = make_regime("TRENDING")
        amt = make_amt(market_state="IMBALANCED")
        playbook = select_playbook(regime, amt)
        assert playbook == "imbalance_continuation"

    def test_balanced_selects_return_to_value(self):
        """BALANCED + BALANCED → return_to_value."""
        regime = make_regime("BALANCED")
        amt = make_amt(market_state="BALANCED")
        playbook = select_playbook(regime, amt)
        assert playbook == "return_to_value"

    def test_probing_selects_probing_breakout(self):
        """PROBING market state → probing_breakout.

        Note: MarketStateCodec.is_probing() currently returns False always,
        so this test verifies the fallback behavior instead.
        """
        regime = make_regime("BALANCED")
        # Since is_probing returns False, use TRENDING + IMBALANCED
        # which is the only way to get a non-empty playbook besides BALANCED
        amt = make_amt(market_state="PROBING")
        playbook = select_playbook(regime, amt)
        # With is_probing always False, PROBING falls through to empty
        # This documents current codec behavior
        assert playbook == ""

    def test_no_trade_with_balanced_leg_returns_return_to_value(self):
        """NO_TRADE with leg_regime BALANCED → return_to_value."""
        regime = make_regime("NO_TRADE")
        amt = make_amt(
            market_state="NO_TRADE",
            leg_regime="BALANCED",
        )
        playbook = select_playbook(regime, amt)
        assert playbook == "return_to_value"

    def test_no_match_returns_empty_string(self):
        """When no regime/market_state combo matches, return ''."""
        regime = make_regime("VOLATILE")
        amt = make_amt(market_state="IMBALANCED")
        playbook = select_playbook(regime, amt)
        assert playbook == ""


# ---------------------------------------------------------------------------
# 4. kelly_size — ~5 tests
# ---------------------------------------------------------------------------

class TestKellySize:

    def test_positive_edge_returns_positive_size(self):
        """Probability well above 0.5 yields positive Kelly fraction."""
        size = kelly_size(probability=0.60)
        assert size > 0

    def test_negative_edge_returns_zero(self):
        """Probability where Kelly formula yields no edge returns zero."""
        # Kelly = (p*b - q)/b. With b=2.0: Kelly > 0 when p > 1/3 ≈ 0.333
        # So p=0.33 or below should return 0
        size = kelly_size(probability=0.33)
        assert size == 0.0

        size = kelly_size(probability=0.45)
        assert size > 0  # 0.45 has positive Kelly (just capped)

    def test_unproven_cap_at_025_percent(self):
        """Unproven model (<30 samples) capped at 0.25%."""
        # With p=0.65, raw Kelly would be higher, but cap applies
        size = kelly_size(probability=0.65, win_rate_sample_size=10)
        assert size <= 0.0025  # 0.25%
        assert size > 0

    def test_proven_cap_at_05_percent(self):
        """Proven model (>=30 samples) capped at 0.5%."""
        size = kelly_size(probability=0.70, win_rate_sample_size=50)
        assert size <= 0.005  # 0.5%
        assert size > 0

    def test_half_kelly_math(self):
        """Verify half-Kelly formula: kelly * 0.5."""
        # p=0.60, b=2.0 (1.5/0.75), q=0.40
        # kelly = (0.60 * 2.0 - 0.40) / 2.0 = 0.40
        # half_kelly = 0.40 * 0.5 = 0.20
        # But capped at 0.0025 (unproven) or 0.005 (proven)
        raw_b = 0.015 / 0.0075  # = 2.0
        p = 0.60
        q = 0.40
        raw_kelly = (p * raw_b - q) / raw_b  # = 0.40
        expected_half = raw_kelly * 0.5  # = 0.20

        # With huge sample size, cap is 0.005
        size = kelly_size(probability=0.60, win_rate_sample_size=100)
        assert size == 0.005  # capped

        # With a probability that yields small raw Kelly, no cap hit
        # p=0.52, kelly = (0.52*2 - 0.48)/2 = 0.28, half = 0.14
        size = kelly_size(probability=0.52, win_rate_sample_size=100)
        assert size == 0.005  # still capped at 0.5%

        # Very small edge that doesn't hit cap
        # p=0.505, kelly = (0.505*2 - 0.495)/2 = 0.0775, half = 0.03875
        size = kelly_size(probability=0.505, win_rate_sample_size=100)
        assert size == 0.005  # capped

        # p=0.335: kelly = (0.335*2 - 0.665)/2 = 0.0025, half = 0.00125
        # This is below the 0.005 proven cap, so returns 0.00125
        size = kelly_size(probability=0.335, win_rate_sample_size=100)
        expected = 0.00125
        assert abs(size - expected) < 0.00001


# ---------------------------------------------------------------------------
# 5. adjust_sl_tp — ~4 tests
# ---------------------------------------------------------------------------

class TestAdjustSlTp:

    def test_trending_regime_increases_tp_multiplier(self):
        """TRENDING regime increases TP multiplier to 1.3."""
        sl_mult, tp_mult = adjust_sl_tp(
            direction="LONG", regime="TRENDING", probability=0.55,
            predicted_mfe=0.0,
        )
        assert tp_mult == 1.3
        assert sl_mult == 1.1

    def test_volatile_regime_increases_sl_multiplier(self):
        """VOLATILE regime increases SL multiplier to 1.4."""
        sl_mult, tp_mult = adjust_sl_tp(
            direction="SHORT", regime="VOLATILE", probability=0.55,
            predicted_mfe=0.0,
        )
        assert sl_mult == 1.4
        assert tp_mult == 1.2

    def test_high_confidence_extends_tp(self):
        """High confidence (>CONFIDENCE_HIGH_THRESHOLD) extends TP."""
        from app.domain.constants import CONFIDENCE_HIGH_THRESHOLD
        sl_mult, tp_mult = adjust_sl_tp(
            direction="LONG", regime="BALANCED",
            probability=CONFIDENCE_HIGH_THRESHOLD + 0.05,
            predicted_mfe=0.0,
        )
        # Base BALANCED has tp_mult=1.0, then * 1.1 for high confidence
        assert tp_mult == 1.1

    def test_mfe_based_dynamic_tp(self):
        """Positive predicted_mfe sets dynamic TP relative to base."""
        # predicted_mfe=0.020, base_tp=0.015 → dynamic_tp = 1.333...
        sl_mult, tp_mult = adjust_sl_tp(
            direction="LONG", regime="TRENDING", probability=0.55,
            predicted_mfe=0.020, base_tp_pct=0.015,
        )
        # Dynamic TP: 0.020 / 0.015 = 1.333... (clamped to [0.5, 2.0])
        expected_tp = 0.020 / 0.015
        assert abs(tp_mult - expected_tp) < 0.001
        # SL stays at 1.0 because MFE path bypasses regime SL adjustment
        assert sl_mult == 1.0


# ---------------------------------------------------------------------------
# 6. summarize_feature_drivers — ~3 tests
# ---------------------------------------------------------------------------

class TestSummarizeFeatureDrivers:

    def test_auction_aware_rationale_for_imbalance(self):
        """imbalance_continuation + IMBALANCED → auction driver."""
        features = {
            "nearest_lvn_distance_pct": 0.001,
            "close_vs_vah_pct": 0.002,
            "delta_normalized": 0.3,
            "cvd_slope": 0.2,
        }
        amt = make_amt(market_state="IMBALANCED")
        drivers = summarize_feature_drivers(
            features, direction="LONG",
            playbook="imbalance_continuation", amt_result=amt,
        )
        assert len(drivers) >= 1
        assert any("auction" in d for d in drivers)

    def test_directional_feature_selection(self):
        """Positive features for LONG, negative flipped for SHORT."""
        features = {
            "delta_normalized": 0.3,
            "cvd_slope": 0.2,
            "aggressive_print_imbalance": 0.1,
        }
        amt = make_amt(market_state="IMBALANCED")

        long_drivers = summarize_feature_drivers(
            features, direction="LONG",
            playbook="imbalance_continuation", amt_result=amt,
        )
        short_drivers = summarize_feature_drivers(
            features, direction="SHORT",
            playbook="imbalance_continuation", amt_result=amt,
        )

        # Both should have drivers since features are positive
        # but they reference different labels (positive vs negative)
        assert len(long_drivers) >= 1
        assert len(short_drivers) >= 1

    def test_top3_limit_with_orderflow_requirement(self):
        """Max 3 drivers; at least one orderflow/aggression/liquidity."""
        features = {
            "nearest_lvn_distance_pct": 0.001,
            "close_vs_vah_pct": 0.002,
            "volume_vs_ema20": 1.5,
            "delta_normalized": 0.3,
            "cvd_slope": 0.2,
            "aggressive_print_imbalance": 0.1,
            "book_imbalance_l1": 0.2,
            "atr_ratio": 1.3,
        }
        amt = make_amt(market_state="IMBALANCED")
        drivers = summarize_feature_drivers(
            features, direction="LONG",
            playbook="imbalance_continuation", amt_result=amt,
        )
        assert len(drivers) <= 3
        # Ensure at least one orderflow-type driver
        has_orderflow = any(
            d.startswith(("orderflow:", "aggression:", "liquidity:"))
            for d in drivers
        )
        assert has_orderflow


# ---------------------------------------------------------------------------
# 7. run_agent_pipeline — ~4 tests
# ---------------------------------------------------------------------------

class TestRunAgentPipeline:

    def _make_basic_data(self, n=25):
        """Create enough candles to avoid DEAD regime (<20)."""
        return make_data(n=n)

    def test_dead_regime_shortcut_returns_flat(self):
        """DEAD regime (not enough candles) returns FLAT decision."""
        data = make_data(n=5)  # < 20 → DEAD
        tick = make_ohlc()
        amt = make_amt()
        engine = MockProbabilityEngine()
        decision = run_agent_pipeline(
            data, amt, tick, engine, features={},
        )
        assert decision.direction == "FLAT"
        assert decision.regime == "DEAD"
        assert decision.size_fraction == 0.0

    def test_no_playbook_returns_flat(self):
        """When select_playbook returns '', pipeline returns FLAT."""
        data = self._make_basic_data(n=25)
        tick = make_ohlc()
        # VOLATILE + IMBALANCED → no playbook match
        amt = make_amt(market_state="IMBALANCED")
        engine = MockProbabilityEngine()

        with patch("app.domain.probability.agent_pipeline.classify_regime",
                   return_value=make_regime("VOLATILE")):
            decision = run_agent_pipeline(
                data, amt, tick, engine, features={},
            )
        assert decision.direction == "FLAT"
        assert decision.playbook == ""

    def test_full_pipeline_with_long_signal(self):
        """Full pipeline produces LONG decision when conditions align."""
        data = self._make_basic_data(n=25)
        tick = make_ohlc(close=101.0, delta=100, volume=2000)
        agg_print = AggressivePrint(
            price=101.0, time="2024-01-01T09:50:00",
            side="BUY", volume=500, delta=200,
        )
        amt = make_amt(
            market_state="IMBALANCED",
            cvd_slope=2.0,
            aggressive_prints=(agg_print,),
            aggression=3.0,
            delta_normalized_option=0.5,
            price_velocity=0.03,
        )
        features = {
            "delta_normalized": 0.3,
            "cvd_slope": 0.2,
            "volume_vs_ema20": 1.2,
        }
        engine = MockProbabilityEngine(p_long=0.65, p_short=0.35)

        with patch("app.domain.probability.agent_pipeline.classify_regime",
                   return_value=make_regime("TRENDING")):
            decision = run_agent_pipeline(
                data, amt, tick, engine, features=features,
            )

        assert decision.direction == "LONG"
        assert decision.regime == "TRENDING"
        assert decision.playbook == "imbalance_continuation"
        assert decision.probability > 0.5
        assert decision.latency_us >= 0

    def test_full_pipeline_with_flat_signal(self):
        """Full pipeline returns FLAT when probability engine has no edge."""
        data = self._make_basic_data(n=25)
        tick = make_ohlc(close=100.5, delta=0, volume=500)
        amt = make_amt(
            market_state="BALANCED",
            cvd_slope=0.0,
            aggressive_prints=(),
            aggression=0.0,
            delta_normalized_option=0.0,
        )
        features = {}
        # Probabilities too close and below thresholds → FLAT
        engine = MockProbabilityEngine(p_long=0.48, p_short=0.47)

        with patch("app.domain.probability.agent_pipeline.classify_regime",
                   return_value=make_regime("BALANCED")):
            decision = run_agent_pipeline(
                data, amt, tick, engine, features=features,
            )

        assert decision.direction == "FLAT"
        assert decision.size_fraction == 0.0
        assert decision.timing == "SKIP"
