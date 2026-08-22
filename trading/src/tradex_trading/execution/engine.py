"""Reactive execution engine — the v4 order spine.

Wires the reactive pipeline: idempotency → risk → fill → OMS, all as
RxPY operators on the ReactiveBus.  This is the core of v4 — the
reactive execution pipeline.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from tradex_domain.enums import OrderStatus, OrderType, TimeInForce
from tradex_domain.errors import OrderRejectedError
from tradex_domain.events import (
    ErrorOccurred,
    OrderFilled,
    OrderPlaced,
    OrderRejected,
    PlaceOrderCommand,
)
from tradex_domain.execution import Fill, Order, OrderReceipt, OrderRequest, Position
from tradex_domain.value_objects import CorrelationId, OrderId

from tradex_trading.execution.fees import FeeCalculator
from tradex_trading.execution.fill_sources import FillSource, _make_order
from tradex_trading.execution.order_manager import OrderManager
from tradex_trading.execution.position_manager import PositionManager
from tradex_trading.execution.reconciliation import DriftItem, ReconciliationEngine
from tradex_trading.execution.trading_cache import TradingCache

if TYPE_CHECKING:
    from tradex_trading.runtime.metrics import MetricsRegistry

log = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.UNKNOWN,
})

# ---------------------------------------------------------------------------
# Latency instrumentation
# ---------------------------------------------------------------------------

_SUBMISSION_HISTOGRAM = "orders.submission_latency_millis"
_FILL_HISTOGRAM = "orders.fill_latency_millis"
_SLIPPAGE_HISTOGRAM = "orders.slippage_bps"

#: Sliding window (seconds) for the max-orders-per-minute rate limit.
_RATE_WINDOW_SECONDS = 60


class _OrderTiming:
    """Captures submission/ACK/fill instants for one correlation."""

    __slots__ = ("submit_start", "ack_wall", "fill_wall", "reference_price")

    def __init__(
        self,
        submit_start: float,
        reference_price: Decimal | None = None,
    ) -> None:
        self.submit_start = submit_start
        self.ack_wall = submit_start
        self.fill_wall = submit_start
        self.reference_price = reference_price


class LatencyTracker:
    """Dict-keyed timing store keyed by correlation id with final-state cleanup.

    The `_fn` delete callback:
    - ACK subscriber: call _finalize on terminal write
    - Fill subscriber: _finalize on terminal write (already called),
    - Also must be thread-safe: `threading.RLock` guards all access.
    """

    def __init__(self, metrics: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, _OrderTiming] = {}
        #: Metrics registry for latency/slippage histograms. Previously the
        #: tracker never held a metrics reference, so every ``record_ack`` /
        #: ``record_fill`` raised AttributeError (swallowed by the engine's
        #: try/except) and the submission/fill/slippage metrics were dead.
        self._metrics = metrics

    def record_submit(self,
                      correlation_id: CorrelationId,
                      submit_start: float,
                      reference_price: Decimal | None = None,
                      ) -> None:
        """Record submission start time for an order."""
        with self._lock:
            cid_key = str(getattr(correlation_id, "value", correlation_id))
            self._entries[cid_key] = _OrderTiming(
                submit_start=submit_start,
                reference_price=reference_price,
            )

    def record_ack(self, correlation_id: CorrelationId, ack_wall: float) -> None:
        """Record ACK time for an order."""
        with self._lock:
            cid_key = str(getattr(correlation_id, "value", correlation_id))
            entry = self._entries.get(cid_key)
            if entry is None:
                return
            entry.ack_wall = ack_wall
            # Compute submission latency on ACK if possible
            if self._metrics is not None:
                self._metrics.histogram(_SUBMISSION_HISTOGRAM).observe(
                    (ack_wall - entry.submit_start) * 1000,
                )
            # Log
            log.info(
                "Order ACK'd — submission_latency_ms=%.2f",
                (ack_wall - entry.submit_start) * 1000,
            )

    def record_fill(self,
                    correlation_id: CorrelationId,
                    fill_wall: float,
                    fill_price: Decimal,
                    ) -> None:
        """Record fill time and compute fill latency + slippage."""
        with self._lock:
            cid_key = str(getattr(correlation_id, "value", correlation_id))
            entry = self._entries.get(cid_key)
            if entry is None:
                return
            entry.fill_wall = fill_wall
            # Fill latency from ACK time
            if self._metrics is not None:
                self._metrics.histogram(_FILL_HISTOGRAM).observe(
                    (fill_wall - entry.ack_wall) * 1000,
                )
            # Slippage from reference price if available (metric math in float;
            # money stays Decimal in the accounting layer).
            if entry.reference_price is not None and entry.reference_price > 0:
                ref = float(entry.reference_price)
                price = float(fill_price)
                slippage_bps = abs(price - ref) / ref * 10_000.0
                if self._metrics is not None:
                    self._metrics.histogram(_SLIPPAGE_HISTOGRAM).observe(slippage_bps)
                log.info(
                    "Order filled — fill_latency_ms=%.2f slippage_bps=%.2f",
                    (fill_wall - entry.ack_wall) * 1000,
                    slippage_bps,
                )
            else:
                log.info(
                    "Order filled — fill_latency_ms=%.2f",
                    (fill_wall - entry.ack_wall) * 1000,
                )
            # Clean up after terminal state
            self._entries.pop(str(getattr(correlation_id, "value", correlation_id)), None)

    def cleanup(self, correlation_id: CorrelationId) -> None:
        """Clean up timing entry for a completed order."""
        with self._lock:
            cid_key = str(getattr(correlation_id, "value", correlation_id))
            self._entries.pop(cid_key, None)


# ---------------------------------------------------------------------------
# Risk gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    """Outcome of a risk check — approved flag plus human-readable reason."""

    approved: bool
    reason: str = ""


# ---------------------------------------------------------------------------
# Order store
# ---------------------------------------------------------------------------


@runtime_checkable
class OrderStore(Protocol):
    """Persistence abstraction for orders."""

    def upsert(self, order: Order) -> None: ...
    def get(self, order_id: OrderId) -> Order | None: ...
    def all_orders(self) -> list[Order]: ...


class InMemoryOrderStore:
    """Dict-backed OrderStore for tests and single-process use."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def upsert(self, order: Order) -> None:
        self._orders[order.order_id.value] = order

    def get(self, order_id: OrderId) -> Order | None:
        key = order_id.value if isinstance(order_id, OrderId) else str(order_id)
        return self._orders.get(key)

    def all_orders(self) -> list[Order]:
        return list(self._orders.values())


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdempotencyDuplicate:
    """A completed idempotent request — its recorded result is returned."""

    result: Any


