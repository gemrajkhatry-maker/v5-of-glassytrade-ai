"""Performance profiling for SubmissionHandler under high-frequency load.

Measures throughput and latency for various OMS scenarios:
- Full fills (best case)
- Partial fills (reconciliation overhead)
- Rejections (error handling overhead)
- Mixed workloads (realistic scenario)

Run with: pytest tests/quant/test_submission_handler_performance.py --benchmark-only
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock


from quant.decision.signal_builder import Signal
from quant.engine.submission_handler import SubmissionHandler


# ---------------------------------------------------------------------------
# High-performance simulated OMS
# ---------------------------------------------------------------------------

@dataclass
class PerfFill:
    """Minimal fill representation for performance testing."""
    order_id: str
    requested_quantity: float
    filled_quantity: float
    fill_price: float


class HighPerfOMS:
    """High-performance OMS simulator for benchmarking."""

    def __init__(
        self,
        lot_size: float = 1.0,
        fill_behavior: str = "full",
        partial_fill_ratio: float = 0.5,
    ):
        self.lot_size = lot_size
        self.fill_behavior = fill_behavior
        self.partial_fill_ratio = partial_fill_ratio
        self.last_fill: PerfFill | None = None
        self._order_counter = 0

    def submit(self, signal: Signal, quantity: float) -> Any:
        """Simulate OMS submission with minimal overhead."""
        self._order_counter += 1

        if self.fill_behavior == "full":
            self.last_fill = PerfFill(
                order_id=f"ORD-{self._order_counter}",
                requested_quantity=quantity,
                filled_quantity=quantity,
                fill_price=signal.entry,
            )
        elif self.fill_behavior == "partial":
            filled_qty = quantity * self.partial_fill_ratio
            self.last_fill = PerfFill(
                order_id=f"ORD-{self._order_counter}",
                requested_quantity=quantity,
                filled_quantity=filled_qty,
                fill_price=signal.entry,
            )
        elif self.fill_behavior == "reject":
            raise RuntimeError("Order rejected")

        return MagicMock()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeBar:
    time: str = "2026-01-15T10:00:00+05:30"
    open: float = 100.0
    high: float = 105.0
    low: float = 95.0
    close: float = 102.0
    volume: float = 1000.0


@dataclass
class FakeRiskState:
    trades_today: int = 0
    equity: float = 100000.0


class FakeRisk:
    def __init__(self):
        self.model_sizing_failures = 0
        self._state = FakeRiskState()

    def state(self):
        return self._state

    def position_size(self, entry, sl, *, lot_size=1.0, is_expiry=False, max_lots=None, forecast=None, side=""):
        return lot_size * 10


class FakePositionManager:
    def __init__(self):
        self.current_position = None


class FakePortfolioRisk:
    def can_accept(self, trade_risk, symbol=""):
        return True, "OK"

    def register_open(self, trade_risk, symbol=""):
        return True

    def release(self, amount, symbol=""):
        pass


def make_signal(entry=100.0):
    return Signal(
        type="LONG",
        reason="Triple-A",
        entry=entry,
        sl=98.0,
        tp=106.0,
        rr=3.0,
        model_label="Triple-A",
        symbol="NIFTY24JAN100CE",
        timestamp="2026-01-15T10:00:00+05:30",
    )


def make_submission_handler(oms: HighPerfOMS):
    _open_trade_risk = 0.0

    def get_open_trade_risk():
        return _open_trade_risk

    def set_open_trade_risk(v):
        nonlocal _open_trade_risk
        _open_trade_risk = v

    return SubmissionHandler(
        config={
            "symbol": "NIFTY24JAN100CE",
            "contract_expiry": None,
            "max_lots": None,
            "execution_model": None,
            "contract": None,
            "execution_enabled": True,
        },
        deps={
            "risk": FakeRisk(),
            "oms": oms,
            "get_portfolio_risk": lambda: FakePortfolioRisk(),
            "get_position_manager": lambda: FakePositionManager(),
            "forecast_fn": None,
        },
        state={
            "get_bar_index": lambda: 10,
            "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda v: None,
            "get_latch": lambda: {},
            "set_latch": lambda k, v: None,
            "pop_latch": lambda k: None,
            "get_open_trade_risk": get_open_trade_risk,
            "set_open_trade_risk": set_open_trade_risk,
            "get_exposure_state": lambda: None,
            "set_exposure_state": lambda v: None,
            "set_entry_time_epoch": lambda v: None,
            "set_last_rejected_bar_index": lambda: None,
        },
        emit=lambda event: None,
        latch_or_signal_block=lambda signal, reason, bar_time: None,
        notify_advisor_position=lambda bar, amt_dto, position: None,
    )


# ---------------------------------------------------------------------------
# Performance benchmarks
# ---------------------------------------------------------------------------

class TestSubmissionHandlerPerformance:
    """Performance benchmarks for SubmissionHandler."""

    def test_full_fill_throughput(self, benchmark):
        """Measure throughput for full fill scenario (best case)."""
        oms = HighPerfOMS(fill_behavior="full")
        handler = make_submission_handler(oms)
        bar = FakeBar()
        signal = make_signal()

        def submit_order():
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        benchmark(submit_order)
        # Benchmark will report iterations and time

    def test_partial_fill_throughput(self, benchmark):
        """Measure throughput for partial fill scenario (reconciliation overhead)."""
        oms = HighPerfOMS(fill_behavior="partial", partial_fill_ratio=0.5)
        handler = make_submission_handler(oms)
        bar = FakeBar()
        signal = make_signal()

        def submit_order():
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        benchmark(submit_order)

    def test_rejection_throughput(self, benchmark):
        """Measure throughput for rejection scenario (error handling overhead)."""
        oms = HighPerfOMS(fill_behavior="reject")
        handler = make_submission_handler(oms)
        bar = FakeBar()
        signal = make_signal()

        def submit_order():
            try:
                handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
            except Exception:
                pass  # Expected

        benchmark(submit_order)

    def test_high_frequency_burst(self, benchmark):
        """Measure throughput for high-frequency burst (1000 orders)."""
        oms = HighPerfOMS(fill_behavior="full")
        handler = make_submission_handler(oms)
        bar = FakeBar()

        def submit_burst():
            for i in range(1000):
                signal = make_signal(entry=100.0 + i * 0.01)
                handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        benchmark(submit_burst)

    def test_mixed_workload(self, benchmark):
        """Measure throughput for mixed workload (70% full, 20% partial, 10% reject)."""
        oms_full = HighPerfOMS(fill_behavior="full")
        oms_partial = HighPerfOMS(fill_behavior="partial", partial_fill_ratio=0.5)
        oms_reject = HighPerfOMS(fill_behavior="reject")

        handler_full = make_submission_handler(oms_full)
        handler_partial = make_submission_handler(oms_partial)
        handler_reject = make_submission_handler(oms_reject)

        bar = FakeBar()

        def submit_mixed():
            for i in range(100):
                signal = make_signal(entry=100.0 + i * 0.01)
                if i < 70:
                    handler_full.submit(signal, bar, {}, MagicMock(), "Triple-A")
                elif i < 90:
                    handler_partial.submit(signal, bar, {}, MagicMock(), "Triple-A")
                else:
                    try:
                        handler_reject.submit(signal, bar, {}, MagicMock(), "Triple-A")
                    except Exception:
                        pass

        benchmark(submit_mixed)


# ---------------------------------------------------------------------------
# Latency measurements
# ---------------------------------------------------------------------------

class TestSubmissionHandlerLatency:
    """Latency measurements for SubmissionHandler."""

    def test_single_order_latency(self):
        """Measure latency for a single order submission."""
        import time

        oms = HighPerfOMS(fill_behavior="full")
        handler = make_submission_handler(oms)
        bar = FakeBar()
        signal = make_signal()

        # Warmup
        for _ in range(100):
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        # Measure
        start = time.perf_counter()
        iterations = 10000
        for _ in range(iterations):
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
        end = time.perf_counter()

        total_time = end - start
        avg_latency_us = (total_time / iterations) * 1_000_000
        throughput = iterations / total_time

        print(f"\n{'='*70}")
        print("SubmissionHandler Latency Profile")
        print(f"{'='*70}")
        print(f"Total time: {total_time:.3f}s")
        print(f"Iterations: {iterations}")
        print(f"Average latency: {avg_latency_us:.2f} µs")
        print(f"Throughput: {throughput:.0f} orders/sec")
        print(f"{'='*70}")

        # Assertions for performance regression detection
        assert avg_latency_us < 1000, f"Latency too high: {avg_latency_us:.2f} µs"
        assert throughput > 1000, f"Throughput too low: {throughput:.0f} orders/sec"

    def test_partial_fill_latency(self):
        """Measure latency for partial fill scenario."""
        import time

        oms = HighPerfOMS(fill_behavior="partial", partial_fill_ratio=0.5)
        handler = make_submission_handler(oms)
        bar = FakeBar()
        signal = make_signal()

        # Warmup
        for _ in range(100):
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        # Measure
        start = time.perf_counter()
        iterations = 10000
        for _ in range(iterations):
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
        end = time.perf_counter()

        total_time = end - start
        avg_latency_us = (total_time / iterations) * 1_000_000
        throughput = iterations / total_time

        print(f"\n{'='*70}")
        print("SubmissionHandler Partial Fill Latency Profile")
        print(f"{'='*70}")
        print(f"Total time: {total_time:.3f}s")
        print(f"Iterations: {iterations}")
        print(f"Average latency: {avg_latency_us:.2f} µs")
        print(f"Throughput: {throughput:.0f} orders/sec")
        print(f"{'='*70}")

        assert avg_latency_us < 1500, f"Latency too high: {avg_latency_us:.2f} µs"

    def test_high_frequency_sustainability(self):
        """Measure sustained throughput over 100k orders."""
        import time

        oms = HighPerfOMS(fill_behavior="full")
        handler = make_submission_handler(oms)
        bar = FakeBar()

        # Warmup
        for i in range(1000):
            signal = make_signal(entry=100.0 + i * 0.01)
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        # Measure sustained throughput
        start = time.perf_counter()
        iterations = 100000
        for i in range(iterations):
            signal = make_signal(entry=100.0 + i * 0.01)
            handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
        end = time.perf_counter()

        total_time = end - start
        throughput = iterations / total_time
        avg_latency_us = (total_time / iterations) * 1_000_000

        print(f"\n{'='*70}")
        print("SubmissionHandler High-Frequency Sustainability Profile")
        print(f"{'='*70}")
        print(f"Total orders: {iterations}")
        print(f"Total time: {total_time:.3f}s")
        print(f"Sustained throughput: {throughput:.0f} orders/sec")
        print(f"Average latency: {avg_latency_us:.2f} µs")
        print(f"{'='*70}")

        # Performance requirements for Python-based trading system
        # Note: Python overhead limits throughput compared to C++/Java systems
        # 2000+ orders/sec is good for Python with full pipeline execution
        assert throughput > 2000, f"Throughput too low: {throughput:.0f} orders/sec"
        assert avg_latency_us < 600, f"Latency too high: {avg_latency_us:.2f} µs"
