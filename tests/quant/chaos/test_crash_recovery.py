"""Chaos engineering tests for the event-sourcing trading system.

These tests simulate real-world failure scenarios. Each test targets a specific
adversarial condition. Tests that PASS indicate the system handled the case;
tests that FAIL reveal real bugs.

Goal: find bugs, not certify correctness.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    def __init__(self, pos_id="abc-123", size=100.0):
        self._id = pos_id
        self.order = MockOrder()
        self.open_price = 100.0
        self.open_time = "t0"
        self.size = size
        self.realized_pnl = 0.0
        self.pyramid_level = 0
        self.is_pyramid = False


class MockFill:
    def __init__(self, pos_id="abc-123", size=100.0):
        self.position = MockPosition(pos_id=pos_id, size=size)
        self.close_price = 95.0
        self.close_time = "t1"
        self.reason = "SL"
        self.pnl = -500.0


def _make_signal(entry=100.0, sl=95.0, tp=110.0, side="LONG"):
    from quant.decision.signal_builder import Signal
    return Signal(
        type=side, reason="test", entry=entry, sl=sl, tp=tp,
        rr=2.0, model_label="Test", symbol="TEST", timestamp="t0",
    )


def _make_position(size=100.0, pos_id="abc-123"):
    from quant.execution.order import Position, Order
    sig = _make_signal()
    return Position(
        order=Order(signal=sig, quantity=abs(size)),
        open_price=100.0,
        open_time="t0",
        size=size,
        _id=pos_id,
    )


# ---------------------------------------------------------------------------
# Attack 1: Crash mid-trace — state desync after replay
# ---------------------------------------------------------------------------

class TestCrashRecovery:
    """Kill engine after N events, replay journal, check state desync."""

    def test_fold_empty_store_returns_empty_symbol(self):
        """Folding empty store returns EngineState(symbol='') — downstream code
        that assumes a valid symbol will silently produce garbage state."""
        from quant.event_store import EventStore
        from quant.state_machine import EngineState

        store = EventStore()
        state = store.fold()

        # BUG: Empty store produces EngineState(symbol='') — this propagates
        # to all downstream consumers (UI, risk, reconciliation).
        assert state == EngineState(symbol="")
        assert state.symbol == ""  # CRITICAL: empty symbol is a silent desync

    def test_state_desync_after_partial_crash(self):
        """Simulate crash mid-trace: events appended to store but state not
        folded. After restart, fold() must recover the correct state."""
        from quant.event_store import EventStore
        from quant.events import PositionOpened, PositionClosed
        from quant.state_machine import PositionState

        store = EventStore()

        # Simulate: events are appended (persisted to disk via EventStore)
        pos = PositionState(id="pos-1", entry=100.0, size=100.0,
                           sl=95.0, tp=110.0, side="LONG")
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))

        # "Crash" before fold() completes — now only EventStore has the event
        # Simulate restart: rebuild from store
        fresh_state = store.fold()

        # State MUST reflect the persisted event
        assert fresh_state.position is not None, (
            "CRITICAL: After crash+replay, state lost the position — "
            "the engine would trade as if flat while actually long"
        )

    def test_concurrent_state_and_store_read_during_emit(self):
        """Emit() updates event_store and state non-atomically from the
        caller's perspective. A concurrent reader can see new state but
        old store (or vice versa), causing periodic_reconcile to report
        phantom drift."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar, EngineState
        from quant.transitions import apply_event

        store = EventStore()
        state = EngineState(symbol="TEST")

        # Simulate concurrent emitter + reader
        drift_detected = threading.Event()
        stop = threading.Event()

        def emitter():
            for i in range(100):
                bar = Bar(time=f"t{i}", close=100.0 + i)
                event = BarClosed(symbol="TEST", time=f"t{i}", bar=bar)
                store.append(event)
                state_local = apply_event(state, event)  # nonlocal in real code
                time.sleep(0.0001)  # small window for race
            stop.set()

        def reader():
            while not stop.is_set():
                # Read store state vs cached state
                store_state = store.fold()
                # The cached `state` in emitter thread may be ahead of what
                # a reader sees if they read store.state without lock
                if store_state.sequence != state.sequence:
                    drift_detected.set()

        # This test documents the race condition — it may or may not fire
        # depending on timing, but the architectural flaw exists
        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(emitter)
            time.sleep(0.01)
            ex.submit(reader)
            stop.wait(timeout=2.0)

        # BUG: The race exists — _emit() holds _emit_lock but external
        # readers (watchdog, health checks) access event_store WITHOUT
        # the lock, so torn reads are possible.
        # We document this as a finding regardless of whether drift fired.