@runtime_checkable
class IdempotencyGuard(Protocol):
    def check_and_reserve(
        self, correlation_id: CorrelationId,
    ) -> IdempotencyDuplicate | None: ...
    def record_result(
        self, correlation_id: CorrelationId, result: Any,
    ) -> None: ...
    def release(self, correlation_id: CorrelationId) -> None: ...


class MemoryIdempotencyGuard:
    """In-process correlation-id dedupe with reservation + release."""

    def __init__(self) -> None:
        self._reserved: set[str] = set()
        self._completed: dict[str, Any] = {}
        self._lock = threading.RLock()

    def check_and_reserve(
        self, correlation_id: CorrelationId,
    ) -> IdempotencyDuplicate | None:
        key = str(correlation_id.value)
        with self._lock:
            if key in self._completed:
                return IdempotencyDuplicate(result=self._completed[key])
            if key in self._reserved:
                raise RuntimeError(
                    f"idempotency key is already reserved: {key}",
                )
            self._reserved.add(key)
            return None

    def record_result(
        self, correlation_id: CorrelationId, result: Any,
    ) -> None:
        key = str(correlation_id.value)
        with self._lock:
            self._completed[key] = result
            self._reserved.discard(key)

    def release(self, correlation_id: CorrelationId) -> None:
        with self._lock:
            self._reserved.discard(str(correlation_id.value))


