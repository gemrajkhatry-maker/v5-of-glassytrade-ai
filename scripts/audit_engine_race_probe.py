"""Audit probe: is the shared TimesFMEngine's per-bar dedup thread-safe?

In TIMESFM_END_TO_END mode the advisor (worker thread) and the E2E strategy
(engine thread) share ONE TimesFMEngine. add_context() dedups with a
check-then-act:

    if bar_index >= 0 and self._last_context_bar.get(symbol) == bar_index:
        return self._context_window(buf)
    buf.append(price)
    self._last_context_bar[symbol] = bar_index

With no lock, two threads calling it for the SAME bar can both pass the check
and both append -> the model's inference window contains the bar twice, which
is the exact double-feed the C1 regression lock claims to prevent.

This probe forces that interleaving deterministically (it does not rely on
timing luck) by making the dedup read block until both threads have done it.
Read-only: mutates nothing on disk, patches in-process only.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_engine import TimesFMEngine


class RendezvousDict(dict):
    """dict whose .get() waits until both consumers have read it.

    This is the adversarial scheduler: it releases both threads past the
    check-then-act window at the same moment, which is precisely what an OS
    preemption or GIL switch can do on a busy bar.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._barrier = threading.Barrier(2, timeout=5)

    def get(self, key, default=None):
        value = super().get(key, default)
        try:
            self._barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return value


def main():
    engine = TimesFMEngine(target_horizon=8)
    symbol = "NIFTY"
    bar = Bar("2026-09-10T10:00:00+05:30", 100.0, 101.0, 99.0, 100.5, 1000, 100)
    ctx = DecisionContext(symbol=symbol, bar=bar, bar_index=42)

    # Adversarial scheduling: both consumers clear the dedup check together.
    engine._last_context_bar = RendezvousDict()

    errors = []

    def consumer(name):
        try:
            engine.add_context(ctx)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc!r}")

    t1 = threading.Thread(target=consumer, args=("advisor/worker",))
    t2 = threading.Thread(target=consumer, args=("strategy/engine",))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)

    depth = len(engine._price_buffers[symbol])
    prices = list(engine._price_buffers[symbol])

    print("\n=== shared-engine per-bar dedup under concurrency ===\n")
    print(f"  one bar, two concurrent consumers (same bar_index=42)")
    print(f"  expected buffer depth : 1")
    print(f"  actual   buffer depth : {depth}")
    print(f"  buffer contents       : {prices}")
    if errors:
        print(f"  errors                : {errors}")
    if depth == 1:
        print("  => dedup held under this interleaving")
    else:
        print("  => DOUBLE-FEED: the model window contains the bar twice")
    print()


if __name__ == "__main__":
    main()
