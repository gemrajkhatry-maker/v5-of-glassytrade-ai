"""Focused tests for LLMEntryHandler — session quant gate, should_run, regime DEAD.

Legacy900+ line suite was skipped (stale vs current handler). These cases track
behaviour that must not regress: session phase bypass, AMT/LLM gating, quant DEAD.
Broader session-calendar coverage: test_llm_session_market_resolution.py.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.llm_entry_handler import LLMEntryHandler
from quant.probability.agent_pipeline import AgentDecision
from quant.contracts.value_objects import AMTResult, OHLC


def _amt(**kwargs: object) -> AMTResult:
    base = {
        "market_state": "IMBALANCE",
        "poc": 100.0,
        "value_area_high": 105.0,
        "value_area_low": 95.0,
    }
    base.update(kwargs)
    return AMTResult(**base)  # type: ignore[arg-type]


def _tick(ts: str = "2025-01-15T10:00:00+05:30") -> OHLC:
    return OHLC.create(ts, 100.0, 101.0, 99.0, 100.0, 1000.0)


class _SessionStub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_ai_time = 0.0
        self._ai_running = False
        self.last_ai_analysis: dict | None = None
        self.data = [OHLC.create("2025-01-15T09:20:00+05:30", 100.0, 101.0, 99.0, 100.0, 500.0)]
        self.order_book = None
        self._llm_memory: list[str] = []
        self._agent_decision = None
        self._prior_profile = None
        self._prior_print_levels: list[float] = []
        self._last_fp_domain = None


def test_run_entry_session_phase_blocks_persists_quant_phase_blocked():
    gen = MagicMock()
    gen.is_ready.return_value = True
    storage = MagicMock()
    handler = LLMEntryHandler(gen_ai_service=gen, storage=storage, exchange="NSE")
    session = _SessionStub()
    amt = _amt()
    tick = _tick()
    blocked = SimpleNamespace(
        allow_entry=False,
        session="RESTRICTED_PHASE",
        allow_trend=False,
    )
    with patch(
        "app.application.handlers.llm_entry_handler.get_session_info",
        return_value=blocked,
    ):
        handler.run_entry(session, "NIFTY 27 MAR 23000 CE", tick, amt)

    assert session.last_ai_analysis is not None
    assert session.last_ai_analysis["raw_output"] == "QUANT_PHASE_BLOCKED"
    assert session.last_ai_analysis["direction"] == "FLAT"
    assert session._ai_running is False
    storage.save_llm_decision.assert_called_once()
    call_kw = storage.save_llm_decision.call_args[0][0]
    assert call_kw.get("raw_output") == "QUANT_PHASE_BLOCKED"


@patch.object(LLMEntryHandler, "_build_gate_context", return_value=("", False))
def test_run_entry_quant_regime_dead_skips_llm_queue(_mock_gate_ctx):
    gen = MagicMock()
    gen.is_ready.return_value = True
    handler = LLMEntryHandler(gen_ai_service=gen, exchange="NSE")
    session = _SessionStub()
    session._agent_decision = AgentDecision(
        direction="LONG",
        probability=0.62,
        regime="DEAD",
        playbook="return_to_value",
        timing="ENTER_NOW",
        size_fraction=0.1,
        sl_adjust=1.0,
        tp_adjust=1.0,
        latency_us=0,
        rationale="test",
    )
    amt = _amt(market_state="BALANCED")
    tick = _tick()
    allowed = SimpleNamespace(
        allow_entry=True,
        session="NSE_PRIMARY",
        allow_trend=True,
    )
    with patch(
        "app.application.handlers.llm_entry_handler.get_session_info",
        return_value=allowed,
    ):
        handler.run_entry(session, "NIFTY 27 MAR 23000 CE", tick, amt)

    assert session.last_ai_analysis is not None
    assert session.last_ai_analysis["raw_output"] == "QUANT_DEAD_MARKET"
    assert session._ai_running is False


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"poc": 0.0}, False),
        ({"value_area_high": 0.0}, False),
        ({"market_state": "DEAD"}, False),
    ],
)
def test_should_run_false_amt_or_state(kwargs, expected):
    gen = MagicMock()
    gen.is_ready.return_value = True
    handler = LLMEntryHandler(gen_ai_service=gen)
    amt = _amt(**kwargs)
    ok = handler.should_run(
        last_ai_time=time.time() - 120.0,
        ai_running=False,
        has_position=False,
        has_managed_positions=False,
        in_cooldown=False,
        amt_result=amt,
    )
    assert ok is expected


def test_should_run_false_when_ai_running_or_position_or_cooldown_or_not_ready():
    gen = MagicMock()
    gen.is_ready.return_value = True
    handler = LLMEntryHandler(gen_ai_service=gen)
    amt = _amt()
    assert handler.should_run(
        last_ai_time=time.time() - 120.0,
        ai_running=True,
        has_position=False,
        has_managed_positions=False,
        in_cooldown=False,
        amt_result=amt,
    ) is False
    assert handler.should_run(
        last_ai_time=time.time() - 120.0,
        ai_running=False,
        has_position=True,
        has_managed_positions=False,
        in_cooldown=False,
        amt_result=amt,
    ) is False
    assert handler.should_run(
        last_ai_time=time.time() - 5.0,
        ai_running=False,
        has_position=False,
        has_managed_positions=False,
        in_cooldown=False,
        amt_result=amt,
    ) is False
    gen.is_ready.return_value = False
    assert handler.should_run(
        last_ai_time=time.time() - 120.0,
        ai_running=False,
        has_position=False,
        has_managed_positions=False,
        in_cooldown=False,
        amt_result=amt,
    ) is False


def test_should_run_true_when_spacing_and_amt_ok():
    gen = MagicMock()
    gen.is_ready.return_value = True
    handler = LLMEntryHandler(gen_ai_service=gen)
    amt = _amt()
    assert handler.should_run(
        last_ai_time=time.time() - 60.0,
        ai_running=False,
        has_position=False,
        has_managed_positions=False,
        in_cooldown=False,
        amt_result=amt,
    ) is True
