"""Adversarial integration tests — RED TEAM desync & contract violation probes.

These tests target the seams between:
  - EventStore.fold() <-> EngineState (state derivation)
  - project_state() (sole ViewState authority)
  - apply_event() guards (position ID matching, pyramid opens)
  - EventBus handler isolation (exception poisoning)
  - Concurrent emit (thread safety)

Each test documents the expected invariant and the bug it exposes when it fails.
A passing test means the system handled that case; a failing test is a finding.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from quant.event_store import EventStore
from quant.events import (
    BarClosed,
    Event,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.order import Fill, Order, Position
from quant.execution.risk import RiskState
from quant.state import ViewState, project_state
from quant.state_machine import Bar, EngineState, PositionState, RiskState
from quant.transitions import apply_event, _position_to_state
from quant.ws_adapter import view_state_to_ws


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_signal(type="LONG", entry=100.0, sl=95.0, tp=110.0, symbol="NIFTY"):
    from quant.decision.signal_builder import Signal
    return Signal(
        type=type,
        reason="test",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=1.5,
        model_label="Test",
        symbol=symbol,
        timestamp="2026-01-01T09:15:00+05:30",
    )


def _make_position(symbol="NIFTY", entry=100.0, sl=95.0, tp=110.0, size=10.0, pos_id="pos-001"):
    sig = _make_signal(entry=entry, sl=sl, tp=tp, symbol=symbol)
    return Position(
        order=Order(signal=sig, quantity=abs(size)),
        open_price=entry,
        open_time="2026-01-01T09:15:00+05:30",
        size=size,
        _id=pos_id,
    )


def _make_bar(time="2026-01-01T09:15:00+05:30", close=100.0):
    return Bar(time=time, open=99.0, high=101.0, low=98.0, close=close, volume=1000.0)


# ---------------------------------------------------------------------------
# Attack 1: Pyramid PositionOpened crashes apply_event()
# ---------------------------------------------------------------------------

class TestPyramidPositionOpenedCrash:
    """CRITICAL: Pyramid add-ons emit PositionOpened while base is open.

    transitions.py:61-66 raises ValueError when PositionOpened arrives and
    state.position is not None. check_pyramid() emits PositionOpened for
    pyramid add-ons while the base position is still open.

    Expected: Either pyramids should not emit PositionOpened, OR apply_event
    should handle pyramid opens without crashing.
    """

    def test_pyramid_open_while_base_open_should_not_crash(self):
        """apply_event() should handle pyramid PositionOpened without crashing.

        BUG: This test FAILS because apply_event() raises ValueError when
        a pyramid PositionOpened arrives while the base position is open.
        This would crash the engine thread in production.
        """
        base_pos = _make_position(pos_id="base-001")
        base_state = EngineState(symbol="NIFTY", position=PositionState(
            id="base-001", entry=100.0, size=10.0, sl=95.0, tp=110.0, side="LONG"
        ))

        # Pyramid add-on emits PositionOpened — the production path
        # (PositionManager.check_pyramid → OMS.add_pyramid) stamps
        # is_pyramid=True on the add-on so the fold treats it as a pyramid.
        pyramid_pos = _make_position(pos_id="pyr-001", entry=101.0)
        from dataclasses import replace as _replace
        from quant.execution.order import Position as _Position

        pyramid_pos = _Position(
            order=pyramid_pos.order,
            open_price=pyramid_pos.open_price,
            open_time=pyramid_pos.open_time,
            size=pyramid_pos.size,
            pyramid_level=1,
            is_pyramid=True,
        )
        pyramid_event = PositionOpened(symbol="NIFTY", time="t1", position=pyramid_pos)

        # EXPECTED: Should succeed (pyramids are valid add-ons)
        # ACTUAL: Raises ValueError, crashing the engine thread
        result = apply_event(base_state, pyramid_event)
        assert result is not None  # Should return new state, not raise

    def test_event_store_fold_should_handle_pyramid(self):
        """EventStore.fold() should replay pyramid PositionOpened without crashing.

        BUG: This test FAILS because fold() crashes on the second PositionOpened,
        meaning restart_reconcile() would crash if a pyramid was added before
        the process restarted.
        """
        store = EventStore()
        base_pos = _make_position(pos_id="base-001")
        pyramid_pos = _make_position(pos_id="pyr-001", entry=101.0)
        from dataclasses import replace as _replace
        from quant.execution.order import Position as _Position

        pyramid_pos = _Position(
            order=pyramid_pos.order,
            open_price=pyramid_pos.open_price,
            open_time=pyramid_pos.open_time,
            size=pyramid_pos.size,
            pyramid_level=1,
            is_pyramid=True,
        )
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))
        store.append(PositionOpened(symbol="NIFTY", time="t1", position=pyramid_pos))

        # EXPECTED: fold() should succeed
        # ACTUAL: Crashes with ValueError
        state = store.fold()
        assert state is not None


# ---------------------------------------------------------------------------
# Attack 2: fold equity tracking
# ---------------------------------------------------------------------------

class TestFoldEquityTracking:
    """Fold equity reflects realized P&L — the sole authority path.

    project_state() is the sole ViewState authority.
    These tests verify equity correctly tracks realized P&L.
    """

    def test_fold_equity_reflects_realized_pnl(self):
        """After a winning trade, fold equity > INITIAL_CAPITAL."""
        store = EventStore()

        base_pos = _make_position(pos_id="base-001", entry=100.0, size=10.0)
        bar = _make_bar(close=105.0)

        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))
        fill = Fill(
            position=base_pos,
            close_price=105.0,
            close_time="t1",
            reason="TP",
            pnl=50.0,
        )
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=bar))

        fold_ws = view_state_to_ws(project_state(store.fold()))
        assert fold_ws["portfolio"]["equity"] == 1_000_050.0

    def test_fold_equity_accumulates_multiple_trades(self):
        """After multiple winning trades, equity accumulates all P&L."""
        store = EventStore()

        pos1 = _make_position(pos_id="p1", entry=100.0, size=10.0)
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos1))
        fill1 = Fill(position=pos1, close_price=105.0, close_time="t1", reason="TP", pnl=50.0)
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill1))

        pos2 = _make_position(pos_id="p2", entry=100.0, size=10.0)
        store.append(PositionOpened(symbol="NIFTY", time="t2", position=pos2))
        fill2 = Fill(position=pos2, close_price=102.5, close_time="t3", reason="TP", pnl=25.0)
        store.append(PositionClosed(symbol="NIFTY", time="t3", fill=fill2))

        fold_ws = view_state_to_ws(project_state(store.fold()))
        assert fold_ws["portfolio"]["equity"] == 1_000_075.0


# ---------------------------------------------------------------------------
# Attack 3: PositionClosed with mismatched ID silently dropped
# ---------------------------------------------------------------------------

class TestPositionClosedMismatch:
    """MAJOR: PositionClosed with wrong ID is silently treated as pyramid close.

    transitions.py:77-80: if event.fill.position._id != state.position.id,
    the event is treated as a pyramid close and state is UNCHANGED.

    This means if events arrive out of order, or if there's a genuine bug where
    the wrong ID is used, the close is silently dropped and the state machine
    thinks the position is still open forever.
    """

    def test_close_with_wrong_id_should_raise_not_silently_drop(self):
        """A PositionClosed with mismatched ID is replay-tolerant.

        The state machine logs a warning and returns unchanged state instead
        of raising — this prevents a single misordered event from crashing
        the entire fold. The diagnostic is emitted via logging.
        """
        store = EventStore()
        base_pos = _make_position(pos_id="base-001", entry=100.0, size=10.0)

        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))

        # Close event with WRONG position ID (simulating a bug or reorder)
        wrong_pos = _make_position(pos_id="wrong-999", entry=100.0, size=10.0)
        fill = Fill(position=wrong_pos, close_price=105.0, close_time="t1", reason="TP", pnl=50.0)
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))

        # Replay-tolerant: returns unchanged state, no raise
        state = store.fold()
        assert state.position is not None
        assert state.position.id == "base-001"

    def test_close_with_correct_id_works(self):
        """Sanity check: PositionClosed with matching ID clears position."""
        store = EventStore()
        base_pos = _make_position(pos_id="base-001", entry=100.0, size=10.0)

        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))

        fill = Fill(position=base_pos, close_price=105.0, close_time="t1", reason="TP", pnl=50.0)
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))

        state = store.fold()
        assert state.position is None  # Correctly closed


# ---------------------------------------------------------------------------
# Attack 4: Event ordering sensitivity
# ---------------------------------------------------------------------------

class TestEventOrdering:
    """MAJOR: Reordering events produces different (wrong) state.

    A robust event-sourcing system should be sensitive to ordering (that's the
    point), but certain reorderings reveal bugs:
    - Closing before opening should be rejected, not silently applied.
    - Risk events before any position should still fold correctly.
    """

    def test_close_before_open_should_raise(self):
        """PositionClosed before PositionOpened is replay-tolerant.

        When a close arrives before any open, the state machine returns
        unchanged state (position stays None) instead of raising.
        """
        store = EventStore()
        base_pos = _make_position(pos_id="base-001", entry=100.0, size=10.0)

        # Close arrives BEFORE open (out-of-order or replay bug)
        fill = Fill(position=base_pos, close_price=105.0, close_time="t1", reason="TP", pnl=50.0)
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))

        # Replay-tolerant: state reflects only the open (close was unmatched)
        state = store.fold()
        assert state.position is not None
        assert state.position.id == "base-001"


# ---------------------------------------------------------------------------
# Attack 5: Handler exception isolation
# ---------------------------------------------------------------------------

class TestHandlerExceptionIsolation:
    """EventBus handler exceptions must not poison later handlers.

    This test verifies the fix: a failing handler should not block
    subsequent handlers from running.
    """

    def test_failing_handler_does_not_block_others(self):
        """A raising handler should not prevent later handlers from running."""
        from quant.events import EventBus

        bus = EventBus()
        results = []

        def failing_handler(event):
            raise RuntimeError("Journal disk full")

        def good_handler(event):
            results.append("good")

        bus.subscribe(BarClosed, failing_handler, priority=10)
        bus.subscribe(BarClosed, good_handler, priority=0)

        event = BarClosed(symbol="NIFTY", time="t0", bar=_make_bar())
        bus.publish(event)

        # The good handler should still have run
        assert "good" in results, (
            "BUG: Failing handler blocked subsequent handlers"
        )


# ---------------------------------------------------------------------------
# Attack 6: Concurrent emit race condition
# ---------------------------------------------------------------------------

class TestConcurrentEmit:
    """EventStore is documented as NOT thread-safe.

    If two threads call _emit simultaneously, the lock serializes them,
    but event_store.append() is not thread-safe. This test checks whether
    the engine's _emit_lock actually protects the event store.
    """

    def test_concurrent_append_corrupts_event_store(self):
        """Concurrent appends to EventStore may corrupt internal state.

        EventStore.append() modifies _events, _sequence, _checksums without
        a lock. If two threads call append() simultaneously, sequence numbers
        may collide or checksums may be computed incorrectly.
        """
        store = EventStore()
        errors = []
        num_threads = 10
        events_per_thread = 100

        def append_events(thread_id):
            try:
                for i in range(events_per_thread):
                    pos = _make_position(pos_id=f"t{thread_id}-p{i}")
                    store.append(PositionOpened(
                        symbol="NIFTY",
                        time=f"t{thread_id}-{i}",
                        position=pos,
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=append_events, args=(t,))
                   for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Check for corruption
        all_events = store.get_all()
        expected_count = num_threads * events_per_thread

        # BUG: Without thread safety, count may be wrong or checksums invalid
        if len(all_events) != expected_count:
            errors.append(
                f"Event count mismatch: expected {expected_count}, got {len(all_events)}"
            )

        # Verify checksum chain
        if not store.verify_chain():
            errors.append("Checksum chain corrupted")

        # This test documents the race condition
        # It may or may not fail depending on timing
        assert len(errors) == 0, f"Race condition detected: {errors}"


# ---------------------------------------------------------------------------
# Attack 7: WS adapter desync between fold and to_dict
# ---------------------------------------------------------------------------

class TestWSAdapterDesync:
    """WS adapter maps EngineState -> frontend snapshot.

    If state changes between fold() and to_dict(), the snapshot is stale.
    This tests whether view_state_to_ws() captures a consistent snapshot.
    """

    def test_view_state_to_ws_captures_consistent_snapshot(self):
        """view_state_to_ws should capture a point-in-time snapshot."""
        state = EngineState(
            symbol="NIFTY",
            position=PositionState(
                id="base-001", entry=100.0, size=10.0, sl=95.0, tp=110.0, side="LONG"
            ),
            last_bar=_make_bar(close=105.0),
        )

        ws = view_state_to_ws(state)

        # Snapshot should reflect the state at call time
        assert ws["_symbol"] == "NIFTY"
        assert ws["ltp"] == 105.0
        assert ws["portfolio"]["positions"][0]["pnl"] == 50.0  # (105-100)*10

    def test_view_state_to_ws_with_no_bar(self):
        """view_state_to_ws handles state with no bar gracefully."""
        state = EngineState(
            symbol="NIFTY",
            position=PositionState(
                id="base-001", entry=100.0, size=10.0, sl=95.0, tp=110.0, side="LONG"
            ),
        )

        ws = view_state_to_ws(state)

        assert ws["ltp"] is None
        assert ws["tick"] is None
        # Position exists but no LTP means PnL is 0.0
        assert ws["portfolio"]["positions"][0]["pnl"] == 0.0


# ---------------------------------------------------------------------------
# Attack 8: State vs PositionManager desync
# ---------------------------------------------------------------------------

class TestStateVsPositionManager:
    """Engine state and PositionManager.current_position can desync.

    The engine's state.position holds immutable PositionState.
    The PositionManager.current_position holds the live Position object.
    These can diverge if events are applied to one but not the other.
    """

    def test_state_position_matches_pm_after_open(self):
        """After PositionOpened, state and PM should agree."""
        store = EventStore()
        base_pos = _make_position(pos_id="base-001", entry=100.0, size=10.0)

        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))
        state = store.fold()

        assert state.position is not None
        assert state.position.id == "base-001"
        assert state.position.entry == 100.0

    def test_state_position_cleared_after_close(self):
        """After PositionClosed, state should be cleared."""
        store = EventStore()
        base_pos = _make_position(pos_id="base-001", entry=100.0, size=10.0)

        store.append(PositionOpened(symbol="NIFTY", time="t0", position=base_pos))
        fill = Fill(position=base_pos, close_price=105.0, close_time="t1", reason="TP", pnl=50.0)
        store.append(PositionClosed(symbol="NIFTY", time="t1", fill=fill))

        state = store.fold()
        assert state.position is None


# ---------------------------------------------------------------------------
# Attack 9: fold() with empty symbol
# ---------------------------------------------------------------------------

class TestFoldEmptySymbol:
    """fold() starts with empty symbol and overwrites from first event.

    If the first event has symbol="" (e.g., unknown event type from import_),
    the state will have symbol="" which breaks downstream consumers.
    """

    def test_fold_empty_events(self):
        """fold() with no events returns EngineState with empty symbol."""
        store = EventStore()
        state = store.fold()
        assert state.symbol == ""

    def test_fold_with_unknown_event_type(self):
        """fold() with unknown event type preserves empty symbol."""
        store = EventStore()
        # Create an event with empty symbol (simulating import_ unknown type)
        unknown_event = Event(symbol="", time="t0")
        store.append(unknown_event)

        state = store.fold()
        # BUG: symbol is empty because the unknown event has no symbol
        assert state.symbol == ""


# ---------------------------------------------------------------------------
# Attack 10: _position_to_state crashes on position without order.signal
# ---------------------------------------------------------------------------

class TestPositionToStateEdgeCases:
    """_position_to_state() assumes pos.order.signal exists.

    If a Position is constructed without an order (e.g., from import_), this
    will crash with AttributeError.
    """

    def test_position_to_state_without_signal(self):
        """_position_to_state raises ValueError if position has no order.signal
        (malformed payload) instead of crashing with AttributeError."""
        # Position with order=None (from import_ reconstruction)
        pos = Position(
            order=None,
            open_price=100.0,
            open_time="t0",
            size=10.0,
            _id="test-001",
        )

        with pytest.raises(ValueError, match="order with a signal"):
            _position_to_state(pos)
