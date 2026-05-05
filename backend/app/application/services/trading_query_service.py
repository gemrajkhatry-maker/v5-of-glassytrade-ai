"""Application services for trading-router use cases."""

from __future__ import annotations

from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side, PositionStatus, Source
from app.infrastructure.serialization.schemas import position_event_to_dto


class TradingQueryService:
    """Use-case service for trading query endpoints."""

    def build_lifecycle_summary(self, events: list[dict]) -> dict:
        opened = next((event for event in events if event.get("event_type") in {"OPENED", "RECOVERED"}), None)
        closed = next((event for event in reversed(events) if event.get("event_type") == "CLOSED"), None)
        partial_exits = [event for event in events if event.get("event_type") == "PARTIAL_EXIT"]
        stale_reconciliations = sum(1 for event in events if event.get("event_type") == "RECONCILED_STALE")

        return {
            "positionId": events[0].get("position_id", ""),
            "symbol": events[0].get("symbol", ""),
            "eventCount": len(events),
            "status": "CLOSED" if closed else "OPEN",
            "openedAt": (opened or {}).get("event_time", ""),
            "closedAt": (closed or {}).get("event_time", ""),
            "side": (opened or {}).get("side"),
            "entryPrice": (opened or {}).get("entry_price"),
            "exitPrice": (closed or {}).get("exit_price"),
            "pnl": (closed or {}).get("pnl"),
            "source": (opened or {}).get("source"),
            "partialExitCount": len(partial_exits),
            "staleReconciliationCount": stale_reconciliations,
            "eventTypes": [event.get("event_type", "") for event in events],
            "events": [position_event_to_dto(event) for event in events],
        }

    def build_stats_from_closed_trades(self, request) -> dict:
        from app.infrastructure.serialization.schemas import stats_to_dto

        portfolio = Portfolio()
        for t in request.closed_trades:
            portfolio.closed_trades.append(
                Position(
                    id=t.id,
                    symbol=t.symbol,
                    side=Side(t.side),
                    source=Source(t.source),
                    entry_price=t.entry_price,
                    size=t.size,
                    stop_loss=t.stop_loss,
                    take_profit=t.take_profit,
                    pnl=t.pnl,
                    entry_time=t.entry_time,
                    status=PositionStatus(t.status),
                    exit_price=t.exit_price,
                    exit_time=t.exit_time,
                    close_reason=t.close_reason,
                )
            )

        stats = portfolio.get_stats(Source(request.source))
        return stats_to_dto(stats)
