"""
Dhan Application Converters - Data conversion utilities.

This module provides conversion utilities for transforming between:
- Dhan-specific domain entities (DhanInstrument, DhanQuote, etc.)
- Broker-agnostic entities (Instrument, Quote, etc.)

All converters are stateless static methods for simplicity and testability.

Example:
    >>> from brokers.broker.dhan.application import DhanConverter
    >>> from brokers.broker.dhan.domain import DhanQuote
    >>>
    >>> # Convert DhanQuote to broker-agnostic Quote
    >>> quote = DhanConverter.to_quote(dhan_quote)
"""

from datetime import datetime, date
from typing import Dict, Any, Optional, List

from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OptionChain,
    DepthLevel,
)
from brokers.broker.types import (
    Exchange,
    OptionType,
    OrderSide,
    OrderType,
    OrderStatus,
)

from brokers.broker.dhan.domain import (
    DhanInstrument,
    DhanQuote,
    DhanTick,
    DhanOrder,
    DhanPosition,
    DhanOption,
    DhanOptionChain,
    ExchangeSegment,
    InstrumentTypeEnum,
    OptionType as DhanOptionType,
)
from brokers.broker.dhan.domain.segment_mapping import SEGMENT_TO_EXCHANGE
from brokers.broker.dhan.domain.segment_mapping import (
    exchange_to_segment_name,
    segment_name_to_exchange,
)


# =============================================================================
# Helper Functions (for backward compatibility with dhanhq_custom)
# =============================================================================


def to_segment(exchange: Optional[str]) -> Optional[str]:
    """
    Convert user-friendly exchange to internal segment code.

    This function provides backward compatibility with dhanhq_custom.src.exchange.to_segment.

    Args:
        exchange: Exchange enum, string, or None

    Returns:
        Internal segment code (e.g., 'NSE_EQ', 'NSE_FNO') or None

    Example:
        >>> from brokers.broker.dhan.application import to_segment
        >>> to_segment("NSE")
        'NSE_EQ'
        >>> to_segment("NFO")
        'NSE_FNO'
        >>> to_segment("MCX")
        'MCX_COMM'
    """
    if exchange is None:
        return None

    # Handle Exchange enum
    if isinstance(exchange, Exchange):
        return exchange_to_segment_name(exchange)

    # Handle string
    exchange_upper = str(exchange).upper().strip()

    # Direct mapping for user-friendly names
    string_to_segment = {
        "NSE": "NSE_EQ",
        "BSE": "BSE_EQ",
        "NFO": "NSE_FNO",
        "BFO": "BSE_FNO",
        "MCX": "MCX_COMM",
        "INDEX": "IDX_I",
        "CDS": "NSE_CURRENCY",
        # Also support internal codes directly
        "NSE_EQ": "NSE_EQ",
        "BSE_EQ": "BSE_EQ",
        "NSE_FNO": "NSE_FNO",
        "BSE_FNO": "BSE_FNO",
        "MCX_COMM": "MCX_COMM",
        "IDX_I": "IDX_I",
        "NSE_CURRENCY": "NSE_CURRENCY",
    }
    return string_to_segment.get(exchange_upper, exchange_upper)


# =============================================================================
# Dhan Converter
# =============================================================================


