"""ADVERSARIAL tests: Golden Replay Drift Detection.

These tests inject CORRUPTION and DRIFT into the event store / state
to verify that reconciliation detects tampering.

Each test documents:
- The attack vector injected
- The expected correct behavior
- The severity if the system FAILS to detect it (Critical/Major/Minor)

A test FAILING means the system was BLIND to the attack (bug found).
A test PASSING means the system detected the attack (handled).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockBar:
    def __init__(self, close=100.0):
        self.time = "t0"
        self.open = 100.0
        self.high = 101.0
        self.low = 99.0
        self.close = close
        self.volume = 100.0
        self.vwap = 100.0
        self.buy_volume = 50.0
        self.sell_volume = 50.0
        self.oi = 1000.0


class MockSignal:
    def __init__(self):
        self.type = "LONG"
        self.reason = "test"
        self.entry = 100.0
        self.sl = 95.0
        self.tp = 110.0
        self.rr = 2.0
        self.model_label = "Triple-A"
        self.symbol = "NIFTY"
        self.timestamp = "t0"


class MockOrder:
    def __init__(self):
        self.signal = MockSignal()
        self.quantity = 100.0


class MockPosition:
    """Minimal Position stand-in with required attributes."""
    def __init__(self, pos_id="abc-123"):
        self._id = pos_id
        self.order = MockOrder()
        self.open_price = 100.0
        self.open_time = "t0"
        self.size = 100.0
        self.realized_pnl = 0.0
        self.pyramid_level = 0
        self.is_pyramid = False


def _make_golden_store():
    """Build a clean event store with one position opened."""
    from quant.event_store import EventStore
    from quant.events import PositionOpened
    from quant.state_machine import PositionState

    store = EventStore()
    pos = PositionState(
        id="pos-001",
        entry=100.0,
        size=100.0,
        sl=95.0,
        tp=110.0,
        side="LONG",
    )
    store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
    return store, pos


def _make_engine_with_store(store):
    """Bind a pre-populated EventStore to a QuantEngine without running it."""
    from quant.runtime import QuantEngine

    class SyntheticGateway:
        def __init__(self): self._ticks = []
        def subscribe(self, symbol): pass
        def next_tick(self): return None
        def try_next_tick(self): return None

    engine = QuantEngine(SyntheticGateway(), "NIFTY", interval_seconds=1)
    engine.event_store = store
    return engine


# ===================================================================
# ATTACK 1: Checksum payload blindness — tamper with position data
# ===================================================================

class TestChecksumTampering:
    """CRITICAL: The SHA-256 checksum chain covers only {prev, symbol, time, type}
    — NOT the event payload. Tampering with position data (entry, size, SL, TP)
    is INVISIBLE to verify_chain().

    Expected: System MUST detect payload tampering.
    Severity: CRITICAL — a corrupted position in the journal would cause the
    engine to trade on phantom parameters (wrong entry, wrong SL/TP).
    """

    def test_tampered_position_entry_should_fail_verification(self):
        """Tamper with position.entry — verify_chain MUST detect this."""
        store, pos = _make_golden_store()

        # Verify the clean chain is valid
        assert store.verify_chain() is True

        # ATTACK: Replace event with tampered position data
        from quant.state_machine import PositionState
        from quant.events import PositionOpened

        tampered_pos = PositionState(
            id="pos-001",
            entry=9999.0,  # ATTACK: phantom entry price
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        tampered_event = PositionOpened(symbol="NIFTY", time="t0", position=tampered_pos)
        store._events[0] = tampered_event
        # NOTE: checksums list unchanged — simulates attacker who knows the
        # hashing scheme but hopes payload isn't covered.

        # BUG: verify_chain only hashes {prev, symbol, time, type}
        # The payload (entry, size, sl, tp) is NOT hashed
        chain_valid = store.verify_chain()

        # EXPECTED (correct behavior): tampering detected
        assert chain_valid is False, (
            "CRITICAL BUG: verify_chain did NOT detect payload tampering. "
            "Checksum chain covers only metadata, not position data."
        )


# ===================================================================
# ATTACK 2: State drift injection — memory state diverges from journal
# ===================================================================

class TestStateDriftInjection:
    """MAJOR: In-memory EngineState can be mutated independently of the EventStore
    (e.g., a bug in a state transition, or a concurrent modification). The
    periodic_reconcile() MUST detect this drift.

    Expected: reconcile detects drift and reports it.
    Severity: MAJOR — undetected drift means the engine trades on phantom
    state (thinks it has no position when it does, or vice versa).
    """

    def test_state_cleared_but_journal_has_position(self):
        """ATTACK: In-memory state.position set to None while events say open."""
        store, pos = _make_golden_store()
        engine = _make_engine_with_store(store)

        # Run startup reconcile to get state from journal
        engine.startup_reconcile()
        assert engine.state.position is not None

        # ATTACK: Clear the in-memory state directly (simulating a bug / race)
        from dataclasses import replace
        engine.state = replace(engine.state, position=None)

        # Periodic reconcile should detect drift
        result = engine.periodic_reconcile()

        # EXPECTED: drift detected
        assert result.has_drift is True, (
            "MAJOR BUG: periodic_reconcile did not detect state cleared in memory"
        )
        assert any("position" in d for d in result.discrepancies)

    def test_state_position_mutated_without_event(self):
        """ATTACK: Modify position size in state WITHOUT appending an event."""
        store, pos = _make_golden_store()
        engine = _make_engine_with_store(store)

        engine.startup_reconcile()
        assert engine.state.position.size == 100.0

        # ATTACK: Mutate size directly in state
        from quant.state_machine import PositionState
        tampered_pos = PositionState(
            id="pos-001",
            entry=100.0,
            size=500.0,  # ATTACK: 5x size
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        engine.state = engine.state.with_position(tampered_pos)

        result = engine.periodic_reconcile()

        # EXPECTED: Drift MUST be detected
        assert result.has_drift is True, (
            "MAJOR BUG: periodic_reconcile did not detect size mutation in state"
        )


# ===================================================================
# ATTACK 3: Sequence gap injection — events skipped in the log
# ===================================================================

class TestSequenceGap:
    """MAJOR: An attacker (or disk corruption) could delete events from the
    middle of the log. The system should detect that events are MISSING.

    Expected: Detect the gap via sequence monotonicity or count mismatch.
    Severity: MAJOR — a missing PositionClosed event means the engine thinks
    a closed position is still open, risking double-entry.
    """

    def test_missing_position_closed_event_should_be_detected(self):
        """ATTACK: Delete the PositionClosed event from the store."""
        from quant.event_store import EventStore
        from quant.events import PositionOpened, PositionClosed
        from quant.state_machine import PositionState
        from quant.execution.order import Fill, Position, Order
        from quant.decision.signal_builder import Signal

        store = EventStore()
        pos = PositionState(
            id="pos-001",
            entry=100.0,
            size=100.0,
            sl=95.0,
            tp=110.0,
            side="LONG",
        )
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))

        sig = Signal(
            type="LONG", reason="test", entry=100.0, sl=95.0, tp=110.0,
            rr=2.0, model_label="Triple-A", symbol="NIFTY", timestamp="t1",
        )
        closed_pos = Position(
            order=Order(signal=sig, quantity=100.0),
            open_price=100.0,
            open_time="t0",
            size=100.0,
            realized_pnl=0.0,
            _id="pos-001",
        )
        fill = Fill(
            position=closed_pos,
            close_price=105.0,
            close_time="t1",
            reason="TP",
            pnl=500.0,
        )
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))

        # Verify clean state is positionless
        clean_state = store.fold()
        assert clean_state.position is None

        # ATTACK: Delete the close event (simulate disk truncation / tampering)
        store._events.pop()
        store._checksums.pop()

        # EXPECTED: System should detect the missing event
        # BUG: No mechanism exists — sequence numbers are append-only
        # and the checksum still validates because we removed the last checksum too.
        # The state is wrong but no alarm fires.

        # The fold now shows position still open (the close was lost)
        tampered_state = store.fold()

        # EXPECTED: System should detect this inconsistency
        # (e.g., via event count validation, expected sequence range, or
        # a separate "expected events" manifest)
        assert tampered_state.position is None, (
            "MAJOR BUG: Missing PositionClosed event went undetected — "
            "fold() shows position still open after close was deleted"
        )


# ===================================================================
# ATTACK 4: Replay attack — replay old events as new
# ===================================================================

class TestReplayAttack:
    """CRITICAL: Replaying old events (e.g., duplicate PositionOpened) should
    be detected and rejected. The fold() applies events sequentially and the
    second PositionOpened raises ValueError (guard: position already open).
    But this exception propagates and KILLS the fold.

    Expected: Replay is either prevented OR detected cleanly.
    Severity: CRITICAL — a replay attack could open duplicate positions or
    crash the reconciliation, leaving the engine unable to resume trading.
    """

    def test_replay_position_opened_should_be_detected_not_crash(self):
        """ATTACK: Append the same PositionOpened event twice."""
        store, pos = _make_golden_store()

        # ATTACK: Replay the same event
        from quant.events import PositionOpened
        store.append(PositionOpened(symbol="NIFTY", time="t1", position=pos))

        # EXPECTED: fold() should detect replay and return a clean result
        # (e.g., skip duplicate, or return a ReplayDetected sentinel)
        # BUG: fold() raises ValueError, killing reconciliation
        try:
            result = store.fold()
            # If we get here, replay was handled gracefully
            assert result is not None
        except ValueError as e:
            pytest.fail(
                f"CRITICAL BUG: fold() crashed on replay attack — {e}. "
                "Reconciliation should detect replay, not raise."
            )


# ===================================================================
# ATTACK 5: Time manipulation — future timestamps, zero timestamps
# ===================================================================

class TestTimeManipulation:
    """MINOR: Events with future/zero/negative timestamps are accepted without
    validation. This could cause state transitions to apply out of order or
    produce nonsensical time-ordered state.

    Expected: Events with invalid timestamps should be rejected or flagged.
    Severity: MINOR — time manipulation alone doesn't corrupt position state
    directly, but can confuse downstream consumers (UI, analytics).
    """

    def test_future_timestamp_should_be_rejected(self):
        """ATTACK: Append an event with a future timestamp."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()

        future_bar = Bar(
            time="2099-12-31T23:59:59",
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=100.0, vwap=100.0, buy_volume=50.0, sell_volume=50.0, oi=1000.0,
        )

        # EXPECTED: append() should reject future timestamps
        with pytest.raises(ValueError):
            store.append(BarClosed(symbol="NIFTY", time="2099-12-31T23:59:59", bar=future_bar))

    def test_zero_timestamp_should_be_rejected(self):
        """ATTACK: Append an event with empty timestamp."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        bar = Bar(
            time="",
            open=100.0, high=101.0, low=99.0, close=100.0,
            volume=100.0, vwap=100.0, buy_volume=50.0, sell_volume=50.0, oi=1000.0,
        )

        # EXPECTED: append() should reject empty timestamps
        with pytest.raises(ValueError):
            store.append(BarClosed(symbol="NIFTY", time="", bar=bar))


# ===================================================================
# ATTACK 6: Import tampering — forged events via import_
# ===================================================================

class TestImportTampering:
    """CRITICAL: The import_() method reconstructs events from dicts. An attacker
    who can write to the persistence layer can inject forged events.

    Expected: import_() should validate events against a schema or checksum.
    Severity: CRITICAL — forged events bypass the entire append-only audit trail.
    """

    def test_import_forged_position_event_should_be_rejected(self):
        """ATTACK: Import a forged event dict that claims a position was opened."""
        from quant.event_store import EventStore

        store = EventStore()

        # ATTACK: Forge an event dict directly
        forged_events = [
            {
                "sequence": 1,
                "symbol": "NIFTY",
                "time": "t0",
                "event_type": "PositionOpened",
                "payload": {
                    "position": {
                        "id": "forged-001",
                        "entry": 100.0,
                        "size": 10000.0,  # ATTACK: huge size
                        "sl": 95.0,
                        "tp": 110.0,
                        "side": "LONG",
                    }
                },
            }
        ]

        # EXPECTED: import_() should validate and reject forged events
        with pytest.raises(ValueError):
            store.import_(forged_events)


# ===================================================================
# ATTACK 7: Exception swallowing in periodic reconcile
# ===================================================================

class TestExceptionSwallowing:
    """MAJOR: _periodic_state_reconcile() catches generic Exception and logs at
    DEBUG level. If periodic_reconcile() itself has a bug, the watchdog
    silently ignores it — ops never see the failure.

    Expected: Reconciliation errors should be logged at WARNING or higher.
    Severity: MAJOR — silent failure means drift goes undetected.
    """

    def test_periodic_reconcile_exception_must_not_be_swallowed(self):
        """ATTACK: Inject a bug in periodic_reconcile that raises.

        FIXED: multi_engine._periodic_state_reconcile logs the failure at
        WARNING with the traceback, so ops see reconciliation outages.
        """
        store, pos = _make_golden_store()
        engine = _make_engine_with_store(store)
        engine.startup_reconcile()

        # Monkey-patch to simulate a bug in periodic_reconcile
        def buggy_reconcile():
            raise RuntimeError("simulated bug in reconciliation logic")

        engine.periodic_reconcile = buggy_reconcile

        import logging
        import io
        import threading

        from quant.multi_engine import QuantCoordinator

        # Capture log output on the coordinator's logger at WARNING. The
        # StreamHandler default formatter emits only the message, so pin a
        # level-inclusive formatter to make the assertion meaningful.
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("quant.multi_engine")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)

        # Build a minimal coordinator bound to the buggy engine and run the
        # REAL _periodic_state_reconcile path (not a simulation of it).
        coord = QuantCoordinator.__new__(QuantCoordinator)
        coord._lock = threading.Lock()
        coord._engines = {"NIFTY": engine}
        try:
            coord._periodic_state_reconcile()
        finally:
            logger.removeHandler(handler)

        log_output = log_stream.getvalue()

        # EXPECTED: Error should be logged at WARNING or higher
        assert "WARNING" in log_output or "ERROR" in log_output or "CRITICAL" in log_output, (
            "MAJOR BUG: Reconciliation exception swallowed below WARNING — "
            "ops will never see reconciliation failures. "
            f"Log output: {log_output!r}"
        )


# ===================================================================
# ATTACK 8: Risk state drift without event emission
# ===================================================================

class TestRiskStateDrift:
    """CRITICAL: Risk halt state must be consistent between memory and journal.
    If state says halted but journal says not (or vice versa), the engine could
    resume trading after an emergency halt was lifted in memory but not persisted.

    Expected: periodic_reconcile detects risk drift and emits RiskUpdated.
    Severity: CRITICAL — trading past an emergency halt is a safety violation.
    """

    def test_risk_halt_lifted_in_memory_only_should_be_detected(self):
        """ATTACK: Halt risk in event store, but clear halt in memory state."""
        from quant.event_store import EventStore
        from quant.events import RiskUpdated
        from quant.state_machine import RiskState
        from quant.execution.risk import RiskState as ExecRiskState

        store = EventStore()
        exec_risk = ExecRiskState(
            daily_pnl=0.0,
            consecutive_losses=0,
            halted=True,
            halt_reason="daily loss limit reached",
            risk_per_trade_pct=0.005,
            trades_today=3,
            equity=100000.0,
        )
        store.append(RiskUpdated(symbol="NIFTY", time="t0", risk=exec_risk))

        engine = _make_engine_with_store(store)
        engine.startup_reconcile()
        assert engine.state.risk.halted is True

        # ATTACK: Clear halt in memory only (simulating a bug / race)
        from dataclasses import replace
        engine.state = replace(engine.state, risk=RiskState(
            daily_pnl=0.0, trades_today=3, halted=False, halt_reason=""
        ))

        result = engine.periodic_reconcile()

        # EXPECTED: MUST detect drift and emit risk event
        assert result.has_drift is True, (
            "CRITICAL BUG: Risk halt cleared in memory but periodic_reconcile "
            "did not detect the drift"
        )
        assert result.risk_event_emitted is True
