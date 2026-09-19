"""Fabio AMT GatePipeline rule matrix tests.

Systematically validates each gate and the full DecisionService.evaluate()
pipeline across controlled DecisionContext scenarios:

- Gate 1: session phase, warmup, setup permission, spread
- Gate 2: position/cooldown, thesis-flip exception
- Gate 3: Triple-A edge guards and setup paths
- Gate 4: stop-width cap
- DecisionService: full evaluation with VA-fade fallback

Each test constructs a synthetic DecisionContext with known fields and
asserts the exact gate results and decision outcomes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quant.bars import Bar  # noqa: E402
from quant.contracts.enums import MarketState  # noqa: E402
from quant.decision.context import DecisionContext  # noqa: E402
from quant.decision.decision_service import DecisionService, QuantDecision  # noqa: E402
from quant.decision.pipeline import GatePipeline  # noqa: E402
from quant.decision.result import GateResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(close: float = 100.0, time: str = "1787664660") -> Bar:
    return Bar(
        time=time, open=100.0, high=101.0, low=99.0,
        close=close, volume=1000.0, vwap=100.0,
        buy_volume=500.0, sell_volume=500.0, oi=10000.0, delta=0.0,
    )


def _make_ctx(**overrides) -> DecisionContext:
    """Build a DecisionContext with sensible defaults; override any field."""
    defaults = dict(
        bar=_make_bar(),
        symbol="TEST_SYMBOL",
        market="MCX",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        position_side="",
        cooldown_remaining_sec=0,
        risk_halted=False,
        agent_direction="LONG",
        agent_probability=0.0,
        market_state=MarketState.BALANCED,
        balance_ratio=0.5,
        tick_size=0.05,
        bid=99.95,
        ask=100.05,
        time_str="1787664660",
        session_phase="OPENING",
        allow_trend=True,
        allow_reversion=True,
    )
    defaults.update(overrides)
    return DecisionContext(**defaults)


def _gate_passed(results: list[GateResult], gate_no: int) -> bool:
    """Check if a specific gate passed."""
    for r in results:
        if r.gate == gate_no:
            return r.passed
    return False


def _gate_reason(results: list[GateResult], gate_no: int) -> str:
    """Get the reason string for a specific gate."""
    for r in results:
        if r.gate == gate_no:
            return r.reason or ""
    return ""


# ---------------------------------------------------------------------------
# Gate 1: Session Phase
# ---------------------------------------------------------------------------


class TestGate1SessionPhase:
    def test_session_closed_rejected(self):
        ctx = _make_ctx(session_open=False)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 1)
        assert "Session closed" in _gate_reason(results, 1)

    def test_warmup_incomplete_rejected(self):
        ctx = _make_ctx(warmup_complete=False)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 1)
        assert "insufficient bars" in _gate_reason(results, 1).lower()

    def test_normal_session_passes(self):
        ctx = _make_ctx()
        results = GatePipeline().evaluate(ctx)
        assert _gate_passed(results, 1)

    def test_wide_spread_rejected(self):
        # Spread must exceed 4% of close (4% of 100.0 = 4.0) to be rejected
        ctx = _make_ctx(bid=99.0, ask=105.0)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 1)
        assert "spread" in _gate_reason(results, 1).lower()


# ---------------------------------------------------------------------------
# Gate 2: Position / Cooldown
# ---------------------------------------------------------------------------


class TestGate2PositionCooldown:
    def test_position_open_rejected(self):
        ctx = _make_ctx(position_open=True)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 2)
        assert "Position already open" in _gate_reason(results, 2)

    def test_cooldown_active_rejected(self):
        ctx = _make_ctx(cooldown_remaining_sec=30)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 2)
        assert "cooldown" in _gate_reason(results, 2).lower()

    def test_no_position_no_cooldown_passes(self):
        ctx = _make_ctx()
        results = GatePipeline().evaluate(ctx)
        assert _gate_passed(results, 2)

    def test_thesis_flip_bypasses_position_block(self):
        """allow_positioned=True bypasses the position blocker only."""
        ctx = _make_ctx(position_open=True)
        results = GatePipeline().evaluate(ctx, allow_positioned=True)
        assert _gate_passed(results, 2)
        assert "thesis-flip" in _gate_reason(results, 2)

    def test_cooldown_still_enforced_with_thesis_flip(self):
        """Cooldown seconds always enforce, even with allow_positioned."""
        ctx = _make_ctx(position_open=True, cooldown_remaining_sec=15)
        results = GatePipeline().evaluate(ctx, allow_positioned=True)
        assert not _gate_passed(results, 2)
        assert "cooldown" in _gate_reason(results, 2).lower()


# ---------------------------------------------------------------------------
# Gate 3: Triple-A Edge
# ---------------------------------------------------------------------------


class TestGate3TripleAEdge:
    def test_no_direction_rejected(self):
        ctx = _make_ctx(agent_direction=None)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 3)

    def test_dead_market_rejected(self):
        ctx = _make_ctx(market_state=MarketState.DEAD)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 3)
        assert "dead market" in _gate_reason(results, 3).lower()

    def test_no_edge_no_setup_rejected(self):
        """No setup evidence, no triple-a signal, no drive, no LVN → rejected."""
        ctx = _make_ctx()
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 3)
        assert "no" in _gate_reason(results, 3).lower() or "No Triple-A" in _gate_reason(results, 3)

    def test_anti_climax_long_rejected(self):
        """Price above +2σ VWAP rejects LONG."""
        ctx = _make_ctx(
            agent_direction="LONG",
            vwap_upper_2=100.5,
            vwap_std=2.0,
        )
        # bar.close=100.0 < vwap_upper_2=100.5, so no anti-climax
        # Need close > vwap_upper_2
        ctx = _make_ctx(
            bar=_make_bar(close=101.0),
            agent_direction="LONG",
            vwap_upper_2=100.5,
            vwap_std=2.0,
        )
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 3)
        assert "anti-climax" in _gate_reason(results, 3).lower()


# ---------------------------------------------------------------------------
# Gate 4: Risk-Reward (Stop Cap)
# ---------------------------------------------------------------------------


class TestGate4RiskReward:
    def test_no_bar_rejected(self):
        ctx = _make_ctx(bar=None)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 4)

    def test_no_direction_rejected(self):
        ctx = _make_ctx(agent_direction=None)
        results = GatePipeline().evaluate(ctx)
        assert not _gate_passed(results, 4)

    def test_normal_stop_passes(self):
        """A normal stop distance should pass the cap."""
        ctx = _make_ctx()
        results = GatePipeline().evaluate(ctx)
        # Gate 4 checks stop width against cap; with default bar at 100.0
        # and tick_size=0.05, the cap is max(200, 100*0.0075/0.05) = max(200, 15) = 200 ticks
        # Structural stop should be well within 200 ticks
        assert _gate_passed(results, 4)


# ---------------------------------------------------------------------------
# DecisionService.evaluate() — Full Pipeline
# ---------------------------------------------------------------------------


class TestDecisionServiceEvaluate:
    def test_risk_halted_returns_halted(self):
        ctx = _make_ctx(risk_halted=True)
        decision = DecisionService().evaluate(ctx)
        assert not decision.approved
        assert decision.reason == "HALTED"

    def test_risk_halted_bypassed_for_thesis_flip(self):
        """allow_positioned=True bypasses the risk halt check."""
        ctx = _make_ctx(risk_halted=True)
        decision = DecisionService().evaluate(ctx, allow_positioned=True)
        # Should NOT be HALTED — halt check is bypassed
        assert decision.reason != "HALTED"

    def test_no_bar_returns_no_edge(self):
        ctx = _make_ctx(bar=None)
        decision = DecisionService().evaluate(ctx)
        assert not decision.approved
        assert decision.reason == "NO_EDGE"

    def test_gate1_failure_hard_rejects_no_fade(self):
        """Gate 1 failure → GATE_REJECTED, no VA-fade fallback."""
        ctx = _make_ctx(session_open=False)
        decision = DecisionService().evaluate(ctx)
        assert not decision.approved
        assert decision.reason == "GATE_REJECTED"

    def test_gate2_failure_hard_rejects_no_fade(self):
        """Gate 2 failure (position open) → GATE_REJECTED, no VA-fade fallback."""
        ctx = _make_ctx(position_open=True)
        decision = DecisionService().evaluate(ctx)
        assert not decision.approved
        assert decision.reason == "GATE_REJECTED"

    def test_dead_market_no_edge(self):
        """Dead market after gates → NO_EDGE (no fade allowed)."""
        ctx = _make_ctx(
            market_state=MarketState.DEAD,
            agent_direction="LONG",
        )
        decision = DecisionService().evaluate(ctx)
        assert not decision.approved
        assert decision.reason == "NO_EDGE"

    def test_block_reasons_populated_on_rejection(self):
        """Rejected decisions carry block_reasons for UI/logs."""
        ctx = _make_ctx(session_open=False)
        decision = DecisionService().evaluate(ctx)
        assert len(decision.block_reasons) > 0, (
            "Rejected decision should have block_reasons"
        )

    def test_gate_results_tuple_populated(self):
        """Every evaluation carries gate_results for audit."""
        ctx = _make_ctx()
        decision = DecisionService().evaluate(ctx)
        assert len(decision.gate_results) > 0, (
            "Decision should have gate_results"
        )
