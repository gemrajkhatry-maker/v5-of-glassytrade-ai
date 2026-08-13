"""
Tests for Dhan Domain Layer.

This module tests all domain layer components:
    - Entities: DhanInstrument, DhanQuote, DhanTick, DhanOption, DhanOptionChain, DhanOrder, DhanPosition
    - Value Objects: ExchangeSegment, InstrumentType, DepthLevel, MarketDepth, OHLC, Greeks
    - Errors: Complete error hierarchy
    - Constants: API URLs, exchange segment IDs, instrument types, etc.
"""

import pytest
from datetime import datetime, date
from dataclasses import FrozenInstanceError

from brokers.broker.dhan.domain import (
    # Entities
    DhanInstrument,
    DhanQuote,
    DhanTick,
    DhanOption,
    DhanOptionChain,
    DhanOrder,
    DhanPosition,
    
    # Value Objects
    ExchangeSegment,
    InstrumentTypeEnum,
    InstrumentTypeVO,
    DepthLevel,
    MarketDepth,
    OHLC,
    Greeks,
    OptionType,
    FeedType,
    ProductType,
    OrderValidity,
    
    # Errors
    DhanError,
    DhanAuthError,
    DhanTokenExpiredError,
    DhanTokenInvalidError,
    DhanAccessDeniedError,
    DhanNetworkError,
    DhanConnectionError,
    DhanTimeoutError,
    DhanRateLimitError,
    DhanMarketDataError,
    DhanSymbolNotFoundError,
    DhanInvalidExchangeError,
    DhanHistoricalDataError,
    DhanDataError,
    DhanInvalidDataError,
    DhanMissingDataError,
    DhanOrderError,
    DhanOrderRejectedError,
    DhanInsufficientMarginError,
    DhanInvalidOrderError,
    DhanOrderNotFoundError,
    DhanSymbolError,
    DhanSymbolMappingError,
    DhanInstrumentNotFoundError,
    DhanWebSocketError,
    DhanWebSocketConnectionError,
    DhanWebSocketDisconnectedError,
    DhanWebSocketMessageError,
    DhanConfigError,
    DhanMissingConfigError,
    
    # Error utilities
    ERROR_CODE_MAP,
    get_error_by_code,
    create_error_from_response,
    
    # Constants
    API_BASE_URL,
    API_VERSION,
    WS_URL,
    API_URL,
    NSE_CASH,
    NSE_FNO,
    NSE_CURRENCY,
    BSE_CASH,
    MCX,
    BSE_FNO,
    EQUITY,
    FUTURES,
    OPTIONS,
    CURRENCY,
    COMMODITY,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELLED,
    TRANSACTION_TYPE_BUY,
    TRANSACTION_TYPE_SELL,
    PRODUCT_TYPE_INTRADAY,
    PRODUCT_TYPE_MARGIN,
    PRODUCT_TYPE_CNC,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_LIMIT,
    VALIDITY_DAY,
    VALIDITY_IMMEDIATE,
    FEED_TYPE_TICKER,
    FEED_TYPE_QUOTE,
    FEED_TYPE_FULL,
    LOT_SIZES,
    STRIKE_STEPS,
    RATE_LIMIT_DEFAULT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MAX_RETRIES,
    ERROR_CODE_INVALID_TOKEN,
    ERROR_CODE_TOKEN_EXPIRED,
    ERROR_CODE_RATE_LIMIT,
)


# =============================================================================
# Tests for DhanInstrument
# =============================================================================

