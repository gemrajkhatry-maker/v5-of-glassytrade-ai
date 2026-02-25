"""
Dhan Domain Entities - Core domain entities for Dhan broker.

This module defines the core domain entities for the Dhan broker.
All entities are immutable (frozen dataclasses) and contain no
external dependencies.

These entities extend the base entities from brokers/broker/entities.py
with Dhan-specific fields and functionality.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Tuple, Any

from .value_objects import (
    ExchangeSegment,
    InstrumentTypeVO,
    InstrumentTypeEnum,
    DepthLevel,
    MarketDepth,
    OHLC,
    Greeks,
    OptionType,
)
from .constants import LOT_SIZES, STRIKE_STEPS


# =============================================================================
# Core Entities
# =============================================================================

@dataclass(frozen=True)
class DhanInstrument:
    """
    Extended instrument with Dhan-specific fields.
    
    Represents a tradeable instrument on the Dhan platform with
    all the metadata required for trading and market data operations.
    
    Attributes:
        security_id: Dhan's unique numeric identifier for this instrument.
        trading_symbol: The trading symbol (e.g., "NIFTY23FEB18000CE").
        symbol: The underlying symbol (e.g., "NIFTY").
        exchange_segment: The exchange segment this instrument belongs to.
        instrument_type: The type of instrument (equity, future, option).
        expiry_date: Expiry date for derivatives (None for equity).
        strike: Strike price for options (None for non-options).
        option_type: Option type (CE/PE) for options (None for non-options).
        lot_size: Lot size for derivatives (1 for equity).
        tick_size: Minimum price movement.
        isin: ISIN code for equities.
        segment_name: Segment name from Dhan (e.g., "NIFTY").
    
    Example:
        >>> instrument = DhanInstrument(
        ...     security_id="12345",
        ...     trading_symbol="NIFTY23FEB18000CE",
        ...     symbol="NIFTY",
        ...     exchange_segment=ExchangeSegment.NSE_FNO,
        ...     instrument_type=InstrumentTypeEnum.INDEX_OPTION,
        ...     expiry_date=date(2023, 2, 23),
        ...     strike=18000.0,
        ...     option_type=OptionType.CALL,
        ...     lot_size=25
        ... )
    """
    security_id: str
    trading_symbol: str
    symbol: str
    exchange_segment: ExchangeSegment
    instrument_type: InstrumentTypeEnum
    expiry_date: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[OptionType] = None
    lot_size: int = 1
    tick_size: float = 0.05
    isin: Optional[str] = None
    segment_name: Optional[str] = None
    
    @property
    def is_option(self) -> bool:
        """Check if this instrument is an option."""
        return self.instrument_type.is_option
    
    @property
    def is_future(self) -> bool:
        """Check if this instrument is a future."""
        return self.instrument_type.is_future
    
    @property
    def is_equity(self) -> bool:
        """Check if this instrument is equity."""
        return self.instrument_type.is_equity
    
    @property
    def is_index(self) -> bool:
        """Check if this instrument is an index."""
        return self.instrument_type.is_index
    
    @property
    def is_derivative(self) -> bool:
        """Check if this instrument is a derivative."""
        return self.is_option or self.is_future
    
    @property
    def is_call(self) -> bool:
        """Check if this is a call option."""
        return self.option_type == OptionType.CALL
    
    @property
    def is_put(self) -> bool:
        """Check if this is a put option."""
        return self.option_type == OptionType.PUT
    
    @property
    def display_name(self) -> str:
        """Get a human-readable display name."""
        if self.trading_symbol:
            return self.trading_symbol
        return f"{self.symbol}_{self.exchange_segment.name}"
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.display_name
    
    def __repr__(self) -> str:
        """Return repr."""
        return (
            f"DhanInstrument(security_id={self.security_id!r}, "
            f"trading_symbol={self.trading_symbol!r}, "
            f"symbol={self.symbol!r})"
        )


@dataclass(frozen=True)
class DhanQuote:
    """
    Immutable quote with full market depth.
    
    Represents a complete market quote for an instrument including
    OHLC prices, volume, and market depth.
    
    Attributes:
        security_id: Dhan's security ID for the instrument.
        ltp: Last traded price.
        open: Opening price for the day.
        high: Highest price for the day.
        low: Lowest price for the day.
        close: Previous close price.
        volume: Total volume traded for the day.
        bid: Best bid price.
        ask: Best ask price.
        oi: Open interest (for derivatives).
        timestamp: Quote timestamp.
        bid_depth: Tuple of bid depth levels (up to 5 levels).
        ask_depth: Tuple of ask depth levels (up to 5 levels).
        instrument: Optional reference to the DhanInstrument.
    
    Example:
        >>> quote = DhanQuote(
        ...     security_id="12345",
        ...     ltp=18050.50,
        ...     open=18000.00,
        ...     high=18100.00,
        ...     low=17950.00,
        ...     close=17980.00,
        ...     volume=1000000,
        ...     bid=18050.00,
        ...     ask=18051.00,
        ...     timestamp=datetime.now()
        ... )
    """
    security_id: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: float
    ask: float
    oi: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    bid_depth: Tuple[DepthLevel, ...] = ()
    ask_depth: Tuple[DepthLevel, ...] = ()
    instrument: Optional[DhanInstrument] = None
    
    @property
    def spread(self) -> float:
        """Calculate the bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def mid_price(self) -> float:
        """Calculate the mid-point between bid and ask."""
        return (self.bid + self.ask) / 2
    
    @property
    def vwap(self) -> float:
        """
        Calculate approximate VWAP.
        
        Note: This is an approximation using OHLC average.
        True VWAP requires tick-by-tick data.
        """
        if self.volume == 0:
            return self.ltp
        # Approximate using typical price
        typical_price = (self.high + self.low + self.close) / 3
        return typical_price
    
    @property
    def change(self) -> float:
        """Calculate the absolute change from previous close."""
        return self.ltp - self.close
    
    @property
    def change_percent(self) -> float:
        """Calculate the percentage change from previous close."""
        if self.close == 0:
            return 0.0
        return (self.change / self.close) * 100
    
    @property
    def range(self) -> float:
        """Calculate the day's price range."""
        return self.high - self.low
    
    @property
    def ohlc(self) -> OHLC:
        """Get OHLC value object."""
        return OHLC(
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.ltp  # Use LTP as current close
        )
    
    @property
    def market_depth(self) -> MarketDepth:
        """Get MarketDepth value object."""
        return MarketDepth(
            bid_levels=self.bid_depth,
            ask_levels=self.ask_depth
        )
    
    @property
    def best_bid_quantity(self) -> int:
        """Get quantity at best bid."""
        return self.bid_depth[0].quantity if self.bid_depth else 0
    
    @property
    def best_ask_quantity(self) -> int:
        """Get quantity at best ask."""
        return self.ask_depth[0].quantity if self.ask_depth else 0


