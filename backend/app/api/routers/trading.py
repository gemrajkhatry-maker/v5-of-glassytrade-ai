"""Trading router — portfolio, stats, and lifecycle REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.application.services.trading_session import TradingSessionService

from app.api.dependencies import get_storage, get_trading_session
from app.domain.ports.storage import IStorage
from app.application.services.trading_query_service import TradingQueryService
from app.infrastructure.serialization.schemas import (
    StatsRequestDTO, portfolio_to_dto, position_event_to_dto,
)


_trading_query_service = TradingQueryService()

router = APIRouter(prefix="/trading", tags=["trading"])


@router.post("/portfolio/create")
async def create_portfolio(
    session: TradingSessionService = Depends(get_trading_session),
):
    portfolio = session.create_portfolio()
    return portfolio_to_dto(portfolio)


@router.post("/stats")
async def compute_stats(req: StatsRequestDTO):
    """Legacy stats endpoint — compute from a list of closed trades."""
    return _trading_query_service.build_stats_from_closed_trades(req)


@router.get("/positions/events")
async def get_position_events(
    position_id: str | None = Query(default=None, alias="positionId"),
    symbol: str | None = Query(default=None),
    storage: IStorage = Depends(get_storage),
):
    """Return append-only lifecycle events for operator inspection & audit."""
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
    """Return the audit-friendly lifecycle view for a single position."""
    events = storage.query_position_events(position_id=position_id)
    if not events:
        raise HTTPException(status_code=404, detail="Position lifecycle not found")
    return _trading_query_service.build_lifecycle_summary(events)
