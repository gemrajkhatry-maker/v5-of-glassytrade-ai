"""Task 4 tests — overseer pos_state completeness, 15s cooldown, bounded drop-busy queue.

Covers:
- pos_state includes stop_loss / take_profit / hold_time_seconds / risk_tier /
  daily_pnl / consecutive_losses / daily_loss_pct / symbol (prompt_builder reads
  these exact keys).
- OVERSEER_COOLDOWN is 15.0 and should_run() enforces it.
- Per-symbol queue is maxsize=2 and a third enqueue drops without blocking.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.application.handlers.llm_overseer_handler import (
    LLMOverseerHandler,
    OVERSEER_COOLDOWN,
)
from quant.contracts.entities import Position, PositionStatus, Side


_created_handlers = []


@pytest.fixture(autouse=True)
def _cleanup_handlers():
    yield
    for h in _created_handlers:
        h.cleanup()
    _created_handlers.clear()


def _make_handler():
    adapter = MagicMock()
    adapter.predict.return_value = '{"action":"HOLD","reason":"test"}'
    gen_ai = MagicMock()
    gen_ai.llm_adapter = adapter
    gen_ai.is_ready.return_value = True
    trade_manager = MagicMock()
    trade_manager.get_position_metrics.return_value = {
        "tick_count": 5,
        "runner_active": False,
        "partial_taken": False,
        "mae": 1.0,
        "mfe": 2.0,
        "cushion_state": "OPEN",
    }
    handler = LLMOverseerHandler(
        gen_ai_service=gen_ai,
        trade_manager=trade_manager,
        storage=MagicMock(),
    )
    _created_handlers.append(handler)
    return handler, gen_ai, trade_manager


class _FakePortfolio:
    def __init__(self, positions):
        self.positions = positions


@dataclass
class _FakeSession:
    portfolio: _FakePortfolio
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_overseer_time: float = 0.0
    _overseer_running: bool = False
    _ai_running: bool = False
    last_ai_analysis: dict | None = None


def _make_position(**overrides) -> Position:
    pos = Position(
        id="pos-1",
        symbol="SYM",
        side=Side.LONG,
        entry_price=Decimal("100.0"),
        size=Decimal("1"),
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("115.0"),
        entry_time=(datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        status=PositionStatus.OPEN,
    )
    for key, value in overrides.items():
        setattr(pos, key, value)
    return pos


def _make_session() -> _FakeSession:
    return _FakeSession(portfolio=_FakePortfolio(positions=[_make_position()]))


def _make_tick():
    tick = MagicMock()
    tick.close = 105.0
    tick.open = 100.0
    tick.high = 106.0
    tick.low = 99.0
    tick.delta = 10.0
    tick.vwap = 100.0
    tick.volume = 1000
    return tick


def _make_amt():
    amt = MagicMock()
    amt.state = "BALANCED"
    amt.market_state = "BALANCED"
    amt.poc = 100.0
    amt.value_area_high = 110.0
    amt.value_area_low = 90.0
    amt.aggression = 0.5
    amt.cvd_slope = 0.0
    amt.cvd_divergence = None
    amt.aggressive_prints = []
    return amt


# =====================================================================
# pos_state completeness
# =====================================================================


class TestPosState:
    def test_pos_state_includes_sl_tp_hold_time_and_risk(self):
        handler, _, _ = _make_handler()
        position = _make_position()
        risk_state = {
            "risk_tier": "MOMENTUM",
            "daily_pnl": 1250.50,
            "consecutive_losses": 2,
            "daily_loss_pct": -0.012,
        }
        pos_state = handler._build_pos_state(position, _make_tick(), _make_amt(), risk_state)

        assert pos_state["symbol"] == "SYM"
        assert pos_state["stop_loss"] == 95.0
        assert pos_state["take_profit"] == 115.0
        assert 115 <= pos_state["hold_time_seconds"] <= 125
        assert pos_state["risk_tier"] == "MOMENTUM"
        assert pos_state["daily_pnl"] == 1250.50
        assert pos_state["consecutive_losses"] == 2
        assert pos_state["daily_loss_pct"] == -0.012

    def test_pos_state_risk_defaults_when_risk_state_missing(self):
        handler, _, _ = _make_handler()
        position = _make_position()
        pos_state = handler._build_pos_state(position, _make_tick(), _make_amt(), None)

        assert pos_state["symbol"] == "SYM"
        assert pos_state["stop_loss"] == 95.0
        assert pos_state["take_profit"] == 115.0
        assert pos_state["hold_time_seconds"] >= 0
        assert pos_state["risk_tier"] == "C"
        assert pos_state["daily_pnl"] == 0.0
        assert pos_state["consecutive_losses"] == 0
        assert pos_state["daily_loss_pct"] == 0.0

    def test_hold_time_seconds_is_zero_without_entry_time(self):
        handler, _, _ = _make_handler()
        position = _make_position(entry_time="")
        pos_state = handler._build_pos_state(position, _make_tick(), _make_amt(), None)
        assert pos_state["hold_time_seconds"] == 0


# =====================================================================
# Cooldown
# =====================================================================


class TestCooldown:
    def test_cooldown_constant_is_15s(self):
        assert OVERSEER_COOLDOWN == 15.0

    def test_should_run_respects_15s_cooldown(self):
        handler, *_ = _make_handler()
        assert (
            handler.should_run(
                last_overseer_time=time.time(),
                overseer_running=False,
                ai_running=False,
                has_position=True,
            )
            is False
        )
        assert (
            handler.should_run(
                last_overseer_time=time.time() - 16,
                overseer_running=False,
                ai_running=False,
                has_position=True,
            )
            is True
        )


# =====================================================================
# Bounded drop-busy queue
# =====================================================================


class TestBoundedQueue:
    def test_queue_maxsize_is_two(self):
        handler, *_ = _make_handler()
        session = _make_session()
        handler.run_overseer(session, "SYM", _make_tick(), _make_amt())
        assert handler._llm_queues["SYM"].maxsize == 2

    def test_third_enqueue_drops_without_blocking(self):
        handler, *_ = _make_handler()
        session = _make_session()

        # Pre-fill the queue (worker thread never spawned for a known symbol)
        # so put_nowait must raise queue.Full on the third attempt.
        handler._llm_queues["SYM"] = queue.Queue(maxsize=2)
        handler._llm_queues["SYM"].put("first")
        handler._llm_queues["SYM"].put("second")

        handler.run_overseer(session, "SYM", _make_tick(), _make_amt())

        assert handler._llm_queues["SYM"].qsize() == 2
        assert session._overseer_running is False
