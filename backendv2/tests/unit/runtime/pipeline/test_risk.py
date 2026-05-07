"""Tests for the RiskEvaluation pipeline stage.

Covers safety gates (kill switch, flash crash, circuit breaker, position lifecycle),
snapshot/restore round-trips, and per-symbol isolation.
"""

from __future__ import annotations

import pytest
from decimal import Decimal

from app.runtime.pipeline.risk import RiskEvaluation
from app.runtime.pipeline.events import (
    GateResult,
    GateResultType,
    RiskResult,
    Signal,
    PositionEvent,
)


def _make_signal(symbol: str = "BANKNIFTY", signal_type: str = "LONG",
                 entry: float = 45000.0) -> Signal:
    return Signal(
        symbol=symbol,
        timestamp=1_700_000_000_000_000_000,
        type=signal_type,
        entry=entry,
        sl=entry - 100.0,
        tp=entry + 200.0,
        rr=2.0,
        confidence=0.75,
        reason="test",
    )


def _make_gate(symbol: str = "BANKNIFTY", result: GateResultType = GateResultType.APPROVED,
               signal: Signal | None = None) -> GateResult:
    return GateResult(
        symbol=symbol,
        timestamp=1_700_000_000_000_000_000,
        signal=signal or _make_signal(symbol),
        result=result,
    )


# ---------------------------------------------------------------------------
# 1. Safety gate tests
# ---------------------------------------------------------------------------

class TestKillSwitch:
    """Kill switch blocks trading when active."""

    def test_blocks_when_kill_switch_active(self) -> None:
        risk = RiskEvaluation()
        state = risk._state_for("BANKNIFTY")
        # The actual blocking gate is RiskManager._daily.halted (the standalone
        # KillSwitch on _SymbolRiskState is for snapshot/telemetry only).
        state.kill_switch.trigger("manual halt")
        state.risk_manager._daily.halted = True
        state.risk_manager._daily.halt_reason = "manual halt"

        gate = _make_gate()
        results = risk.process(gate)

        assert len(results) == 1
        r = results[0]
        assert r.approved is False
        assert r.kill_switch_active is True

    def test_blocks_via_daily_halt(self) -> None:
        risk = RiskEvaluation()
        state = risk._state_for("BANKNIFTY")
        state.risk_manager._daily.halted = True
        state.risk_manager._daily.halt_reason = "daily halt"

        gate = _make_gate()
        results = risk.process(gate)

        assert len(results) == 1
        assert results[0].approved is False
        assert results[0].kill_switch_active is False  # standalone KS not triggered
        assert "daily halt" in results[0].rejection_reason

    def test_passes_when_kill_switch_inactive(self) -> None:
        risk = RiskEvaluation()
        gate = _make_gate()
        results = risk.process(gate)

        assert len(results) == 1
        assert results[0].approved is True
        assert results[0].kill_switch_active is False


class TestFlashCrashProtector:
    """Flash crash protector blocks on price velocity."""

    def test_blocks_on_flash_crash_velocity(self) -> None:
        risk = RiskEvaluation()
        symbol = "NIFTY"

        # Feed a rapid price drop: 100 -> 96 is 4% in <5 seconds (>2% flash threshold)
        risk.observe_price(symbol, 100.0, 1_000_000_000)
        risk.observe_price(symbol, 96.0, 1_000_000_004)

        gate = _make_gate(symbol=symbol)
        results = risk.process(gate)

        assert len(results) == 1
        r = results[0]
        assert r.approved is False
        assert r.circuit_breaker_triggered is True
        assert r.kill_switch_active is True
        assert "Flash crash" in r.rejection_reason

    def test_passes_on_normal_velocity(self) -> None:
        risk = RiskEvaluation()
        symbol = "NIFTY"

        # Small price change within normal bounds
        risk.observe_price(symbol, 100.0, 1_000_000_000)
        risk.observe_price(symbol, 100.1, 1_000_000_004)

        gate = _make_gate(symbol=symbol)
        results = risk.process(gate)

        assert len(results) == 1
        assert results[0].approved is True


