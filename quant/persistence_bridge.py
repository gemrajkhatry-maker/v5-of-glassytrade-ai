"""Project PositionOpened/Closed onto IStorage so restart can restore the book."""

from __future__ import annotations

from quant.events import PositionClosed, PositionOpened, PositionReduced
from quant.execution.order import position_to_row


class PositionStorageBridge:
    def __init__(self, storage) -> None:
        self._storage = storage

    def attach(self, bus) -> None:
        bus.subscribe(PositionOpened, self.on_opened, priority=-50)
        bus.subscribe(PositionReduced, self.on_reduced, priority=-50)
        bus.subscribe(PositionClosed, self.on_closed, priority=-50)

    def on_opened(self, event: PositionOpened) -> None:
        self._storage.save_open_position(position_to_row(event.symbol, event.position))

    def on_closed(self, event: PositionClosed) -> None:
        pos = event.fill.position
        self._storage.delete_open_position(pos._id)
        sig = pos.order.signal
        self._storage.save_trade({
            "position_id": pos._id,
            "symbol": event.symbol,
            "side": "LONG" if pos.size > 0 else "SHORT",
            "entry_price": pos.open_price,
            "exit_price": event.fill.close_price,
            "size": pos.size,
            "pnl": event.fill.pnl,
            "source": sig.model_label,
            "reason": event.fill.reason,
            "opened_at": pos.open_time,
            "closed_at": event.fill.close_time,
        })
        if hasattr(self._storage, "save_position_event"):
            self._storage.save_position_event({
                "event_type": "POSITION_CLOSED",
                "symbol": event.symbol,
                "position_id": pos._id,
                "reason": event.fill.reason,
            })

    def on_reduced(self, event: PositionReduced) -> None:
        """Persist both the partial fill and the still-open residual."""
        self._storage.save_open_position(
            position_to_row(event.symbol, event.remaining)
        )
        if hasattr(self._storage, "save_position_event"):
            self._storage.save_position_event({
                "event_type": "POSITION_REDUCED",
                "symbol": event.symbol,
                "position_id": event.remaining._id,
                "quantity": event.fill.position.size,
                "price": event.fill.close_price,
                "pnl": event.fill.pnl,
                "reason": event.fill.reason,
            })
