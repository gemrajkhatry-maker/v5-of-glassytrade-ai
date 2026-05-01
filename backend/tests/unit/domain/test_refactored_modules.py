"""Tests for refactored probability modules."""

import pytest
from app.domain.probability import (
    RegimeState, RegimeHysteresis,
    DirectionSignal,
    kelly_size, adjust_sl_tp,
    select_playbook, playbook_thresholds, summarize_feature_drivers,
)
from app.domain.fabio_ai.services.narrative_builder import (
    _build_narrative_session_context,
    _build_narrative_market_state,
    _build_narrative_order_flow,
)
from app.domain.fabio_ai.services.response_parser import (
    parse_entry_response,
    parse_overseer_response,
    compute_tighten_sl,
)


class TestRegimeClassifier:
    def test_regime_state_creation(self):
        state = RegimeState("TRENDING", True, True, 1.0)
        assert state.regime == "TRENDING"
        assert state.allowed_long is True

    def test_hysteresis_apply(self):
        h = RegimeHysteresis(min_persistence=2)
        state = RegimeState("TRENDING", True, True, 1.0)
        result = h.apply(state)
        assert result.regime == "TRENDING"

    def test_hysteresis_requires_persistence(self):
        h = RegimeHysteresis(min_persistence=3)
        initial = RegimeState("BALANCED", True, True, 1.0)
        h.apply(initial)  # Set initial regime
        
        # Change should not flip immediately
        new_state = RegimeState("TRENDING", True, True, 1.0)
        result = h.apply(new_state)
        assert result.regime == "BALANCED"  # Still initial until persistence met


class TestDirectionTiming:
    def test_direction_signal(self):
        signal = DirectionSignal("LONG", 0.75, "test")
        assert signal.direction == "LONG"
        assert signal.probability == 0.75


class TestSizing:
    def test_kelly_size_positive_edge(self):
        size = kelly_size(0.6, 1.5)
        assert 0 < size <= 0.25

    def test_kelly_size_fifty_fifty(self):
        # 0.5 probability with 1.5 R/R gives edge = 0.5 - 0.5/1.5 = 0.167
        size = kelly_size(0.5, 1.5)
        assert size > 0

    def test_kelly_size_negative_edge(self):
        size = kelly_size(0.4, 1.5)
        assert abs(size) < 0.01  # Allow for floating point precision

    def test_adjust_sl_tp_long(self):
        sl, tp, sl_adj, tp_adj = adjust_sl_tp(100, "LONG", 5, 10, 1.0)  # vol_mult = 2.0
        assert sl == 90.0  # 100 - 5 * 2.0
        assert tp == 105.0  # 100 + 10 * 0.5 (tp_mult = 1/2.0)

    def test_adjust_sl_tp_short(self):
        sl, tp, sl_adj, tp_adj = adjust_sl_tp(100, "SHORT", 5, 10, 1.0)
        assert sl == 110.0  # 100 + 5 * 2.0
        assert tp == 95.0  # 100 - 10 * 0.5


class TestPlaybook:
    def test_select_trending(self):
        state = RegimeState("TRENDING", True, True, 1.0)
        assert select_playbook(state, "IMBALANCED") == "imbalance_continuation"

    def test_select_balanced(self):
        state = RegimeState("BALANCED", True, True, 1.0)
        assert select_playbook(state, "BALANCED") == "return_to_value"

    def test_playbook_thresholds(self):
        assert playbook_thresholds("imbalance_continuation") == (0.7, 0.6, 0.8)

    def test_feature_drivers(self):
        data = {"delta_imbalance": True, "cvd_slope": 100}
        drivers = summarize_feature_drivers(data)
        assert "delta_imbalance" in drivers


class TestNarrativeBuilder:
    def test_session_context(self):
        data = {"session_name": "OPEN", "prior_poc": 100, "prior_vah": 105, "prior_val": 95}
        parts = _build_narrative_session_context(data)
        assert any("OPEN" in p for p in parts)

    def test_order_flow(self):
        data = {"delta": 100, "cvd_slope": 50}
        parts = _build_narrative_order_flow(data)
        assert any("buying" in p.lower() for p in parts)


class TestResponseParser:
    def test_parse_entry_json(self):
        result = parse_entry_response('{"direction": "LONG", "confidence": 0.75}')
        assert result.get("direction") == "LONG"

    def test_parse_overseer(self):
        result = parse_overseer_response('{"action": "EXIT", "urgency": "URGENT"}', {})
        assert result.action == "EXIT"
        assert result.urgency == "URGENT"

    def test_compute_tighten_sl(self):
        pos_state = {"entry_price": 100, "stop_loss": 95, "mfe": 10}
        factor = compute_tighten_sl(pos_state)
        assert 0 < factor <= 1.0