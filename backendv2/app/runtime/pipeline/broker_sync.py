"""Broker reconciliation and synchronization stage."""

from __future__ import annotations

import logging
from dataclasses import asdict
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import FillEvent, OrderStatusEvent

logger = logging.getLogger(__name__)


class BrokerSynchronization:
    """Reconcile broker acknowledgements and emit fills."""

    def __init__(self):
        self._metrics = StageMetrics(stage_name="BrokerSynchronization")
        self._open_orders: dict[str, OrderStatusEvent] = {}

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, order_status: OrderStatusEvent) -> list[FillEvent]:
        try:
            self._open_orders[order_status.order_id] = order_status
            if order_status.status == "FILLED":
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
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, list[dict[str, object]]]:
        return {
            "open_orders": [asdict(order) for order in self._open_orders.values()],
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
