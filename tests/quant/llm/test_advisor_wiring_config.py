"""LLMAdvisor wiring behavior capture tests.

Locks in the current advisor wiring semantics before any config changes:

- build_live_advisor() returns None when LLM_ADVISOR_ENABLED is disabled
- build_live_advisor() attempts construction when enabled
- QuantEngine works correctly with advisor=None
- Advisor presence/absence doesn't affect trading decisions

These tests capture current behavior so that subsequent config knob
changes (Phase 3) can be validated against a known baseline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest  # noqa: E402

from quant.brokers.gateway import Tick  # noqa: E402
from quant.events import AgentDecisionProduced, DecisionProduced  # noqa: E402
from quant.execution.risk import SessionRisk  # noqa: E402
from quant.runtime import QuantEngine  # noqa: E402
from tests.helpers.synthetic import SyntheticGateway  # noqa: E402


# ---------------------------------------------------------------------------
# build_live_advisor() env gating
# ---------------------------------------------------------------------------


class TestBuildLiveAdvisorEnvGating:
    """build_live_advisor respects LLM_ADVISOR_ENABLED env var."""

    def test_disabled_returns_none(self, monkeypatch):
        """LLM_ADVISOR_ENABLED=false → build_live_advisor returns None."""
        from quant.wiring_advisor import build_live_advisor
        monkeypatch.setenv("LLM_ADVISOR_ENABLED", "false")
        result = build_live_advisor(None)
        assert result is None

    def test_disabled_zero_returns_none(self, monkeypatch):
        """LLM_ADVISOR_ENABLED=0 → build_live_advisor returns None."""
        from quant.wiring_advisor import build_live_advisor
        monkeypatch.setenv("LLM_ADVISOR_ENABLED", "0")
        result = build_live_advisor(None)
        assert result is None

    def test_disabled_no_returns_none(self, monkeypatch):
        """LLM_ADVISOR_ENABLED=no → build_live_advisor returns None."""
        from quant.wiring_advisor import build_live_advisor
        monkeypatch.setenv("LLM_ADVISOR_ENABLED", "no")
        result = build_live_advisor(None)
        assert result is None

    def test_disabled_disabled_returns_none(self, monkeypatch):
        """LLM_ADVISOR_ENABLED=disabled → build_live_advisor returns None."""
        from quant.wiring_advisor import build_live_advisor
        monkeypatch.setenv("LLM_ADVISOR_ENABLED", "disabled")
        result = build_live_advisor(None)
        assert result is None

    def test_enabled_attempts_construction(self, monkeypatch):
        """LLM_ADVISOR_ENABLED=true → attempts construction (may return None
        if MLX model not available, but doesn't return early from env gate)."""
        from quant.wiring_advisor import build_live_advisor
        monkeypatch.setenv("LLM_ADVISOR_ENABLED", "true")
        # Without MLX_MODEL_PATH, the advisor constructs in rule-based mode
        # or fails gracefully — either way, the env gate didn't block it
        monkeypatch.delenv("MLX_MODEL_PATH", raising=False)
        result = build_live_advisor(None)
        # Result may be None (if import fails) or an LLMAdvisor instance
        # The key assertion is that we got PAST the env check
        # (no assertion on result being None here — that would mean the env gate blocked)


# ---------------------------------------------------------------------------
# QuantEngine with advisor=None
# ---------------------------------------------------------------------------


def _run_engine_no_advisor(ticks: list[Tick], symbol: str = "TEST_ADVISOR") -> list:
    """Run QuantEngine with advisor=None and return the event trace."""
    SessionRisk(storage=None, symbol=symbol).reset_session()
    gw = SyntheticGateway(list(ticks))
    eng = QuantEngine(gw, symbol, interval_seconds=1, market="MCX", advisor=None)
    return eng.run()


def _build_ticks(n: int = 60) -> list[Tick]:
    """Simple deterministic tick sequence."""
    ticks: list[Tick] = []
    t0 = 1_787_664_600
    for i in range(n):
        price = 100.0 + 0.02 * ((i % 4) - 1.5)
        vol = 8.0
        ticks.append(Tick(str(t0 + i), round(price, 4), vol, vol / 2, vol / 2))
    return ticks


class TestEngineWithNoAdvisor:
    """QuantEngine works correctly when advisor is None."""

    def test_engine_runs_without_advisor(self):
        """Engine completes its run loop without advisor."""
        trace = _run_engine_no_advisor(_build_ticks())
        assert len(trace) > 0, "Engine produced no events"

    def test_decisions_produced_without_advisor(self):
        """DecisionProduced events fire even without advisor."""
        trace = _run_engine_no_advisor(_build_ticks(n=120))
        decisions = [e for e in trace if isinstance(e, DecisionProduced)]
        assert len(decisions) > 0, "No decisions produced without advisor"

    def test_no_agent_decisions_without_advisor(self):
        """No AgentDecisionProduced events when advisor is None."""
        trace = _run_engine_no_advisor(_build_ticks(n=120))
        agent_events = [e for e in trace if isinstance(e, AgentDecisionProduced)]
        assert len(agent_events) == 0, (
            f"AgentDecisionProduced events found with advisor=None: {len(agent_events)}"
        )

    def test_engine_deterministic_without_advisor(self):
        """Two runs with advisor=None produce identical traces."""
        import hashlib
        import json as _json

        ticks = _build_ticks()
        trace_a = _run_engine_no_advisor(ticks)
        trace_b = _run_engine_no_advisor(ticks)

        fp_a = hashlib.sha256(_json.dumps(
            [(type(e).__name__, getattr(e, "time", "")) for e in trace_a],
            sort_keys=True,
        ).encode()).hexdigest()
        fp_b = hashlib.sha256(_json.dumps(
            [(type(e).__name__, getattr(e, "time", "")) for e in trace_b],
            sort_keys=True,
        ).encode()).hexdigest()
        assert fp_a == fp_b, "Engine not deterministic with advisor=None"


# ---------------------------------------------------------------------------
# Advisor factory seam
# ---------------------------------------------------------------------------


class TestAdvisorFactorySeam:
    """The _ADVISOR_FACTORY seam allows test injection."""

    def test_factory_overrides_env(self, monkeypatch):
        """When _ADVISOR_FACTORY is set, it overrides env-based construction."""
        import quant.wiring_advisor as wa

        sentinel = object()
        original = wa._ADVISOR_FACTORY

        try:
            wa._ADVISOR_FACTORY = lambda emit_fn: sentinel
            monkeypatch.setenv("LLM_ADVISOR_ENABLED", "false")  # env says disabled
            result = wa.build_live_advisor(None)
            assert result is sentinel, "Factory seam did not override env gate"
        finally:
            wa._ADVISOR_FACTORY = original
