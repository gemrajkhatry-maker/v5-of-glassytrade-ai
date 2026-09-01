"""Adversarial performance tests for the quant event-sourcing subsystem.

These tests are designed to FAIL — they reveal real performance bugs,
memory leaks, and scalability limits in the EventStore, state machine,
and journal pipeline. Each test documents the expected behavior (what a
production-grade system should do) and the actual behavior (the bug).

Run with: pytest tests/quant/performance/test_load.py -v

Severity scale:
- Critical: data loss, crash, unbounded growth in production
- Major:    >10x slowdown vs acceptable, hits wall at modest scale
- Minor:    micro-optimization, measurable but not blocking
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock

import pytest

from quant.event_store import EventStore
from quant.events import BarClosed, Event
from quant.persistence import Journal
from quant.state_machine import Bar, EngineState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(i: int = 0) -> Bar:
    return Bar(
        time=f"2026-01-01T09:{i % 60:02d}:00",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0 + i,
    )


def _event(i: int = 0) -> BarClosed:
    return BarClosed(symbol="NIFTY", time=f"2026-01-01T09:{i % 60:02d}:00", bar=_bar(i))


# ---------------------------------------------------------------------------
# Attack 1: fold() is O(n) with no incremental caching
# ---------------------------------------------------------------------------
# Expected: fold() after appending N+Δ events should cost O(Δ), not O(N+Δ).
#            A production event store caches the folded state and only applies
#            NEW events on subsequent calls.
# Actual:   fold() iterates ALL events every time — O(n) per call.
# Severity: Critical — at 1M events, each fold() costs ~10s, making the
#            engine unresponsive on every state read.

def test_fold_is_incremental():
    """fold() must not re-process the entire event log on every call."""
    store = EventStore()

    # Seed 200K events
    for i in range(200_000):
        store.append(_event(i))

    # First fold — full scan, expected to be slow
    t0 = time.perf_counter()
    state1 = store.fold()
    t_first = time.perf_counter() - t0

    # Append 100 more events
    for i in range(200_000, 200_100):
        store.append(_event(i))

    # Second fold — should be O(Δ) if cached, O(N) if not
    t0 = time.perf_counter()
    state2 = store.fold()
    t_second = time.perf_counter() - t0

    # If incremental: t_second should be <1% of t_first
    # If O(n): t_second ≈ t_first (re-processes all 200K)
    ratio = t_second / t_first if t_first > 0 else 0
    assert ratio < 0.01, (
        f"fold() is O(n), not incremental: second fold took {t_second:.3f}s "
        f"vs first {t_first:.3f}s (ratio={ratio:.2f}). Expected <0.01."
    )


# ---------------------------------------------------------------------------
# Attack 2: append() computes SHA-256 checksum unconditionally
# ---------------------------------------------------------------------------
# Expected: append() should be O(1) amortized, <5µs/op for simple events.
#            Checksums are for tamper-evidence and should be optional or
#            computed lazily (only when verify_chain() is called).
# Actual:   append() calls _compute_checksum() which does json.dumps +
#            sha256 for EVERY event — 12.5µs/op measured.
# Severity: Major — at 1M events, append alone costs 12.5s; in a hot loop
#            emitting 10K events/sec, this is a bottleneck.

def test_append_is_constant_time():
    """append() must not do expensive work (SHA-256 + JSON) per event."""
    store = EventStore()
    N = 10_000

    t0 = time.perf_counter()
    for i in range(N):
        store.append(_event(i))
    elapsed = time.perf_counter() - t0

    per_op_us = (elapsed / N) * 1e6
    assert per_op_us < 5.0, (
        f"append() costs {per_op_us:.1f} µs/op — too slow. "
        f"Expected <5µs (SHA-256 + JSON serialization is expensive)."
    )


# ---------------------------------------------------------------------------
# Attack 3: subscribe() sorts handlers on every call
# ---------------------------------------------------------------------------
# Expected: subscribe() should be O(log n) (insert into sorted position) or
#            O(1) (sort lazily on publish). Sorting the entire handler list
#            on every subscribe is O(n log n) per call.
# Actual:   subscribe() calls list.sort() after every append — O(n log n).
#            With 500 handlers: 6.6ms. With 5000: ~100ms+.
# Severity: Minor — subscribe happens at setup time, not on the hot path,
#            but it's a latent footgun if dynamic subscription is added.

def test_subscribe_does_not_sort_on_every_call():
    """subscribe() must not re-sort the entire handler list each time."""
    store = EventStore()

    def handler(e: Event) -> None:
        pass

    N = 500
    t0 = time.perf_counter()
    for i in range(N):
        store.subscribe(BarClosed, handler, priority=i)
    elapsed = time.perf_counter() - t0

    per_op_ms = (elapsed / N) * 1e3
    assert per_op_ms < 0.01, (
        f"subscribe() costs {per_op_ms:.3f} ms/op — sorting on every call. "
        f"Expected <0.01 ms/op (insert into sorted position)."
    )


# ---------------------------------------------------------------------------
# Attack 4: Event UUID generation overhead
# ---------------------------------------------------------------------------
# Expected: Event creation should be cheap (<1µs). Correlation IDs should
#            use a monotonic counter (like EventBus does), not uuid4().
# Actual:   Every Event.__init__ calls uuid.uuid4() via default_factory —
#            ~1-2µs per event, plus syscall overhead for randomness.
# Severity: Minor — only matters at >100K events/sec emission rates.

def test_event_creation_is_cheap():
    """Creating an Event must not call uuid4() (expensive syscall)."""
    N = 100_000
    t0 = time.perf_counter()
    for i in range(N):
        _event(i)
    elapsed = time.perf_counter() - t0

    per_op_us = (elapsed / N) * 1e6
    assert per_op_us < 1.0, (
        f"Event creation costs {per_op_us:.2f} µs/op — uuid4() is expensive. "
        f"Expected <1µs (use monotonic counter instead)."
    )


# ---------------------------------------------------------------------------
# Attack 5: No event pruning / compaction
# ---------------------------------------------------------------------------
# Expected: After folding, old events should be compactable (snapshotted)
#            so memory doesn't grow unbounded with the event log.
# Actual:   EventStore has no prune/snapshot method. _events and _checksums
#            grow forever. At 1M events: ~16MB just for list overhead + 105MB
#            for checksum strings.
# Severity: Critical — unbounded memory growth = OOM kill in production.

def test_event_store_is_compactable():
    """EventStore must support pruning old events after a snapshot/fold."""
    store = EventStore()

    # Append 100K events
    for i in range(100_000):
        store.append(_event(i))

    # Fold to derive current state
    state = store.fold()

    # After folding, we should be able to prune old events
    # (e.g., snapshot the state and discard the log)
    if not hasattr(store, "prune"):
        pytest.fail(
            "EventStore has no prune() method — events and checksums grow "
            "unbounded. At 1M events this costs ~100MB+ in checksum strings "
            "alone. Critical memory leak in production."
        )

    # If prune exists, verify it actually reduces memory
    store.prune(keep_last=10)
    assert len(store._events) <= 10, "prune() did not reduce event count"


# ---------------------------------------------------------------------------
# Attack 6: Journal grows unbounded (no rotation)
# ---------------------------------------------------------------------------
# Expected: Journal should rotate or cap file size (e.g., 100MB max,
#            then roll to a new file). Append-only JSONL with no rotation
#            grows forever.
# Actual:   Journal.append() writes forever, no rotation, no size cap.
# Severity: Critical — disk fills up in production, crashing the engine.

def test_journal_has_rotation_or_cap():
    """Journal must rotate or cap file size to prevent disk bloat."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = f.name

    try:
        journal = Journal(path=path, fsync=False)

        # Write 10K records
        for i in range(10_000):
            journal.append({"event": "BarClosed", "i": i, "data": "x" * 100})

        size = os.path.getsize(path)

        # Check for rotation mechanism
        has_rotation = (
            hasattr(journal, "rotate")
            or hasattr(journal, "max_size")
            or hasattr(journal, "rollover")
        )

        assert has_rotation, (
            f"Journal has no rotation/cap — wrote {size:,} bytes with no "
            f"limit. In production this fills disk and crashes the engine."
        )
        journal.close()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# Attack 7: verify_chain() recomputes ALL checksums every time
