"""Entry-flow gating tests (Task 3 of AMT Strategy Cleanup).

Verifies:
- ``_last_entry_candle_time`` is initialized at session create and advanced on
  EVERY closed candle (not just when a signal is built) so ``is_new_candle``
  is meaningful from tick one (audit defect C.2).
- The entry LLM gate is event-driven: candle close OR monitoring cadence OR
  structural event triggers (market-state transition, VWAP ±2σ cross, new
  break/absorption), always with a 60s floor.
- The dead ``run_overseer`` variable is removed from the tick path.
"""

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from quant.contracts.value_objects import OHLC, AMTResult
from app.application.services.session_state_manager import (
    SessionState,
    SessionStateManager,
)
from app.application.services.session_orchestrator import SessionOrchestrator
from app.application.services.session_runtime_contracts import LLMTriggerContract


def _tick(close=100.0, time_str="2026-01-15T10:30:00Z"):
    return OHLC(
        time=time_str,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=500.0,
        vwap=100.0,
        delta=100.0,
    )


def _amt(market_state="BALANCED", **kw):
    kwargs = dict(
        market_state=market_state,
        poc=100.0,
        value_area_high=105.0,
        value_area_low=95.0,
    )
    kwargs.update(kw)
    return AMTResult(**kwargs)


# ---------------------------------------------------------------------------
# Session create: _last_entry_candle_time initialized
# ---------------------------------------------------------------------------

def test_last_entry_candle_time_initialized_at_session_create():
    manager = SessionStateManager(storage=None)
    session = manager.get_or_create_session("SYM")
    assert session._last_entry_candle_time == ""


# ---------------------------------------------------------------------------
# is_new_candle must be driven by the closed-candle cursor, not the signal build
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_deps():
    broker = MagicMock()
    broker.execute_order.return_value = None
    gen_ai = MagicMock()
    gen_ai.is_ready.return_value = False  # Prevent entry LLM fires
    storage = MagicMock()
    storage.get_recent_trades.return_value = []
    storage.get_previous_session_profile.return_value = None
    storage.load_open_positions.return_value = []
    storage.kv_get.return_value = None
    probability_engine = MagicMock()
    probability_engine.is_ready.return_value = False
    return {
        "broker": broker,
        "gen_ai": gen_ai,
        "storage": storage,
        "probability_engine": probability_engine,
    }


def _make_service(mock_deps):
    with patch("app.application.services.forward_test_logger.ForwardTestLogger") as mock_fwd:
        mock_fwd.side_effect = Exception("no-op")
        from app.application.services.trading_session import TradingSessionService
        return TradingSessionService(
            broker=mock_deps["broker"],
            gen_ai_service=mock_deps["gen_ai"],
            storage=mock_deps["storage"],
            probability_engine=mock_deps["probability_engine"],
        )


@pytest.fixture
def cleanup_service_handlers():
    services = []
    yield services
    for svc in services:
        if hasattr(svc, "_llm_handler"):
            svc._llm_handler.cleanup()
        if hasattr(svc, "_overseer_handler"):
            svc._overseer_handler.cleanup()


def test_last_entry_candle_time_advances_on_closed_candle_even_when_entry_blocked(
    mock_deps, cleanup_service_handlers
):
    """No entry decision is ever built (gen_ai not ready) yet the entry cursor
    must advance on each closed candle so is_new_candle is meaningful."""
    svc = _make_service(mock_deps)
    cleanup_service_handlers.append(svc)
    session = svc.get_or_create_session("NIFTY")
    session.trading_state = "TRADABLE"
    session._last_monitoring_llm = time.time()  # silence monitoring cadence
    cache = svc._get_cache("NIFTY")

    t1 = _tick(close=100.0, time_str="2026-01-15T10:30:00Z")
    svc.process_tick("NIFTY", t1)
    assert cache.get_last_entry_candle_time() == t1.time

    # same-candle sub-update must NOT look like a new candle
    t1b = _tick(close=100.5, time_str="2026-01-15T10:30:00Z")
    svc.process_tick("NIFTY", t1b)
    assert cache.get_last_entry_candle_time() == t1.time

    # a genuinely new candle advances the cursor
    t2 = _tick(close=101.0, time_str="2026-01-15T10:35:00Z")
    svc.process_tick("NIFTY", t2)
    assert cache.get_last_entry_candle_time() == t2.time


def test_dead_run_overseer_variable_removed_from_tick_path(
    mock_deps, cleanup_service_handlers
):
    svc = _make_service(mock_deps)
    cleanup_service_handlers.append(svc)
    src = inspect.getsource(svc._on_tick)
    assert "run_overseer =" not in src


# ---------------------------------------------------------------------------
# Structural event triggers (session_orchestrator)
# ---------------------------------------------------------------------------