class RiskManager:
    """Simple risk manager with configurable limits."""

    def __init__(
        self,
        max_order_value: Decimal | None = None,
        max_position_value: Decimal | None = None,
        max_orders_per_minute: int | None = None,
        *,
        live_orders_enabled: bool = True,
        positions_provider: Any | None = None,
    ) -> None:
        self._max_order_value = max_order_value
        self._max_position_value = max_position_value
        self._max_orders_per_minute = max_orders_per_minute
        self._recent_orders: deque[datetime] = deque()
        self._lock = threading.Lock()
        self._live_orders_enabled = live_orders_enabled
        #: Callable returning current positions (e.g. an OMS cache) so
        #: ``max_position_value`` can be enforced against live exposure. When
        #: None (backtest boot, unit tests), the position check is skipped.
        self._positions_provider = positions_provider
        #: Count of orders denied by ``check()`` (any gate). Read by
        #: BacktestEngine to populate ``BacktestResult.num_rejected`` without
        #: re-implementing rejection bookkeeping in its own loop.
        self._rejected_count = 0

    def _position_exposure(self) -> Decimal:
        """Absolute notional of all open positions (qty * avg_price)."""
        total = Decimal("0")
        if self._positions_provider is None:
            return total
        positions = self._positions_provider()
        for pos in positions:
            qty = getattr(pos, "quantity", None)
            avg = getattr(pos, "avg_price", None)
            if qty is None or avg is None:
                continue
            total += abs(qty.value) * avg.value
        return total

    def _incoming_exposure(self, request: OrderRequest) -> Decimal:
        """Notional of the incoming order (price * quantity)."""
        price = request.price
        if price is None or price.value <= 0:
            return Decimal("0")
        return price.value * request.quantity.value

    @property
    def live_orders_enabled(self) -> bool:
        """Master gate: when False, all orders are rejected."""
        return self._live_orders_enabled

    @live_orders_enabled.setter
    def live_orders_enabled(self, value: bool) -> None:
        self._live_orders_enabled = value

    def set_positions_provider(self, provider: Any) -> None:
        """Bind the position source used for ``max_position_value``.

        ``provider`` is a zero-arg callable returning an iterable of
        positions (e.g. ``engine.cache.all_positions``). When unset the
        position check is skipped.
        """
        self._positions_provider = provider

    @property
    def positions_provider_bound(self) -> bool:
        """True when a positions provider is bound (max_position_value live)."""
        return self._positions_provider is not None

    def check(self, request: OrderRequest, now: datetime | None = None) -> bool:
        """Return True if the order passes risk checks, False to reject.

        Parameters
        ----------
        now : datetime | None
            Evaluation instant for the orders-per-minute window. Defaults to
            wall clock (``datetime.now(UTC)``). A caller replaying a
            deterministic event stream — e.g. BacktestEngine — should pass the
            event timestamp so the rate-limit decision reproduces across runs
            (parity review area #5: deterministic event processing).

        Notes
        -----
        All ``now`` values within one manager must share tz-awareness
        (naive or aware) — the window subtraction compares them directly.
        BacktestEngine resets the window at run start, so one manager is
        dedicated to one mode and never mixes IST tz-naive backtest
        timestamps with aware wall-clock live timestamps.
        """
        with self._lock:
            # Master gate
            if not self._live_orders_enabled:
                return self._deny()

            # Price-less orders cannot be notional-evaluated: when a value or
            # position cap is configured, a MARKET order without a (positive)
            # reference price would silently bypass both limits — fail closed.
            if (
                (request.price is None or request.price.value <= 0)
                and (
                    self._max_order_value is not None
                    or self._max_position_value is not None
                )
            ):
                return self._deny()

            # Order value check
            if self._max_order_value is not None and request.price is not None:
                order_value = request.price.value * request.quantity.value
                if order_value > self._max_order_value:
                    return self._deny()

            # Position value check (cumulative exposure + incoming order)
            if self._max_position_value is not None:
                exposure = self._position_exposure() + self._incoming_exposure(request)
                if exposure > self._max_position_value:
                    return self._deny()

            # Rate limit check
            if self._max_orders_per_minute is not None:
                now = now if now is not None else datetime.now(UTC)
                # Purge old entries
                while self._recent_orders and (
                    (now - self._recent_orders[0]).total_seconds() > _RATE_WINDOW_SECONDS
                ):
                    self._recent_orders.popleft()
                if len(self._recent_orders) >= self._max_orders_per_minute:
                    return self._deny()
                self._recent_orders.append(now)

            return True

    def _deny(self) -> bool:
        """Record a rejection and return ``False`` (caller returns it)."""
        self._rejected_count += 1
        return False

    @property
    def rejected_count(self) -> int:
        """Number of orders denied by :meth:`check` since construction."""
        return self._rejected_count

    def reset_rate_window(self) -> None:
        """Clear the orders-per-minute window and rejection counter.

        BacktestEngine calls this at the start of every run so a shared
        RiskManager never leaks rate-limit state between independent
        backtests — results stay a pure function of (data, config,
        strategy) (parity review area #8: reproducible). The reactive/live
        path never calls it, so the live rate limit is unaffected.
        """
        with self._lock:
            self._recent_orders.clear()
            self._rejected_count = 0

    def check_order(self, request: OrderRequest, context: Any = None) -> RiskCheckResult:
        """v3-parity risk check returning rich result."""
        approved = self.check(request)
        return RiskCheckResult(
            approved=approved,
            reason="" if approved else "risk_check_failed",
        )


