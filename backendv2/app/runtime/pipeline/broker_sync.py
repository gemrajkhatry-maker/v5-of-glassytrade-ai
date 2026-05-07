"""Broker reconciliation and synchronization stage."""

from __future__ import annotations

import logging
from dataclasses import asdict
from app.runtime.contracts import OrderLifecycleStatus
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import FillEvent, OrderStatusEvent

logger = logging.getLogger(__name__)


class BrokerSynchronization:
    """Reconcile broker acknowledgements and emit fills."""

    def __init__(self):
        self._metrics = StageMetrics(stage_name="BrokerSynchronization")
        self._open_orders: dict[str, OrderStatusEvent] = {}
        self._seen_fill_keys: set[tuple[str, float, float, str]] = set()

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, order_status: OrderStatusEvent) -> list[FillEvent]:
        try:
            status = str(order_status.status).upper()
            if status in {
                OrderLifecycleStatus.CANCELLED.value,
                OrderLifecycleStatus.REJECTED.value,
                OrderLifecycleStatus.EXPIRED.value,
            }:
                self._open_orders.pop(order_status.order_id, None)
                self._metrics.record(0)
                return []

            self._open_orders[order_status.order_id] = order_status
            if status in {OrderLifecycleStatus.FILLED.value, OrderLifecycleStatus.PARTIAL.value}:
                if order_status.filled_quantity <= 0 or order_status.filled_price <= 0:
                    logger.warning(
                        "Ignoring fill status without executable quantity/price: order_id=%s status=%s",
                        order_status.order_id,
                        status,
                    )
                    self._metrics.record_error()
                    return []
                fill_key = (
                    order_status.order_id,
                    float(order_status.filled_quantity),
                    float(order_status.filled_price),
                    status,
                )
                if fill_key in self._seen_fill_keys:
                    self._metrics.record(0)
                    return []
                self._seen_fill_keys.add(fill_key)
                if status == OrderLifecycleStatus.FILLED.value:
                    self._open_orders.pop(order_status.order_id, None)
                fill = FillEvent(
                    order_id=order_status.order_id,
                    symbol=order_status.symbol,
                    side="",
                    quantity=order_status.filled_quantity,
                    price=order_status.filled_price,
                    timestamp=order_status.timestamp,
                )
                self._metrics.record(0)
                return [fill]
            self._metrics.record(0)
            return []
        except Exception:
            self._metrics.record_error()
            logger.exception("Broker sync failed")
            return []

    def warmup(self) -> None:
        self._open_orders = {}
        self._seen_fill_keys = set()
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        return {
            "open_orders": [asdict(order) for order in self._open_orders.values()],
            "seen_fills": [list(item) for item in sorted(self._seen_fill_keys)],
        }

    def restore(self, payload: dict[str, list[dict[str, object]]]) -> None:
        self._open_orders = {}
        if not isinstance(payload, dict):
            return
        open_orders = payload.get("open_orders")
        if isinstance(open_orders, list):
            for item in open_orders:
                if not isinstance(item, dict):
                    continue
                from app.runtime.pipeline.events import OrderStatusEvent
                try:
                    event = OrderStatusEvent(**item)
                    self._open_orders[event.order_id] = event
                except (TypeError, ValueError):
                    continue
        seen_fills = payload.get("seen_fills")
        if isinstance(seen_fills, list):
            for item in seen_fills:
                if not isinstance(item, list) or len(item) != 4:
                    continue
                try:
                    self._seen_fill_keys.add((str(item[0]), float(item[1]), float(item[2]), str(item[3])))
                except (TypeError, ValueError):
                    continue
