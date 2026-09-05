"""Dhan order and position entities."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class DhanOrder:
    """
    Immutable order representation.
    
    Represents an order placed through the Dhan broker.
    
    Attributes:
        order_id: Dhan's unique order ID.
        security_id: Security ID of the instrument.
        trading_symbol: Trading symbol.
        order_type: Type of order (MARKET, LIMIT, SL, SL-M).
        transaction_type: BUY or SELL.
        quantity: Order quantity.
        price: Limit price (0 for market orders).
        trigger_price: Trigger price for SL orders.
        status: Current order status.
        filled_quantity: Quantity filled so far.
        average_price: Average execution price.
        product_type: Product type (I, M, C, CO, BO).
        validity: Order validity (DAY, IOC, GTC).
        timestamp: Order timestamp.
        message: Any message from the exchange.
    """
    order_id: str
    security_id: str
    trading_symbol: str
    order_type: str
    transaction_type: str
    quantity: int
    price: float = 0.0
    trigger_price: float = 0.0
    status: str = "PENDING"
    filled_quantity: int = 0
    average_price: float = 0.0
    product_type: str = "M"
    validity: str = "DAY"
    timestamp: datetime = field(default_factory=datetime.now)
    message: str = ""
    
    @property
    def is_buy(self) -> bool:
        """Check if this is a buy order."""
        return self.transaction_type == "BUY"
    
    @property
    def is_sell(self) -> bool:
        """Check if this is a sell order."""
        return self.transaction_type == "SELL"
    
    @property
    def is_market(self) -> bool:
        """Check if this is a market order."""
        return self.order_type == "MARKET"
    
    @property
    def is_limit(self) -> bool:
        """Check if this is a limit order."""
        return self.order_type == "LIMIT"
    
    @property
    def is_stop_loss(self) -> bool:
        """Check if this is a stop loss order."""
        return self.order_type in ("SL", "SL-M")
    
    @property
    def is_pending(self) -> bool:
        """Check if order is pending."""
        return self.status in ("PENDING", "TRANSIT")
    
    @property
    def is_complete(self) -> bool:
        """Check if order is complete."""
        return self.status in ("TRADED", "CANCELLED", "REJECTED")
    
    @property
    def is_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.status == "TRADED" or self.filled_quantity == self.quantity
    
    @property
    def is_cancelled(self) -> bool:
        """Check if order is cancelled."""
        return self.status == "CANCELLED"
    
    @property
    def is_rejected(self) -> bool:
        """Check if order is rejected."""
        return self.status == "REJECTED"
    
    @property
    def pending_quantity(self) -> int:
        """Get remaining quantity to be filled."""
        return self.quantity - self.filled_quantity
    
    @property
    def fill_percentage(self) -> float:
        """Get fill percentage."""
        if self.quantity == 0:
            return 0.0
        return (self.filled_quantity / self.quantity) * 100


@dataclass(frozen=True)
class DhanPosition:
    """
    Immutable position representation.
    
    Represents a current position held in the portfolio.
    
    Attributes:
        security_id: Security ID of the instrument.
        trading_symbol: Trading symbol.
        quantity: Net position quantity (positive for long, negative for short).
        average_price: Average entry price.
        ltp: Current last traded price.
        pnl: Unrealized profit/loss.
        pnl_percent: Unrealized P&L percentage.
        product_type: Product type (I, M, C).
    """
    security_id: str
    trading_symbol: str
    quantity: int
    average_price: float
    ltp: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    product_type: str = "M"
    
    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.quantity < 0
    
    @property
    def is_flat(self) -> bool:
        """Check if position is flat (no position)."""
        return self.quantity == 0
    
    @property
    def abs_quantity(self) -> int:
        """Get absolute quantity."""
        return abs(self.quantity)
    
    @property
    def notional_value(self) -> float:
        """Calculate notional value of position."""
        return abs(self.quantity) * self.ltp
    
    @property
    def investment_value(self) -> float:
        """Calculate invested value."""
        return abs(self.quantity) * self.average_price