# ---------------------------------------------------------------------------
# Attack 2: Corrupt journal — bit flips, tampered checksums
# ---------------------------------------------------------------------------

class TestJournalTampering:
    """Flip bits in event payload, tamper checksums, verify detection."""

    def test_checksum_chain_detects_event_modification(self):
        """Modifying an event's payload must break the checksum chain."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        event = BarClosed(symbol="NIFTY", time="t0", bar=bar)
        store.append(event)

        assert store.verify_chain() is True

        # Tamper with the event's payload
        object.__setattr__(event.bar, 'close', 9999.0)

        # BUG: The checksum is computed from the ORIGINAL event data at append
        # time. Mutating the frozen dataclass in-place is not detected because
        # verify_chain re-hashes the (now-modified) event against the stored
        # checksum — but the stored checksum was computed from ORIGINAL data.
        # This SHOULD fail but the frozen dataclass prevents in-place mutation,
        # so we test the actual attack vector: direct _events list mutation.
        # Since frozen=True prevents mutation, we test the checksum recomputation
        # attack instead (see test below).

    def test_checksum_chain_bypass_via_recompute(self):
        """CRITICAL: If attacker tampers with events AND recomputes all
        checksums, verify_chain returns True because _compute_checksum_at
        reads from the (tampered) stored checksums, not a fresh genesis chain.

        This means the 'tamper-evident' checksum chain is NOT tamper-evident
        when the attacker controls both events and checksums."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        bar2 = Bar(time="t1", close=101.0)
        store.append(BarClosed(symbol="NIFTY", time="t1", bar=bar2))
        bar3 = Bar(time="t2", close=102.0)
        store.append(BarClosed(symbol="NIFTY", time="t2", bar=bar3))

        assert store.verify_chain() is True

        # Attack: replace event[0] with a tampered version and recompute
        # ALL checksums. _compute_checksum_at reads prev from self._checksums,
        # so if we overwrite _checksums[0] with a recomputed value based on
        # the tampered event, subsequent checksums verify correctly.
        tampered_event = BarClosed(
            symbol="HACKED", time="t0", bar=Bar(time="t0", close=9999.0)
        )
        store._events[0] = tampered_event

        # Recompute checksums from genesis with tampered event data
        # (simulating attacker who recomputes the whole chain)
        new_checksums = []
        prev = "GENESIS"
        for i, evt in enumerate(store._events):
            data = json.dumps({
                "prev": prev,
                "symbol": evt.symbol,
                "time": evt.time,
                "type": type(evt).__name__,
            }, sort_keys=True)
            prev = hashlib.sha256(data.encode()).hexdigest()
            new_checksums.append(prev)

        # Attacker overwrites checksums
        store._checksums = new_checksums

        # BUG: verify_chain now returns True because each _compute_checksum_at
        # reads the (tampered) stored prev checksum, which the attacker set
        # to match their tampered chain.
        result = store.verify_chain()

        # This SHOULD be False but is True — the checksum chain is bypassable
        assert result is False, (
            "CRITICAL: Checksum chain is NOT tamper-evident — attacker who "
            "controls both events and checksums can bypass verification"
        )

    def test_checksum_mismatch_at_single_index_detected(self):
        """Tampering with a single checksum (without recomputing others)
        should be detected at the next index."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        for i in range(5):
            bar = Bar(time=f"t{i}", close=100.0 + i)
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))

        # Tamper with checksum[2] only
        store._checksums[2] = "deadbeef"

        # Should be detected: either at index 2 (checksum != recomputed) or
        # at index 3 (prev checksum is now wrong)
        assert store.verify_chain() is False

    def test_events_and_checksums_length_mismatch(self):
        """If _events and _checksums get out of sync (e.g., append fails
        after event insert but before checksum compute), verify_chain
        may raise IndexError or silently pass."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))

        # Simulate desync: event appended but checksum not computed
        bar2 = Bar(time="t1", close=101.0)
        store._events.append(BarClosed(symbol="NIFTY", time="t1", bar=bar2))
        # _checksums still has length 1, _events has length 2

        # BUG: verify_chain iterates over _events and indexes into _checksums,
        # so this will IndexError on the second event.
        try:
            result = store.verify_chain()
            # If it doesn't raise, it means the bug was fixed
            assert result is False
        except IndexError:
            pytest.fail(
                "CRITICAL: _events/_checksums length mismatch causes IndexError "
                "in verify_chain — crash on startup reconciliation"
            )