def test_market_state_transition_event_trigger():
    s = SessionState(symbol="SYM")
    # first observation seeds the cursor — no trigger yet
    assert SessionOrchestrator.detect_market_state_transition(s, "BALANCED") is False
    assert SessionOrchestrator.detect_market_state_transition(s, "IMBALANCED") is True
    # same state again — no repeat
    assert SessionOrchestrator.detect_market_state_transition(s, "IMBALANCED") is False
    assert SessionOrchestrator.detect_market_state_transition(s, "BALANCED") is True
    # transitions into/out of non-event states do not trigger
    assert SessionOrchestrator.detect_market_state_transition(s, "DEAD") is False
    assert SessionOrchestrator.detect_market_state_transition(s, "IMBALANCED") is False


def test_vwap_2sigma_cross_event_trigger():
    s = SessionState(symbol="SYM")
    # first tick — no prior close to cross from
    assert SessionOrchestrator.detect_vwap_sigma_cross(s, 99.0, 101.0, 99.0) is False
    # price breaks above the +2σ band
    assert SessionOrchestrator.detect_vwap_sigma_cross(s, 102.0, 101.0, 99.0) is True
    # remains above — no repeat cross
    assert SessionOrchestrator.detect_vwap_sigma_cross(s, 103.0, 101.0, 99.0) is False
    # breaks below the -2σ band from inside
    assert SessionOrchestrator.detect_vwap_sigma_cross(s, 98.0, 101.0, 99.0) is True


def test_new_break_or_absorption_event_trigger():
    s = SessionState(symbol="SYM")
    assert SessionOrchestrator.detect_new_break_or_absorption(s, "UP", "") is True
    assert SessionOrchestrator.detect_new_break_or_absorption(s, "UP", "") is False
    assert SessionOrchestrator.detect_new_break_or_absorption(s, "DOWN", "") is True
    assert SessionOrchestrator.detect_new_break_or_absorption(s, "", "") is False
    assert SessionOrchestrator.detect_new_break_or_absorption(s, "", "BUY_ABSORBED") is True


def test_resolve_llm_triggers_surfaces_event_trigger_on_market_state_transition():
    session = SessionState(symbol="SYM")
    session._last_market_state = "BALANCED"  # simulate prior tick
    amt = _amt(market_state="IMBALANCED", vwap_upper_2=101.0, vwap_lower_2=99.0)
    tick = _tick(close=100.0)
    contract = SessionOrchestrator.resolve_llm_triggers(
        should_trigger_llm_fn=lambda *a, **k: False,
        session=session,
        has_position=False,
        ai_running=False,
        in_cooldown=False,
        amt_result=amt,
        event=SimpleNamespace(tick=tick),
        ai_time=0.0,
        market_state="IMBALANCED",
        last_monitoring_llm=time.time() - 400,
        now_ts=time.time(),
        trading_enabled=True,
    )
    assert contract.event_trigger is True


# ---------------------------------------------------------------------------
# Entry LLM gate: 60s floor + candle / monitoring / event triggers
# ---------------------------------------------------------------------------

def test_entry_llm_gate_honors_60s_floor():
    now = time.time()
    # 10s since the last LLM call → blocked even with a trigger present
    assert SessionOrchestrator.should_fire_entry_llm(
        trigger_llm=True, is_new_candle=True, monitoring_trigger=False, event_trigger=False,
        last_ai_time=now - 10, now_ts=now, cooldown_seconds=60.0,
    ) is False
    # >60s → fires on candle close
    assert SessionOrchestrator.should_fire_entry_llm(
        trigger_llm=True, is_new_candle=True, monitoring_trigger=False, event_trigger=False,
        last_ai_time=now - 90, now_ts=now, cooldown_seconds=60.0,
    ) is True


def test_entry_llm_gate_fires_on_monitoring_or_event_without_new_candle():
    now = time.time()
    assert SessionOrchestrator.should_fire_entry_llm(
        trigger_llm=False, is_new_candle=False, monitoring_trigger=True, event_trigger=False,
        last_ai_time=now - 90, now_ts=now, cooldown_seconds=60.0,
    ) is True
    assert SessionOrchestrator.should_fire_entry_llm(
        trigger_llm=False, is_new_candle=False, monitoring_trigger=False, event_trigger=True,
        last_ai_time=now - 90, now_ts=now, cooldown_seconds=60.0,
    ) is True
    # same candle, no monitoring, no event → nothing fires
    assert SessionOrchestrator.should_fire_entry_llm(
        trigger_llm=False, is_new_candle=False, monitoring_trigger=False, event_trigger=False,
        last_ai_time=now - 90, now_ts=now, cooldown_seconds=60.0,
    ) is False


# ---------------------------------------------------------------------------
# LLMTriggerContract carries the event trigger flag
# ---------------------------------------------------------------------------

def test_llm_trigger_contract_carries_event_trigger():
    c = LLMTriggerContract(trigger_llm=False, monitoring_trigger=False, event_trigger=True)
    assert c.event_trigger is True
