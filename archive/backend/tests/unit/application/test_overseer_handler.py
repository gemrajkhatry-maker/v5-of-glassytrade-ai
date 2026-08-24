"""Tests for LLMOverseerHandler — timeout, ADD cooldown, probability override."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.llm_overseer_handler import (
    LLMOverseerHandler,
    OVERSEER_COOLDOWN,
    ADD_COOLDOWN,
    MAX_ADDS_PER_POSITION,
)
from quant.inference.prompt_builder import OverseerAction


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_created_handlers = []

@pytest.fixture(autouse=True)
def cleanup_handlers():
    yield
    for h in _created_handlers:
        h.cleanup()
    _created_handlers.clear()

def _make_handler(predict_return='{"action":"HOLD","reason":"test"}', probability_engine=None):
    adapter = MagicMock()
    adapter.predict.return_value = predict_return

    gen_ai = MagicMock()
    gen_ai.llm_adapter = adapter
    gen_ai.is_ready.return_value = True

    event_bus = MagicMock()
    trade_manager = MagicMock()
    storage = MagicMock()

    handler = LLMOverseerHandler(
        gen_ai_service=gen_ai,
        
        trade_manager=trade_manager,
        storage=storage,
        probability_engine=probability_engine,
    )
    _created_handlers.append(handler)
    return handler, gen_ai, trade_manager, storage


def _make_pos_state(**overrides):
    state = {
        "position_id": "pos-1",
        "side": "LONG",
        "entry_price": 100.0,
        "current_price": 105.0,
        "unrealized_pnl_pct": 0.05,
        "time_in_trade_secs": 60,
        "stop_loss": 95.0,
        "take_profit": 115.0,
        "partial_taken": False,
        "trailing_active": False,
        "market_state": "BALANCED",
    }
    state.update(overrides)
    return state


@dataclass
class FakeSession:
    portfolio: MagicMock = field(default_factory=MagicMock)
    data: list = field(default_factory=list)
    last_ai_analysis: dict | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_overseer_time: float = 0
    _overseer_running: bool = False
    _last_ai_time: float = 0
    _ai_running: bool = False


# =====================================================================
# should_run tests
# =====================================================================

class TestShouldRun:
    def test_no_position(self):
        handler, *_ = _make_handler()
        assert handler.should_run(0, False, False, False) is False

    def test_already_running(self):
        handler, *_ = _make_handler()
        assert handler.should_run(0, True, False, True) is False

    def test_ai_running(self):
        handler, *_ = _make_handler()
        assert handler.should_run(0, False, True, True) is False

    def test_cooldown(self):
        handler, *_ = _make_handler()
        assert handler.should_run(time.time(), False, False, True) is False

    def test_model_not_ready(self):
        handler, gen_ai, *_ = _make_handler()
        gen_ai.is_ready.return_value = False
        assert handler.should_run(0, False, False, True) is False

    def test_happy_path(self):
        handler, *_ = _make_handler()
        assert handler.should_run(0, False, False, True) is True


# =====================================================================
# _execute_decision tests
# =====================================================================

class TestExecuteDecision:
    def test_hold_does_nothing(self):
        handler, _, tm, _ = _make_handler()
        session = FakeSession()
        pos_state = _make_pos_state()
        handler._execute_decision(
            OverseerAction(action="HOLD", reason="ok"),
            session, "SYM", 105.0, pos_state,
        )
        tm.adjust_stop_loss.assert_not_called()

    def test_tighten_sl(self):
        handler, _, tm, _ = _make_handler()
        tm.adjust_stop_loss.return_value = True
        session = FakeSession()
        pos_state = _make_pos_state()
        handler._execute_decision(
            OverseerAction(action="TIGHTEN_SL", new_sl_price=98.0, reason="tighten"),
            session, "SYM", 105.0, pos_state,
        )
        tm.adjust_stop_loss.assert_called_once_with("pos-1", 98.0)

    def test_tighten_sl_rejected(self):
        handler, _, tm, _ = _make_handler()
        tm.adjust_stop_loss.return_value = False
        session = FakeSession()
        pos_state = _make_pos_state()
        handler._execute_decision(
            OverseerAction(action="TIGHTEN_SL", new_sl_price=90.0, reason="widen"),
            session, "SYM", 105.0, pos_state,
        )
        tm.adjust_stop_loss.assert_called_once()

    def test_partial_exit(self):
        handler, _, tm, _ = _make_handler()
        session = FakeSession()
        mock_pos = MagicMock()
        mock_pos.status = "OPEN"
        mock_pos.id = "pos-1"
        session.portfolio.positions = [mock_pos]
        session.portfolio.partial_close_position.return_value = 50.0
        pos_state = _make_pos_state()

        handler._execute_decision(
            OverseerAction(action="PARTIAL_EXIT", reason="take profits"),
            session, "SYM", 105.0, pos_state,
        )
        session.portfolio.partial_close_position.assert_called_once()
        tm.adjust_stop_loss.assert_called_once_with(mock_pos, 100.0)

    def test_partial_already_taken(self):
        handler, _, tm, _ = _make_handler()
        session = FakeSession()
        pos_state = _make_pos_state(partial_taken=True)
        handler._execute_decision(
            OverseerAction(action="PARTIAL_EXIT", reason="take more"),
            session, "SYM", 105.0, pos_state,
        )
        session.portfolio.partial_close_position.assert_not_called()

    def test_full_exit(self):
        handler, _, tm, _ = _make_handler()
        session = FakeSession()
        mock_pos = MagicMock()
        mock_pos.status = "OPEN"
        mock_pos.id = "pos-1"
        session.portfolio.positions = [mock_pos]
        pos_state = _make_pos_state()

        handler._execute_decision(
            OverseerAction(action="FULL_EXIT", reason="exit now"),
            session, "SYM", 105.0, pos_state,
        )
        session.portfolio.close_position.assert_called_once()
        tm.record_exit_time.assert_called_once()

    def test_add_profitable(self):
        handler, _, _, _ = _make_handler()
        session = FakeSession()
        pos_state = _make_pos_state(unrealized_pnl_pct=0.03)
        handler._execute_decision(
            OverseerAction(action="ADD", reason="pyramid"),
            session, "SYM", 105.0, pos_state,
        )
        assert handler._add_count == 1
        assert handler._last_add_time > 0

    def test_add_rejected_losing(self):
        handler, _, _, _ = _make_handler()
        session = FakeSession()
        pos_state = _make_pos_state(unrealized_pnl_pct=-0.02)
        handler._execute_decision(
            OverseerAction(action="ADD", reason="pyramid"),
            session, "SYM", 95.0, pos_state,
        )
        assert handler._add_count == 0

    def test_add_cooldown(self):
        handler, _, _, _ = _make_handler()
        handler._last_add_time = time.time()  # just now
        handler._add_count = 1
        session = FakeSession()
        pos_state = _make_pos_state(unrealized_pnl_pct=0.05)
        handler._execute_decision(
            OverseerAction(action="ADD", reason="pyramid again"),
            session, "SYM", 106.0, pos_state,
        )
        assert handler._add_count == 1  # unchanged

    def test_add_max_count(self):
        handler, _, _, _ = _make_handler()
        handler._add_count = MAX_ADDS_PER_POSITION
        session = FakeSession()
        pos_state = _make_pos_state(unrealized_pnl_pct=0.05)
        handler._execute_decision(
            OverseerAction(action="ADD", reason="more"),
            session, "SYM", 106.0, pos_state,
        )
        assert handler._add_count == MAX_ADDS_PER_POSITION  # unchanged


# =====================================================================
# reset_position_state
# =====================================================================

class TestResetPositionState:
    def test_resets_add_state(self):
        handler, *_ = _make_handler()
        handler._add_count = 2
        handler._last_add_time = 999.0
        handler.reset_position_state()
        assert handler._add_count == 0
        assert handler._last_add_time == 0.0


# =====================================================================
# Timeout test
# =====================================================================

class TestTimeout:
    def test_timeout_returns_hold(self):
        """When LLM predict() times out, overseer should default to no action (HOLD)."""
        import concurrent.futures

        handler, gen_ai, tm, storage = _make_handler()

        # Make predict hang
        def slow_predict(*args):
            time.sleep(10)
            return '{"action":"HOLD","reason":"slow"}'
        gen_ai.llm_adapter.predict.side_effect = slow_predict

        session = FakeSession()
        mock_pos = MagicMock()
        mock_pos.status = "OPEN"
        mock_pos.id = "pos-1"
        session.portfolio.positions = [mock_pos]

        mp = MagicMock()
        mp.position_id = "pos-1"
        tm._positions = {"pos-1": mp}
        tm.get_position_state.return_value = _make_pos_state()
        tm.get_position_metrics.return_value = {}

        tick = MagicMock()
        tick.close = 105.0
        tick.delta = 10.0
        tick.vwap = 100.0
        tick.volume = 1000

        amt = MagicMock()
        amt.market_state = "BALANCED"
        amt.value_area_high = 110.0
        amt.value_area_low = 90.0
        amt.poc = 100.0
        amt.cvd_slope = 0.0
        amt.cvd_divergence = None
        amt.aggressive_prints = []

        # Override timeout to 0.1s for test speed
        with patch('app.application.handlers.llm_overseer_handler.settings') as mock_settings:
            mock_settings.LLM_TIMEOUT_SECONDS = 0.1
            handler.run_overseer(session, "SYM", tick, amt)

        # _llm_queues is a per-symbol dict after the multi-symbol refactor
        q = handler._llm_queues.get("SYM")
        if q:
            q.join()

        # No trade actions should have been taken (timeout → HOLD)
        tm.adjust_stop_loss.assert_not_called()
        session.portfolio.close_position.assert_not_called()


# =====================================================================
# Probability override test (unit-level, tests _worker logic directly)
# =====================================================================

class TestProbabilityOverride:
    def test_high_reversal_overrides_hold_to_exit(self):
        """When exit_probability > 0.65 and LLM says HOLD, override to FULL_EXIT."""
        # Create mock probability engine that returns low P(long wins) = high P(adverse)
        from quant.contracts.ports.probability_inference import ProbabilityEstimate
        prob_engine = MagicMock()
        prob_engine.is_ready.return_value = True
        def fake_estimate(features):
            return ProbabilityEstimate(
                p_long_target=0.20, p_short_target=0.80,
                expected_mfe_long=0.0, expected_mfe_short=0.0,
            )
        prob_engine.estimate.side_effect = fake_estimate

        # Patch extract_features to return dummy features so the probability path succeeds
        def fake_extract_features(*args, **kwargs):
            from quant.probability.features import FEATURE_NAMES
            return {name: 0.0 for name in FEATURE_NAMES}
        
        with patch('quant.probability.features.extract_features', side_effect=fake_extract_features):

            handler, gen_ai, tm, storage = _make_handler(
                predict_return='{"action":"HOLD","reason":"looks fine"}',
                probability_engine=prob_engine,
            )

            # Need 20+ data bars for probability engine to fire
            from quant.contracts.value_objects import OHLC
            fake_bars = [OHLC(open=100, high=101, low=99, close=100, volume=1000, delta=0, time="2025-01-01T10:00:00Z", vwap=100)] * 25
            session = FakeSession(data=fake_bars)
            mock_pos = MagicMock()
            mock_pos.status = "OPEN"
            mock_pos.id = "pos-1"
            mock_pos.symbol = "SYM"
            mock_pos.side.value = "LONG"
            mock_pos.entry_price = 100.0
            mock_pos.is_open = True
            mock_pos.partial_taken = False
            session.portfolio.positions = [mock_pos]

            mp = MagicMock()
            mp.position_id = "pos-1"
            tm._positions = {"pos-1": mp}
            tm.get_position_state.return_value = _make_pos_state()
            tm.get_position_metrics.return_value = {}

            tick = MagicMock()
            tick.close = 105.0
            tick.delta = 10.0
            tick.vwap = 100.0
            tick.volume = 1000
            tick.open = 100.0
            tick.high = 106.0
            tick.low = 99.0
            tick.time = "2025-01-01T10:30:00Z"

            amt = MagicMock()
            amt.market_state = "BALANCED"
            amt.value_area_high = 110.0
            amt.value_area_low = 90.0
            amt.poc = 100.0
            amt.cvd_slope = 0.0
            amt.cvd_divergence = None
            amt.aggressive_prints = []
            amt.aggression = 0.5
            amt.session_vwap = 100.0
            amt.hvns = []
            amt.lvns = []
            amt.leg_poc = 0
            amt.leg_lvns = []
            amt.profile_shape = "D"
            amt.lvn_play = None

            handler.run_overseer(session, "SYM", tick, amt)
            # _llm_queues is a per-symbol dict after the multi-symbol refactor
            q = handler._llm_queues.get("SYM")
            if q:
                q.join()

            # Should have called close_position due to probability override
            # P(long wins) = 0.20, so P(adverse for LONG) = 0.80 > 0.65 → FULL_EXIT
            session.portfolio.close_position.assert_called_once()
