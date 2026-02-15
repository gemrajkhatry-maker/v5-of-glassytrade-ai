"""Trading router — portfolio and stats REST endpoints."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_trading_session
from app.application.services.trading_session import TradingSessionService
from app.domain.trading.models.enums import Source
from app.infrastructure.serialization.schemas import (
    StatsRequestDTO, portfolio_to_dto, stats_to_dto,
)

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
