"""
Position/portfolio conversion utilities for the Dhan broker.

Split out of ``converters.py`` (WS4): converts between Dhan position
representations, raw API responses and broker-agnostic Position entities.
All functions are stateless; ``converters.DhanConverter`` re-exposes them
as staticmethods.
"""

from typing import Any, Dict

from shared.entities.models import Instrument, Position
from brokers.broker.types import Exchange

from brokers.broker.dhan.domain import DhanPosition
from brokers.broker.dhan.domain.segment_mapping import SEGMENT_TO_EXCHANGE


def to_position(dhan_position: DhanPosition) -> Position:
    """
    Convert DhanPosition to broker-agnostic Position.

    Args:
        dhan_position: Dhan-specific position entity.

    Returns:
        Broker-agnostic Position entity.

    Example:
        >>> position = DhanConverter.to_position(dhan_position)
        >>> print(position.quantity)  # 50
    """
    # Create minimal instrument
    instrument = Instrument(
        symbol=dhan_position.trading_symbol,
        exchange=Exchange.NSE,  # Default
        security_id=dhan_position.security_id,
    )

    return Position(
        instrument=instrument,
        quantity=float(dhan_position.quantity),
        avg_price=dhan_position.average_price,
        unrealized_pnl=dhan_position.pnl,
        realized_pnl=0.0,  # Not tracked in DhanPosition
    )


def position_from_api_response(data: Dict[str, Any]) -> Position:
    """
    Create Position from raw Dhan API response.

    Args:
        data: Raw API response data.

    Returns:
        Broker-agnostic Position entity.

    Example:
        >>> position = DhanConverter.position_from_api_response(response_data)
    """
    # Map exchange
    segment = data.get("exchangeSegment", "NSE_EQ")
    exchange = SEGMENT_TO_EXCHANGE.get(segment, Exchange.NSE)

    # Create instrument
    instrument = Instrument(
        symbol=data.get("tradingSymbol", ""),
        exchange=exchange,
        security_id=str(data.get("securityId", "")),
    )

    return Position(
        instrument=instrument,
        quantity=float(data.get("netQty", 0)),
        avg_price=float(
            data.get("costPrice", 0) or data.get("buyAvg", 0) or data.get("avgPrice", 0)
        ),
        unrealized_pnl=float(data.get("unrealizedProfit", 0)),
        realized_pnl=float(data.get("realizedProfit", 0)),
    )