@dataclass(frozen=True)
class DhanTick:
    """
    Immutable tick data.
    
    Represents a single price update (trade) for an instrument.
    
    Attributes:
        security_id: Dhan's security ID for the instrument.
        ltp: Last traded price.
        volume: Total volume traded (cumulative for the day).
        timestamp: Tick timestamp.
        trade_type: Type of trade ("BUY" or "SELL").
        quantity: Quantity traded in this tick.
        instrument: Optional reference to the DhanInstrument.
    
    Example:
        >>> tick = DhanTick(
        ...     security_id="12345",
        ...     ltp=18050.50,
        ...     volume=1000000,
        ...     timestamp=datetime.now(),
        ...     trade_type="BUY",
        ...     quantity=100
        ... )
    """
    security_id: str
    ltp: float
    volume: int
    timestamp: datetime
    trade_type: str = "UNKNOWN"
    quantity: int = 0
    instrument: Optional[DhanInstrument] = None
    
    @property
    def notional_value(self) -> float:
        """Calculate the notional value of this tick."""
        return self.ltp * self.quantity if self.quantity > 0 else 0.0
    
    @property
    def is_buy(self) -> bool:
        """Check if this is a buy trade."""
        return self.trade_type == "BUY"
    
    @property
    def is_sell(self) -> bool:
        """Check if this is a sell trade."""
        return self.trade_type == "SELL"


# =============================================================================
# Option Entities
# =============================================================================