class TestCircuitBreaker:
    """Circuit breaker blocks on consecutive losses or daily drawdown."""

    def test_blocks_after_consecutive_losses(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        # RiskManager blocks at >=3 consecutive losses, so the circuit breaker
        # evaluate path is only reached when consecutive_losses < 3.  To exercise
        # the CircuitBreakers code path we set a large negative session_pnl that
        # exceeds the daily drawdown threshold (0.5% of default 1M equity = 5000).
        state = risk._state_for(symbol)
        state.risk_manager._daily.consecutive_losses = 2
        state.risk_manager._daily.realized_pnl = -6000.0

        gate = _make_gate(symbol=symbol)
        results = risk.process(gate)

        assert len(results) == 1
        r = results[0]
        assert r.approved is False
        assert r.circuit_breaker_triggered is True
        assert r.kill_switch_active is True

    def test_blocks_on_risk_manager_consecutive_losses(self) -> None:
        """RiskManager itself rejects when consecutive losses >= 3."""
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        state = risk._state_for(symbol)
        state.risk_manager._daily.consecutive_losses = 5

        gate = _make_gate(symbol=symbol)
        results = risk.process(gate)

        assert len(results) == 1
        assert results[0].approved is False
        assert "Consecutive losses" in results[0].rejection_reason

    def test_passes_when_losses_within_limit(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        # Under the consecutive loss limit
        state = risk._state_for(symbol)
        state.risk_manager._daily.consecutive_losses = 1

        gate = _make_gate(symbol=symbol)
        results = risk.process(gate)

        assert len(results) == 1
        assert results[0].approved is True
        assert results[0].circuit_breaker_triggered is False


class TestPositionLifecycle:
    """Position lifecycle events update portfolio state."""

    def test_open_position_updates_portfolio(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        event = PositionEvent(
            symbol=symbol,
            timestamp=1_700_000_000_000_000_000,
            event_type="OPENED",
            position_id="pos-1",
            entry_price=45000.0,
            size=10.0,
            side="LONG",
            stop_loss=44900.0,
            take_profit=45200.0,
        )
        risk.sync_position_event(event)

        state = risk._state_for(symbol)
        assert len(state.portfolio.positions) == 1
        pos = state.portfolio.positions[0]
        assert pos.id == "pos-1"
        assert float(pos.entry_price) == 45000.0

    def test_close_position_updates_balance(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        # Open first
        risk.sync_position_event(PositionEvent(
            symbol=symbol,
            timestamp=1_700_000_000_000_000_000,
            event_type="OPENED",
            position_id="pos-1",
            entry_price=45000.0,
            size=10.0,
            side="LONG",
            stop_loss=44900.0,
            take_profit=45200.0,
        ))

        initial_balance = risk._state_for(symbol).portfolio.balance

        # Close with profit
        risk.sync_position_event(PositionEvent(
            symbol=symbol,
            timestamp=1_700_000_000_000_000_001,
            event_type="CLOSED",
            position_id="pos-1",
            pnl=500.0,
        ))

        state = risk._state_for(symbol)
        assert len(state.portfolio.positions) == 0
        assert state.portfolio.balance > initial_balance

    def test_retract_position_removes_without_accounting(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        # Open then retract
        risk.sync_position_event(PositionEvent(
            symbol=symbol,
            timestamp=1_700_000_000_000_000_000,
            event_type="OPENED",
            position_id="pos-1",
            entry_price=45000.0,
            size=10.0,
            side="LONG",
            stop_loss=44900.0,
            take_profit=45200.0,
        ))
        initial_balance = risk._state_for(symbol).portfolio.balance

        risk.retract_position(symbol, "pos-1")

        state = risk._state_for(symbol)
        assert len(state.portfolio.positions) == 0
        # Balance should not change on retract (no trade outcome)
        assert state.portfolio.balance == initial_balance


# ---------------------------------------------------------------------------
# 2. Snapshot / restore tests
# ---------------------------------------------------------------------------

class TestSnapshotRestore:
    """State serializes and restores correctly."""

    def test_snapshot_round_trip(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        # Mutate state
        state = risk._state_for(symbol)
        state.kill_switch.trigger("test halt")
        state.risk_manager._daily.consecutive_losses = 3
        state.risk_manager._daily.realized_pnl = -200.0

        snap = risk.snapshot()

        assert symbol in snap
        assert snap[symbol]["kill_switch"]["is_halted"] is True
        assert snap[symbol]["risk_manager"]["daily"]["consecutive_losses"] == 3
        assert snap[symbol]["risk_manager"]["daily"]["realized_pnl"] == -200.0

    def test_restore_matches_snapshot(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        state = risk._state_for(symbol)
        state.kill_switch.trigger("restore test")
        state.risk_manager._daily.consecutive_losses = 4
        state.risk_manager._daily.realized_pnl = -300.0
        state.portfolio.balance = Decimal("95000")
        state.portfolio.equity = Decimal("95000")

        snap = risk.snapshot()

        # Restore into a fresh instance
        risk2 = RiskEvaluation()
        risk2.restore(snap)

        restored = risk2._state_for(symbol)
        assert restored.kill_switch.is_halted is True
        assert restored.risk_manager._daily.consecutive_losses == 4
        assert restored.risk_manager._daily.realized_pnl == -300.0
        assert float(restored.portfolio.balance) == 95000.0

    def test_restore_then_process_respects_restored_state(self) -> None:
        risk = RiskEvaluation()
        symbol = "BANKNIFTY"

        state = risk._state_for(symbol)
        state.kill_switch.trigger("pre-existing halt")
        state.risk_manager._daily.halted = True
        state.risk_manager._daily.halt_reason = "pre-existing halt"

        snap = risk.snapshot()

        risk2 = RiskEvaluation()
        risk2.restore(snap)

        gate = _make_gate(symbol=symbol)
        results = risk2.process(gate)

        assert len(results) == 1
        assert results[0].kill_switch_active is True
        assert results[0].approved is False


# ---------------------------------------------------------------------------
# 3. Per-symbol isolation tests
# ---------------------------------------------------------------------------

class TestPerSymbolIsolation:
    """Risk state is tracked per symbol independently."""

    def test_state_created_per_symbol(self) -> None:
        risk = RiskEvaluation()
        risk._state_for("BANKNIFTY")
        risk._state_for("NIFTY")

        assert "BANKNIFTY" in risk._state
        assert "NIFTY" in risk._state
        assert risk._state["BANKNIFTY"] is not risk._state["NIFTY"]

    def test_kill_switch_one_symbol_does_not_affect_other(self) -> None:
        risk = RiskEvaluation()

        # Trigger kill switch on BANKNIFTY only
        state_bn = risk._state_for("BANKNIFTY")
        state_bn.kill_switch.trigger("BN halt")
        state_bn.risk_manager._daily.halted = True
        state_bn.risk_manager._daily.halt_reason = "BN halt"

        # BANKNIFTY should be blocked
        gate_bn = _make_gate(symbol="BANKNIFTY")
        results_bn = risk.process(gate_bn)
        assert results_bn[0].approved is False
        assert results_bn[0].kill_switch_active is True

        # NIFTY should still pass
        gate_nf = _make_gate(symbol="NIFTY")
        results_nf = risk.process(gate_nf)
        assert results_nf[0].approved is True
        assert results_nf[0].kill_switch_active is False

    def test_flash_crash_one_symbol_does_not_affect_other(self) -> None:
        risk = RiskEvaluation()

        # Trigger flash crash on NIFTY
        risk.observe_price("NIFTY", 100.0, 1_000_000_000)
        risk.observe_price("NIFTY", 96.0, 1_000_000_004)

        # NIFTY blocked
        gate_nf = _make_gate(symbol="NIFTY")
        results_nf = risk.process(gate_nf)
        assert results_nf[0].approved is False
        assert results_nf[0].circuit_breaker_triggered is True

        # BANKNIFTY passes
        gate_bn = _make_gate(symbol="BANKNIFTY")
        results_bn = risk.process(gate_bn)
        assert results_bn[0].approved is True

    def test_portfolio_independent_per_symbol(self) -> None:
        risk = RiskEvaluation()

        # Open a position on BANKNIFTY
        risk.sync_position_event(PositionEvent(
            symbol="BANKNIFTY",
            timestamp=1_700_000_000_000_000_000,
            event_type="OPENED",
            position_id="pos-bn",
            entry_price=45000.0,
            size=10.0,
            side="LONG",
            stop_loss=44900.0,
            take_profit=45200.0,
        ))

        bn_state = risk._state_for("BANKNIFTY")
        nf_state = risk._state_for("NIFTY")

        assert len(bn_state.portfolio.positions) == 1
        assert len(nf_state.portfolio.positions) == 0


# ---------------------------------------------------------------------------
# 4. Lifecycle / error handling
# ---------------------------------------------------------------------------

class TestLifecycleAndErrors:
    """Warmup, reset, teardown, and error resilience."""

    def test_warmup_clears_state(self) -> None:
        risk = RiskEvaluation()
        risk._state_for("BANKNIFTY")
        assert "BANKNIFTY" in risk._state

        risk.warmup()
        assert risk._state == {}

    def test_reset_clears_state(self) -> None:
        risk = RiskEvaluation()
        risk._state_for("BANKNIFTY")
        risk.reset()
        assert risk._state == {}

    def test_process_returns_empty_on_bad_input(self) -> None:
        risk = RiskEvaluation()
        # Pass a gate with no signal (will cause an exception inside process)
        gate = GateResult(
            symbol="BANKNIFTY",
            timestamp=1_700_000_000_000_000_000,
            signal=None,
            result=GateResultType.APPROVED,
        )
        results = risk.process(gate)
        assert results == []

    def test_metrics_updated_after_process(self) -> None:
        risk = RiskEvaluation()
        gate = _make_gate()
        risk.process(gate)

        assert risk.metrics.processed_count == 1
        assert risk.metrics.stage_name == "RiskEvaluation"
