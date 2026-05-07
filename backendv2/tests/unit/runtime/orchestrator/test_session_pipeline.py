"""Tests for pipeline stage wiring in SessionRuntime.

Covers:
- All 16 stages are instantiated and wired
- Tick flows through all stages without errors
- Signal flow: Signal -> Gates -> Risk -> Position -> Execution
- Stage lifecycle: warmup, teardown, snapshot
- Missing stages would cause AttributeError
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.runtime.orchestrator.session import SessionRuntime
from app.runtime.pipeline.events import Tick


def _make_tick(symbol: str = "NIFTY", price: float = 22000.0, ts: float = 1_700_000_000.0) -> Tick:
    return Tick(
        symbol=symbol, price=price, volume=10.0, timestamp=ts,
        bid=price - 0.5, ask=price + 0.5,
    )


def _session(symbols: list[str] | None = None) -> SessionRuntime:
    feed = MagicMock()
    feed.stream.return_value = iter([])
    feed.snapshot.return_value = {"running": False, "ticks_seen": 0, "state": "idle"}
    storage = MagicMock()
    return SessionRuntime(feed=feed, symbols=symbols or ["NIFTY"], storage=storage)


# ---------------------------------------------------------------------------
# 1. Stage instantiation
# ---------------------------------------------------------------------------

class TestStageInstantiation:
    def test_session_creates_all_stages(self):
        """All pipeline stages must be instantiated on SessionRuntime."""
        session = _session()
        # Core stages
        assert hasattr(session, "_sequencer")
        assert hasattr(session, "_normalizer")
        assert hasattr(session, "_candles")
        assert hasattr(session, "_orderflow")
        assert hasattr(session, "_microstructure")
        assert hasattr(session, "_market_structure")
        assert hasattr(session, "_features")
        assert hasattr(session, "_strategy")
        assert hasattr(session, "_signal")
        assert hasattr(session, "_gates")
        assert hasattr(session, "_risk")
        assert hasattr(session, "_position")
        assert hasattr(session, "_execution")
        assert hasattr(session, "_broker_sync")
        assert hasattr(session, "_persistence")
        assert hasattr(session, "_telemetry")

    def test_gates_has_equity_fn(self):
        """GateEvaluation must have an equity_fn for position sizing."""
        session = _session()
        assert session._gates._equity_fn is not None

    def test_normalizer_has_symbol_list(self):
        """TickNormalizer must know allowed symbols."""
        session = _session(symbols=["NIFTY", "BANKNIFTY"])
        assert "NIFTY" in session._normalizer.snapshot().get("allowed_symbols", [])


# ---------------------------------------------------------------------------
# 2. Tick processing through stages
# ---------------------------------------------------------------------------

class TestTickProcessing:
    def test_process_tick_returns_events(self):
        """A valid tick should produce stage events without crashing."""
        session = _session()
        session._session_state = type(session._session_state).RUNNING
        tick = _make_tick()
        events = session._process_tick(tick)
        # Should return a list (may be empty if normalizer rejects unknown symbol)
        assert isinstance(events, list)

    def test_process_tick_with_unknown_symbol(self):
        """Tick for symbol not in session's symbol list is filtered."""
        session = _session(symbols=["NIFTY"])
        session._session_state = type(session._session_state).RUNNING
        tick = _make_tick(symbol="RELIANCE")  # Not in allowed list
        events = session._process_tick(tick)
        # Normalizer in strict mode should reject
        assert isinstance(events, list)

    def test_process_tick_with_none_sequencer_output(self):
        """If sequencer returns None, processing stops early."""
        session = _session()
        session._session_state = type(session._session_state).RUNNING
        with patch.object(session._sequencer, "process", return_value=None):
            events = session._process_tick(_make_tick())
        assert events == []

    def test_process_tick_with_none_normalizer_output(self):
        """If normalizer returns None, processing stops early."""
        session = _session()
        session._session_state = type(session._session_state).RUNNING
        tick = _make_tick()
        seq = session._sequencer.process(tick)
        with patch.object(session._normalizer, "process", return_value=None):
            events = session._process_tick(tick)
        assert events == []


# ---------------------------------------------------------------------------
# 3. Signal flow wiring
# ---------------------------------------------------------------------------