@dataclass(frozen=True)
class DhanOption:
    """
    Option contract with Greeks.
    
    Represents an option contract with its current market data
    and option Greeks.
    
    Attributes:
        strike: Strike price of the option.
        option_type: Type of option (CE for Call, PE for Put).
        ltp: Last traded price.
        bid: Best bid price.
        ask: Best ask price.
        oi: Open interest.
        volume: Volume traded for the day.
        iv: Implied volatility (as decimal, e.g., 0.25 for 25%).
        delta: Option delta.
        gamma: Option gamma.
        theta: Option theta (time decay per day).
        vega: Option vega.
        instrument: Optional reference to the DhanInstrument.
    
    Example:
        >>> option = DhanOption(
        ...     strike=18000.0,
        ...     option_type="CE",
        ...     ltp=150.50,
        ...     bid=150.00,
        ...     ask=151.00,
        ...     oi=500000,
        ...     volume=10000,
        ...     iv=0.18,
        ...     delta=0.55
        ... )
    """
    strike: float
    option_type: str  # "CE" or "PE"
    ltp: float
    bid: float
    ask: float
    oi: int
    volume: int
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    instrument: Optional[DhanInstrument] = None
    
    @property
    def spread(self) -> float:
        """Calculate the bid-ask spread."""
        return self.ask - self.bid
    
    @property
    def mid_price(self) -> float:
        """Calculate the mid-point between bid and ask."""
        return (self.bid + self.ask) / 2
    
    @property
    def greeks(self) -> Greeks:
        """Get Greeks value object."""
        return Greeks(
            iv=self.iv,
            delta=self.delta,
            gamma=self.gamma,
            theta=self.theta,
            vega=self.vega
        )
    
    @property
    def is_call(self) -> bool:
        """Check if this is a call option."""
        return self.option_type == "CE"
    
    @property
    def is_put(self) -> bool:
        """Check if this is a put option."""
        return self.option_type == "PE"
    
    def intrinsic_value(self, spot_price: float) -> float:
        """
        Calculate intrinsic value.
        
        Args:
            spot_price: Current spot price of the underlying.
        
        Returns:
            Intrinsic value of the option.
        """
        if self.is_call:
            return max(0.0, spot_price - self.strike)
        else:
            return max(0.0, self.strike - spot_price)
    
    def time_value(self, spot_price: float) -> float:
        """
        Calculate time value.
        
        Args:
            spot_price: Current spot price of the underlying.
        
        Returns:
            Time value of the option.
        """
        return max(0.0, self.ltp - self.intrinsic_value(spot_price))
    
    def is_itm(self, spot_price: float) -> bool:
        """
        Check if option is in-the-money.
        
        Args:
            spot_price: Current spot price of the underlying.
        
        Returns:
            True if the option is in-the-money.
        """
        return self.intrinsic_value(spot_price) > 0
    
    def is_otm(self, spot_price: float) -> bool:
        """
        Check if option is out-of-the-money.
        
        Args:
            spot_price: Current spot price of the underlying.
        
        Returns:
            True if the option is out-of-the-money.
        """
        return not self.is_itm(spot_price)
    
    def moneyness(self, spot_price: float) -> str:
        """
        Get moneyness description.
        
        Args:
            spot_price: Current spot price of the underlying.
        
        Returns:
            "ITM", "ATM", or "OTM".
        """
        intrinsic = self.intrinsic_value(spot_price)
        if abs(spot_price - self.strike) < spot_price * 0.005:
            return "ATM"
        if intrinsic > 0:
            return "ITM"
        else:
            return "OTM"