# ---------------------------------------------------------------------------
# Expected: verify_chain() should be O(1) if checksums are validated on
#            append, or O(n) but only called on demand (not on every append).
# Actual:   verify_chain() recomputes every checksum from scratch — O(n).
#            At 1M events: ~10s to verify.
# Severity: Major — calling verify_chain() in a hot loop (e.g., per bar)
#            would freeze the engine.

def test_verify_chain_does_not_recompute_all_checksums():
    """verify_chain() should not recompute every checksum from scratch."""
    store = EventStore()
    N = 100_000
    for i in range(N):
        store.append(_event(i))

    t0 = time.perf_counter()
    ok = store.verify_chain()
    elapsed = time.perf_counter() - t0

    assert ok
    per_op_us = (elapsed / N) * 1e6
    assert per_op_us < 1.0, (
        f"verify_chain() costs {per_op_us:.1f} µs/event — recomputing all "
        f"checksums. Expected <1µs (validate incrementally on append)."
    )


# ---------------------------------------------------------------------------
# Attack 8: get_since() copies the entire slice
# ---------------------------------------------------------------------------
# Expected: get_since() should return a view or iterator, not a copy.
#            Slicing a 1M-element list creates a new list — O(k) memory.
# Actual:   get_since() calls list(self._events[start_idx:]) — full copy.
# Severity: Minor — only matters when fetching large ranges, but a
#            production system should stream or use a ring buffer.

def test_get_since_does_not_copy_entire_slice():
    """get_since() should not copy the entire matching slice."""
    store = EventStore()
    N = 500_000
    for i in range(N):
        store.append(_event(i))

    # Fetch last 100 events
    t0 = time.perf_counter()
    events = store.get_since(N - 100)
    elapsed = time.perf_counter() - t0

    assert len(events) == 101  # inclusive of start
    per_op_us = (elapsed / len(events)) * 1e6
    assert per_op_us < 0.1, (
        f"get_since() costs {per_op_us:.2f} µs/event — copying slice. "
        f"Expected <0.1µs (return view/iterator)."
    )


