"""Execution pipeline stage."""

from __future__ import annotations

import asyncio
import logging

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import PositionEvent, OrderRequest, OrderStatusEvent
from app.infrastructure.adapters.infrastructure_adapters import IBroker

logger = logging.getLogger(__name__)


class ExecutionPipeline:
    """Submit orders to broker adapters and emit execution events."""

    def __init__(self, broker: IBroker | None = None):
        self._broker = broker
        self._metrics = StageMetrics(stage_name="ExecutionPipeline")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, position_event: PositionEvent) -> list[OrderStatusEvent]:
        if position_event.event_type != "OPENED":
            return []
        request = OrderRequest(
            symbol=position_event.symbol,
            side="BUY" if position_event.side in ("BUY", "LONG") else "SELL",
            quantity=position_event.size,
            order_type="MARKET",
            price=position_event.entry_price,
            correlation_id=position_event.position_id,
        )
        if self._broker is None:
            self._metrics.record(0)
            return [self._to_status(position_event, "FILLED", filled_quantity=position_event.size, filled_price=position_event.entry_price)]
        try:
            self._run_broker_order(
                request.symbol,
                request.side,
                request.quantity,
                request.price,
            )
            self._metrics.record(0)
            return [self._to_status(position_event, "FILLED", filled_quantity=request.quantity, filled_price=request.price)]
        except Exception:
            self._metrics.record_error()
            logger.exception("Order execution failed")
            return [self._to_status(position_event, "REJECTED")]

    def _run_broker_order(self, symbol: str, side: str, quantity: float, price: float) -> object:
        order_coro = self._broker.place_order(symbol, side, quantity, price)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # Deterministic fallback in async runtimes: execute in a temporary loop.
                temp_loop = asyncio.new_event_loop()
                try:
                    return temp_loop.run_until_complete(order_coro)
                finally:
                    temp_loop.close()
        except RuntimeError:
            pass
        return asyncio.run(order_coro)

    def _to_status(
        self,
        position_event: PositionEvent,
        status: str,
        filled_quantity: float = 0.0,
        filled_price: float = 0.0,
    ) -> OrderStatusEvent:
        return OrderStatusEvent(
            order_id=position_event.position_id,
            symbol=position_event.symbol,
            status=status,
            filled_quantity=filled_quantity,
            filled_price=filled_price,
            remaining_quantity=max(0.0, position_event.size - filled_quantity),
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