@dataclass(frozen=True)
class DhanOptionChain:
    """
    Immutable option chain.
    
    Represents a complete option chain for an underlying with
    all strikes for a specific expiry.
    
    Attributes:
        underlying: The underlying symbol (e.g., "NIFTY").
        expiry: Expiry date of the options.
        spot_price: Current spot price of the underlying.
        strikes: Dictionary mapping strike prices to DhanOption tuples (call, put).
        timestamp: When this chain was retrieved.
        step_size: Strike price step size.
    
    Example:
        >>> chain = DhanOptionChain(
        ...     underlying="NIFTY",
        ...     expiry=date(2023, 2, 23),
        ...     spot_price=18000.0,
        ...     strikes={
        ...         17900: (call_17900, put_17900),
        ...         18000: (call_18000, put_18000),
        ...         18100: (call_18100, put_18100),
        ...     },
        ...     timestamp=datetime.now()
        ... )
    """
    underlying: str
    expiry: date
    spot_price: float
    strikes: Dict[float, Tuple[DhanOption, DhanOption]]  # strike -> (call, put)
    timestamp: datetime = field(default_factory=datetime.now)
    step_size: float = 50.0
    
    @property
    def atm_strike(self) -> float:
        """Get the at-the-money strike price."""
        if not self.strikes:
            return 0.0
        # Find closest strike to spot
        return min(self.strikes.keys(), key=lambda s: abs(s - self.spot_price))
    
    @property
    def strike_prices(self) -> Tuple[float, ...]:
        """Get sorted tuple of strike prices."""
        return tuple(sorted(self.strikes.keys()))
    
    @property
    def call_count(self) -> int:
        """Get number of call options."""
        return len(self.strikes)
    
    @property
    def put_count(self) -> int:
        """Get number of put options."""
        return len(self.strikes)
    
    def get_atm(self) -> Tuple[Optional[DhanOption], Optional[DhanOption]]:
        """
        Get ATM call and put.
        
        Returns:
            Tuple of (call, put) at the ATM strike, or (None, None) if not found.
        """
        atm = self.atm_strike
        if atm in self.strikes:
            return self.strikes[atm]
        return (None, None)
    
    def get_by_strike(self, strike: float) -> Tuple[Optional[DhanOption], Optional[DhanOption]]:
        """
        Get call and put at specific strike.
        
        Args:
            strike: The strike price to look up.
        
        Returns:
            Tuple of (call, put) at the strike, or (None, None) if not found.
        """
        return self.strikes.get(strike, (None, None))
    
    def get_otm(self, distance: int = 1) -> Tuple[Optional[DhanOption], Optional[DhanOption]]:
        """
        Get OTM call and put by strike distance.
        
        Args:
            distance: Number of strikes away from ATM (default 1).
        
        Returns:
            Tuple of (otm_call, otm_put).
        """
        strikes = self.strike_prices
        if not strikes:
            return (None, None)
        
        atm_idx = strikes.index(self.atm_strike)
        
        # OTM call is below ATM (lower strike for calls)
        otm_call_idx = max(0, atm_idx - distance)
        otm_call_strike = strikes[otm_call_idx]
        
        # OTM put is above ATM (higher strike for puts)
        otm_put_idx = min(len(strikes) - 1, atm_idx + distance)
        otm_put_strike = strikes[otm_put_idx]
        
        call = self.strikes.get(otm_call_strike, (None, None))[0]
        put = self.strikes.get(otm_put_strike, (None, None))[1]
        
        return (call, put)
    
    def get_itm(self, distance: int = 1) -> Tuple[Optional[DhanOption], Optional[DhanOption]]:
        """
        Get ITM call and put by strike distance.
        
        Args:
            distance: Number of strikes away from ATM (default 1).
        
        Returns:
            Tuple of (itm_call, itm_put).
        """
        strikes = self.strike_prices
        if not strikes:
            return (None, None)
        
        atm_idx = strikes.index(self.atm_strike)
        
        # ITM call is above ATM (higher strike for calls)
        itm_call_idx = min(len(strikes) - 1, atm_idx + distance)
        itm_call_strike = strikes[itm_call_idx]
        
        # ITM put is below ATM (lower strike for puts)
        itm_put_idx = max(0, atm_idx - distance)
        itm_put_strike = strikes[itm_put_idx]
        
        call = self.strikes.get(itm_call_strike, (None, None))[0]
        put = self.strikes.get(itm_put_strike, (None, None))[1]
        
        return (call, put)
    
    def get_calls(self) -> Tuple[DhanOption, ...]:
        """Get all call options sorted by strike."""
        return tuple(self.strikes[s][0] for s in self.strike_prices if self.strikes[s][0])
    
    def get_puts(self) -> Tuple[DhanOption, ...]:
        """Get all put options sorted by strike."""
        return tuple(self.strikes[s][1] for s in self.strike_prices if self.strikes[s][1])
    
    def get_strikes_in_range(
        self,
        lower_strike: float,
        upper_strike: float
    ) -> Dict[float, Tuple[DhanOption, DhanOption]]:
        """
        Get strikes within a range.
        
        Args:
            lower_strike: Lower bound strike price.
            upper_strike: Upper bound strike price.
        
        Returns:
            Dictionary of strikes within the range.
        """
        return {
            strike: options
            for strike, options in self.strikes.items()
            if lower_strike <= strike <= upper_strike
        }
    
    def total_call_oi(self) -> int:
        """Calculate total call open interest."""
        return sum(call.oi for call, _ in self.strikes.values() if call)
    
    def total_put_oi(self) -> int:
        """Calculate total put open interest."""
        return sum(put.oi for _, put in self.strikes.values() if put)
    
    def put_call_ratio(self) -> float:
        """
        Calculate put-call ratio based on OI.
        
        Returns:
            Put-call ratio (total put OI / total call OI).
        """
        call_oi = self.total_call_oi()
        if call_oi == 0:
            return 0.0
        return self.total_put_oi() / call_oi


# =============================================================================
# Order Entities
# =============================================================================

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
