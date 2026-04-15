"""Trading router — portfolio, stats, and lifecycle REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_storage, get_trading_session
from app.application.services.trading_session import TradingSessionService
from app.domain.ports.storage import IStorage
from app.domain.trading.models.enums import Source
from app.infrastructure.serialization.schemas import (
    StatsRequestDTO, portfolio_to_dto, position_event_to_dto, stats_to_dto,
)

router = APIRouter(prefix="/trading", tags=["trading"])


def _build_lifecycle_summary(events: list[dict]) -> dict:
    """Summarise append-only lifecycle events for one position."""
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


@router.post("/portfolio/create")
async def create_portfolio(
    session: TradingSessionService = Depends(get_trading_session),
):
    portfolio = session.create_portfolio()
    return portfolio_to_dto(portfolio)


@router.post("/stats")
async def compute_stats(req: StatsRequestDTO):
    """Legacy stats endpoint — compute from a list of closed trades."""
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.trading.models.entities import Position
    from app.domain.trading.models.enums import Side, PositionStatus

    # Build a temporary Portfolio to compute stats
    portfolio = Portfolio()
    for t in req.closed_trades:
        portfolio.closed_trades.append(Position(
            id=t.id, symbol=t.symbol,
            side=Side(t.side), source=Source(t.source),
            entry_price=t.entry_price, size=t.size,
            stop_loss=t.stop_loss, take_profit=t.take_profit,
            pnl=t.pnl, entry_time=t.entry_time,
            status=PositionStatus(t.status),
            exit_price=t.exit_price, exit_time=t.exit_time,
            close_reason=t.close_reason,
        ))

    source = Source(req.source)
    stats = portfolio.get_stats(source)
    return stats_to_dto(stats)


@router.get("/positions/events")
async def get_position_events(
    position_id: str | None = Query(default=None, alias="positionId"),
    symbol: str | None = Query(default=None),
    storage: IStorage = Depends(get_storage),
):
    """Return append-only lifecycle events for operator inspection and replay."""
    events = storage.query_position_events(position_id=position_id, symbol=symbol)
    return {
        "count": len(events),
        "events": [position_event_to_dto(event) for event in events],
    }


@router.get("/positions/{position_id}/lifecycle")
async def get_position_lifecycle(
    position_id: str,
    storage: IStorage = Depends(get_storage),
):
    """Return the replay-friendly lifecycle view for a single position."""
    events = storage.query_position_events(position_id=position_id)
    if not events:
        raise HTTPException(status_code=404, detail="Position lifecycle not found")
    return _build_lifecycle_summary(events)
