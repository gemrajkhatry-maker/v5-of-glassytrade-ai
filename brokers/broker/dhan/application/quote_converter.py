"""
Quote and market-data conversion utilities for the Dhan broker.

Split out of ``converters.py`` (WS4): converts between Dhan quote/tick
representations, raw API responses, WebSocket messages and broker-agnostic
entities. All functions are stateless; ``converters.DhanConverter``
re-exposes them as staticmethods.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from brokers.broker.entities import (
    DepthLevel,
    Instrument,
    Quote,
    Tick,
)
from brokers.broker.types import Exchange

from brokers.broker.dhan.domain import DhanQuote, DhanTick

if TYPE_CHECKING:
    from brokers.broker.entities import MarketDepth


def to_quote(dhan_quote: DhanQuote) -> Quote:
    """
    Convert DhanQuote to broker-agnostic Quote.

    Args:
        dhan_quote: Dhan-specific quote entity.

    Returns:
        Broker-agnostic Quote entity.

    Example:
        >>> quote = DhanConverter.to_quote(dhan_quote)
        >>> print(quote.ltp)  # 18050.50
    """
    # Get or create instrument
    instrument = None
    if dhan_quote.instrument:
        from brokers.broker.dhan.application.instrument_converter import to_instrument

        instrument = to_instrument(dhan_quote.instrument)
    else:
        # Create minimal instrument from security_id
        instrument = Instrument(
            symbol="",
            exchange=Exchange.NSE,  # Default
            security_id=dhan_quote.security_id,
        )

    oi_val = getattr(dhan_quote, "oi", None)
    oi = int(oi_val) if oi_val is not None else None
    return Quote(
        instrument=instrument,
        ltp=dhan_quote.ltp,
        bid=dhan_quote.bid,
        ask=dhan_quote.ask,
        volume=dhan_quote.volume,
        open=dhan_quote.open,
        high=dhan_quote.high,
        low=dhan_quote.low,
        close=dhan_quote.close,
        timestamp=dhan_quote.timestamp,
        oi=oi,
    )


def to_tick(dhan_tick: DhanTick) -> Tick:
    """
    Convert DhanTick to broker-agnostic Tick.

    Args:
        dhan_tick: Dhan-specific tick entity.

    Returns:
        Broker-agnostic Tick entity.

    Example:
        >>> tick = DhanConverter.to_tick(dhan_tick)
        >>> print(tick.price)  # 18050.50
    """
    # Get or create instrument
    instrument = None
    if dhan_tick.instrument:
        from brokers.broker.dhan.application.instrument_converter import to_instrument

        instrument = to_instrument(dhan_tick.instrument)
    else:
        # Create minimal instrument from security_id
        instrument = Instrument(
            symbol="",
            exchange=Exchange.NSE,  # Default
            security_id=dhan_tick.security_id,
        )

    return Tick(
        instrument=instrument,
        price=dhan_tick.ltp,
        volume=dhan_tick.volume,
        timestamp=dhan_tick.timestamp,
    )


def quote_from_api_response(
    data: Dict[str, Any], security_id: str, exchange: Exchange = Exchange.NSE
) -> Quote:
    """
    Create Quote from raw Dhan API response.

    Args:
        data: Raw API response data.
        security_id: Security ID for the quote.
        exchange: Exchange for the instrument.

    Returns:
        Broker-agnostic Quote entity.

    Example:
        >>> quote = DhanConverter.quote_from_api_response(response_data, "12345")
    """
    instrument = Instrument(
        symbol=data.get("tradingSymbol", ""),
        exchange=exchange,
        security_id=security_id,
    )

    oi_raw = data.get("oi", data.get("OI"))
    oi = int(oi_raw) if oi_raw is not None and str(oi_raw).strip() != "" else None
    # LTP fallback order matches dhanhq_custom: LTP, ltp, last_price
    ltp = float(
        data.get("LTP") or data.get("ltp") or data.get("last_price") or 0
    )

    def _parse_depth_levels(levels: Any) -> Optional[List[DepthLevel]]:
        if not levels or not isinstance(levels, list):
            return None
        out = []
        for lev in levels:
            if not isinstance(lev, dict):
                continue
            price = float(lev.get("price", lev.get("Price", 0)))
            qty = int(lev.get("quantity", lev.get("Quantity", 0)))
            orders = lev.get("orders", lev.get("Orders"))
            if orders is not None:
                orders = int(orders)
            out.append(DepthLevel(price=price, quantity=qty, orders=orders))
        return out if out else None

    bid_depth = _parse_depth_levels(data.get("bid_depth"))
    ask_depth = _parse_depth_levels(data.get("ask_depth"))

    return Quote(
        instrument=instrument,
        ltp=ltp,
        bid=float(data.get("bid", data.get("bid_price", 0))),
        ask=float(data.get("ask", data.get("ask_price", 0))),
        volume=int(data.get("volume", 0)),
        open=float(data.get("open", 0)),
        high=float(data.get("high", 0)),
        low=float(data.get("low", 0)),
        close=float(data.get("close", 0)),
        timestamp=datetime.now(),
        oi=oi,
        bid_depth=bid_depth,
        ask_depth=ask_depth,
    )


def tick_from_ws_message(
    data: Dict[str, Any], security_id: str, instrument: Optional[Instrument] = None
) -> Tick:
    """
    Create Tick from WebSocket message data.

    Args:
        data: WebSocket message data.
        security_id: Security ID for the tick.
        instrument: Optional pre-existing instrument.

    Returns:
        Broker-agnostic Tick entity.

    Example:
        >>> tick = DhanConverter.tick_from_ws_message(ws_data, "12345")
    """
    if instrument is None:
        instrument = Instrument(
            symbol="",
            exchange=Exchange.NSE,
            security_id=security_id,
        )

    return Tick(
        instrument=instrument,
        price=float(data.get("LTP", data.get("ltp", 0))),
        volume=int(data.get("volume", data.get("total_quantity", 0))),
        timestamp=datetime.now(),
    )


def depth_from_api_response(
    data: Dict[str, Any], security_id: str, instrument: Instrument
) -> "MarketDepth":
    """
    Create MarketDepth from WebSocket depth message data.

    Args:
        data: WebSocket depth message data.
        security_id: Security ID for the instrument.
        instrument: Instrument being tracked.

    Returns:
        MarketDepth entity with bid/ask levels.

    Example:
        >>> depth = DhanConverter.depth_from_api_response(ws_data, "12345", instrument)
    """
    from brokers.broker.entities import MarketDepth, DepthLevel

    # Parse bid levels (up to 20)
    bid_levels = []
    bid_data = data.get("bids", data.get("bid", []))
    if bid_data:
        for i, level in enumerate(bid_data[:20]):
            bid_levels.append(
                DepthLevel(
                    price=float(level.get("price", level.get("Price", 0))),
                    quantity=int(level.get("quantity", level.get("Quantity", 0))),
                    orders=int(level.get("orders", level.get("Orders", 0)))
                    if "orders" in level or "Orders" in level
                    else None,
                )
            )

    # Parse ask levels (up to 20)
    ask_levels = []
    ask_data = data.get("asks", data.get("ask", []))
    if ask_data:
        for i, level in enumerate(ask_data[:20]):
            ask_levels.append(
                DepthLevel(
                    price=float(level.get("price", level.get("Price", 0))),
                    quantity=int(level.get("quantity", level.get("Quantity", 0))),
                    orders=int(level.get("orders", level.get("Orders", 0)))
                    if "orders" in level or "Orders" in level
                    else None,
                )
            )

    # Determine side based on which levels are present
    if bid_levels and not ask_levels:
        side = "bid"
        levels = bid_levels
    elif ask_levels and not bid_levels:
        side = "ask"
        levels = ask_levels
    else:
        # If both present, create two separate MarketDepth objects
        # For now, prefer bids
        side = "bid"
        levels = bid_levels

    return MarketDepth(
        symbol=instrument.symbol,
        security_id=security_id,
        side=side,
        levels=levels,
        timestamp=datetime.now(),
    )