class TestDhanInstrument:
    """Tests for DhanInstrument entity."""
    
    def test_create_option_instrument(
        self,
        sample_instrument: DhanInstrument
    ):
        """Test creating an option instrument."""
        assert sample_instrument.security_id == "12345"
        assert sample_instrument.trading_symbol == "NIFTY23FEB18000CE"
        assert sample_instrument.symbol == "NIFTY"
        assert sample_instrument.exchange_segment == ExchangeSegment.NSE_FNO
        assert sample_instrument.instrument_type == InstrumentTypeEnum.INDEX_OPTION
        assert sample_instrument.expiry_date == date(2023, 2, 23)
        assert sample_instrument.strike == 18000.0
        assert sample_instrument.option_type == OptionType.CALL
        assert sample_instrument.lot_size == 25
    
    def test_create_equity_instrument(
        self,
        sample_equity_instrument: DhanInstrument
    ):
        """Test creating an equity instrument."""
        assert sample_equity_instrument.security_id == "10001"
        assert sample_equity_instrument.symbol == "TCS"
        assert sample_equity_instrument.exchange_segment == ExchangeSegment.NSE_EQ
        assert sample_equity_instrument.instrument_type == InstrumentTypeEnum.EQUITY
        assert sample_equity_instrument.expiry_date is None
        assert sample_equity_instrument.strike is None
        assert sample_equity_instrument.option_type is None
    
    def test_instrument_is_frozen(self, sample_instrument: DhanInstrument):
        """Test that instrument is immutable (frozen dataclass)."""
        with pytest.raises(FrozenInstanceError):
            sample_instrument.symbol = "RELIANCE"
    
    def test_is_option_property(self, sample_instrument: DhanInstrument):
        """Test is_option property."""
        assert sample_instrument.is_option is True
    
    def test_is_future_property(
        self,
        sample_future_instrument: DhanInstrument
    ):
        """Test is_future property."""
        assert sample_future_instrument.is_future is True
        assert sample_future_instrument.is_option is False
    
    def test_is_equity_property(
        self,
        sample_equity_instrument: DhanInstrument
    ):
        """Test is_equity property."""
        assert sample_equity_instrument.is_equity is True
        assert sample_equity_instrument.is_option is False
        assert sample_equity_instrument.is_future is False
    
    def test_is_derivative_property(
        self,
        sample_instrument: DhanInstrument,
        sample_equity_instrument: DhanInstrument
    ):
        """Test is_derivative property."""
        assert sample_instrument.is_derivative is True
        assert sample_equity_instrument.is_derivative is False
    
    def test_is_call_put_properties(self, sample_instrument: DhanInstrument):
        """Test is_call and is_put properties."""
        assert sample_instrument.is_call is True
        assert sample_instrument.is_put is False
        
        # Create put option
        put_instrument = DhanInstrument(
            security_id="12346",
            trading_symbol="NIFTY23FEB18000PE",
            symbol="NIFTY",
            exchange_segment=ExchangeSegment.NSE_FNO,
            instrument_type=InstrumentTypeEnum.INDEX_OPTION,
            option_type=OptionType.PUT,
        )
        assert put_instrument.is_call is False
        assert put_instrument.is_put is True
    
    def test_display_name(self, sample_instrument: DhanInstrument):
        """Test display_name property."""
        assert sample_instrument.display_name == "NIFTY23FEB18000CE"
    
    def test_str_representation(self, sample_instrument: DhanInstrument):
        """Test string representation."""
        assert str(sample_instrument) == "NIFTY23FEB18000CE"
    
    def test_repr_representation(self, sample_instrument: DhanInstrument):
        """Test repr representation."""
        repr_str = repr(sample_instrument)
        assert "DhanInstrument" in repr_str
        assert "12345" in repr_str
        assert "NIFTY23FEB18000CE" in repr_str


# =============================================================================
# Tests for DhanQuote
# =============================================================================

class TestDhanQuote:
    """Tests for DhanQuote entity."""
    
    def test_create_quote(self, sample_quote: DhanQuote):
        """Test creating a quote."""
        assert sample_quote.security_id == "12345"
        assert sample_quote.ltp == 18050.50
        assert sample_quote.open == 18000.00
        assert sample_quote.high == 18100.00
        assert sample_quote.low == 17950.00
        assert sample_quote.close == 17980.00
        assert sample_quote.volume == 1000000
        assert sample_quote.bid == 18050.00
        assert sample_quote.ask == 18051.00
    
    def test_quote_is_frozen(self, sample_quote: DhanQuote):
        """Test that quote is immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_quote.ltp = 20000.00
    
    def test_spread_property(self, sample_quote: DhanQuote):
        """Test spread calculation."""
        assert sample_quote.spread == 1.00
    
    def test_mid_price_property(self, sample_quote: DhanQuote):
        """Test mid price calculation."""
        assert sample_quote.mid_price == 18050.50
    
    def test_change_properties(self, sample_quote: DhanQuote):
        """Test change and change_percent properties."""
        assert sample_quote.change == 70.50  # 18050.50 - 17980.00
        assert abs(sample_quote.change_percent - 0.3921) < 0.01
    
    def test_range_property(self, sample_quote: DhanQuote):
        """Test range calculation."""
        assert sample_quote.range == 150.00  # 18100 - 17950
    
    def test_ohlc_property(self, sample_quote: DhanQuote):
        """Test OHLC value object property."""
        ohlc = sample_quote.ohlc
        assert isinstance(ohlc, OHLC)
        assert ohlc.open == 18000.00
        assert ohlc.high == 18100.00
        assert ohlc.low == 17950.00
        assert ohlc.close == 18050.50  # LTP
    
    def test_best_bid_ask_quantity(self, sample_quote: DhanQuote):
        """Test best bid/ask quantity properties."""
        assert sample_quote.best_bid_quantity == 500
        assert sample_quote.best_ask_quantity == 500


# =============================================================================
# Tests for DhanTick
# =============================================================================

class TestDhanTick:
    """Tests for DhanTick entity."""
    
    def test_create_tick(self, sample_tick: DhanTick):
        """Test creating a tick."""
        assert sample_tick.security_id == "12345"
        assert sample_tick.ltp == 18050.50
        assert sample_tick.volume == 1000000
        assert sample_tick.trade_type == "BUY"
        assert sample_tick.quantity == 100
    
    def test_tick_is_frozen(self, sample_tick: DhanTick):
        """Test that tick is immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_tick.ltp = 20000.00
    
    def test_notional_value_property(self, sample_tick: DhanTick):
        """Test notional value calculation."""
        assert sample_tick.notional_value == 1805050.00  # 18050.50 * 100
    
    def test_is_buy_sell_properties(self, sample_tick: DhanTick):
        """Test is_buy and is_sell properties."""
        assert sample_tick.is_buy is True
        assert sample_tick.is_sell is False
        
        sell_tick = DhanTick(
            security_id="12345",
            ltp=18050.50,
            volume=1000000,
            timestamp=datetime.now(),
            trade_type="SELL",
        )
        assert sell_tick.is_buy is False
        assert sell_tick.is_sell is True


