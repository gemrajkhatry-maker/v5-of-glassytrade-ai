"""PHASE 10 — concurrency / load audit against the REAL quant engine.

Run:  PYTHONPATH=backend:. .venv/bin/python -m pytest runtime_audit/audit/test_phase10_concurrency.py -q -s

Covers:
  1. Multi-symbol streaming (4 real QuantEngines, concurrent feed, exact bar counts, no bleed)
  2. Parallel PaperOMS order submission invariants
  3. Concurrent SQLite writes from two adapter instances on one DB file
  4. EventBus strict ordering under load + the 10k trace-cap truncation policy
  5. Memory growth probe (50k ticks through one engine, tracemalloc)
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
import tracemalloc
from collections import deque

import pytest

from quant.brokers.gateway import Tick
from quant.events import DepthUpdated, EventBus
from quant.execution.order import Fill, Order, Position
from quant.execution.oms import PaperOMS
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeGateway:
    """Thread-safe tick source satisfying the BrokerGateway protocol."""

    def __init__(self, symbol: str, ticks: list[Tick]):
        self.symbol = symbol
        self._ticks = list(ticks)
        self._lock = threading.Lock()
        self._idx = 0
        self.subscribed = False

    def subscribe(self, symbol: str) -> None:
        self.subscribed = True

    def next_tick(self) -> Tick | None:
        with self._lock:
            if self._idx >= len(self._ticks):
                return None
            t = self._ticks[self._idx]
            self._idx += 1
            return t


def make_ticks(symbol_epoch_base: int, count: int, interval_s: int = 1) -> list[Tick]:
    """Synthetic ticks spread across distinct aggregator windows."""
    ticks = []
    for i in range(count):
        epoch = symbol_epoch_base + i // 2  # 2 ticks per window
        price = 100.0 + (i % 50) * 0.25
        ticks.append(
            Tick(
                time=str(epoch),
                price=price,
                volume=10.0,
                buy_volume=6.0,
                sell_volume=4.0,
            )
        )
    return ticks


def build_engine(symbol: str, ticks: list[Tick], interval_seconds: int = 1) -> QuantEngine:
    gw = FakeGateway(symbol, ticks)
    return QuantEngine(gw, symbol, interval_seconds=interval_seconds)


# ---------------------------------------------------------------------------
# 1. Multi-symbol streaming — exact bar counts, no cross-engine bleed
# ---------------------------------------------------------------------------


def test_phase10_multi_symbol_streaming_no_lost_ticks_no_bleed():
    N = 4
    M = 600  # ticks per engine
    symbols = [f"SYM{i}" for i in range(N)]
    engines = []
    for i, sym in enumerate(symbols):
        # Distinct epoch bases so windows never collide across symbols.
        ticks = make_ticks(1_000_000 + i * 100_000, M)
        engines.append(build_engine(sym, ticks))

    traces: dict[str, list] = {}
    errors: list[BaseException] = []

    def run_one(sym: str, eng: QuantEngine) -> None:
        try:
            traces[sym] = eng.run()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=run_one, args=(s, e), daemon=True)
        for s, e in zip(symbols, engines)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert not errors, f"engine thread crashed: {errors!r}"

    for i, sym in enumerate(symbols):
        trace = traces[sym]
        # Every event must belong to its own engine's symbol — no bleed.
        wrong = [e for e in trace if getattr(e, "symbol", sym) != sym]
        assert not wrong, f"cross-engine symbol bleed into {sym}: {wrong[:3]}"

        bar_closes = [e for e in trace if type(e).__name__ == "BarClosed"]
        # M ticks, 2 per window -> M/2 windows -> M/2 - 1 closed bars.
        expected_bars = M // 2 - 1
        assert len(bar_closes) == expected_bars, (
            f"{sym}: lost/duplicated bars — got {len(bar_closes)}, "
            f"expected {expected_bars}"
        )
        # Bar times strictly increasing and unique (no duplicated windows).
        times = [b.bar.time for b in bar_closes]
        assert all(int(times[k]) < int(times[k + 1]) for k in range(len(times) - 1)), (
            f"{sym}: bar times not strictly increasing"
        )


# ---------------------------------------------------------------------------
# 2. Parallel PaperOMS submission — state machine invariants under concurrency
# ---------------------------------------------------------------------------


def test_phase10_parallel_oms_invariants():
    oms = PaperOMS(lot_size=1.0)
    results: list[tuple[Position, Fill]] = []
    lock = threading.Lock()

    def worker(tid: int) -> None:
        local = []
        for i in range(250):
            long = (tid + i) % 2 == 0
            entry = 100.0 + i * 0.1
            sl, tp = (entry - 1.0, entry + 2.0) if long else (entry + 1.0, entry - 2.0)
            sig = Signal(
                type="LONG" if long else "SHORT",
                reason=f"t{tid}-{i}",
                entry=entry,
                sl=sl,
                tp=tp,
                rr=2.0,
                model_label="Triple-A",
                symbol="SYM0",
                timestamp=str(1700000000 + i),
            )
            pos = oms.submit(sig, quantity=10)
            fill = oms.close(pos, price=tp, time=sig.timestamp, reason="TP")
            local.append((pos, fill))
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=worker, args=(k,), daemon=True) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert len(results) == 4 * 250, f"lost submissions: {len(results)}"
    ids = set()
    for pos, fill in results:
        sig = pos.order.signal
        if sig.type == "LONG":
            assert sig.sl < sig.entry < sig.tp, f"LONG invariant broken: {sig}"
        else:
            assert sig.sl > sig.entry > sig.tp, f"SHORT invariant broken: {sig}"
        # No double-fill: each submit yields a distinct Position object; the
        # fill references exactly the position it closed.
        assert fill.position is not None
        assert fill.position.open_price == pos.open_price
        # PnL consistent with signed size.
        expected_pnl = (fill.close_price - pos.open_price) * pos.size
        assert abs(fill.pnl - expected_pnl) < 1e-9
        ids.add(id(pos))
    assert len(ids) == len(results), "double-fill: Position objects reused"
    # Positions are frozen dataclasses — mutation after close is impossible.
    pos0, _ = results[0]
    try:
        pos0.realized_pnl = 999.0  # type: ignore[misc]
        raise AssertionError("Position mutated after close — not frozen!")
    except Exception as exc:
        assert type(exc).__name__ == "FrozenInstanceError", f"unexpected: {exc!r}"


# ---------------------------------------------------------------------------
# 3. Concurrent SQLite writes — two adapters, one DB file
# ---------------------------------------------------------------------------


def test_phase10_sqlite_concurrent_writes(tmp_path):
    from backend.app.infrastructure.storage.database import SQLiteStorageAdapter

    db_file = str(tmp_path / "concurrent.db")
    adapter_a = SQLiteStorageAdapter(db_path=db_file)
    adapter_b = SQLiteStorageAdapter(db_path=db_file)

    n_per_adapter = 2000
    lock_errors: list[str] = []
    done = {"a": False, "b": False}

    def write_ticks(adapter, symbol: str, tag: str) -> None:
        try:
            for i in range(n_per_adapter):
                adapter.save_tick(
                    symbol,
                    {
                        "time": f"{tag}-{i:06d}",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1.0,
                        "delta": 0.5,
                    },
                )
        except sqlite3.OperationalError as exc:
            lock_errors.append(f"{symbol}: {exc}")
        finally:
            done[tag] = True

    ta = threading.Thread(target=write_ticks, args=(adapter_a, "AAAA", "a"))
    tb = threading.Thread(target=write_ticks, args=(adapter_b, "BBBB", "b"))
    t0 = time.time()
    ta.start(); tb.start()
    ta.join(timeout=120); tb.join(timeout=120)
    elapsed = time.time() - t0

    assert done["a"] and done["b"], "writer thread timed out"
    # Force-flush both buffers (the 5s timer would also do it).
    adapter_a._flush_ticks()
    adapter_b._flush_ticks()

    # Read back through an independent connection.
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    count_a = conn.execute("SELECT COUNT(*) c FROM ticks WHERE symbol='AAAA'").fetchone()["c"]
    count_b = conn.execute("SELECT COUNT(*) c FROM ticks WHERE symbol='BBBB'").fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM ticks").fetchone()["c"]
    conn.close()

    print(f"\n[sqlite] elapsed={elapsed:.2f}s rows A={count_a}/{n_per_adapter} "
          f"B={count_b}/{n_per_adapter} total={total} lock_errors={lock_errors}")

    assert count_a == n_per_adapter, f"LOST ROWS in AAAA: {count_a}/{n_per_adapter}"
    assert count_b == n_per_adapter, f"LOST ROWS in BBBB: {count_b}/{n_per_adapter}"
    assert not lock_errors, f"unrecoverable lock errors: {lock_errors}"


# ---------------------------------------------------------------------------
# 4. Event ordering under load + 10k cap behavior
# ---------------------------------------------------------------------------


def test_phase10_event_bus_ordering_strict():
    bus = EventBus()
    seen: list[int] = []
    bus.subscribe(DepthUpdated, lambda e: seen.append(int(e.event_id)))

    n = 10_000
    for i in range(n):
        bus.publish(DepthUpdated(symbol="X", time="0", depth={"p": i}))

    assert len(seen) == n, f"handler missed events: {len(seen)}/{n}"
    assert seen == sorted(seen), "event ordering violated"
    assert len(set(seen)) == n, "duplicate event_ids"
    print("\n[eventbus] 10k events: strict seq ordering OK, zero loss")


def test_phase10_trace_cap_10k_truncation_policy():
    """What happens at event 10001 on the REAL engine trace?"""
    eng = build_engine("CAPTEST", [], interval_seconds=60)
    emitted: list[str] = []
    total = 10_001
    for i in range(total):
        eid_before = None
        eng._emit(DepthUpdated(symbol="CAPTEST", time="0", depth={"i": i}))
        emitted.append(str(i))  # logical marker; real check below via depth payload

    trace = eng._trace
    print(f"\n[cap] emitted={total} trace_len={len(trace)} maxlen={trace.maxlen}")
    assert len(trace) == 10_000, f"trace not capped at 10k: {len(trace)}"
    # The FIRST emitted event must be gone — silent lossy truncation.
    first = trace[0]
    assert first.depth["i"] == 1, (
        f"expected event#0 evicted, but trace[0].depth={first.depth}"
    )
    last = trace[-1]
    assert last.depth["i"] == total - 1, "newest event missing"
    print("[cap] FINDING: deque(maxlen=10000) silently DROPS OLDEST events "
          "(event #0 lost at emit #10001). No warning, no counter.")


# ---------------------------------------------------------------------------
# 5. Memory growth probe — 50k ticks through one engine
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "FINDING (confirmed by execution + tracemalloc statistics): growth is "
        "NOT bounded. quant/amt/dto.py:135 embeds the FULL per-candle footprint "
        "(~11,859 level dicts per AmtUpdated in this run) into every event; the "
        "engine._trace deque(maxlen=10000) bounds event COUNT, not bytes. "
        "833 closed bars retained 8.7M level dicts == ~2.4GB."
    ),
)
def test_phase10_memory_growth_50k_ticks():
    count = 50_000
    ticks = [
        Tick(time=str(2_000_000 + i), price=100.0 + (i % 100) * 0.05,
             volume=1.0, buy_volume=0.6, sell_volume=0.4)
        for i in range(count)
    ]
    eng = build_engine("MEMTEST", ticks, interval_seconds=60)

    tracemalloc.start()
    base_current, base_peak = tracemalloc.get_traced_memory()
    t0 = time.time()
    trace = eng.run()
    elapsed = time.time() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    growth_mb = (cur - base_current) / 1024 / 1024
    peak_mb = peak / 1024 / 1024
    bars = sum(1 for e in trace if type(e).__name__ == "BarClosed")
    print(f"\n[memory] ticks={count} bars_closed={bars} elapsed={elapsed:.1f}s "
          f"growth={growth_mb:.2f}MB peak={peak_mb:.2f}MB")

    THRESHOLD_MB = 150.0
    print(f"[memory] FINDING: growth={growth_mb:.2f}MB far exceeds {THRESHOLD_MB}MB "
          f"threshold — trace is count-bounded, not byte-bounded "
          f"(~2.9MB retained per closed bar via AmtUpdated footprints)")
    assert growth_mb < THRESHOLD_MB, (
        f"unbounded memory growth: {growth_mb:.2f}MB > {THRESHOLD_MB}MB"
    )
