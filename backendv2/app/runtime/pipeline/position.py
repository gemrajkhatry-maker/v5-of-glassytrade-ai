"""Position lifecycle stage."""

from __future__ import annotations

import logging
from typing import Union
from decimal import Decimal

from app.domain.trading.model.enums import SignalType, Source, SetupType, PositionStatus, Side
from app.domain.trading.model.entities import Signal as DomainSignal
from app.domain.trading.model.entities import Position
from app.domain.trading.model.aggregates import Portfolio
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import Signal, RiskResult, PositionEvent, OrderStatusEvent, FillEvent
from app.runtime.pipeline.events import ExitDecision as PipelineExitDecision

logger = logging.getLogger(__name__)


class PositionLifecycle:
    """Orchestrates portfolio mutations and position lifecycle outputs."""

    def __init__(self):
        self._portfolio: dict[str, Portfolio] = {}
        self._metrics = StageMetrics(stage_name="PositionLifecycle")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def _portfolio_for(self, symbol: str) -> Portfolio:
        if symbol not in self._portfolio:
            self._portfolio[symbol] = Portfolio.create_default()
        return self._portfolio[symbol]

    def process(
        self,
        items: Union[Signal, RiskResult, PositionEvent, FillEvent, PipelineExitDecision, OrderStatusEvent],
    ) -> list[PositionEvent]:
        if isinstance(items, Signal):
            return self._handle_signal(items)
        if isinstance(items, RiskResult):
            return []
        if isinstance(items, PipelineExitDecision):
            return self._handle_exit_decision(items)
        if isinstance(items, FillEvent):
            return self._handle_fill(items)
        if isinstance(items, OrderStatusEvent):
            return self._handle_order_status(items)
        if isinstance(items, PositionEvent):
            return []
        return []

    def _handle_signal(self, signal: Signal) -> list[PositionEvent]:
        try:
            if signal.type == "NO_TRADE":
                return []
            portfolio = self._portfolio_for(signal.symbol)
            domain_signal = _to_domain_signal(signal)
            opened = portfolio.open_position(domain_signal, signal.symbol)
            if opened is None:
                return []
            event = PositionEvent(
                symbol=signal.symbol,
                timestamp=signal.timestamp,
                event_type="OPENED",
                position_id=opened.id,
                entry_price=float(opened.entry_price),
                size=float(opened.size),
                side=opened.side.name if hasattr(opened, "side") else signal.type,
                stop_loss=float(opened.stop_loss),
                take_profit=float(opened.take_profit),
                pnl=0.0,
            )
            self._metrics.record(0)
            return [event]
        except Exception:
            self._metrics.record_error()
            logger.exception("Failed to open position")
            return []

    def _handle_fill(self, fill: FillEvent) -> list[PositionEvent]:
        if not fill.order_id:
            self._metrics.record(0)
            return []

        portfolio = self._portfolio_for(fill.symbol)
        symbol = fill.symbol
        order_id = fill.order_id
        if not symbol or not order_id:
            self._metrics.record(0)
            return []

        closed = None
        # Prefer explicit full-order closure by id to stay aligned with live broker semantics.
        if any(position.id == order_id and position.is_open for position in portfolio.positions):
            target = next((p for p in portfolio.positions if p.id == order_id and p.is_open), None)
            if target is not None and fill.quantity >= float(target.size):
                closed = portfolio.close_position(order_id, fill.price, reason="FILLED")
            elif target is not None:
                closed_size = 0.0
                try:
                    closed_size = max(0.0, fill.quantity / float(target.size))
                except (TypeError, ValueError, ZeroDivisionError):
                    closed_size = 0.0
                if closed_size > 0:
                    realized = portfolio.partial_close_position(order_id, closed_size, fill.price, reason="PARTIAL_FILLED")
                    if realized is not None:
                        # Snapshot a partial-close event with the remaining position state.
                        return [PositionEvent(
                            symbol=symbol,
                            timestamp=fill.timestamp,
                            event_type="UPDATED",
                            position_id=order_id,
                            pnl=float(realized),
                            partial_taken=False,
                            runner_active=False,
                        )]
        if closed is None:
            self._metrics.record(0)
            return []

        exit_timestamp = float(fill.timestamp) if hasattr(fill, "timestamp") else 0.0
        if closed.exit_time not in (None, ""):
            try:
                exit_timestamp = float(closed.exit_time)
            except (TypeError, ValueError):
                pass
        self._metrics.record(0)
        return [PositionEvent(
            symbol=symbol,
            timestamp=exit_timestamp,
            event_type="CLOSED",
            position_id=closed.id,
            entry_price=float(closed.entry_price),
            size=float(closed.size),
            side=closed.side.name,
            stop_loss=float(closed.stop_loss),
            take_profit=float(closed.take_profit),
            pnl=float(closed.pnl),
            exit_reason=closed.close_reason or "",
        )]

    def _handle_order_status(self, order_status: OrderStatusEvent) -> list[PositionEvent]:
        if order_status.order_id in ("", None) or order_status.symbol in ("", None):
            self._metrics.record(0)
            return []
        if order_status.status not in ("REJECTED", "CANCELLED"):
            self._metrics.record(0)
            return []

        portfolio = self._portfolio_for(order_status.symbol)
        for index, position in enumerate(list(portfolio.positions)):
            if position.id == order_status.order_id and position.status == PositionStatus.OPEN:
                portfolio.positions.pop(index)
                position.status = PositionStatus.CLOSED
                position.close_reason = order_status.status
                if position.exit_price is None:
                    position.exit_price = None
                if position.exit_time is None:
                    position.exit_time = None
                self._metrics.record(0)
                return [
                    PositionEvent(
                        symbol=order_status.symbol,
                        timestamp=order_status.timestamp,
                        event_type="CLOSED",
                        position_id=position.id,
                        entry_price=float(position.entry_price),
                        size=float(position.size),
                        side=position.side.name,
                        stop_loss=float(position.stop_loss),
                        take_profit=float(position.take_profit),
                        pnl=float(position.pnl),
                        exit_reason=order_status.status,
                        partial_taken=position.partial_taken,
                        runner_active=position.runner_active,
                    )
                ]
        self._metrics.record(0)
        return []

    def _handle_exit_decision(self, decision: PipelineExitDecision) -> list[PositionEvent]:
        self._metrics.record(0)
        return []

    def process_exit_signal(self, symbol: str, position_id: str, pct: float, price: float, reason: str) -> list[PositionEvent]:
        portfolio = self._portfolio_for(symbol)
        position = None
        for pos in list(portfolio.positions):
            if pos.id == position_id and pos.status == PositionStatus.OPEN:
                position = pos
                break
        if position is None:
            return []
        if pct >= 1.0:
            closed = portfolio.close_position(position_id, price, reason=reason)
            if closed is None:
                return []
            exit_timestamp = 0.0
            if closed.exit_time not in (None, ""):
                try:
                    exit_timestamp = float(closed.exit_time)
                except (TypeError, ValueError):
                    exit_timestamp = 0.0
            return [PositionEvent(
                symbol=symbol,
                timestamp=exit_timestamp,
                event_type="CLOSED",
                position_id=closed.id,
                entry_price=float(closed.entry_price),
                size=float(closed.size),
                side=closed.side.name,
                stop_loss=float(closed.stop_loss),
                take_profit=float(closed.take_profit),
                pnl=float(closed.pnl),
                exit_reason=reason,
            )]
        return []

    def get_portfolio(self, symbol: str) -> Portfolio:
        return self._portfolio_for(symbol)

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Return runtime-visible portfolio state per symbol."""
        return {
            symbol: {
                "balance": float(portfolio.balance),
                "equity": float(portfolio.equity),
                "leverage": portfolio.leverage,
                "open_positions": [
                    _serialize_position(position)
                    for position in portfolio.positions
                    if position.status == PositionStatus.OPEN
                ],
            }
            for symbol, portfolio in self._portfolio.items()
        }

    def warmup(self) -> None:
        self._portfolio = {}
        self._metrics.reset()

    def teardown(self) -> None:
        self._portfolio = {}
        self._metrics.reset()

    def reset(self) -> None:
        self.warmup()

    def restore(self, payload: dict[str, dict]) -> None:
        self._portfolio = {}
        for symbol, state in payload.items():
            if not isinstance(state, dict):
                continue
            portfolio = Portfolio.create_default()
            if "balance" in state:
                portfolio.balance = Decimal(str(state["balance"]))
            if "equity" in state:
                portfolio.equity = Decimal(str(state["equity"]))
            if "leverage" in state:
                portfolio.leverage = int(state["leverage"] or 1)
            open_positions_payload = state.get("open_positions")
            if isinstance(open_positions_payload, list):
                for raw_position in open_positions_payload:
                    if not isinstance(raw_position, dict):
                        continue
                    portfolio.positions.append(_deserialize_position(raw_position))
            self._portfolio[symbol] = portfolio


def _to_domain_signal(signal: Signal):
    return DomainSignal(
        type=SignalType.BUY if signal.type == "LONG" else SignalType.SELL,
        price=signal.entry,
        reason=signal.reason,
        stop_loss=signal.sl,
        take_profit=signal.tp,
        timestamp=str(signal.timestamp),
        setup=SetupType.TREND_MODEL,
        source=Source.AMT,
        metadata={
            "symbol": signal.symbol,
            "confidence": signal.confidence,
            "rr": signal.rr,
            "option_lot_size": 1,
            "strike": 0,
            "is_expiry": False,
        },
    )


def _serialize_position(position: object) -> dict[str, object]:
    symbol = getattr(position, "symbol", "")
    side = getattr(position, "side", None)
    stop_loss = getattr(position, "stop_loss", 0.0)
    take_profit = getattr(position, "take_profit", 0.0)
    entry_price = getattr(position, "entry_price", 0.0)
    size = getattr(position, "size", 0.0)
    pnl = getattr(position, "pnl", 0.0)
    return {
        "id": str(getattr(position, "id", "")),
        "symbol": symbol,
        "side": str(side),
        "status": str(getattr(position, "status", "")),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "entry_price": float(entry_price),
        "size": float(size),
        "pnl": float(pnl),
        "entry_time": getattr(position, "entry_time", ""),
        "exit_price": getattr(position, "exit_price", None),
        "exit_time": getattr(position, "exit_time", None),
        "close_reason": getattr(position, "close_reason", None),
        "metadata": getattr(position, "metadata", None),
    }


def _deserialize_position(raw: dict[str, object]) -> Position:
    status = str(raw.get("status", PositionStatus.OPEN.value if hasattr(PositionStatus.OPEN, "value") else "OPEN"))
    side_value = str(raw.get("side", "LONG"))
    try:
        side = Side(side_value)
    except ValueError:
        side = Side.LONG
    status_enum = PositionStatus.OPEN
    for item in PositionStatus:
        if status == item.value:
            status_enum = item
            break
    return Position(
        id=str(raw.get("id", "")),
        symbol=str(raw.get("symbol", "")),
        side=side,
        source=Source.AMT,
        entry_price=Decimal(str(raw.get("entry_price", 0.0))),
        size=Decimal(str(raw.get("size", 0.0))),
        stop_loss=Decimal(str(raw.get("stop_loss", 0.0))),
        take_profit=Decimal(str(raw.get("take_profit", 0.0))),
        pnl=Decimal(str(raw.get("pnl", 0.0))),
        entry_time=str(raw.get("entry_time", "")),
        status=status_enum,
        exit_price=Decimal(str(raw.get("exit_price", 0.0))) if raw.get("exit_price") is not None else None,
        exit_time=str(raw.get("exit_time", "")) if raw.get("exit_time") is not None else None,
        close_reason=raw.get("close_reason"),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None,
    )
