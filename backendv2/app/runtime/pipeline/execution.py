"""Execution pipeline stage."""

from __future__ import annotations

import asyncio
import inspect
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.runtime.contracts import OrderLifecycleStatus
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import PositionEvent, OrderRequest, OrderStatusEvent

logger = logging.getLogger(__name__)


class ExecutionPipeline:
    """Submit orders to broker adapters and emit execution events."""

    def __init__(self, broker: Any | None = None):
        self._broker = broker
        self._metrics = StageMetrics(stage_name="ExecutionPipeline")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def bind(self, broker: Any) -> None:
        """Bind the lifecycle-owned execution adapter."""
        self._broker = broker

    def process(self, position_event: PositionEvent) -> list[OrderStatusEvent]:
        if position_event.event_type != "OPENED":
            return []
        request = OrderRequest(
            symbol=position_event.symbol,
            side="BUY" if position_event.side in ("BUY", "LONG") else "SELL",
            quantity=position_event.size,
            order_type="MARKET",
            price=position_event.entry_price,
            position_id=position_event.position_id,
            correlation_id=position_event.position_id,
        )
        if self._broker is None:
            self._metrics.record_error()
            return [
                self._to_status(
                    position_event,
                    OrderLifecycleStatus.REJECTED.value,
                    reject_reason="Execution broker not bound",
                )
            ]
        try:
            order_events = self._submit_order(request, position_event)
            self._metrics.record(0)
            return order_events
        except Exception as exc:
            self._metrics.record_error()
            logger.exception("Order execution failed")
            return [
                self._to_status(
                    position_event,
                    OrderLifecycleStatus.REJECTED.value,
                    reject_reason=str(exc) or "Order execution failed",
                )
            ]

    def _submit_order(
        self,
        request: OrderRequest,
        position_event: PositionEvent,
    ) -> list[OrderStatusEvent]:
        broker = self._broker
        if hasattr(broker, "submit_order"):
            raw = self._run_maybe_awaitable(broker.submit_order(request))
        elif hasattr(broker, "place_order"):
            raw = self._run_maybe_awaitable(
                broker.place_order(request.symbol, request.side, request.quantity, request.price)
            )
        else:
            return [
                self._to_status(
                    position_event,
                    OrderLifecycleStatus.REJECTED.value,
                    reject_reason="Execution adapter does not implement submit_order/place_order",
                )
            ]

        events = self._coerce_status_events(raw, request, position_event)
        if not events:
            return [
                self._to_status(
                    position_event,
                    OrderLifecycleStatus.REJECTED.value,
                    reject_reason="Execution adapter returned no order status",
                )
            ]
        return events

    def _run_maybe_awaitable(self, result: object) -> object:
        if not inspect.isawaitable(result):
            return result
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(result)
        if not loop.is_running():
            return loop.run_until_complete(result)
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(result)).result()

    def _coerce_status_events(
        self,
        raw: object,
        request: OrderRequest,
        position_event: PositionEvent,
    ) -> list[OrderStatusEvent]:
        if raw is None:
            return []
        if isinstance(raw, OrderStatusEvent):
            return [raw]
        if isinstance(raw, list):
            events: list[OrderStatusEvent] = []
            for item in raw:
                events.extend(self._coerce_status_events(item, request, position_event))
            return events
        if isinstance(raw, dict):
            status = str(raw.get("status", OrderLifecycleStatus.PENDING.value)).upper()
            if status == "DUMMY":
                return [
                    self._to_status(
                        position_event,
                        OrderLifecycleStatus.REJECTED.value,
                        reject_reason="Broker returned dummy status",
                    )
                ]
            if status not in {item.value for item in OrderLifecycleStatus}:
                status = OrderLifecycleStatus.UNKNOWN.value
            order_id = str(raw.get("order_id") or raw.get("orderId") or position_event.position_id)
            filled_quantity = 0.0
            filled_price = 0.0
            if status in {OrderLifecycleStatus.FILLED.value, OrderLifecycleStatus.PARTIAL.value}:
                filled_quantity = float(raw.get("filled_quantity", raw.get("qty", request.quantity)) or 0.0)
                filled_price = float(raw.get("filled_price", raw.get("price", request.price)) or 0.0)
            remaining = max(0.0, request.quantity - filled_quantity)
            return [
                OrderStatusEvent(
                    order_id=order_id,
                    symbol=request.symbol,
                    status=status,
                    filled_quantity=filled_quantity,
                    filled_price=filled_price,
                    remaining_quantity=remaining,
                    reject_reason=str(raw.get("reject_reason", raw.get("reason", "")) or ""),
                    timestamp=position_event.timestamp,
                )
            ]
        return [
            self._to_status(
                position_event,
                OrderLifecycleStatus.UNKNOWN.value,
                reject_reason=f"Unsupported execution response type: {type(raw).__name__}",
            )
        ]

    def _to_status(
        self,
        position_event: PositionEvent,
        status: str,
        filled_quantity: float = 0.0,
        filled_price: float = 0.0,
        reject_reason: str = "",
    ) -> OrderStatusEvent:
        return OrderStatusEvent(
            order_id=position_event.position_id,
            symbol=position_event.symbol,
            status=status,
            filled_quantity=filled_quantity,
            filled_price=filled_price,
            remaining_quantity=max(0.0, position_event.size - filled_quantity),
            reject_reason=reject_reason,
            timestamp=position_event.timestamp,
        )

    def warmup(self) -> None:
        self._metrics.reset()

    def teardown(self) -> None:
        self._metrics.reset()

    def reset(self) -> None:
        self._metrics.reset()

    def snapshot(self) -> dict[str, object]:
        return {"broker_bound": self._broker is not None}

    def restore(self, payload: dict[str, object]) -> None:
        self._metrics.reset()
        # Broker adapters are lifecycle-owned by orchestrator composition and are
        # intentionally not restored from snapshot payloads.
        _ = payload  # keep signature consistent for checkpoint restoration.