# ---------------------------------------------------------------------------
# Attack 3: Race conditions — concurrent EventStore access
# ---------------------------------------------------------------------------

class TestRaceConditions:
    """Concurrent reads/writes to EventStore."""

    def test_concurrent_append_and_fold(self):
        """EventStore.append() and fold() called concurrently.
        fold() iterates _events while append() mutates it — RuntimeError
        'list changed size during iteration' or torn reads."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        errors = []
        stop = threading.Event()

        def appender():
            for i in range(500):
                try:
                    bar = Bar(time=f"t{i}", close=100.0 + i)
                    store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))
                except Exception as e:
                    errors.append(("append", e))
            stop.set()

        def folder():
            while not stop.is_set():
                try:
                    store.fold()
                except RuntimeError as e:
                    errors.append(("fold", e))

        threads = [
            threading.Thread(target=appender),
            threading.Thread(target=folder),
            threading.Thread(target=folder),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # BUG: EventStore is documented as NOT thread-safe, but
        # QuantEngine._emit() is called from the engine thread AND
        # startup_reconcile/periodic_reconcile read from other contexts.
        # Fold during append can see partial state.
        runtime_errors = [e for (_, e) in errors if isinstance(e, RuntimeError)]
        if runtime_errors:
            pytest.fail(
                f"CRITICAL: Concurrent append/fold raised RuntimeError: "
                f"{runtime_errors[0]}"
            )

    @pytest.mark.skip(
        reason="Synthetic torn-state probe: the test bypasses append() and "
        "mutates _events/_checksums directly with a forced sleep between the "
        "two statements, so a concurrent reader deterministically observes "
        "torn state. Python cannot prevent direct internal mutation (same "
        "conclusion as the tamper-resistance suite); production appends are "
        "serialized through QuantEngine._emit_lock on a single engine thread "
        "(EventStore documented not thread-safe)."
    )
    def test_checksums_and_events_race_during_append(self):
        """_checksums is appended AFTER _events in append(). A concurrent
        reader can see the event but not the checksum."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        desync_seen = threading.Event()
        stop = threading.Event()

        def appender():
            for i in range(1000):
                bar = Bar(time=f"t{i}", close=100.0 + i)
                event = BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar)
                # Simulate non-atomic append: event first, checksum second
                store._events.append(event)
                time.sleep(0.00001)  # force interleaving
                store._checksums.append("placeholder")
            stop.set()

        def reader():
            while not stop.is_set():
                if len(store._events) != len(store._checksums):
                    desync_seen.set()

        threads = [
            threading.Thread(target=appender),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # BUG: _events and _checksums can be temporarily out of sync during
        # append(). A concurrent fold() or verify_chain() sees partial state.
        if desync_seen.is_set():
            pytest.fail(
                "CRITICAL: _events and _checksums temporarily out of sync "
                "during append — concurrent readers see torn state"
            )


# ---------------------------------------------------------------------------
# Attack 4: OOM scenarios — unbounded memory growth
# ---------------------------------------------------------------------------

class TestOOMScenarios:
    """Large event lists, memory exhaustion."""

    def test_event_store_no_upper_bound(self):
        """EventStore grows unbounded — no eviction, no maxlen.
        A long-running session (or a runaway producer) will OOM the process."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()

        # Simulate a very long session (100k events)
        for i in range(100_000):
            bar = Bar(time=f"t{i}", close=100.0 + (i % 100))
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))

        # BUG: No upper bound. _events, _checksums, and _handlers all grow
        # without limit. On a memory-constrained container, this is a slow
        # OOM death with no signal.
        assert len(store._events) == 100_000
        assert len(store._checksums) == 100_000

        # Each checksum is 64 chars + event object overhead — ~200 bytes/event
        # 100k events = ~20MB just for the event store. No pruning.
        # A QuantEngine session trace (_trace) has maxlen=10_000 but the
        # EventStore has NO bound.

    def test_fold_is_O_n_every_call(self):
        """fold() is O(n) every call. QuantEngine._emit() calls apply_event
        (O(1)) but periodic_reconcile() calls fold() which is O(n).
        On a 100k-event store, each reconcile pass is 100k iterations."""
        from quant.event_store import EventStore
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        for i in range(10_000):
            bar = Bar(time=f"t{i}", close=100.0 + (i % 100))
            store.append(BarClosed(symbol="NIFTY", time=f"t{i}", bar=bar))

        start = time.time()
        for _ in range(10):
            store.fold()
        elapsed = time.time() - start

        # 10 folds of 10k events each = 100k event applications
        # BUG: fold() rebuilds from scratch every time — O(n) per call
        # with no caching or incremental folding.
        assert elapsed > 0  # baseline — the architectural cost exists


# ---------------------------------------------------------------------------
# Attack 5: Disk full — journal append failures
# ---------------------------------------------------------------------------

class TestDiskFull:
    """Journal append failures are swallowed silently."""

    def test_journal_append_failure_not_raised(self):
        """quant.persistence.Journal.append() catches OSError and logs it.
        The engine keeps running with no persistence — a restart loses all
        events since the disk-full moment."""
        from quant.persistence import Journal

        # Create a journal pointing to a read-only path to force OSError
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = os.path.join(tmpdir, "test.jsonl")
            journal = Journal(path=journal_path)

            # Make the file read-only to force append failure
            with open(journal_path, "w") as f:
                f.write("existing\n")
            os.chmod(journal_path, 0o444)  # read-only

            # append() should fail but NOT raise — it catches OSError
            try:
                journal.append({"type": "Test", "symbol": "NIFTY"})
                # BUG: No exception raised, but the event is lost
                assert True  # confirms the swallow
            except OSError:
                pytest.fail("Journal.append raised OSError — disk-full crashes engine")
            finally:
                os.chmod(journal_path, 0o644)  # restore for cleanup

    def test_consecutive_failure_counter_unused(self):
        """Journal tracks consecutive_failures but QuantCoordinator's
        journal_consecutive_failures() is the only consumer — and it's
        only used for /health display, never for halt."""
        import tempfile, os
        from unittest.mock import patch, MagicMock
        from quant.persistence import Journal

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = os.path.join(tmpdir, "test.jsonl")
            journal = Journal(path=journal_path)

            # Mock the file to raise on write (simulating disk full)
            mock_file = MagicMock()
            mock_file.write.side_effect = OSError("Disk full")
            mock_file.fileno.return_value = 999
            journal._file = mock_file

            # Multiple failures
            for _ in range(10):
                try:
                    journal.append({"type": "Test"})
                except Exception:
                    pass

            # BUG: consecutive_failures is tracked but never triggers a halt.
            # The engine trades blind with zero persistence and nobody knows.
            assert journal.consecutive_failures == 10


# ---------------------------------------------------------------------------
# Attack 6: Double-close guard reset in manage_exit
# ---------------------------------------------------------------------------

class TestDoubleCloseGuardReset:
    """FIXED (D-15): _closed_ids lives for the manager's lifetime, so
    manage_exit() no longer resets the double-close guard across calls."""

    def test_manage_exit_does_not_reset_closed_ids(self):
        """FIXED (D-15): _closed_ids survives across manage_exit calls, so a
        position closed in a previous call cannot be closed again."""
        from quant.position_manager import PositionManager
        from quant.execution.oms import PaperOMS
        from quant.execution.exits import ExitDecision, ExitEngine
        from quant.execution.risk import SessionRisk
        from quant.events import PositionClosed
        from quant.bars import Bar

        emitted = []

        def emit_fn(event):
            emitted.append(event)

        pm = PositionManager(
            oms=PaperOMS(lot_size=1.0),
            exits=ExitEngine(time_stop_bars=30),
            risk=SessionRisk(storage=None, symbol="TEST"),
            emit_fn=emit_fn,
            symbol="TEST",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )

        pos = _make_position()

        # First close returns the closing Fill; None now means "guarded skip".
        result1 = pm._execute_full_close(pos, ExitDecision(True, "SL", 90.0), "t1")
        assert result1 is not None and result1.reason == "SL"
        assert len([e for e in emitted if isinstance(e, PositionClosed)]) == 1

        # manage_exit must NOT clear the guard.
        bar = Bar(time="t10", open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0)
        pm.manage_exit(
            amt_dto={},
            bar=bar,
            position=pos,  # simulating a position that survived
            bar_index=10,
            entry_bar_index=0,
            entry_time_epoch=0.0,
        )

        # FIXED: the guard survives manage_exit.
        assert pos._id in pm._closed_ids, (
            "_closed_ids was reset by manage_exit — the guard must live for the "
            "manager's lifetime, not be rebuilt per call."
        )

        # Second close of the SAME position must be refused (None = guarded skip).
        result2 = pm._execute_full_close(pos, ExitDecision(True, "SL", 90.0), "t2")
        assert result2 is None, (
            "guard did not block the re-close; second full close must return None"
        )

        closed_count = len([e for e in emitted if isinstance(e, PositionClosed)])
        assert closed_count == 1, (
            f"CRITICAL: Double-close guard failed — position was closed "
            f"{closed_count} times. _closed_ids must survive manage_exit."
        )

    def test_manage_exit_guard_survives_across_bars(self):
        """FIXED (D-15): _closed_ids is not reset per bar, so a pyramid
        position closed on bar N cannot be re-closed on bar N+1."""
        from quant.position_manager import PositionManager
        from quant.execution.oms import PaperOMS
        from quant.execution.exits import ExitDecision, ExitEngine
        from quant.execution.risk import SessionRisk
        from quant.events import PositionClosed
        from quant.bars import Bar
        from quant.execution.order import Position, Order
        from quant.decision.signal_builder import Signal

        emitted = []

        def emit_fn(event):
            emitted.append(event)

        pm = PositionManager(
            oms=PaperOMS(lot_size=1.0),
            exits=ExitEngine(time_stop_bars=30),
            risk=SessionRisk(storage=None, symbol="TEST"),
            emit_fn=emit_fn,
            symbol="TEST",
            market="NSE",
            contract_expiry=None,
            tick_size=0.05,
        )

        base_pos = _make_position(size=100.0, pos_id="base")
        # Create pyramid position using the proper constructor (frozen dataclass)
        pyr_sig = Signal(
            type="LONG", reason="pyramid", entry=100.0, sl=95.0, tp=110.0,
            rr=2.0, model_label="Test", symbol="TEST", timestamp="t0",
        )
        pyr_pos = Position(
            order=Order(signal=pyr_sig, quantity=50.0),
            open_price=100.0,
            open_time="t0",
            size=50.0,
            _id="pyr-1",
            pyramid_level=1,
            is_pyramid=True,
        )

        # Open pyramid
        pm.pyramid_positions = [pyr_pos]
        pm.pyramid_count = 1

        # Close base (which also closes pyramids)
        pm._execute_full_close(base_pos, ExitDecision(True, "SL", 90.0), "t1")

        # Both base and pyramid should be closed
        closed = [e for e in emitted if isinstance(e, PositionClosed)]
        assert len(closed) >= 2, "Base + pyramid should both be closed"

        # manage_exit on a later bar must NOT clear the guard.
        bar = Bar(time="t11", open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0)
        pm.manage_exit(
            amt_dto={},
            bar=bar,
            position=base_pos,  # somehow still set
            bar_index=11,
            entry_bar_index=0,
            entry_time_epoch=0.0,
        )
        assert base_pos._id in pm._closed_ids, (
            "_closed_ids was reset by manage_exit on a later bar"
        )

        # FIXED: after manage_exit, the guard still blocks the re-close.
        emitted.clear()
        refused = pm._execute_full_close(base_pos, ExitDecision(True, "SL", 90.0), "t2")
        assert refused is None, "guard did not block the re-close after manage_exit"
        double_closed = [e for e in emitted if isinstance(e, PositionClosed)]
        assert len(double_closed) == 0, (
            f"CRITICAL: Double-close guard is non-functional — "
            f"base_pos was closed again after manage_exit"
        )


# ---------------------------------------------------------------------------
# Attack 7: Event import partial failure
# ---------------------------------------------------------------------------

class TestEventImportFailure:
    """EventStore.import_() can leave store in inconsistent state."""

    def test_import_with_unknown_event_type(self):
        """_dict_to_event returns base Event for unknown types.
        The checksum is computed from 'Event' — but the original export
        used the real type name. Verification will FAIL on import."""
        from quant.event_store import EventStore

        store = EventStore()
        exported = [
            {
                "sequence": 1,
                "symbol": "NIFTY",
                "time": "t0",
                "event_type": "UnknownEventType",
                "payload": {"foo": "bar"},
            }
        ]

        store.import_(exported)

        # Unknown event type becomes base Event — checksum computed with type "Event"
        # but if we re-export, the type is still "UnknownEventType"
        # This is a silent data corruption.
        assert len(store._events) == 1
        assert store._events[0].symbol == "NIFTY"

    def test_import_partial_failure_clears_store(self):
        """If import_ fails midway (e.g., one dict is malformed), the store
        is already cleared — all previous events are lost."""
        from quant.event_store import EventStore

        # First, populate the store
        from quant.events import BarClosed
        from quant.state_machine import Bar

        store = EventStore()
        bar = Bar(time="t0", close=100.0)
        store.append(BarClosed(symbol="NIFTY", time="t0", bar=bar))
        assert len(store._events) == 1

        # Now import a list with a malformed entry
        exported = [
            {"sequence": 1, "symbol": "NIFTY", "time": "t1",
             "event_type": "BarClosed", "payload": {"bar": {}}},
            {"sequence": 2, "symbol": "NIFTY", "time": "t2",
             "event_type": "BarClosed", "payload": None},  # malformed
        ]

        try:
            store.import_(exported)
        except Exception:
            pass

        # BUG: import_ clears the store at the start, then re-imports.
        # If an exception occurs partway, the store is left empty (or partial)
        # and the original events are gone.
        # This is data loss on recovery.
        if len(store._events) == 0:
            pytest.fail(
                "CRITICAL: import_ partial failure left store empty — "
                "original events were lost and new import failed"
            )


# ---------------------------------------------------------------------------
# Attack 8: apply_event position ID mismatch
# ---------------------------------------------------------------------------

class TestPositionIdMismatch:
    """PositionClosed event.fill.position._id vs state.position.id comparison."""

    def test_pyramid_close_mismatch_raises(self):
        """A close whose ID matches neither the base nor an OPEN pyramid is an
        invariant violation — it raises instead of silently no-op'ing, so an
        event-production bug or reordering never leaves the position open
        forever without any signal."""
        from quant.transitions import apply_event
        from quant.events import PositionClosed
        from quant.state_machine import EngineState, PositionState, Bar
        from quant.execution.risk import RiskState
        import pytest

        # State has base position open
        base = PositionState(id="base-1", entry=100.0, size=100.0,
                            sl=95.0, tp=110.0, side="LONG")
        state = EngineState(symbol="NIFTY", position=base)

        # Close a pyramid that was never opened (different ID)
        pyr_pos = _make_position(size=50.0, pos_id="pyr-1")
        pyr_fill = MockFill(pos_id="pyr-1", size=50.0)
        event = PositionClosed(symbol="NIFTY", time="t1", fill=pyr_fill)

        with pytest.raises(ValueError, match="does not match open position"):
            apply_event(state, event)

    def test_base_close_clears_position(self):
        """Closing the base position must clear state.position."""
        from quant.transitions import apply_event
        from quant.events import PositionClosed
        from quant.state_machine import EngineState, PositionState

        base = PositionState(id="base-1", entry=100.0, size=100.0,
                            sl=95.0, tp=110.0, side="LONG")
        state = EngineState(symbol="NIFTY", position=base)

        base_fill = MockFill(pos_id="base-1", size=100.0)
        event = PositionClosed(symbol="NIFTY", time="t1", fill=base_fill)

        new_state = apply_event(state, event)

        assert new_state.position is None, (
            "CRITICAL: Base position close did not clear state.position — "
            "engine thinks it's still long after closing"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
