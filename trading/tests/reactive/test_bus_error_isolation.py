"""Tests for per-subscriber error isolation in ReactiveBus.subscribe()."""

from __future__ import annotations

from typing import Any

from tradex_trading.reactive.bus import ReactiveBus


class _FakeCounter:
    def __init__(self) -> None:
        self.value = 0

    def inc(self) -> None:
        self.value += 1


class _FakeMetrics:
    def __init__(self) -> None:
        self.counters: dict[str, _FakeCounter] = {}

    def counter(self, name: str) -> _FakeCounter:
        if name not in self.counters:
            self.counters[name] = _FakeCounter()
        return self.counters[name]


def _raise_on_next(m: Any) -> None:
    del m
    raise RuntimeError("subscriber boom")


class TestSubscriberIsolation:
    def test_raising_subscriber_does_not_block_others(self) -> None:
        bus = ReactiveBus()
        received: list[Any] = []
        bus.subscribe(on_next=_raise_on_next)
        bus.subscribe(on_next=received.append)
        bus.publish("m1")
        bus.publish("m2")
        assert received == ["m1", "m2"]

    def test_publish_does_not_raise_with_raising_subscriber(self) -> None:
        bus = ReactiveBus()
        received: list[Any] = []
        bus.subscribe(on_next=_raise_on_next)
        bus.subscribe(on_next=received.append)
        bus.publish("m")  # Should not raise
        assert received == ["m"]

    def test_error_is_logged(self, caplog: Any) -> None:
        import logging

        bus = ReactiveBus()
        bus.subscribe(on_next=_raise_on_next)
        with caplog.at_level(logging.ERROR, logger="tradex_trading.reactive.bus"):
            bus.publish("m")
        assert any("Subscriber error" in r.message for r in caplog.records)

    def test_subscriber_errors_counter_increments(self) -> None:
        metrics = _FakeMetrics()
        bus = ReactiveBus(metrics=metrics)
        bus.subscribe(on_next=_raise_on_next)
        bus.publish("m1")
        bus.publish("m2")
        assert metrics.counters["bus.messages.subscriber_errors"].value == 2

    def test_no_metrics_no_crash(self) -> None:
        bus = ReactiveBus()
        received: list[Any] = []
        bus.subscribe(on_next=_raise_on_next)
        bus.subscribe(on_next=received.append)
        bus.publish("m")
        assert received == ["m"]


class TestBackpressure:
    """Bounded subscribers decouple delivery onto a worker thread with a real
    bounded queue: the publisher never blocks, and overflow evicts the oldest
    message, firing the backpressure callback once until the queue drains."""

    @staticmethod
    def _wait_for(received: list[Any], n: int, timeout: float = 2.0) -> None:
        import time

        deadline = time.monotonic() + timeout
        while len(received) < n and time.monotonic() < deadline:
            time.sleep(0.005)

    def test_bounded_buffer_delivers_asynchronously(self) -> None:
        bus = ReactiveBus()
        received: list[Any] = []
        bus.subscribe(on_next=received.append, max_queue_size=10)
        bus.publish("m1")
        bus.publish("m2")
        self._wait_for(received, 2)
        assert received == ["m1", "m2"]
        bus.dispose()

    def test_overflow_evicts_oldest_and_signals_once(self) -> None:
        import threading

        bus = ReactiveBus()
        received: list[Any] = []
        backpressure: list[str] = []
        entered = threading.Event()
        gate = threading.Event()
        lock = threading.Lock()

        def slow(msg: Any) -> None:
            if msg == "m1":
                entered.set()
                gate.wait()  # block the worker until released
            with lock:
                received.append(msg)

        bus.subscribe(
            on_next=slow,
            max_queue_size=2,
            on_backpressure=lambda t: backpressure.append(t),
            subscriber_type="bp-test",
        )
        bus.publish("m1")
        assert entered.wait(timeout=2.0)  # worker is inside slow("m1")
        bus.publish("m2")  # queued (1/2)
        bus.publish("m3")  # queued (2/2)
        bus.publish("m4")  # overflow -> evict m2, signal backpressure
        assert backpressure == ["bp-test"]
        gate.set()  # release the worker; m1, m3, m4 delivered
        self._wait_for(received, 3)
        assert received == ["m1", "m3", "m4"]
        bus.dispose()

    def test_bounded_buffer_without_callback_still_delivers(self) -> None:
        bus = ReactiveBus()
        received: list[Any] = []
        bus.subscribe(on_next=received.append, max_queue_size=10)
        bus.publish("m1")
        bus.publish("m2")
        self._wait_for(received, 2)
        assert received == ["m1", "m2"]
        bus.dispose()