# =============================================================================
# Tests for DhanOption
# =============================================================================

class TestDhanOption:
    """Tests for DhanOption entity."""
    
    def test_create_option(self, sample_option: DhanOption):
        """Test creating an option."""
        assert sample_option.strike == 18000.0
        assert sample_option.option_type == "CE"
        assert sample_option.ltp == 150.50
        assert sample_option.iv == 0.18
        assert sample_option.delta == 0.55
    
    def test_option_is_frozen(self, sample_option: DhanOption):
        """Test that option is immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_option.ltp = 200.00
    
    def test_is_call_put_properties(self, sample_option: DhanOption):
        """Test is_call and is_put properties."""
        assert sample_option.is_call is True
        assert sample_option.is_put is False
    
    def test_intrinsic_value_call(self, sample_option: DhanOption):
        """Test intrinsic value for call option."""
        # Call with spot 18100, strike 18000
        intrinsic = sample_option.intrinsic_value(18100.0)
        assert intrinsic == 100.0
        
        # OTM call
        intrinsic_otm = sample_option.intrinsic_value(17900.0)
        assert intrinsic_otm == 0.0
    
    def test_intrinsic_value_put(self):
        """Test intrinsic value for put option."""
        put_option = DhanOption(
            strike=18000.0,
            option_type="PE",
            ltp=150.50,
            bid=150.00,
            ask=151.00,
            oi=500000,
            volume=10000,
        )
        
        # Put with spot 17900, strike 18000
        intrinsic = put_option.intrinsic_value(17900.0)
        assert intrinsic == 100.0
        
        # OTM put
        intrinsic_otm = put_option.intrinsic_value(18100.0)
        assert intrinsic_otm == 0.0
    
    def test_time_value(self, sample_option: DhanOption):
        """Test time value calculation."""
        # Spot at 18000, intrinsic = 0
        time_value = sample_option.time_value(18000.0)
        assert time_value == 150.50  # Full premium is time value
        
        # Spot at 18100, intrinsic = 100
        time_value_itm = sample_option.time_value(18100.0)
        assert time_value_itm == 50.50  # 150.50 - 100
    
    def test_moneyness(self, sample_option: DhanOption):
        """Test moneyness calculation."""
        # ITM call
        assert sample_option.moneyness(18100.0) == "ITM"
        
        # OTM call
        assert sample_option.moneyness(17900.0) == "OTM"
        
        # ATM call (within 0.5%)
        assert sample_option.moneyness(18050.0) == "ATM"
    
    def test_greeks_property(self, sample_option: DhanOption):
        """Test Greeks value object property."""
        greeks = sample_option.greeks
        assert isinstance(greeks, Greeks)
        assert greeks.iv == 0.18
        assert greeks.delta == 0.55


# =============================================================================
# Tests for DhanOptionChain
# =============================================================================

class TestDhanOptionChain:
    """Tests for DhanOptionChain entity."""
    
    def test_create_option_chain(self, sample_option_chain: DhanOptionChain):
        """Test creating an option chain."""
        assert sample_option_chain.underlying == "NIFTY"
        assert sample_option_chain.expiry == date(2023, 2, 23)
        assert sample_option_chain.spot_price == 18000.0
        assert len(sample_option_chain.strikes) == 3
    
    def test_atm_strike_property(self, sample_option_chain: DhanOptionChain):
        """Test ATM strike calculation."""
        assert sample_option_chain.atm_strike == 18000.0
    
    def test_strike_prices_property(self, sample_option_chain: DhanOptionChain):
        """Test strike prices property."""
        strikes = sample_option_chain.strike_prices
        assert strikes == (17900.0, 18000.0, 18100.0)
    
    def test_get_atm(self, sample_option_chain: DhanOptionChain):
        """Test get_atm method."""
        call, put = sample_option_chain.get_atm()
        assert call is not None
        assert put is not None
        assert call.strike == 18000.0
        assert put.strike == 18000.0
    
    def test_get_by_strike(self, sample_option_chain: DhanOptionChain):
        """Test get_by_strike method."""
        call, put = sample_option_chain.get_by_strike(17900.0)
        assert call is not None
        assert put is not None
        assert call.strike == 17900.0
    
    def test_get_otm(self, sample_option_chain: DhanOptionChain):
        """Test get_otm method."""
        otm_call, otm_put = sample_option_chain.get_otm(distance=1)
        # OTM call is below ATM (lower strike)
        assert otm_call.strike == 17900.0
        # OTM put is above ATM (higher strike)
        assert otm_put.strike == 18100.0
    
    def test_get_itm(self, sample_option_chain: DhanOptionChain):
        """Test get_itm method."""
        itm_call, itm_put = sample_option_chain.get_itm(distance=1)
        # ITM call is above ATM (higher strike)
        assert itm_call.strike == 18100.0
        # ITM put is below ATM (lower strike)
        assert itm_put.strike == 17900.0
    
    def test_get_calls_puts(self, sample_option_chain: DhanOptionChain):
        """Test get_calls and get_puts methods."""
        calls = sample_option_chain.get_calls()
        puts = sample_option_chain.get_puts()
        
        assert len(calls) == 3
        assert len(puts) == 3
    
    def test_total_oi(self, sample_option_chain: DhanOptionChain):
        """Test total OI calculations."""
        call_oi = sample_option_chain.total_call_oi()
        put_oi = sample_option_chain.total_put_oi()
        
        assert call_oi == 1500000  # 3 * 500000
        assert put_oi == 1200000  # 3 * 400000
    
    def test_put_call_ratio(self, sample_option_chain: DhanOptionChain):
        """Test put-call ratio calculation."""
        pcr = sample_option_chain.put_call_ratio()
        assert abs(pcr - 0.8) < 0.01  # 1200000 / 1500000


# =============================================================================
# Tests for DhanOrder
# =============================================================================

class TestDhanOrder:
    """Tests for DhanOrder entity."""
    
    def test_create_order(self, sample_order: DhanOrder):
        """Test creating an order."""
        assert sample_order.order_id == "ORDER123"
        assert sample_order.security_id == "12345"
        assert sample_order.order_type == "LIMIT"
        assert sample_order.transaction_type == "BUY"
        assert sample_order.quantity == 50
        assert sample_order.price == 150.00
        assert sample_order.status == "PENDING"
    
    def test_order_is_frozen(self, sample_order: DhanOrder):
        """Test that order is immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_order.status = "TRADED"
    
    def test_is_buy_sell_properties(self, sample_order: DhanOrder):
        """Test is_buy and is_sell properties."""
        assert sample_order.is_buy is True
        assert sample_order.is_sell is False
    
    def test_is_market_limit_properties(self):
        """Test is_market and is_limit properties."""
        market_order = DhanOrder(
            order_id="ORDER_MKT",
            security_id="12345",
            trading_symbol="NIFTY23FEB18000CE",
            order_type="MARKET",
            transaction_type="BUY",
            quantity=50,
        )
        assert market_order.is_market is True
        assert market_order.is_limit is False
        
        limit_order = DhanOrder(
            order_id="ORDER_LMT",
            security_id="12345",
            trading_symbol="NIFTY23FEB18000CE",
            order_type="LIMIT",
            transaction_type="BUY",
            quantity=50,
            price=150.00,
        )
        assert limit_order.is_limit is True
        assert limit_order.is_market is False
    
    def test_is_stop_loss_property(self):
        """Test is_stop_loss property."""
        sl_order = DhanOrder(
            order_id="ORDER_SL",
            security_id="12345",
            trading_symbol="NIFTY23FEB18000CE",
            order_type="SL",
            transaction_type="BUY",
            quantity=50,
            trigger_price=145.00,
        )
        assert sl_order.is_stop_loss is True
    
    def test_status_properties(self, sample_order: DhanOrder, sample_filled_order: DhanOrder):
        """Test status-related properties."""
        assert sample_order.is_pending is True
        assert sample_order.is_complete is False
        assert sample_order.is_filled is False
        
        assert sample_filled_order.is_pending is False
        assert sample_filled_order.is_complete is True
        assert sample_filled_order.is_filled is True
    
    def test_pending_quantity_property(self, sample_order: DhanOrder, sample_filled_order: DhanOrder):
        """Test pending_quantity property."""
        assert sample_order.pending_quantity == 50
        assert sample_filled_order.pending_quantity == 0
    
    def test_fill_percentage_property(self, sample_order: DhanOrder, sample_filled_order: DhanOrder):
        """Test fill_percentage property."""
        assert sample_order.fill_percentage == 0.0
        assert sample_filled_order.fill_percentage == 100.0


