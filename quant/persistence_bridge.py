"""Project PositionOpened/Closed onto IStorage so restart can restore the book."""

from __future__ import annotations

from quant.events import PositionClosed, PositionOpened, PositionReduced, StopMoved
from quant.execution.order import position_to_row


def _costs_dict(costs):
    if costs is None:
        return None
    return {
        "slippage": costs.slippage,
        "stt": costs.stt,
        "exchange_fee": costs.exchange_fee,
        "brokerage": costs.brokerage,
        "gst": costs.gst,
        "sebi_charges": costs.sebi_charges,
        "total": costs.total,
    }


class PositionStorageBridge:
    def __init__(self, storage, contract=None) -> None:
        self._storage = storage
        self._contract = contract
        self._open_rows: dict[str, dict] = {}  # position_id -> last saved row

    def _identity(self) -> dict:
        """Return durable broker-neutral identity without changing old schemas."""
        if self._contract is None:
            return {}
        return {
            "contract_exchange": self._contract.exchange,
            "contract_expiry": self._contract.expiry,
            "contract_lot_size": self._contract.lot_size,
            "contract_tick_size": self._contract.tick_size,
            "contract_strike": self._contract.strike,
            "contract_option_type": self._contract.option_type,
            "contract_multiplier": self._contract.multiplier,
        }

    def attach(self, bus) -> None:
        bus.subscribe(PositionOpened, self.on_opened, priority=-50)
        bus.subscribe(PositionReduced, self.on_reduced, priority=-50)
        bus.subscribe(PositionClosed, self.on_closed, priority=-50)
        bus.subscribe(StopMoved, self.on_stop_moved, priority=-50)

    def _save_fill(self, *, fill_id: str, position_id: str, symbol: str,
                   side: str, quantity: float, fill_price: float,
                   pnl: float, event_time: str, fill=None, costs=None) -> None:
        """Write a fill when the adapter supports the ledger; old test doubles
        remain valid while production storage gets an idempotent record."""
        if not hasattr(self._storage, "save_fill"):
            return
        costs = costs if costs is not None else (
            _costs_dict(getattr(fill, "costs", None)) if fill is not None else None
        )
        payload = {
            "fill_id": fill_id,
            "order_id": getattr(fill, "logical_id", "") if fill is not None else f"entry:{position_id}",
            "position_id": position_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "fill_price": fill_price,
            "pnl": pnl,
            "event_time": event_time,
            "costs": costs,
            "net_pnl": pnl,
        }
        payload.update(self._identity())
        self._storage.save_fill(payload)

    def on_opened(self, event: PositionOpened) -> None:
        position = event.position
        row = {
            **position_to_row(event.symbol, position),
            **self._identity(),
        }
        self._open_rows[position.id] = row
        self._storage.save_open_position(row)
        self._save_fill(
            fill_id=f"entry:{position.id}",
            position_id=position.id,
            symbol=event.symbol,
            side="BUY" if position.size > 0 else "SELL",
            quantity=abs(position.size),
            fill_price=position.open_price,
            pnl=0.0,
            event_time=event.time,
            costs=_costs_dict(getattr(position, "entry_costs", None)),
        )

    def on_closed(self, event: PositionClosed) -> None:
        pos = event.fill.position
        self._open_rows.pop(pos.id, None)
        self._save_fill(
            fill_id=(getattr(event.fill, "logical_id", "") or f"close:{pos.id}:{event.fill.close_time}:{event.fill.reason}"),
            position_id=pos.id,
            symbol=event.symbol,
            side="SELL" if pos.size > 0 else "BUY",
            quantity=abs(pos.size),
            fill_price=event.fill.close_price,
            pnl=event.fill.pnl,
            event_time=event.fill.close_time,
            fill=event.fill,
        )
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
            "entry_costs": _costs_dict(getattr(pos, "entry_costs", None)),
            "exit_costs": _costs_dict(getattr(event.fill, "costs", None)),
            "net_pnl": event.fill.pnl,
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
        prior = self._open_rows.get(event.remaining.id, {})
        row = {
            **prior,
            **position_to_row(event.symbol, event.remaining, stop_meta={
                "breakeven": prior.get("breakeven"),
                "trail_stop": prior.get("trail_stop"),
                "tp_tier": prior.get("tp_tier"),
                "entry_time_epoch": prior.get("entry_time_epoch"),
                "stop_loss": prior.get("stop_loss"),
            }),
            **self._identity(),
        }
        self._open_rows[event.remaining.id] = row
        self._storage.save_open_position(row)
        partial = event.fill
        pos = partial.position
        self._save_fill(
            fill_id=(getattr(partial, "logical_id", "") or f"partial:{pos.id}:{partial.close_time}:{partial.reason}"),
            position_id=pos.id,
            symbol=event.symbol,
            side="SELL" if pos.size > 0 else "BUY",
            quantity=abs(pos.size),
            fill_price=partial.close_price,
            pnl=partial.pnl,
            event_time=partial.close_time,
            fill=partial,
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

    def on_stop_moved(self, event: StopMoved) -> None:
        """Persist ratcheted stop / BE onto the durable open-position row."""
        pid = str(event.position_id or "")
        if not pid:
            return
        row = dict(self._open_rows.get(pid) or {})
        if not row:
            # Best-effort: load from storage if we missed the open event.
            try:
                rows = self._storage.load_open_positions() or []
            except Exception:
                rows = []
            for r in rows:
                if str(r.get("id") or "") == pid:
                    row = dict(r)
                    break
        if not row:
            return
        row["stop_loss"] = float(event.new_sl)
        if event.stop_kind == "BREAKEVEN" or event.reason == "BREAKEVEN_ARMED":
            row["breakeven"] = float(event.new_sl)
        if event.stop_kind == "TRAIL" or event.reason == "TRAIL_RATCHET":
            row["trail_stop"] = float(event.new_sl)
        # Persist TP tier when carried on the event (restart rehydrate).
        tier = getattr(event, "tp_tier", None)
        if tier is not None:
            row["tp_tier"] = int(tier)
        row.update(self._identity())
        self._open_rows[pid] = row
        self._storage.save_open_position(row)