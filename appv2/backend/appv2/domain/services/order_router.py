"""Order Router — routes orders to correct exchange (NSE_FNO, MCX_COMM, MCX_FNO).

Handles:
- Symbol-to-exchange mapping
- Symbol format conversion (Dhan format → security ID)
- Exchange-specific order validation
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExchangeSegment(str, Enum):
    NSE_FNO = "NSE_FNO"
    NSE_CASH = "NSE_EQ"
    MCX_COMM = "MCX_COMM"
    MCX_FNO = "MCX_FNO"
    BSE_FNO = "BSE_FNO"


@dataclass(frozen=True)
class RoutedOrder:
    symbol: str
    exchange: ExchangeSegment
    security_id: str
    order_type: str
    side: str
    quantity: int
    price: float
    trigger_price: float


class OrderRouter:
    """Routes orders to the correct exchange based on symbol analysis."""

    # Known exchange prefixes
    _NSE_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}
    _MCX_SYMBOLS = {"CRUDEOIL", "CRUDEOILM", "GOLD", "GOLDM", "SILVER", "SILVERM", "NATURALGAS", "COPPER", "ALUMINI", "ZINC", "LEAD", "NICKEL"}

    def __init__(self, symbol_map: dict[str, str] | None = None):
        """
        Args:
            symbol_map: Optional custom mapping of symbol → security_id
        """
        self._symbol_map = symbol_map or {}
        self._exchange_cache: dict[str, ExchangeSegment] = {}

    def route(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> RoutedOrder:
        """Route an order to the correct exchange.

        Args:
            symbol: Symbol in Dhan format (e.g., "NIFTY 20 MAR 23400 CE")
            side: "BUY" or "SELL"
            order_type: "MARKET", "LIMIT", "SL", "SL-M", "BRACKET"
            quantity: Number of lots
            price: Limit price (for LIMIT/SL orders)
            trigger_price: Trigger price (for SL orders)
        """
        exchange = self._detect_exchange(symbol)
        security_id = self._resolve_security_id(symbol)

        return RoutedOrder(
            symbol=symbol,
            exchange=exchange,
            security_id=security_id,
            order_type=order_type,
            side=side,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
        )

    def validate_order(self, routed: RoutedOrder) -> list[str]:
        """Validate order for the target exchange.

        Returns:
            List of validation errors (empty if valid).
        """
        errors = []

        # MCX commodity-specific checks
        if routed.exchange in (ExchangeSegment.MCX_COMM, ExchangeSegment.MCX_FNO):
            if routed.quantity < 1:
                errors.append("MCX minimum quantity is 1")

        # NSE F&O-specific checks
        if routed.exchange == ExchangeSegment.NSE_FNO:
            if routed.order_type in ("LIMIT", "SL") and routed.price <= 0:
                errors.append(f"Price required for {routed.order_type} order on NSE")

        # SL orders require trigger price
        if routed.order_type in ("SL", "SL-M") and routed.trigger_price <= 0:
            errors.append("Trigger price required for SL orders")

        # Bracket order checks
        if routed.order_type == "BRACKET":
            if routed.price <= 0:
                errors.append("Bracket order requires entry price")

        return errors

    def _detect_exchange(self, symbol: str) -> ExchangeSegment:
        """Detect exchange from symbol name."""
        if symbol in self._exchange_cache:
            return self._exchange_cache[symbol]

        symbol_upper = symbol.upper()
        base = symbol_upper.split()[0] if symbol_upper.split() else symbol_upper

        # Check if it's an option (has strike + type)
        is_option = any(kw in symbol_upper for kw in ["CE", "CALL", "PE", "PUT"])

        if base in self._MCX_SYMBOLS:
            exchange = ExchangeSegment.MCX_FNO if is_option else ExchangeSegment.MCX_COMM
        elif base in self._NSE_SYMBOLS:
            exchange = ExchangeSegment.NSE_FNO
        else:
            # Default to NSE F&O
            exchange = ExchangeSegment.NSE_FNO

        self._exchange_cache[symbol] = exchange
        return exchange

    def _resolve_security_id(self, symbol: str) -> str:
        """Resolve symbol to security ID."""
        if symbol in self._symbol_map:
            return self._symbol_map[symbol]
        # Return symbol as-is; broker adapter will resolve it
        return symbol

    def update_symbol_map(self, symbol: str, security_id: str) -> None:
        """Add or update a symbol mapping."""
        self._symbol_map[symbol] = security_id

    def clear_cache(self) -> None:
        self._exchange_cache.clear()