# =============================================================================
# Tests for DhanPosition
# =============================================================================

class TestDhanPosition:
    """Tests for DhanPosition entity."""
    
    def test_create_position(self, sample_position: DhanPosition):
        """Test creating a position."""
        assert sample_position.security_id == "12345"
        assert sample_position.trading_symbol == "NIFTY23FEB18000CE"
        assert sample_position.quantity == 50
        assert sample_position.average_price == 150.00
        assert sample_position.ltp == 155.00
        assert sample_position.pnl == 250.00
    
    def test_position_is_frozen(self, sample_position: DhanPosition):
        """Test that position is immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_position.quantity = 100
    
    def test_is_long_short_flat_properties(self):
        """Test is_long, is_short, is_flat properties."""
        long_pos = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=50,
            average_price=100.0,
        )
        assert long_pos.is_long is True
        assert long_pos.is_short is False
        assert long_pos.is_flat is False
        
        short_pos = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=-50,
            average_price=100.0,
        )
        assert short_pos.is_long is False
        assert short_pos.is_short is True
        assert short_pos.is_flat is False
        
        flat_pos = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=0,
            average_price=100.0,
        )
        assert flat_pos.is_flat is True
    
    def test_abs_quantity_property(self):
        """Test abs_quantity property."""
        long_pos = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=50,
            average_price=100.0,
        )
        assert long_pos.abs_quantity == 50
        
        short_pos = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=-50,
            average_price=100.0,
        )
        assert short_pos.abs_quantity == 50
    
    def test_notional_value_property(self, sample_position: DhanPosition):
        """Test notional_value property."""
        assert sample_position.notional_value == 7750.00  # 50 * 155.00
    
    def test_investment_value_property(self, sample_position: DhanPosition):
        """Test investment_value property."""
        assert sample_position.investment_value == 7500.00  # 50 * 150.00


# =============================================================================
# Tests for Value Objects
# =============================================================================

class TestExchangeSegment:
    """Tests for ExchangeSegment value object."""
    
    def test_predefined_segments(self):
        """Test predefined exchange segments."""
        assert ExchangeSegment.NSE_EQ.name == "NSE_EQ"
        assert ExchangeSegment.NSE_EQ.code == NSE_CASH
        
        assert ExchangeSegment.NSE_FNO.name == "NSE_FNO"
        assert ExchangeSegment.NSE_FNO.code == NSE_FNO
    
    def test_from_code(self):
        """Test from_code class method."""
        segment = ExchangeSegment.from_code(NSE_FNO)
        assert segment == ExchangeSegment.NSE_FNO
        
        segment = ExchangeSegment.from_code(NSE_CASH)
        assert segment == ExchangeSegment.NSE_EQ
        
        # Unknown code
        assert ExchangeSegment.from_code(999) is None
    
    def test_from_name(self):
        """Test from_name class method."""
        segment = ExchangeSegment.from_name("NSE_FNO")
        assert segment == ExchangeSegment.NSE_FNO
        
        segment = ExchangeSegment.from_name("nse_fno")  # Case insensitive
        assert segment == ExchangeSegment.NSE_FNO
        
        # Unknown name
        assert ExchangeSegment.from_name("UNKNOWN") is None
    
    def test_is_equity_derivatives_properties(self):
        """Test is_equity and is_derivatives properties."""
        assert ExchangeSegment.NSE_EQ.is_equity is True
        assert ExchangeSegment.NSE_EQ.is_derivatives is False
        
        assert ExchangeSegment.NSE_FNO.is_equity is False
        assert ExchangeSegment.NSE_FNO.is_derivatives is True
        
        assert ExchangeSegment.MCX.is_commodity is True


class TestInstrumentTypeEnum:
    """Tests for InstrumentTypeEnum enum."""
    
    def test_enum_values(self):
        """Test enum values."""
        assert InstrumentTypeEnum.EQUITY.value == "EQ"
        assert InstrumentTypeEnum.INDEX_OPTION.value == "OPTIDX"
        assert InstrumentTypeEnum.INDEX_FUTURE.value == "FUTIDX"
    
    def test_is_future_property(self):
        """Test is_future property."""
        assert InstrumentTypeEnum.INDEX_FUTURE.is_future is True
        assert InstrumentTypeEnum.STOCK_FUTURE.is_future is True
        assert InstrumentTypeEnum.EQUITY.is_future is False
    
    def test_is_option_property(self):
        """Test is_option property."""
        assert InstrumentTypeEnum.INDEX_OPTION.is_option is True
        assert InstrumentTypeEnum.STOCK_OPTION.is_option is True
        assert InstrumentTypeEnum.EQUITY.is_option is False
    
    def test_is_equity_property(self):
        """Test is_equity property."""
        assert InstrumentTypeEnum.EQUITY.is_equity is True
        assert InstrumentTypeEnum.INDEX_OPTION.is_equity is False


class TestDepthLevel:
    """Tests for DepthLevel value object."""
    
    def test_create_depth_level(self):
        """Test creating a depth level."""
        level = DepthLevel(price=100.50, quantity=1000, orders=5)
        assert level.price == 100.50
        assert level.quantity == 1000
        assert level.orders == 5
    
    def test_average_quantity_per_order(self):
        """Test average_quantity_per_order property."""
        level = DepthLevel(price=100.50, quantity=1000, orders=5)
        assert level.average_quantity_per_order == 200.0
        
        # Zero orders
        zero_level = DepthLevel(price=100.50, quantity=1000, orders=0)
        assert zero_level.average_quantity_per_order == 0.0
    
    def test_notional_value(self):
        """Test notional_value property."""
        level = DepthLevel(price=100.50, quantity=1000, orders=5)
        assert level.notional_value == 100500.0


class TestMarketDepth:
    """Tests for MarketDepth value object."""
    
    def test_create_market_depth(self):
        """Test creating market depth."""
        bid_levels = (
            DepthLevel(price=100.00, quantity=500, orders=3),
            DepthLevel(price=99.50, quantity=1000, orders=5),
        )
        ask_levels = (
            DepthLevel(price=100.50, quantity=400, orders=2),
            DepthLevel(price=101.00, quantity=800, orders=4),
        )
        
        depth = MarketDepth(bid_levels=bid_levels, ask_levels=ask_levels)
        assert len(depth.bid_levels) == 2
        assert len(depth.ask_levels) == 2
    
    def test_best_bid_ask(self):
        """Test best_bid and best_ask properties."""
        bid_levels = (DepthLevel(price=100.00, quantity=500, orders=3),)
        ask_levels = (DepthLevel(price=100.50, quantity=400, orders=2),)
        
        depth = MarketDepth(bid_levels=bid_levels, ask_levels=ask_levels)
        
        assert depth.best_bid.price == 100.00
        assert depth.best_ask.price == 100.50
    
    def test_spread_property(self):
        """Test spread property."""
        bid_levels = (DepthLevel(price=100.00, quantity=500, orders=3),)
        ask_levels = (DepthLevel(price=100.50, quantity=400, orders=2),)
        
        depth = MarketDepth(bid_levels=bid_levels, ask_levels=ask_levels)
        assert depth.spread == 0.50
    
    def test_mid_price_property(self):
        """Test mid_price property."""
        bid_levels = (DepthLevel(price=100.00, quantity=500, orders=3),)
        ask_levels = (DepthLevel(price=100.50, quantity=400, orders=2),)
        
        depth = MarketDepth(bid_levels=bid_levels, ask_levels=ask_levels)
        assert depth.mid_price == 100.25
    
    def test_total_quantities(self):
        """Test total_bid_quantity and total_ask_quantity properties."""
        bid_levels = (
            DepthLevel(price=100.00, quantity=500, orders=3),
            DepthLevel(price=99.50, quantity=1000, orders=5),
        )
        ask_levels = (
            DepthLevel(price=100.50, quantity=400, orders=2),
            DepthLevel(price=101.00, quantity=800, orders=4),
        )
        
        depth = MarketDepth(bid_levels=bid_levels, ask_levels=ask_levels)
        assert depth.total_bid_quantity == 1500
        assert depth.total_ask_quantity == 1200


class TestOHLC:
    """Tests for OHLC value object."""
    
    def test_create_ohlc(self):
        """Test creating OHLC."""
        ohlc = OHLC(open=100.0, high=105.0, low=98.0, close=103.0)
        assert ohlc.open == 100.0
        assert ohlc.high == 105.0
        assert ohlc.low == 98.0
        assert ohlc.close == 103.0
    
    def test_range_property(self):
        """Test range property."""
        ohlc = OHLC(open=100.0, high=105.0, low=98.0, close=103.0)
        assert ohlc.range == 7.0
    
    def test_body_size_property(self):
        """Test body_size property."""
        ohlc = OHLC(open=100.0, high=105.0, low=98.0, close=103.0)
        assert ohlc.body_size == 3.0
    
    def test_is_bullish_bearish(self):
        """Test is_bullish and is_bearish properties."""
        bullish = OHLC(open=100.0, high=105.0, low=98.0, close=103.0)
        assert bullish.is_bullish is True
        assert bullish.is_bearish is False
        
        bearish = OHLC(open=103.0, high=105.0, low=98.0, close=100.0)
        assert bearish.is_bearish is True
        assert bearish.is_bullish is False


class TestGreeks:
    """Tests for Greeks value object."""
    
    def test_create_greeks(self):
        """Test creating Greeks."""
        greeks = Greeks(iv=0.25, delta=0.5, gamma=0.02, theta=-5.0, vega=10.0)
        assert greeks.iv == 0.25
        assert greeks.delta == 0.5
        assert greeks.gamma == 0.02
        assert greeks.theta == -5.0
        assert greeks.vega == 10.0
    
    def test_is_complete_property(self):
        """Test is_complete property."""
        complete = Greeks(iv=0.25, delta=0.5, gamma=0.02, theta=-5.0, vega=10.0)
        assert complete.is_complete is True
        
        incomplete = Greeks(iv=0.25, delta=0.5)
        assert incomplete.is_complete is False


class TestFeedType:
    """Tests for FeedType enum."""
    
    def test_enum_values(self):
        """Test enum values."""
        assert FeedType.TICKER.value == "TICKER"
        assert FeedType.QUOTE.value == "QUOTE"
        assert FeedType.FULL.value == "FULL"
    
    def test_code_property(self):
        """Test code property."""
        assert FeedType.TICKER.code == FEED_TYPE_TICKER
        assert FeedType.QUOTE.code == FEED_TYPE_QUOTE
        assert FeedType.FULL.code == FEED_TYPE_FULL


# =============================================================================
# Tests for Errors
# =============================================================================

class TestDhanError:
    """Tests for base DhanError."""
    
    def test_create_error(self):
        """Test creating a basic error."""
        error = DhanError("Something went wrong")
        assert error.message == "Something went wrong"
        assert error.code is None
        assert error.details == {}
    
    def test_create_error_with_code(self):
        """Test creating error with code."""
        error = DhanError("Error", code="ERR-001")
        assert error.code == "ERR-001"
        assert str(error) == "[ERR-001] Error"
    
    def test_create_error_with_details(self):
        """Test creating error with details."""
        error = DhanError("Error", details={"key": "value"})
        assert error.details == {"key": "value"}
    
    def test_str_representation(self):
        """Test string representation."""
        error = DhanError("Test error", code="TEST-001")
        assert str(error) == "[TEST-001] Test error"
        
        error_no_code = DhanError("Test error")
        assert str(error_no_code) == "Test error"


class TestAuthErrors:
    """Tests for authentication errors."""
    
    def test_token_expired_error(self):
        """Test DhanTokenExpiredError."""
        error = DhanTokenExpiredError(expired_at="2023-01-01")
        assert error.code == "DH-1002"
        assert error.expired_at == "2023-01-01"
    
    def test_token_invalid_error(self):
        """Test DhanTokenInvalidError."""
        error = DhanTokenInvalidError()
        assert error.code == "DH-1001"
    
    def test_access_denied_error(self):
        """Test DhanAccessDeniedError."""
        error = DhanAccessDeniedError()
        assert error.code == "DH-1003"


class TestNetworkErrors:
    """Tests for network errors."""
    
    def test_connection_error(self):
        """Test DhanConnectionError."""
        error = DhanConnectionError()
        assert error.code == "DH-3003"
    
    def test_timeout_error(self):
        """Test DhanTimeoutError."""
        error = DhanTimeoutError(timeout_seconds=30.0)
        assert error.code == "DH-3002"
        assert error.timeout_seconds == 30.0
    
    def test_rate_limit_error(self):
        """Test DhanRateLimitError."""
        error = DhanRateLimitError(retry_after=60)
        assert error.code == "DH-3001"
        assert error.retry_after == 60


class TestOrderErrors:
    """Tests for order errors."""
    
    def test_order_rejected_error(self):
        """Test DhanOrderRejectedError."""
        error = DhanOrderRejectedError(
            order_id="ORDER123",
            rejection_reason="Insufficient margin"
        )
        assert error.code == "DH-5001"
        assert error.order_id == "ORDER123"
        assert error.rejection_reason == "Insufficient margin"
    
    def test_insufficient_margin_error(self):
        """Test DhanInsufficientMarginError."""
        error = DhanInsufficientMarginError(
            required_margin=100000.0,
            available_margin=50000.0
        )
        assert error.code == "DH-5002"
        assert error.required_margin == 100000.0
        assert error.available_margin == 50000.0
    
    def test_order_not_found_error(self):
        """Test DhanOrderNotFoundError."""
        error = DhanOrderNotFoundError(order_id="ORDER123")
        assert error.code == "DH-5004"
        assert error.order_id == "ORDER123"


class TestErrorUtilities:
    """Tests for error utility functions."""
    
    def test_error_code_map(self):
        """Test ERROR_CODE_MAP contains expected mappings."""
        assert ERROR_CODE_MAP["DH-1001"] == DhanTokenInvalidError
        assert ERROR_CODE_MAP["DH-1002"] == DhanTokenExpiredError
        assert ERROR_CODE_MAP["DH-3001"] == DhanRateLimitError
    
    def test_get_error_by_code(self):
        """Test get_error_by_code function."""
        error_class = get_error_by_code("DH-1001")
        assert error_class == DhanTokenInvalidError
        
        # Unknown code
        assert get_error_by_code("UNKNOWN") is None
    
    def test_create_error_from_response(self):
        """Test create_error_from_response function."""
        # Known error code
        error = create_error_from_response(
            code="DH-1001",
            message="Invalid token",
            details={"url": "/api/test"}
        )
        assert isinstance(error, DhanTokenInvalidError)
        assert error.message == "Invalid token"
        
        # Unknown error code
        error = create_error_from_response(
            code="UNKNOWN",
            message="Unknown error"
        )
        assert isinstance(error, DhanError)
        assert error.code == "UNKNOWN"


# =============================================================================
# Tests for Constants
# =============================================================================

class TestConstants:
    """Tests for domain constants."""
    
    def test_api_urls(self):
        """Test API URL constants."""
        assert API_BASE_URL == "https://api.dhan.co"
        assert API_VERSION == "v2"
        assert API_URL == "https://api.dhan.co/v2"
        assert WS_URL == "wss://api-feed.dhan.co"
    
    def test_exchange_segment_ids(self):
        """Test exchange segment ID constants."""
        assert NSE_CASH == 1
        assert NSE_FNO == 2
        assert NSE_CURRENCY == 3
        assert BSE_CASH == 4
        assert MCX == 5
        assert BSE_FNO == 12
    
    def test_instrument_type_ids(self):
        """Test instrument type ID constants."""
        assert EQUITY == 1
        assert FUTURES == 2
        assert OPTIONS == 3
        assert CURRENCY == 4
        assert COMMODITY == 5
    
    def test_order_status_constants(self):
        """Test order status constants."""
        assert ORDER_STATUS_PENDING == "PENDING"
        assert ORDER_STATUS_FILLED == "TRADED"
        assert ORDER_STATUS_CANCELLED == "CANCELLED"
    
    def test_transaction_type_constants(self):
        """Test transaction type constants."""
        assert TRANSACTION_TYPE_BUY == "BUY"
        assert TRANSACTION_TYPE_SELL == "SELL"
    
    def test_product_type_constants(self):
        """Test product type constants."""
        assert PRODUCT_TYPE_INTRADAY == "I"
        assert PRODUCT_TYPE_MARGIN == "M"
        assert PRODUCT_TYPE_CNC == "C"
    
    def test_order_type_constants(self):
        """Test order type constants."""
        assert ORDER_TYPE_MARKET == "MARKET"
        assert ORDER_TYPE_LIMIT == "LIMIT"
    
    def test_validity_constants(self):
        """Test validity constants."""
        assert VALIDITY_DAY == "DAY"
        assert VALIDITY_IMMEDIATE == "IOC"
    
    def test_feed_type_constants(self):
        """Test feed type constants."""
        assert FEED_TYPE_TICKER == 15
        assert FEED_TYPE_QUOTE == 17
        assert FEED_TYPE_FULL == 21
    
    def test_lot_sizes(self):
        """Test lot sizes dictionary (exchange-authoritative Aug 2026)."""
        assert LOT_SIZES["NIFTY"] == 65
        assert LOT_SIZES["BANKNIFTY"] == 30
        assert LOT_SIZES["FINNIFTY"] == 60
        assert "RELIANCE" in LOT_SIZES
    
    def test_strike_steps(self):
        """Test strike steps dictionary."""
        assert STRIKE_STEPS["NIFTY"] == 50.0
        assert STRIKE_STEPS["BANKNIFTY"] == 100.0
        assert STRIKE_STEPS["DEFAULT"] == 5.0
    
    def test_rate_limit_constants(self):
        """Test rate limit constants."""
        assert RATE_LIMIT_DEFAULT == 10
        assert DEFAULT_TIMEOUT_SECONDS == 10.0
        assert DEFAULT_MAX_RETRIES == 3
    
    def test_error_code_constants(self):
        """Test error code constants."""
        assert ERROR_CODE_INVALID_TOKEN == "DH-1001"
        assert ERROR_CODE_TOKEN_EXPIRED == "DH-1002"
        assert ERROR_CODE_RATE_LIMIT == "DH-3001"


# =============================================================================
# Tests for Error Hierarchy
# =============================================================================

class TestErrorHierarchy:
    """Tests for error class hierarchy."""
    
    def test_auth_errors_inherit_from_dhan_auth_error(self):
        """Test auth error inheritance."""
        assert issubclass(DhanTokenExpiredError, DhanAuthError)
        assert issubclass(DhanTokenInvalidError, DhanAuthError)
        assert issubclass(DhanAccessDeniedError, DhanAuthError)
        assert issubclass(DhanAuthError, DhanError)
    
    def test_network_errors_inherit_from_dhan_network_error(self):
        """Test network error inheritance."""
        assert issubclass(DhanConnectionError, DhanNetworkError)
        assert issubclass(DhanTimeoutError, DhanNetworkError)
        assert issubclass(DhanRateLimitError, DhanNetworkError)
        assert issubclass(DhanNetworkError, DhanError)
    
    def test_market_data_errors_inherit_from_dhan_market_data_error(self):
        """Test market data error inheritance."""
        assert issubclass(DhanSymbolNotFoundError, DhanMarketDataError)
        assert issubclass(DhanInvalidExchangeError, DhanMarketDataError)
        assert issubclass(DhanMarketDataError, DhanError)
    
    def test_order_errors_inherit_from_dhan_order_error(self):
        """Test order error inheritance."""
        assert issubclass(DhanOrderRejectedError, DhanOrderError)
        assert issubclass(DhanInsufficientMarginError, DhanOrderError)
        assert issubclass(DhanInvalidOrderError, DhanOrderError)
        assert issubclass(DhanOrderNotFoundError, DhanOrderError)
        assert issubclass(DhanOrderError, DhanError)
    
    def test_websocket_errors_inherit_from_dhan_web_socket_error(self):
        """Test WebSocket error inheritance."""
        assert issubclass(DhanWebSocketConnectionError, DhanWebSocketError)
        assert issubclass(DhanWebSocketDisconnectedError, DhanWebSocketError)
        assert issubclass(DhanWebSocketMessageError, DhanWebSocketError)
        assert issubclass(DhanWebSocketError, DhanError)