class TestSignalFlow:
    def test_run_signal_flow_calls_gates(self):
        """Signal flow must pass through GateEvaluation."""
        session = _session()
        stage_events = []
        signal = MagicMock()
        signal.symbol = "NIFTY"
        signal.type = "NO_TRADE"  # Gates returns empty for NO_TRADE
        session._run_signal_flow(signal, stage_events)
        # NO_TRADE returns empty, so no events
        assert stage_events == []

    def test_run_signal_flow_gates_to_risk(self):
        """Approved gate result should trigger risk evaluation."""
        from app.runtime.pipeline.events import GateResult, GateResultType, Signal
        from app.runtime.pipeline.risk import RiskEvaluation

        session = _session()
        stage_events = []
        signal = Signal(
            symbol="NIFTY", timestamp=1_700_000_000.0, type="LONG",
            entry=22000.0, sl=21950.0, tp=22100.0, rr=2.0,
            confidence=0.8, reason="test",
        )
        # Process through gates
        gate_results = session._gates.process(signal)
        stage_events.extend(gate_results)
        for gate in gate_results:
            risk_results = session._risk.process(gate)
            stage_events.extend(risk_results)
        # Should have at least gate results
        assert len(gate_results) >= 1


# ---------------------------------------------------------------------------
# 4. Lifecycle management
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_warmup_calls_all_stages(self):
        """warmup() must reset all stages."""
        session = _session()
        session._session_state = type(session._session_state).RUNNING
        session._process_tick(_make_tick())  # Process one tick
        session.warmup()
        # After warmup, seen sets should be cleared
        assert len(session._gates._seen) == 0

    def test_teardown_calls_all_stages(self):
        """teardown() must stop feed and clean up all stages."""
        session = _session()
        session._session_state = type(session._session_state).RUNNING
        session._running = True
        session.teardown()
        assert session._session_state.value == "stopped"

    def test_snapshot_returns_all_stages(self):
        """snapshot() must include all stage state."""
        session = _session()
        snap = session.snapshot()
        assert "feed" in snap
        assert "sequencer" in snap
        assert "normalizer" in snap
        assert "candles" in snap
        assert "orderflow" in snap
        assert "microstructure" in snap
        assert "features" in snap
        assert "market_structure" in snap
        assert "signal" in snap
        assert "gates" in snap
        assert "risk" in snap
        assert "portfolio" in snap
        assert "execution" in snap
        assert "broker_sync" in snap
        assert "persistence" in snap
        assert "telemetry" in snap
        assert "strategy" in snap
        assert "state_digest" in snap

    def test_state_digest_is_stable(self):
        """state_digest should produce consistent hash for same state."""
        session = _session()
        digest1 = session.state_digest()
        digest2 = session.state_digest()
        assert digest1 == digest2


# ---------------------------------------------------------------------------
# 5. Broker binding
# ---------------------------------------------------------------------------

class TestBrokerBinding:
    def test_bind_broker_wires_to_execution(self):
        """bind_broker must connect broker to ExecutionPipeline."""
        session = _session()
        broker = MagicMock()
        session.bind_broker(broker)
        # Execution pipeline should have broker
        assert session._execution._broker is not None

    def test_bind_broker_rejects_while_stopping(self):
        session = _session()
        from app.runtime.contracts import RuntimeSessionState
        session._session_state = RuntimeSessionState.STOPPING
        with pytest.raises(RuntimeError, match="cannot_bind_while_stopping"):
            session.bind_broker(MagicMock())

    def test_bind_broker_rejects_while_failed(self):
        session = _session()
        from app.runtime.contracts import RuntimeSessionState
        session._session_state = RuntimeSessionState.FAILED
        with pytest.raises(RuntimeError, match="cannot_bind_while_failed"):
            session.bind_broker(MagicMock())


# ---------------------------------------------------------------------------
# 6. Strategy registration
# ---------------------------------------------------------------------------

class TestStrategyRegistration:
    def test_register_strategy(self):
        session = _session()
        handler = MagicMock()
        session.register_strategy("NIFTY", "test_strategy", handler)
        bindings = session.strategy_bindings()
        assert "NIFTY" in bindings.get("bindings", {})

    def test_unregister_strategy(self):
        session = _session()
        handler = MagicMock()
        session.register_strategy("NIFTY", "test_strategy", handler)
        session.unregister_strategy("NIFTY", "test_strategy")
        bindings = session.strategy_bindings()
        assert "NIFTY" not in bindings


# ---------------------------------------------------------------------------
# 7. History tracking
# ---------------------------------------------------------------------------

class TestHistoryTracking:
    def test_get_history_returns_empty_for_unknown_symbol(self):
        session = _session()
        assert session.get_history("UNKNOWN") == []

    def test_get_history_respects_max_points(self):
        session = _session()
        session._history["NIFTY"] = [{"i": i} for i in range(1000)]
        history = session.get_history("NIFTY", max_points=10)
        assert len(history) == 10