class ExecutionEngine:
    """Single order spine as reactive pipeline.

    idempotency → risk → fill → OMS, all as Observable operators.
    This is the core of v4 — the reactive execution pipeline.
    """

    def __init__(
        self,
        bus: Any,  # ReactiveBus
        fill_source: FillSource,
        risk_manager: RiskManager | None = None,
        idempotency_guard: Any | None = None,
        cache: TradingCache | None = None,
        metrics: MetricsRegistry | None = None,
        fee_calculator: FeeCalculator | None = None,
    ) -> None:
        """
        fee_calculator:
            When provided, every applied fill's fees are deducted from the
            position's realized P&L — making reactive paper/live net P&L
            consistent with BacktestEngine's net cash accounting (HIGH-6b).
        """
        self._bus = bus
        self._fill = fill_source
        self._risk = risk_manager
        self._guard = idempotency_guard
        self._cache = cache or TradingCache()
        self._metrics = metrics
        self._fee_calculator = fee_calculator
        self._order_manager = OrderManager(self._cache)
        self._position_manager = PositionManager(self._cache)
        self._kill_switch = threading.Event()
        self._reconciler = ReconciliationEngine()
        self._latency_tracker = LatencyTracker(metrics=metrics)
        #: Fingerprints of OrderFilled events already applied to the OMS
        #: (order_id + side + qty + price) — re-published broker fills are
        #: skipped, distinct partial fills are each applied in full.
        #: LRU-bounded OrderedDict so old entries are evicted (not the whole set)
        #: when the capacity is exceeded — recent entries (most likely to be
        #: re-published) are preserved.
        self._applied_fills: OrderedDict[tuple, None] = OrderedDict()
        self._applied_fills_max = 50_000
        # Single-writer mutex (P4.16): every engine mutation — submit (via
        # _run_pipeline), cancel, inbound fill, kill-switch — is serialized
        # through this ONE RLock. The per-component locks below (risk, guard,
        # latency, cache) become uncontended on the engine path, and there is
        # a single ownership rule for the engine's mutable state.
        self._mutex = threading.RLock()
        self._setup_pipeline()

    def _process_command_with_timing(self, cmd: PlaceOrderCommand) -> None:
        """Process PlaceOrderCommand, recording submission start time for latency tracking."""
        submit_start = time.perf_counter()
        # Record timing only if correlation_id is available
        cid = cmd.request.correlation_id
        if cid is not None:
            try:
                self._latency_tracker.record_submit(cid, submit_start)
            except Exception:
                # Never let latency tracking break the order pipeline
                pass
        self._process_request(cmd.request)

    def _on_fill_latency(self, event: OrderFilled) -> None:
        """Compute fill latency and slipAge from fill event, emits via MetricsRegistry or log."""
        fill = event.fill
        cid = getattr(fill, "correlation_id", None)
        if cid is None:
            return
        fill_wall = time.perf_counter()
        try:
            self._latency_tracker.record_fill(cid, fill_wall, fill.price.value)
        except Exception:
            # Never let latency tracking break the fill pipeline
            pass

    def _setup_pipeline(self) -> None:
        """Wire the reactive order pipeline using RxPY operators.

        Subscribes to OrderRequest messages on the bus and processes them
        through the pipeline: idempotency → risk → fill → OMS update → publish.
        Also subscribes to PlaceOrderCommand for CQRS-style order submission.
        """
        from rx import operators as ops

        self._pipeline_disposable = self._bus.of_type(OrderRequest).pipe(
            ops.filter(lambda _: not self._kill_switch.is_set()),
        ).subscribe(
            on_next=self._process_request,
            # Unexpected pipeline failures surface as ErrorOccurred. Per-request
            # failures already emit well-formed OrderRejected events inside
            # _process_request, so we never fabricate an Order here.
            on_error=lambda e: self._bus.publish(ErrorOccurred(error=e)),
        )

        # CQRS command subscription — strategies publish PlaceOrderCommand
        # to the bus instead of calling broker adapters directly.
        # Track submission start time for latency measurement.
        self._command_disposable = self._bus.of_type(PlaceOrderCommand).subscribe(
            on_next=lambda cmd: self._process_command_with_timing(cmd),
            on_error=lambda e: self._bus.publish(ErrorOccurred(error=e)),
        )

        # Inbound live-fill bridge — broker order streams (or any publisher)
        # publish OrderFilled on the bus; the engine applies the fill to the
        # OMS idempotently. This is what makes live fills reach the position
        # manager (BrokerFillSource returns ACK-with-no-fill synchronously).
        self._fill_disposable = self._bus.of_type(OrderFilled).subscribe(
            on_next=self._apply_fill,
            on_error=lambda e: self._bus.publish(ErrorOccurred(error=e)),
        )

        # Latency tracker subscription for fill events (for fill latency + slippage)
        self._latency_fill_sub = self._bus.of_type(OrderFilled).subscribe(
            on_next=self._on_fill_latency,
            on_error=lambda e: None,  # never let latency tracking break the bus
        )

    def shutdown(self) -> None:
        """Gracefully shut down the execution engine."""
        log.info("ExecutionEngine shutting down...")
        self._kill_switch.set()
        if hasattr(self, "_pipeline_disposable") and self._pipeline_disposable is not None:
            try:
                self._pipeline_disposable.dispose()
            except Exception as exc:
                log.error("Error disposing pipeline: %s", exc)
        if hasattr(self, "_command_disposable") and self._command_disposable is not None:
            try:
                self._command_disposable.dispose()
            except Exception as exc:
                log.error("Error disposing command subscription: %s", exc)
        if hasattr(self, "_fill_disposable") and self._fill_disposable is not None:
            try:
                self._fill_disposable.dispose()
            except Exception as exc:
                log.error("Error disposing fill subscription: %s", exc)
        if hasattr(self, "_latency_fill_sub") and self._latency_fill_sub is not None:
            try:
                self._latency_fill_sub.dispose()
            except Exception:
                pass
        # Close an injected durable guard (e.g. SQLiteIdempotencyGuard) so its
        # connection is released on shutdown — not leaked for the process life.
        guard_close = getattr(self._guard, "close", None)
        if callable(guard_close):
            try:
                guard_close()
            except Exception as exc:  # pragma: no cover
                log.error("Error closing idempotency guard: %s", exc)
        log.info("ExecutionEngine shutdown complete")

    def __enter__(self) -> ExecutionEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def _process_request(self, request: OrderRequest) -> None:
        """Process a single order request through the pipeline."""
        t0 = time.perf_counter()
        try:
            self._process_request_impl(request)
        finally:
            if self._metrics is not None:
                self._metrics.histogram("orders.process_latency_seconds").observe(
                    time.perf_counter() - t0,
                )

    def _run_pipeline(
        self, request: OrderRequest, *, sync: bool
    ) -> OrderReceipt | None:
        """Serialized pipeline entry — acquires the single-writer mutex."""
        with self._mutex:
            return self._run_pipeline_locked(request, sync=sync)

    def _run_pipeline_locked(
        self, request: OrderRequest, *, sync: bool
    ) -> OrderReceipt | None:
        """Single idempotency→risk→fill→OMS sequence shared by the reactive
        and synchronous submit paths.

        ``sync`` controls the return shape: the reactive path returns ``None``
        (fire-and-forget on the bus); the synchronous path returns an
        ``OrderReceipt``. The kill-switch is checked **before** reserving the
        idempotency correlation id (residual review Task 3) so a trip between
        the two never leaks a permanently-reserved cid.
        """
        log.info(
            "Processing order request for %s (cid=%s, sync=%s)",
            request.instrument, request.correlation_id, sync,
        )

        # 0. Kill switch (cheap — must precede any reservation)
        if self._kill_switch.is_set():
            if sync:
                return OrderReceipt(
                    order_id=OrderId(value="rejected"),
                    status=OrderStatus.REJECTED,
                    message="kill_switch_active",
                )
            return None

        # 1. Idempotency check
        cid = request.correlation_id
        if self._guard is not None and cid is not None:
            dup = self._guard.check_and_reserve(cid)
            if dup is not None:
                # v3 parity: silently replay — original events were already published
                log.info("Idempotency replay for correlation %s", cid)
                if self._metrics is not None:
                    self._metrics.counter("orders.idempotency_replay").inc()
                return dup.result if sync else None

        # 2. Risk check
        if self._risk is not None and not self._risk.check(request):
            log.warning("Risk check failed for order")
            order = _make_order(request, OrderStatus.REJECTED)
            self._order_manager.on_order_created(order)
            self._bus.publish(OrderRejected(order=order, reason="risk_check_failed"))
            if self._metrics is not None:
                self._metrics.counter("orders.rejected").inc()
                self._metrics.counter("risk.rejected").inc()
            # Release the idempotency reservation: a risk rejection is a
            # terminal, deterministic outcome for this correlation id. Leaving
            # it reserved turned a retry into "idempotency key already reserved"
            # instead of a clean re-rejection (and leaked the key forever).
            if self._guard is not None and cid is not None:
                self._guard.release(cid)
            return (
                OrderReceipt(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    message="risk_check_failed",
                )
                if sync
                else None
            )

        # 3. Fill
        try:
            ack_wall = time.perf_counter()
            order, fill = self._fill.submit(request)
            # ACK received: record ACK time for latency tracking
            if cid is not None:
                try:
                    self._latency_tracker.record_ack(cid, ack_wall)
                except Exception:
                    pass
        except Exception as exc:
            boundary_crossed = getattr(
                self._fill, "submission_boundary_crossed", False,
            )
            if boundary_crossed:
                from tradex_domain.errors import OrderSubmissionUnknownError
                raise OrderSubmissionUnknownError(
                    f"Order submission failed after crossing broker boundary: {exc}"
                ) from exc
            if self._guard is not None and cid is not None:
                self._guard.release(cid)
            order = _make_order(request, OrderStatus.REJECTED)
            self._order_manager.on_order_created(order)
            self._bus.publish(OrderRejected(order=order, reason=str(exc)))
            if self._metrics is not None:
                self._metrics.counter("orders.rejected").inc()
            return (
                OrderReceipt(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    message=str(exc),
                )
                if sync
                else None
            )

        # 4. OMS update
        self._order_manager.on_order_created(order)
        self._bus.publish(OrderPlaced(order=order))

        if fill is not None:
            # Guard: skip position update if fill source owns projection
            # (PaperBroker projects positions itself). Idempotent against
            # _apply_fill: the order is FILLED before OrderFilled is published.
            if not getattr(self._fill, "position_projection_owned", False):
                self._position_manager.on_fill(fill)
                self._apply_fee(fill)
            self._order_manager.on_order_filled(order, fill)
            # Self-register: this pipeline-applied fill must not be re-applied
            # by the inbound-fill bridge when it sees our own OrderFilled event
            # (it would double the position for partial fills).
            self._mark_fill_applied(fill)
            self._bus.publish(OrderFilled(fill=fill))
            # Record idempotency result for replay
            if self._guard is not None and cid is not None:
                self._guard.record_result(cid, order.order_id)
            # Clean up latency tracker entry on terminal state
            if cid is not None:
                self._latency_tracker.cleanup(cid)
            log.info(
                "Order filled: %s qty=%s price=%s (cid=%s)",
                order.order_id, fill.quantity, fill.price, cid,
            )
            if self._metrics is not None:
                self._metrics.counter("orders.submitted").inc()
                self._metrics.counter("orders.filled").inc()
        else:
            if self._metrics is not None:
                self._metrics.counter("orders.submitted").inc()

        if not sync:
            return None
        return OrderReceipt(
            order_id=order.order_id,
            status=order.status,
            message="submitted",
        )

    def get_latency_tracker(self) -> LatencyTracker:
        """Expose latency tracker for tests/monitoring."""
        return self._latency_tracker

    def _process_request_impl(self, request: OrderRequest) -> None:
        """Reactive pipeline entry — fire-and-forget (returns nothing)."""
        self._run_pipeline(request, sync=False)

    def _apply_fee(self, fill: Fill) -> None:
        """Deduct *fill*'s fees from the position's realized P&L when fees are
        enabled. No-op when no fee calculator is bound or no position exists.
        Failures propagate loudly — a silently-swallowed fee bug is exactly
        the accounting divergence the parity work exists to prevent.
        """
        if self._fee_calculator is None:
            return
        fee = self._fee_calculator.calculate(fill)
        if fee.amount > 0:
            self._position_manager.on_fee(fill, fee)

    def _apply_fill(self, event: OrderFilled) -> None:
        """Serialized fill entry — acquires the single-writer mutex."""
        with self._mutex:
            self._apply_fill_locked(event)

    def _apply_fill_locked(self, event: OrderFilled) -> None:
        """Apply an inbound OrderFilled to the OMS (live-fill bridge).

        Each ``OrderFilled`` event is one fill occurrence (broker order
        stream → bus). A re-published occurrence is skipped via the
        applied-fill fingerprint set, so duplicates never double-apply while
        distinct partial fills each land in full. The synchronous pipeline
        path marks the order FILLED before publishing, so its own event is a
        no-op here.

        Dedup key: when the venue provides a ``fill.fill_id`` (exchange trade
        id), it uniquely identifies the occurrence — two genuine equal-lot
        partial fills with distinct fill ids are both applied. Without a
        fill id the fingerprint falls back to (order, side, quantity, price),
        so equal-lot partials without venue ids remain indistinguishable from
        a re-publish.
        """
        fill = event.fill
        key = self._fill_fingerprint(fill)
        # The caller holds the single-writer mutex, so this dedup set is only
        # ever touched from one thread at a time (no separate lock needed).
        if key in self._applied_fills:
            self._applied_fills.move_to_end(key)
            return
        self._applied_fills[key] = None
        if len(self._applied_fills) > self._applied_fills_max:
            self._applied_fills.popitem(last=False)

        existing = self._cache.get_order(fill.order_id)
        if existing is not None and existing.status in (
            OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FILLED,
        ):
            # FILLED already = the synchronous pipeline path applied this fill
            # before publishing its own OrderFilled event — never double-apply.
            return
        if not getattr(self._fill, "position_projection_owned", False):
            self._position_manager.on_fill(fill)
            self._apply_fee(fill)
        if existing is not None:
            self._order_manager.on_order_filled(existing, fill)
        else:
            # Unknown order — record a minimal FILLED order so reconciliation
            # sees the fill (e.g. fills for orders placed outside this engine).
            self._cache.update_order(
                Order(
                    order_id=fill.order_id,
                    instrument=fill.instrument,
                    side=fill.side,
                    order_type=OrderType.MARKET,
                    quantity=fill.quantity,
                    price=fill.price,
                    time_in_force=TimeInForce.DAY,
                    status=OrderStatus.FILLED,
                    filled_quantity=fill.quantity,
                    correlation_id=getattr(fill, "correlation_id", None),
                    tag=getattr(fill, "tag", None),
                )
            )
        log.info(
            "Inbound fill applied: %s qty=%s price=%s (engine fill bridge)",
            fill.order_id, fill.quantity, fill.price,
        )

    @staticmethod
    def _fill_fingerprint(fill: Fill) -> tuple:
        """Dedup key for one fill occurrence (bridge fingerprint).

        When the venue provides a ``fill.fill_id`` (exchange trade id) it
        uniquely identifies the occurrence; otherwise the fingerprint falls
        back to (order, side, quantity, price). Shared by the inbound-fill
        bridge and the sync pipeline's self-registration so both compute the
        exact same key for the same fill.
        """
        if fill.fill_id is not None:
            return (fill.fill_id,)
        return (
            fill.order_id.value, fill.side.value, str(fill.quantity.value),
            str(fill.price.value),
        )

    def _mark_fill_applied(self, fill: Fill) -> None:
        """Register a fill as already applied (caller holds the engine mutex).

        The sync pipeline applies a fill and then publishes ``OrderFilled``;
        the inbound-fill bridge subscribes to that event and would otherwise
        re-apply the fill — a double position. Registering the fingerprint
        here makes the bridge's dedup treat the event as a no-op, exactly
        like a re-published broker fill. Keeps partial fills (a sync source
        may return ``PARTIALLY_FILLED``) from double-applying too.
        """
        key = self._fill_fingerprint(fill)
        self._applied_fills[key] = None
        if len(self._applied_fills) > self._applied_fills_max:
            self._applied_fills.popitem(last=False)

    def submit(self, request: OrderRequest) -> OrderReceipt:
        """Synchronous submit — bridges to reactive pipeline.

        Creates the order, runs the fill source, updates OMS, and
        publishes events. Returns an OrderReceipt immediately.
        """
        submit_start = time.perf_counter()
        try:
            return self._submit_impl(request)
        finally:
            if self._metrics is not None:
                self._metrics.histogram("orders.submit_latency_seconds").observe(
                    time.perf_counter() - submit_start,
                )
            # Record submission start for latency tracking (for ACK + fill latency)
            if request.correlation_id is not None:
                # Note: the submit() path goes through _run_pipeline which
                # records ACK time. But we also record submit start here so
                # that the latency tracker has the entry before _run_pipeline
                # runs (for the case where submit() is called directly, not
                # via PlaceOrderCommand).
                self._latency_tracker.record_submit(
                    request.correlation_id,
                    submit_start,
                )

    def _submit_impl(self, request: OrderRequest) -> OrderReceipt:
        """Synchronous submit logic — delegates to the shared pipeline."""
        receipt = self._run_pipeline(request, sync=True)
        if receipt is None:
            raise RuntimeError("sync submit produced no receipt")  # pragma: no cover
        return receipt

    def trip_kill_switch(self, reason: str = "") -> list[str]:
        """Serialized kill switch — acquires the single-writer mutex."""
        with self._mutex:
            return self._trip_kill_switch_locked(reason)

    def _trip_kill_switch_locked(self, reason: str = "") -> list[str]:
        """Halt new submissions and cancel every open order (mutex held)."""
        log.critical("Kill switch tripped: %s", reason)
        if self._metrics is not None:
            self._metrics.counter("kill_switch.tripped").inc()
        self._kill_switch.set()
        # Propagate to risk manager master gate
        if self._risk is not None:
            self._risk.live_orders_enabled = False
        failures: list[str] = []
        for order in self._cache.all_orders():
            if order.status not in _TERMINAL_STATUSES:
                try:
                    self.cancel(order.order_id)
                    # Also cancel at broker via fill source
                    if hasattr(self._fill, "cancel"):
                        self._fill.cancel(order.order_id)
                except Exception as exc:
                    log.error("kill-switch cancel failed for %s: %s", order.order_id, exc)
                    failures.append(order.order_id.value)
        return failures

    def reconcile(
        self,
        *,
        broker_orders: list[Order] | None = None,
        broker_positions: list[Position] | None = None,
        local_positions: list[Position] | None = None,
    ) -> list[DriftItem]:
        """Compare local state vs broker snapshots. Side-effect free."""
        drifts: list[DriftItem] = []
        if broker_positions is not None:
            local = local_positions
            if local is None:
                local = self._cache.all_positions()
            drifts.extend(
                self._reconciler.reconcile(local, broker_positions),
            )
        if broker_orders is not None:
            drifts.extend(
                self._reconciler.compare_orders(
                    self._cache.all_orders(), broker_orders,
                ),
            )
        return drifts

    def cancel(self, order_id: OrderId) -> Order:
        """Serialized cancel — acquires the single-writer mutex."""
        with self._mutex:
            return self._cancel_locked(order_id)

    def _cancel_locked(self, order_id: OrderId) -> Order:
        """Cancel an order (caller holds the engine mutex)."""
        log.info("Cancelling order %s", order_id)
        order = self._cache.get_order(order_id)
        if order is None:
            raise OrderRejectedError(f"Order {order_id.value} not found")
        cancelled = order.transition_to(OrderStatus.CANCELLED)
        self._cache.update_order(cancelled)
        return cancelled

    @property
    def kill_switch(self) -> bool:
        """Whether the kill switch is active."""
        return self._kill_switch.is_set()

    @kill_switch.setter
    def kill_switch(self, value: bool) -> None:
        """Activate or deactivate the kill switch."""
        if value:
            self._kill_switch.set()
        else:
            self._kill_switch.clear()

    def get_order(self, order_id: OrderId) -> Order | None:
        """Look up an order by ID."""
        return self._cache.get_order(order_id)

    def all_orders(self) -> list[Order]:
        """Return all cached orders."""
        return self._cache.all_orders()

    @property
    def cache(self) -> TradingCache:
        """Access the trading cache."""
        return self._cache


__all__ = [
    "ExecutionEngine",
    "IdempotencyDuplicate",
    "IdempotencyGuard",
    "InMemoryOrderStore",
    "MemoryIdempotencyGuard",
    "OrderStore",
    "RiskCheckResult",
    "RiskManager",
]