class DhanConverter:
    """
    Convert between Dhan domain entities and broker-agnostic entities.

    This class provides static methods for converting:
    - DhanInstrument -> Instrument
    - DhanQuote -> Quote
    - DhanTick -> Tick
    - DhanOrder -> Order
    - DhanPosition -> Position
    - DhanOptionChain -> OptionChain
    - OrderRequest -> Dhan API order payload

    All methods are stateless and can be called directly on the class.

    Example:
        >>> # Convert a Dhan quote
        >>> quote = DhanConverter.to_quote(dhan_quote)
        >>>
        >>> # Convert an order request
        >>> payload = DhanConverter.from_order_request(order_request)
    """

    # =========================================================================
    # To Broker-Agnostic Entities
    # =========================================================================

    @staticmethod
    def to_instrument(dhan_instrument: DhanInstrument) -> Instrument:
        """
        Convert DhanInstrument to broker-agnostic Instrument.

        Args:
            dhan_instrument: Dhan-specific instrument entity.

        Returns:
            Broker-agnostic Instrument entity.

        Example:
            >>> instrument = DhanConverter.to_instrument(dhan_inst)
            >>> print(instrument.symbol)  # "NIFTY"
        """
        # Map exchange segment to Exchange enum
        exchange = DhanConverter._segment_to_exchange(dhan_instrument.exchange_segment)

        # Map option type
        option_type = None
        if dhan_instrument.option_type:
            option_type = DhanConverter._map_option_type(dhan_instrument.option_type)

        return Instrument(
            symbol=dhan_instrument.symbol,
            exchange=exchange,
            security_id=dhan_instrument.security_id,
            option_type=option_type,
            strike=dhan_instrument.strike,
            expiry=dhan_instrument.expiry_date,
        )

    @staticmethod
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
            instrument = DhanConverter.to_instrument(dhan_quote.instrument)
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

    @staticmethod
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
            instrument = DhanConverter.to_instrument(dhan_tick.instrument)
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

    @staticmethod
    def to_order(dhan_order: DhanOrder) -> Order:
        """
        Convert DhanOrder to broker-agnostic Order.

        Args:
            dhan_order: Dhan-specific order entity.

        Returns:
            Broker-agnostic Order entity.

        Example:
            >>> order = DhanConverter.to_order(dhan_order)
            >>> print(order.order_id)  # "12345"
        """
        # Create minimal instrument
        instrument = Instrument(
            symbol=dhan_order.trading_symbol,
            exchange=Exchange.NSE,  # Default, could be improved
            security_id=dhan_order.security_id,
        )

        # Map order side
        side = OrderSide.BUY if dhan_order.is_buy else OrderSide.SELL

        # Map order type
        order_type = DhanConverter._map_order_type_from_dhan(dhan_order.order_type)

        # Map order status
        status = DhanConverter._map_order_status_from_dhan(dhan_order.status)

        return Order(
            instrument=instrument,
            side=side,
            quantity=float(dhan_order.quantity),
            price=dhan_order.price if dhan_order.price else None,
            order_id=dhan_order.order_id,
            order_type=order_type,
            filled_quantity=float(dhan_order.filled_quantity),
            status=status,
            timestamp=dhan_order.timestamp,
        )

    @staticmethod
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

    @staticmethod
    def to_option_chain(
        dhan_chain: DhanOptionChain, exchange: Exchange = Exchange.NFO
    ) -> OptionChain:
        """
        Convert DhanOptionChain to broker-agnostic OptionChain.

        Args:
            dhan_chain: Dhan-specific option chain entity.
            exchange: Exchange for the underlying.

        Returns:
            Broker-agnostic OptionChain entity.

        Example:
            >>> chain = DhanConverter.to_option_chain(dhan_chain)
            >>> print(chain.underlying.symbol)  # "NIFTY"
        """
        # Create underlying instrument
        underlying = Instrument(
            symbol=dhan_chain.underlying,
            exchange=exchange,
            security_id="",
        )

        # Build calls and puts dictionaries
        calls: Dict[float, Instrument] = {}
        puts: Dict[float, Instrument] = {}

        for strike, (call_opt, put_opt) in dhan_chain.strikes.items():
            # Add call option
            if call_opt and call_opt.instrument:
                calls[strike] = DhanConverter.to_instrument(call_opt.instrument)
            elif call_opt:
                calls[strike] = Instrument(
                    symbol=f"{dhan_chain.underlying}{strike}CE",
                    exchange=exchange,
                    security_id="",
                    option_type=OptionType.CALL,
                    strike=strike,
                    expiry=dhan_chain.expiry,
                )

            # Add put option
            if put_opt and put_opt.instrument:
                puts[strike] = DhanConverter.to_instrument(put_opt.instrument)
            elif put_opt:
                puts[strike] = Instrument(
                    symbol=f"{dhan_chain.underlying}{strike}PE",
                    exchange=exchange,
                    security_id="",
                    option_type=OptionType.PUT,
                    strike=strike,
                    expiry=dhan_chain.expiry,
                )

        # Calculate ATM strike and step size from the DhanOptionChain
        atm_strike = (
            dhan_chain.atm_strike
            if hasattr(dhan_chain, "atm_strike")
            else (
                min(
                    dhan_chain.strikes.keys(),
                    key=lambda s: abs(s - dhan_chain.spot_price),
                )
                if dhan_chain.strikes
                else 0.0
            )
        )
        step_size = getattr(dhan_chain, "step_size", 50.0)

        return OptionChain(
            underlying=underlying,
            expiry=dhan_chain.expiry,
            spot_price=dhan_chain.spot_price,
            atm_strike=atm_strike,
            step_size=step_size,
            calls=calls,
            puts=puts,
        )

    # =========================================================================
    # From Broker-Agnostic Entities (for API calls)
    # =========================================================================

    @staticmethod
    def from_order_request(
        order: Order,
        client_id: str = "",
        validity: str = "DAY",
    ) -> Dict[str, Any]:
        """
        Convert Order to Dhan API order request payload.

        `product_type` and `trigger_price` are now read directly from the
        Order entity rather than being passed as separate arguments.

        Args:
            order:     Broker-agnostic Order entity.
            client_id: Dhan client ID for the request.
            validity:  Order validity — DAY, IOC.

        Returns:
            Dictionary payload for Dhan place_order API.

        Example:
            >>> order = Order(..., product_type="CNC", trigger_price=18000.0)
            >>> payload = DhanConverter.from_order_request(order)
            >>> response = await http_client.post("/orders", json=payload)
        """
        transaction_type = "BUY" if order.side == OrderSide.BUY else "SELL"

        order_type_map = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.SL: "STOP_LOSS",
            OrderType.SLM: "STOP_LOSS_MARKET",
        }
        dhan_order_type = order_type_map.get(order.order_type, "MARKET")

        payload = {
            "dhanClientId": client_id,
            "transactionType": transaction_type,
            "exchangeSegment": DhanConverter._exchange_to_segment(
                order.instrument.exchange
            ),
            "productType": getattr(order, "product_type", "INTRADAY"),
            "orderType": dhan_order_type,
            "validity": validity,
            "securityId": order.instrument.security_id,
            "quantity": int(order.quantity),
        }

        # LIMIT order: send limit price
        if order.order_type == OrderType.LIMIT and order.price:
            payload["price"] = order.price

        # SL order: send both trigger price (activation) and limit price
        if order.order_type == OrderType.SL:
            trigger = getattr(order, "trigger_price", None) or order.price
            if trigger:
                payload["triggerPrice"] = trigger
            if order.price:
                payload["price"] = order.price

        # SLM order: only trigger price (market execution at trigger)
        if order.order_type == OrderType.SLM:
            trigger = getattr(order, "trigger_price", None) or order.price
            if trigger:
                payload["triggerPrice"] = trigger

        # Dhan idempotency: when the caller sets ``user_order_id`` (e.g. the
        # strategy signal_id), send it as ``correlationId`` so a retried
        # place_order POST (network blip where the first response was lost)
        # is deduplicated broker-side instead of opening a duplicate position.
        correlation_id = str(getattr(order, "user_order_id", "") or "").strip()
        if correlation_id:
            payload["correlationId"] = correlation_id[:36]

        return payload

    @staticmethod
    def from_instrument(instrument: Instrument) -> Dict[str, Any]:
        """
        Convert Instrument to Dhan API lookup parameters.

        Args:
            instrument: Broker-agnostic Instrument entity.

        Returns:
            Dictionary with Dhan lookup parameters.

        Example:
            >>> params = DhanConverter.from_instrument(instrument)
            >>> # Use for API lookup
        """
        return {
            "symbol": instrument.symbol,
            "exchange_segment": DhanConverter._exchange_to_segment(instrument.exchange),
            "security_id": instrument.security_id,
        }

    # =========================================================================
    # From Raw API Responses
    # =========================================================================

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def order_from_api_response(data: Dict[str, Any]) -> Order:
        """
        Create Order from raw Dhan API response.

        Args:
            data: Raw API response data.

        Returns:
            Broker-agnostic Order entity.

        Example:
            >>> order = DhanConverter.order_from_api_response(response_data)
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

        # Map order side
        side = OrderSide.BUY if data.get("transactionType") == "BUY" else OrderSide.SELL

        # Map order type
        order_type = DhanConverter._map_order_type_from_dhan(
            data.get("orderType", "MARKET")
        )

        # Map order status
        status = DhanConverter._map_order_status_from_dhan(
            data.get("orderStatus", "PENDING")
        )

        return Order(
            instrument=instrument,
            side=side,
            quantity=float(data.get("quantity", 0)),
            price=float(data.get("price", 0)) if data.get("price") else None,
            order_id=str(data.get("orderId", "")),
            order_type=order_type,
            filled_quantity=float(data.get("filledQty", data.get("filledQuantity", 0))),
            status=status,
            timestamp=datetime.now(),
        )

    @staticmethod
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

    # =========================================================================
    # Private Helper Methods
    # =========================================================================

    @staticmethod
    def _segment_to_exchange(segment: ExchangeSegment) -> Exchange:
        """Convert ExchangeSegment to Exchange enum."""
        segment_name = segment.name if hasattr(segment, "name") else str(segment)
        return segment_name_to_exchange(segment_name)

    @staticmethod
    def _exchange_to_segment(exchange: Exchange) -> str:
        """Convert Exchange enum to Dhan segment string."""
        return exchange_to_segment_name(exchange)

    @staticmethod
    def _map_option_type(dhan_option_type: DhanOptionType) -> OptionType:
        """Map Dhan option type to broker-agnostic OptionType."""
        if dhan_option_type == DhanOptionType.CALL:
            return OptionType.CALL
        elif dhan_option_type == DhanOptionType.PUT:
            return OptionType.PUT
        return OptionType.CALL  # Default

    @staticmethod
    def _map_order_type_from_dhan(dhan_order_type: str) -> OrderType:
        """Map Dhan order type string to OrderType enum."""
        type_map = {
            "MARKET": OrderType.MARKET,
            "LIMIT": OrderType.LIMIT,
            "STOP_LOSS": OrderType.SL,
            "STOP_LOSS_MARKET": OrderType.SLM,
            "SL": OrderType.SL,
            "SL-M": OrderType.SLM,
        }
        return type_map.get(dhan_order_type.upper(), OrderType.MARKET)

    @staticmethod
    def _map_order_status_from_dhan(dhan_status: str) -> OrderStatus:
        """Map Dhan order status string to OrderStatus enum."""
        status_map = {
            "PENDING": OrderStatus.PENDING,
            "TRANSIT": OrderStatus.PENDING,
            "OPEN": OrderStatus.OPEN,
            "PARTIALLY_FILLED": OrderStatus.OPEN,
            "PART_TRADED": OrderStatus.OPEN,
            "TRADED": OrderStatus.FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "CANCELED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.CANCELLED,
        }
        return status_map.get(dhan_status.upper(), OrderStatus.PENDING)
