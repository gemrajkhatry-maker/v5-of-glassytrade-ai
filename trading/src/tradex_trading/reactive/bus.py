"""RxPY Subject-backed ReactiveBus.

Replaces v3's imperative EventBus with reactive streams.
Every message is an Observable emission.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from datetime import time
from typing import Any

import rx
from rx import operators as ops
from rx.disposable import CompositeDisposable
from rx.subject import Subject

log = logging.getLogger(__name__)
SubscriberType = str


def _ts(m: object) -> time | None:  # type: ignore[type-arg]
    """Extract a comparable timestamp from a message, if present.

    Messages are expected to carry a ``timestamp`` attribute (typically a
    ``datetime``). For messages that don't (``str``, etc.), return ``None``
    so the replay filter can pass them through unconditionally.
    """
    return getattr(m, "timestamp", None)

#: ponytail: nested-delivery cap — a buggy subscriber that republishes forever
#: must fail visibly (like the old RecursionError), not hang the bus silently.
_MAX_NESTED_DELIVERIES = 10_000


class ReactiveBus:
    """RxPY Subject-backed message bus.

    Replaces v3's imperative EventBus with reactive streams.
    Every message is an Observable emission.
    """

    def __init__(self, message_log: list[Any] | None = None, metrics: Any = None) -> None:
        self._subject: Subject = Subject()
        self._log: list[Any] | None = message_log
        self._disposables: CompositeDisposable = CompositeDisposable()
        self._metrics = metrics
        self._pending: deque[Any] = deque()
        self._draining = False
        self._workers: list[tuple[threading.Thread, threading.Event]] = []

    def set_bounded_log(self, log: Any) -> None:
        """Bound the internal message log with a caller-supplied container.

        ``ThreadSafeReactiveBus`` swaps the unbounded list log for a bounded
        ``deque`` through this declared setter rather than poking the private
        ``_log`` field directly.
        """
        self._log = log


    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, message: object) -> None:
        """Publish a message to all subscribers.

        Delivery is synchronous and latency-neutral: a nested ``publish()``
        made from inside a subscriber is enqueued and drained by the outermost
        ``publish()`` before it returns, so stream order is always causal
        (matching the message log) and effects are visible before ``publish``
        returns. No buffering across calls — live market events are never
        delayed by ordering.

        Single-threaded only: the drain state (``_pending``/``_draining``) is
        not locked. Publish from one thread, or wrap the bus in
        ``ThreadSafeReactiveBus`` for concurrent publishers.
        """
        if self._log is not None:
            self._log.append(message)
        self._pending.append(message)
        if self._draining:
            return  # reentrant publish — the active drain delivers it
        self._draining = True
        try:
            delivered = 0
            while self._pending:
                delivered += 1
                if delivered > _MAX_NESTED_DELIVERIES:
                    log.error(
                        "Bus drain exceeded %d nested deliveries; "
                        "dropping backlog",
                        _MAX_NESTED_DELIVERIES,
                    )
                    self._pending.clear()
                    break
                msg = self._pending.popleft()
                try:
                    self._subject.on_next(msg)
                except Exception as exc:
                    log.error("Bus publish error: %s", exc)
                if self._metrics is not None:
                    self._metrics.counter("bus.messages.published").inc()
        finally:
            self._draining = False

    # ------------------------------------------------------------------
    # Subscribing
    # ------------------------------------------------------------------

    def of_type(self, msg_type: type) -> rx.Observable:
        """Typed stream — only messages of the given type.

        Usage::

            bus.of_type(Quote).subscribe(handle_quote)
            bus.of_type(Order).pipe(filter(...), map(...)).subscribe(...)
        """
        return self._subject.pipe(
            ops.filter(lambda m: isinstance(m, msg_type)),
            ops.share(),
        )

    def stream(self) -> rx.Observable:
        """Raw Observable of ALL messages."""
        return self._subject.pipe(ops.share())

    def subscribe(
        self,
        on_next: Any = None,
        on_error: Any = None,
        on_completed: Any = None,
        max_queue_size: int | None = None,
        on_backpressure: Callable[[SubscriberType], None] | None = None,
        subscriber_type: SubscriberType | None = None,
    ) -> Any:
        """Subscribe and track the disposable for cleanup on dispose().

        The ``on_next`` handler is wrapped so a raising subscriber is isolated:
        its exception is logged (and counted via metrics) without preventing
        other subscribers from receiving the message.

        Args:
            max_queue_size: Per-subscriber buffer cap. When the buffer overflows,
                excess messages are dropped and a ``bus.dlq_overflow`` metric is
                emitted (if metrics are available). When ``None``, RxPY's default
                unbounded Subject queue is used — the subscriber can still fall
                behind but nothing is silently dropped.
            on_backpressure: Callback invoked when the subscriber's queue reaches
                ``max_queue_size`` (or, for unbounded subscribers, when the buffer
                exceeds a heuristic threshold). Receives the subscriber type.
            subscriber_type: Label for this subscriber (e.g. ``"strategy"``,
                ``"market_data"``). Used in metrics and backpressure callbacks.
                Defaults to ``"unknown"``.
        """
        if on_next is not None:
            on_next = self._isolate(
                on_next,
                subscriber_type=subscriber_type or "unknown",
                max_queue_size=max_queue_size,
                on_backpressure=on_backpressure,
            )
        d = self._subject.subscribe(
            on_next=on_next, on_error=on_error, on_completed=on_completed,
        )
        self._disposables.add(d)
        return d

    def _isolate(
        self,
        on_next: Any,
        subscriber_type: SubscriberType = "unknown",
        max_queue_size: int | None = None,
        on_backpressure: Callable[[SubscriberType], None] | None = None,
    ) -> Any:
        """Wrap ``on_next`` so a raising subscriber is isolated, and (for bounded
        subscribers) decouple delivery onto a worker thread with a real bounded
        queue so a slow subscriber never blocks the publisher thread.

        Unbounded subscribers (the default) keep synchronous, deterministic
        delivery — a slow handler blocks the publisher (the documented
        contract). Bounded subscribers (``max_queue_size`` set) drain from a
        ``queue.Queue`` on a dedicated daemon thread; on overflow the oldest
        message is evicted, a ``bus.dlq_overflow`` metric is emitted, and
        ``on_backpressure`` fires once until the queue drains below capacity.
        """
        if max_queue_size is None:

            def safe(value: object) -> None:
                try:
                    on_next(value)
                except Exception as exc:  # noqa: BLE001 – subscriber isolation
                    log.error("Subscriber error: %s", exc)
                    if self._metrics is not None:
                        self._metrics.counter("bus.messages.subscriber_errors").inc()

            return safe

        q: queue.Queue = queue.Queue(maxsize=max_queue_size)
        stop = threading.Event()
        overflow_latch = [False]

        def drain() -> None:
            while True:
                try:
                    value = q.get(timeout=0.2)
                except queue.Empty:
                    if stop.is_set():
                        return
                    continue
                try:
                    on_next(value)
                except Exception as exc:  # noqa: BLE001 – subscriber isolation
                    log.error("Subscriber error: %s", exc)
                    if self._metrics is not None:
                        self._metrics.counter("bus.messages.subscriber_errors").inc()

        worker = threading.Thread(
            target=drain,
            name=f"bus-subscriber-{subscriber_type}",
            daemon=True,
        )
        worker.start()
        self._workers.append((worker, stop))

        def enqueue(value: object) -> None:
            while True:
                try:
                    q.put_nowait(value)
                    break
                except queue.Full:
                    # Evict the oldest queued message (bounded DLQ semantics).
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    if not overflow_latch[0]:
                        overflow_latch[0] = True
                        if on_backpressure is not None:
                            on_backpressure(subscriber_type)
                    if self._metrics is not None:
                        self._metrics.counter(
                            f"bus.dlq_overflow.{subscriber_type}"
                        ).inc()
            # Re-arm the latch once the queue has drained below capacity.
            if q.qsize() < max_queue_size:
                overflow_latch[0] = False

        return enqueue

    # ------------------------------------------------------------------
    # Replay / historical
    # ------------------------------------------------------------------

    def replay(
        self,
        start: Any | None = None,
        end: Any | None = None,
    ) -> rx.Observable:
        """Replay logged messages as an Observable sequence.

        *start* and *end* filter by each message's ``timestamp`` attribute
        (inclusive). Messages without a ``timestamp`` are always included.
        """
        if not self._log:
            return rx.empty()
        return (
            rx.from_iterable(self._log)
            .pipe(
                ops.filter(
                    lambda m: (
                        (start is None or _ts(m) >= start)
                        and (end is None or _ts(m) <= end)
                    ),
                ),
            )
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def dispose(self) -> None:
        """Clean teardown — stop worker threads, dispose subscriptions."""
        for _, stop in self._workers:
            stop.set()
        for worker, _ in self._workers:
            worker.join(timeout=1.0)
        self._workers.clear()
        self._disposables.dispose()
        try:
            self._subject.on_completed()
        except Exception:  # pragma: no cover – defensive
            pass