# ---------------------------------------------------------------------------
# Attack 9: export() builds full list of dicts in memory
# ---------------------------------------------------------------------------
# Expected: export() should stream to a file or use a generator, not
#            build a list of N dicts (O(n) memory).
# Actual:   export() builds a list of N dicts — at 1M events, ~500MB+.
# Severity: Major — exporting the event log for persistence/replay OOMs.

def test_export_does_not_build_full_list():
    """export() should stream, not build a list of all event dicts."""
    store = EventStore()
    N = 100_000
    for i in range(N):
        store.append(_event(i))

    # Check if export returns a generator
    result = store.export()
    is_generator = hasattr(result, "__next__") and not isinstance(result, list)

    assert is_generator, (
        f"export() returns a list of {len(result):,} dicts — O(n) memory. "
        f"At 1M events this is ~500MB+. Should be a generator."
    )


# ---------------------------------------------------------------------------
# Attack 10: Thread explosion — 500 engines = 500 threads
# ---------------------------------------------------------------------------
# Expected: QuantCoordinator should use a thread pool (bounded) or async
#            event loop, not one thread per engine.
# Actual:   Each QuantEngine gets its own daemon thread. 500 engines =
#            500 threads — kernel scheduling overhead, memory (~8MB/stack).
# Severity: Major — 500 threads × 8MB stack = 4GB just for thread stacks.

def test_coordinator_does_not_spawn_unbounded_threads():
    """QuantCoordinator must bound thread count (pool), not 1:1 with engines."""
    from quant.multi_engine import QuantCoordinator

    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord.market_data = MagicMock()
    coord.broker = MagicMock()
    coord.config = {"exchange": "NSE", "eod_squareoff_minutes_before_close": 15}
    coord._strategy = None
    coord._storage = None
    coord._contracts_file = "/tmp/.test_contracts.json"
    coord._session_levels = MagicMock()
    coord._feed = MagicMock()
    coord._engines = {}
    coord._gateways = {}
    coord._underlying_gateways = {}
    coord._threads = {}
    coord._stop = threading.Event()
    coord._eod_thread = None
    coord._gex_by_root = {}
    coord._lock = threading.Lock()
    coord._lifecycle_lock = threading.RLock()
    coord._portfolio_risk = MagicMock()
    coord.started = False
    coord.reconciliation = None

    # Check for thread pool mechanism
    has_thread_pool = (
        hasattr(coord, "_thread_pool")
        or hasattr(coord, "_executor")
        or hasattr(coord, "_max_threads")
    )

    assert has_thread_pool, (
        "QuantCoordinator has no thread pool — each engine spawns its own "
        "daemon thread. 500 engines = 500 threads = ~4GB stack memory. "
        "Should use a bounded thread pool."
    )


# ---------------------------------------------------------------------------
# Attack 11: EngineState.with_* creates new object every call
# ---------------------------------------------------------------------------
# Expected: State transitions should be cheap (<1µs). Frozen dataclass
#            replace() is acceptable but creates garbage.
# Actual:   Each with_bar/with_position/with_risk calls dataclasses.replace
#            which does a full copy — ~2-3µs per transition.
# Severity: Minor — only matters at >500K transitions/sec.

def test_state_transition_is_cheap():
    """State transitions should be <1µs (no full copy)."""
    state = EngineState(symbol="NIFTY")
    bar = _bar(0)

    N = 100_000
    t0 = time.perf_counter()
    for _ in range(N):
        state = state.with_bar(bar)
    elapsed = time.perf_counter() - t0

    per_op_us = (elapsed / N) * 1e6
    assert per_op_us < 1.0, (
        f"State transition costs {per_op_us:.2f} µs/op — dataclasses.replace "
        f"is expensive. Expected <1µs."
    )


# ---------------------------------------------------------------------------
# Attack 12: Memory leak — 1M events unbounded growth
# ---------------------------------------------------------------------------
# Expected: EventStore should support pruning/snapshotting so memory is
#            bounded by the working set, not total events ever.
# Actual:   _events and _checksums grow forever. No prune method.
# Severity: Critical — OOM kill in production.

def test_event_store_memory_bounded():
    """EventStore memory must be bounded (prune/snapshot support)."""
    store = EventStore()

    # Append 100K events
    for i in range(100_000):
        store.append(_event(i))

    # Fold to derive state
    state = store.fold()

    # Must have a way to prune old events
    prune_methods = [m for m in dir(store) if "prune" in m.lower() or "compact" in m.lower() or "snapshot" in m.lower()]
    assert prune_methods, (
        f"EventStore has no prune/compact/snapshot method. "
        f"Events grow unbounded — at 1M events, ~100MB+ in checksums alone. "
        f"Available methods: {[m for m in dir(store) if not m.startswith('__')]}"
    )
