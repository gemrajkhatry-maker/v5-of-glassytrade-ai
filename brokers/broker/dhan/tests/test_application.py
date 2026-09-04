"""
Tests for Dhan Application Layer.

This module tests all application layer components:
    - DhanConfig: Configuration dataclass
    - DhanConverter: Data conversion utilities
"""

import os
import pytest
from datetime import datetime, date
from unittest.mock import patch

from brokers.broker.dhan.application import DhanConfig, DhanConverter

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
    OptionType,
    DepthLevel,
)

from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OptionChain,
)

from brokers.broker.types import (
    Exchange,
    OrderSide,
    OrderType,
    OrderStatus,
)


# =============================================================================
# Tests for DhanConfig
# =============================================================================

class TestDhanConfig:
    """Tests for DhanConfig dataclass."""
    
    def test_create_config(self, dhan_config):
        """Test creating DhanConfig with explicit values."""
        assert dhan_config.client_id == "CLIENT123"
        assert dhan_config.access_token == "test_access_token_12345"
        assert dhan_config.base_url == "https://api.dhan.co"
        assert dhan_config.ws_url == "wss://api.dhan.co/ws"
        assert dhan_config.timeout == 10.0
        assert dhan_config.max_retries == 3
    
    def test_config_is_frozen(self, dhan_config):
        """Test that DhanConfig is immutable (frozen dataclass)."""
        with pytest.raises(Exception):  # FrozenInstanceError
            dhan_config.client_id = "NEW_CLIENT"
    
    def test_config_defaults(self):
        """Test DhanConfig default values."""
        config = DhanConfig(
            client_id="CLIENT123",
            access_token="test_token",
        )
        
        # Should have default values
        assert config.base_url == "https://api.dhan.co/v2"
        assert config.ws_url == "wss://api-feed.dhan.co"
        assert config.timeout == 10.0
        assert config.max_retries == 3
    
    def test_from_env_success(self, clean_env):
        """Test creating DhanConfig from environment variables."""
        os.environ["DHAN_CLIENT_ID"] = "ENV_CLIENT"
        os.environ["DHAN_ACCESS_TOKEN"] = "env_token_123"
        
        config = DhanConfig.from_env()
        
        assert config.client_id == "ENV_CLIENT"
        assert config.access_token == "env_token_123"
    
    def test_from_env_with_custom_prefix(self, clean_env):
        """Test creating DhanConfig with custom environment prefix."""
        os.environ["CUSTOM_CLIENT_ID"] = "CUSTOM_CLIENT"
        os.environ["CUSTOM_ACCESS_TOKEN"] = "custom_token"
        
        config = DhanConfig.from_env(prefix="CUSTOM_")
        
        assert config.client_id == "CUSTOM_CLIENT"
        assert config.access_token == "custom_token"
    
    def test_from_env_missing_client_id(self, clean_env, monkeypatch):
        """Test from_env raises error when CLIENT_ID is missing."""
        monkeypatch.setattr(DhanConfig, "_load_dotenv", classmethod(lambda cls: None))
        os.environ["DHAN_ACCESS_TOKEN"] = "token"

        with pytest.raises(ValueError) as exc_info:
            DhanConfig.from_env()

        assert "CLIENT_ID" in str(exc_info.value)

    def test_from_env_missing_access_token(self, clean_env, monkeypatch):
        """Test from_env raises error when ACCESS_TOKEN is missing (and the
        TOTP auto-generation fallback is unavailable)."""
        monkeypatch.setattr(DhanConfig, "_load_dotenv", classmethod(lambda cls: None))
        os.environ["DHAN_CLIENT_ID"] = "CLIENT123"
        # from_env substitutes TOTP_SECRET+PIN for a missing ACCESS_TOKEN —
        # clear them so this test exercises the true missing-credential path.
        os.environ.pop("TOTP_SECRET", None)
        os.environ.pop("PIN", None)

        with pytest.raises(ValueError) as exc_info:
            DhanConfig.from_env()

        assert "ACCESS_TOKEN" in str(exc_info.value)
    
    def test_from_env_optional_values(self, clean_env):
        """Test from_env with optional environment variables."""
        os.environ["DHAN_CLIENT_ID"] = "CLIENT123"
        os.environ["DHAN_ACCESS_TOKEN"] = "token"
        os.environ["DHAN_TIMEOUT"] = "30.0"
        os.environ["DHAN_MAX_RETRIES"] = "5"
        
        config = DhanConfig.from_env()
        
        assert config.timeout == 30.0
        assert config.max_retries == 5
    
    def test_with_access_token(self, dhan_config):
        """Test with_access_token method creates new config."""
        new_config = dhan_config.with_access_token("new_token_456")
        
        # Original should be unchanged
        assert dhan_config.access_token == "test_access_token_12345"
        
        # New config should have new token
        assert new_config.access_token == "new_token_456"
        assert new_config.client_id == dhan_config.client_id
        assert new_config.base_url == dhan_config.base_url
    
    def test_repr_masks_token(self, dhan_config):
        """Test that repr masks the access token."""
        repr_str = repr(dhan_config)
        
        # Should not show full token
        assert "test_access_token_12345" not in repr_str
        assert "****" in repr_str or "..." in repr_str


# =============================================================================
# Tests for DhanConverter - To Broker-Agnostic Entities
# =============================================================================

class TestDhanConverterToInstrument:
    """Tests for DhanConverter.to_instrument method."""
    
    def test_convert_option_instrument(self, sample_instrument: DhanInstrument):
        """Test converting option DhanInstrument to Instrument."""
        result = DhanConverter.to_instrument(sample_instrument)
        
        assert isinstance(result, Instrument)
        assert result.symbol == "NIFTY"
        assert result.security_id == "12345"
        assert result.option_type == OptionType.CALL
        assert result.strike == 18000.0
        assert result.expiry == date(2023, 2, 23)
    
    def test_convert_equity_instrument(self, sample_equity_instrument: DhanInstrument):
        """Test converting equity DhanInstrument to Instrument."""
        result = DhanConverter.to_instrument(sample_equity_instrument)
        
        assert isinstance(result, Instrument)
        assert result.symbol == "TCS"
        assert result.security_id == "10001"
        assert result.option_type is None
        assert result.strike is None
    
    def test_convert_future_instrument(self, sample_future_instrument: DhanInstrument):
        """Test converting future DhanInstrument to Instrument."""
        result = DhanConverter.to_instrument(sample_future_instrument)
        
        assert isinstance(result, Instrument)
        assert result.symbol == "NIFTY"
        assert result.option_type is None
        assert result.expiry == date(2023, 2, 23)


class TestDhanConverterToQuote:
    """Tests for DhanConverter.to_quote method."""
    
    def test_convert_quote(self, sample_quote: DhanQuote):
        """Test converting DhanQuote to Quote."""
        result = DhanConverter.to_quote(sample_quote)
        
        assert isinstance(result, Quote)
        assert result.ltp == 18050.50
        assert result.bid == 18050.00
        assert result.ask == 18051.00
        assert result.volume == 1000000
        assert result.open == 18000.00
        assert result.high == 18100.00
        assert result.low == 17950.00
        assert result.close == 17980.00
        assert result.oi == 500000

    def test_convert_quote_without_instrument(self):
        """Test converting DhanQuote without instrument reference."""
        quote = DhanQuote(
            security_id="12345",
            ltp=18050.50,
            open=18000.00,
            high=18100.00,
            low=17950.00,
            close=17980.00,
            volume=1000000,
            bid=18050.00,
            ask=18051.00,
        )
        
        result = DhanConverter.to_quote(quote)
        
        assert isinstance(result, Quote)
        assert result.instrument.security_id == "12345"


class TestDhanConverterToTick:
    """Tests for DhanConverter.to_tick method."""
    
    def test_convert_tick(self, sample_tick: DhanTick):
        """Test converting DhanTick to Tick."""
        result = DhanConverter.to_tick(sample_tick)
        
        assert isinstance(result, Tick)
        assert result.price == 18050.50
        assert result.volume == 1000000
    
    def test_convert_tick_without_instrument(self):
        """Test converting DhanTick without instrument reference."""
        tick = DhanTick(
            security_id="12345",
            ltp=18050.50,
            volume=1000000,
            timestamp=datetime.now(),
        )
        
        result = DhanConverter.to_tick(tick)
        
        assert isinstance(result, Tick)
        assert result.instrument.security_id == "12345"


class TestDhanConverterToOrder:
    """Tests for DhanConverter.to_order method."""
    
    def test_convert_pending_order(self, sample_order: DhanOrder):
        """Test converting pending DhanOrder to Order."""
        result = DhanConverter.to_order(sample_order)
        
        assert isinstance(result, Order)
        assert result.order_id == "ORDER123"
        assert result.side == OrderSide.BUY
        assert result.quantity == 50.0
        assert result.price == 150.00
        assert result.order_type == OrderType.LIMIT
        assert result.status == OrderStatus.PENDING
    
    def test_convert_filled_order(self, sample_filled_order: DhanOrder):
        """Test converting filled DhanOrder to Order."""
        result = DhanConverter.to_order(sample_filled_order)
        
        assert isinstance(result, Order)
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == 50.0
    
    def test_convert_sell_order(self):
        """Test converting sell order."""
        order = DhanOrder(
            order_id="ORDER_SELL",
            security_id="12345",
            trading_symbol="NIFTY23FEB18000CE",
            order_type="MARKET",
            transaction_type="SELL",
            quantity=50,
        )
        
        result = DhanConverter.to_order(order)
        
        assert result.side == OrderSide.SELL
    
    def test_convert_order_types(self):
        """Test converting different order types."""
        # Market order
        market_order = DhanOrder(
            order_id="ORDER1",
            security_id="12345",
            trading_symbol="TEST",
            order_type="MARKET",
            transaction_type="BUY",
            quantity=50,
        )
        assert DhanConverter.to_order(market_order).order_type == OrderType.MARKET
        
        # Limit order
        limit_order = DhanOrder(
            order_id="ORDER2",
            security_id="12345",
            trading_symbol="TEST",
            order_type="LIMIT",
            transaction_type="BUY",
            quantity=50,
        )
        assert DhanConverter.to_order(limit_order).order_type == OrderType.LIMIT
        
        # Stop loss order
        sl_order = DhanOrder(
            order_id="ORDER3",
            security_id="12345",
            trading_symbol="TEST",
            order_type="SL",
            transaction_type="BUY",
            quantity=50,
        )
        assert DhanConverter.to_order(sl_order).order_type == OrderType.SL


class TestDhanConverterToPosition:
    """Tests for DhanConverter.to_position method."""
    
    def test_convert_long_position(self, sample_position: DhanPosition):
        """Test converting long position."""
        result = DhanConverter.to_position(sample_position)
        
        assert isinstance(result, Position)
        assert result.quantity == 50.0
        assert result.avg_price == 150.00
        assert result.unrealized_pnl == 250.00
    
    def test_convert_short_position(self):
        """Test converting short position."""
        position = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=-50,
            average_price=150.00,
        )
        
        result = DhanConverter.to_position(position)
        
        assert result.quantity == -50.0


class TestDhanConverterToOptionChain:
    """Tests for DhanConverter.to_option_chain method."""
    
    def test_convert_option_chain(self, sample_option_chain: DhanOptionChain):
        """Test converting DhanOptionChain to OptionChain."""
        result = DhanConverter.to_option_chain(sample_option_chain)
        
        assert isinstance(result, OptionChain)
        assert result.underlying.symbol == "NIFTY"
        assert result.expiry == date(2023, 2, 23)
        assert result.spot_price == 18000.0
        assert len(result.calls) == 3
        assert len(result.puts) == 3


# =============================================================================
# Tests for DhanConverter - From Broker-Agnostic Entities
# =============================================================================

class TestDhanConverterFromOrderRequest:
    """Tests for DhanConverter.from_order_request method."""
    
    def test_convert_market_order(self, broker_agnostic_order: Order):
        """Test converting market order to API payload."""
        # Make it a market order
        market_order = Order(
            instrument=broker_agnostic_order.instrument,
            side=OrderSide.BUY,
            quantity=50.0,
            order_type=OrderType.MARKET,
        )
        
        result = DhanConverter.from_order_request(market_order, client_id="CLIENT123")
        
        assert result["transactionType"] == "BUY"
        assert result["orderType"] == "MARKET"
        assert result["quantity"] == 50
        assert result["dhanClientId"] == "CLIENT123"
    
    def test_convert_limit_order(self, broker_agnostic_instrument: Instrument):
        """Test converting limit order to API payload."""
        order = Order(
            instrument=broker_agnostic_instrument,
            side=OrderSide.BUY,
            quantity=50.0,
            price=150.00,
            order_type=OrderType.LIMIT,
        )
        
        result = DhanConverter.from_order_request(order, client_id="CLIENT123")
        
        assert result["orderType"] == "LIMIT"
        assert result["price"] == 150.00
    
    def test_convert_sell_order(self, broker_agnostic_instrument: Instrument):
        """Test converting sell order to API payload."""
        order = Order(
            instrument=broker_agnostic_instrument,
            side=OrderSide.SELL,
            quantity=50.0,
            order_type=OrderType.MARKET,
        )
        
        result = DhanConverter.from_order_request(order, client_id="CLIENT123")
        
        assert result["transactionType"] == "SELL"
    
    def test_convert_stop_loss_order(self, broker_agnostic_instrument: Instrument):
        """Test converting stop loss order to API payload."""
        order = Order(
            instrument=broker_agnostic_instrument,
            side=OrderSide.BUY,
            quantity=50.0,
            price=145.00,
            order_type=OrderType.SL,
        )
        
        result = DhanConverter.from_order_request(order, client_id="CLIENT123")
        
        assert result["orderType"] == "STOP_LOSS"
        assert result["triggerPrice"] == 145.00


class TestDhanConverterFromOrderRequestNewFields:
    """Tests for new trigger_price and product_type fields in from_order_request."""

    @pytest.fixture
    def base_instrument(self):
        return Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="12345",
        )

    def test_product_type_read_from_order(self, base_instrument):
        """from_order_request uses order.product_type not a separate parameter."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            order_type=OrderType.LIMIT,
            price=18000.0,
            product_type="CNC",
        )
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert payload["productType"] == "CNC"

    def test_product_type_defaults_to_intraday(self, base_instrument):
        """from_order_request defaults productType to INTRADAY when not set."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
        )
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert payload["productType"] == "INTRADAY"

    def test_sl_order_uses_trigger_price_field(self, base_instrument):
        """SL order with trigger_price uses that for triggerPrice in payload."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            price=18100.0,
            order_type=OrderType.SL,
            trigger_price=18000.0,
        )
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert payload["orderType"] == "STOP_LOSS"
        assert payload["triggerPrice"] == 18000.0
        assert payload["price"] == 18100.0

    def test_slm_order_uses_trigger_price_only(self, base_instrument):
        """SLM order uses trigger_price only; no limit price in payload."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.SELL,
            quantity=50,
            order_type=OrderType.SLM,
            trigger_price=17900.0,
        )
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert payload["orderType"] == "STOP_LOSS_MARKET"
        assert payload["triggerPrice"] == 17900.0
        assert "price" not in payload

    def test_sl_order_fallback_to_price_when_no_trigger_price(self, base_instrument):
        """SL order without trigger_price falls back to order.price for triggerPrice."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            price=145.0,
            order_type=OrderType.SL,
            # trigger_price intentionally omitted (None)
        )
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert payload["triggerPrice"] == 145.0

    def test_correlation_id_included_from_user_order_id(self, base_instrument):
        """When the caller sets user_order_id (strategy signal_id), it must be
        sent as correlationId — Dhan's idempotency key that deduplicates a
        retried place_order POST instead of opening a duplicate position."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
        )
        setattr(order, "user_order_id", "sig-123-abc")
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert payload["correlationId"] == "sig-123-abc"

    def test_correlation_id_omitted_when_no_user_order_id(self, base_instrument):
        """Orders without user_order_id must not carry a correlationId (Dhan
        treats an absent key as non-idempotent — safe default)."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
        )
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert "correlationId" not in payload

    def test_correlation_id_truncated_to_36_chars(self, base_instrument):
        """Dhan limits correlationId to 36 chars; longer ids are truncated."""
        order = Order(
            instrument=base_instrument,
            side=OrderSide.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
        )
        setattr(order, "user_order_id", "x" * 60)
        payload = DhanConverter.from_order_request(order, client_id="CLIENT123")
        assert len(payload["correlationId"]) == 36


class TestDhanConverterFromInstrument:
    """Tests for DhanConverter.from_instrument method."""
    
    def test_convert_instrument(self, broker_agnostic_instrument: Instrument):
        """Test converting Instrument to API lookup parameters."""
        result = DhanConverter.from_instrument(broker_agnostic_instrument)
        
        assert result["symbol"] == "NIFTY"
        assert result["security_id"] == "12345"
        assert "exchange_segment" in result


# =============================================================================
# Tests for DhanConverter - From API Responses
# =============================================================================

class TestDhanConverterFromApiResponse:
    """Tests for DhanConverter methods from API responses."""
    
    def test_quote_from_api_response(self, api_quote_response):
        """Test creating Quote from API response."""
        result = DhanConverter.quote_from_api_response(
            data=api_quote_response,
            security_id="12345",
        )
        
        assert isinstance(result, Quote)
        assert result.ltp == 18050.50
        assert result.instrument.security_id == "12345"
        assert result.oi == 500000

    def test_quote_from_api_response_without_oi(self):
        """quote_from_api_response sets oi=None when API has no oi."""
        data = {
            "LTP": 100.0,
            "open": 99.0,
            "high": 101.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 10000,
            "bid": 99.5,
            "ask": 100.5,
            "tradingSymbol": "TEST",
        }
        result = DhanConverter.quote_from_api_response(data, "99999")
        assert result.oi is None

    def test_tick_from_ws_message(self, ws_tick_message):
        """Test creating Tick from WebSocket message."""
        result = DhanConverter.tick_from_ws_message(
            data=ws_tick_message,
            security_id="12345",
        )
        
        assert isinstance(result, Tick)
        assert result.price == 18050.50
        assert result.instrument.security_id == "12345"
    
    def test_tick_from_ws_message_with_instrument(
        self,
        ws_tick_message,
        broker_agnostic_instrument
    ):
        """Test creating Tick from WebSocket message with existing instrument."""
        result = DhanConverter.tick_from_ws_message(
            data=ws_tick_message,
            security_id="12345",
            instrument=broker_agnostic_instrument,
        )
        
        assert isinstance(result, Tick)
        assert result.instrument.symbol == "NIFTY"
    
    def test_order_from_api_response(self, api_order_response):
        """Test creating Order from API response."""
        result = DhanConverter.order_from_api_response(api_order_response)
        
        assert isinstance(result, Order)
        assert result.order_id == "ORDER123"
        assert result.side == OrderSide.BUY
        assert result.quantity == 50.0
        assert result.status == OrderStatus.FILLED
    
    def test_position_from_api_response(self, api_position_response):
        """Test creating Position from API response."""
        result = DhanConverter.position_from_api_response(api_position_response)
        
        assert isinstance(result, Position)
        assert result.quantity == 50.0
        assert result.avg_price == 150.00
        assert result.unrealized_pnl == 250.00


# =============================================================================
# Tests for DhanConverter - Private Helper Methods
# =============================================================================

class TestDhanConverterHelpers:
    """Tests for DhanConverter private helper methods."""
    
    def test_segment_to_exchange(self):
        """Test _segment_to_exchange helper."""
        # Test NSE_FNO
        exchange = DhanConverter._segment_to_exchange(ExchangeSegment.NSE_FNO)
        assert exchange == Exchange.NFO
        
        # Test NSE_EQ
        exchange = DhanConverter._segment_to_exchange(ExchangeSegment.NSE_EQ)
        assert exchange == Exchange.NSE
    
    def test_exchange_to_segment(self):
        """Test _exchange_to_segment helper."""
        segment = DhanConverter._exchange_to_segment(Exchange.NFO)
        assert segment == "NSE_FNO"
        
        segment = DhanConverter._exchange_to_segment(Exchange.NSE)
        assert segment == "NSE_EQ"
    
    def test_map_option_type(self):
        """Test _map_option_type helper."""
        from brokers.broker.dhan.domain import OptionType as DhanOptionType
        
        result = DhanConverter._map_option_type(DhanOptionType.CALL)
        assert result == OptionType.CALL
        
        result = DhanConverter._map_option_type(DhanOptionType.PUT)
        assert result == OptionType.PUT
    
    def test_map_order_type_from_dhan(self):
        """Test _map_order_type_from_dhan helper."""
        assert DhanConverter._map_order_type_from_dhan("MARKET") == OrderType.MARKET
        assert DhanConverter._map_order_type_from_dhan("LIMIT") == OrderType.LIMIT
        assert DhanConverter._map_order_type_from_dhan("STOP_LOSS") == OrderType.SL
        assert DhanConverter._map_order_type_from_dhan("STOP_LOSS_MARKET") == OrderType.SLM
        assert DhanConverter._map_order_type_from_dhan("SL") == OrderType.SL
        assert DhanConverter._map_order_type_from_dhan("SL-M") == OrderType.SLM
        
        # Unknown type defaults to MARKET
        assert DhanConverter._map_order_type_from_dhan("UNKNOWN") == OrderType.MARKET
    
    def test_map_order_status_from_dhan(self):
        """Test _map_order_status_from_dhan helper."""
        assert DhanConverter._map_order_status_from_dhan("PENDING") == OrderStatus.PENDING
        assert DhanConverter._map_order_status_from_dhan("TRANSIT") == OrderStatus.PENDING
        assert DhanConverter._map_order_status_from_dhan("TRADED") == OrderStatus.FILLED
        assert DhanConverter._map_order_status_from_dhan("CANCELLED") == OrderStatus.CANCELLED
        assert DhanConverter._map_order_status_from_dhan("REJECTED") == OrderStatus.REJECTED
        
        # Unknown status defaults to PENDING
        assert DhanConverter._map_order_status_from_dhan("UNKNOWN") == OrderStatus.PENDING


# =============================================================================
# Tests for Exchange Mapping Constants
# =============================================================================

class TestExchangeMapping:
    """Tests for exchange mapping constants (single source: segment_mapping)."""
    
    def test_exchange_to_segment_mapping(self):
        """Test exchange_to_segment_name from segment_mapping."""
        from brokers.broker.dhan.domain.segment_mapping import (
            exchange_to_segment_name,
            EXCHANGE_TO_SEGMENT,
        )
        assert exchange_to_segment_name(Exchange.NSE) == "NSE_EQ"
        assert exchange_to_segment_name(Exchange.NFO) == "NSE_FNO"
        assert EXCHANGE_TO_SEGMENT[Exchange.NSE] == "NSE_EQ"
        assert EXCHANGE_TO_SEGMENT[Exchange.BSE] == "BSE_EQ"
        assert EXCHANGE_TO_SEGMENT[Exchange.BFO] == "BSE_FNO"
    
    def test_segment_to_exchange_mapping(self):
        """Test segment_name_to_exchange from segment_mapping."""
        from brokers.broker.dhan.domain.segment_mapping import (
            segment_name_to_exchange,
            SEGMENT_TO_EXCHANGE,
        )
        assert segment_name_to_exchange("NSE_EQ") == Exchange.NSE
        assert segment_name_to_exchange("NSE_FNO") == Exchange.NFO
        assert SEGMENT_TO_EXCHANGE["NSE_EQ"] == Exchange.NSE
        assert SEGMENT_TO_EXCHANGE["BSE_EQ"] == Exchange.BSE


# =============================================================================
# Tests for Edge Cases
# =============================================================================

class TestDhanConverterEdgeCases:
    """Tests for edge cases in DhanConverter."""
    
    def test_convert_quote_with_zero_values(self):
        """Test converting quote with zero values."""
        quote = DhanQuote(
            security_id="12345",
            ltp=0.0,
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            volume=0,
            bid=0.0,
            ask=0.0,
        )
        
        result = DhanConverter.to_quote(quote)
        
        assert result.ltp == 0.0
        assert result.volume == 0
    
    def test_convert_order_with_zero_filled(self):
        """Test converting order with zero filled quantity."""
        order = DhanOrder(
            order_id="ORDER1",
            security_id="12345",
            trading_symbol="TEST",
            order_type="LIMIT",
            transaction_type="BUY",
            quantity=50,
            filled_quantity=0,
        )
        
        result = DhanConverter.to_order(order)
        
        assert result.filled_quantity == 0.0
        assert result.status == OrderStatus.PENDING
    
    def test_convert_position_with_zero_quantity(self):
        """Test converting position with zero quantity."""
        position = DhanPosition(
            security_id="12345",
            trading_symbol="TEST",
            quantity=0,
            average_price=150.00,
        )
        
        result = DhanConverter.to_position(position)
        
        assert result.quantity == 0.0
    
    def test_quote_from_api_response_missing_fields(self):
        """Test creating Quote from API response with missing fields."""
        data = {}  # Empty response
        
        result = DhanConverter.quote_from_api_response(
            data=data,
            security_id="12345",
        )
        
        assert isinstance(result, Quote)
        assert result.ltp == 0.0  # Default value
    
    def test_order_from_api_response_minimal(self):
        """Test creating Order from minimal API response."""
        data = {
            "orderId": "ORDER1",
        }
        
        result = DhanConverter.order_from_api_response(data)
        
        assert isinstance(result, Order)
        assert result.order_id == "ORDER1"
        assert result.quantity == 0.0  # Default


# =============================================================================
# Streaming tests: MCX guard, exchange_segments, stream_full
# =============================================================================

import asyncio
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

from brokers.broker.dhan.application.services.streaming_service import StreamingService
from brokers.broker.dhan.domain.errors import DhanFeedNotSupportedError
from brokers.broker.entities import Instrument, MarketDepth, DepthLevel as BrokerDepthLevel
from brokers.broker.types import Exchange


def _make_ws_message(msg_type: str, data: dict):
    """Build a minimal WSMessage-like object."""
    msg = MagicMock()
    msg.type = msg_type
    msg.data = data
    msg.timestamp = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    return msg


def _make_streaming_service(instrument_map: dict):
    """Return a StreamingService with _prepare_stream mocked."""
    svc = StreamingService.__new__(StreamingService)
    security_ids = list(instrument_map.keys())

    async def _prepare(instruments):
        return security_ids, instrument_map

    svc._prepare_stream = _prepare
    svc._config = MagicMock()
    svc._config.access_token = "tok"
    svc._config.client_id = "cid"
    svc._ensure_initialized = AsyncMock()
    # __new__ bypasses __init__, which normally creates these fields.
    svc._ws_lock = asyncio.Lock()
    svc._depth_ws_lock = asyncio.Lock()
    svc._persistent_ws = None
    svc._persistent_depth_ws = None
    return svc


class TestStreamingNotSupported:
    """stream_quotes and stream_ticker must raise DhanFeedNotSupportedError for MCX."""

    @pytest.mark.asyncio
    async def test_stream_quotes_raises_for_mcx(self):
        inst = Instrument(symbol="CRUDEOIL CE", exchange=Exchange.MCX, security_id="499142")
        svc = _make_streaming_service({"499142": inst})

        with pytest.raises(DhanFeedNotSupportedError) as exc_info:
            async for _ in svc.stream_quotes([inst]):
                pass

        err = exc_info.value
        assert err.feed_type == "QUOTE"
        assert err.exchange == "MCX"

    @pytest.mark.asyncio
    async def test_stream_ticker_raises_for_mcx(self):
        inst = Instrument(symbol="CRUDEOIL CE", exchange=Exchange.MCX, security_id="499142")
        svc = _make_streaming_service({"499142": inst})

        with pytest.raises(DhanFeedNotSupportedError) as exc_info:
            async for _ in svc.stream_ticker([inst]):
                pass

        err = exc_info.value
        assert err.feed_type == "TICKER"
        assert err.exchange == "MCX"


class TestStreamingExchangeSegments:
    """exchange_segments must be correctly derived and passed to subscribe."""

    @pytest.mark.asyncio
    async def test_stream_quotes_passes_nfo_segment(self):
        inst = Instrument(symbol="NIFTY CE", exchange=Exchange.NFO, security_id="12345")
        svc = _make_streaming_service({"12345": inst})

        captured = {}

        async def _fake_subscribe(sids, feed_type, exchange_segments=None):
            captured["segments"] = exchange_segments

        mock_ws = AsyncMock()
        mock_ws.subscribe = _fake_subscribe
        mock_ws.messages = AsyncMock(return_value=iter([]))

        async def _aiter_empty():
            return
            yield  # make it an async generator

        mock_ws.messages = _aiter_empty

        with patch(
            "brokers.broker.dhan.application.services.streaming_service.DhanWebSocketClient",
            return_value=mock_ws,
        ):
            async for _ in svc.stream_quotes([inst]):
                break

        assert captured.get("segments") == ["NSE_FNO"]

    @pytest.mark.asyncio
    async def test_stream_depth_5_passes_mcx_segment(self):
        inst = Instrument(symbol="CRUDEOIL FUT", exchange=Exchange.MCX, security_id="999999")
        svc = _make_streaming_service({"999999": inst})

        captured = {}

        async def _fake_subscribe(sids, feed_type, exchange_segments=None):
            captured["segments"] = exchange_segments

        mock_ws = AsyncMock()
        mock_ws.subscribe = _fake_subscribe

        async def _aiter_empty():
            return
            yield

        mock_ws.messages = _aiter_empty

        with patch(
            "brokers.broker.dhan.application.services.streaming_service.DhanWebSocketClient",
            return_value=mock_ws,
        ):
            async for _ in svc._stream_depth_5([inst]):
                break

        assert captured.get("segments") == ["MCX_COMM"]


class TestStreamFull:
    """stream_full yields correct dicts and passes MCX exchange_segments."""

    @pytest.mark.asyncio
    async def test_stream_full_yields_correct_fields(self):
        inst = Instrument(symbol="CRUDEOIL CE", exchange=Exchange.MCX, security_id="499142")
        svc = _make_streaming_service({"499142": inst})

        pkt_data = {
            "security_id": "499142",
            "ltp": 55.5,
            "open": 50.0,
            "high": 60.0,
            "low": 49.0,
            "close": 52.0,
            "volume": 1000,
            "oi": 500,
            "atp": 54.0,
            "depth_bids": [{"price": 55.0, "qty": 10}],
            "depth_asks": [{"price": 56.0, "qty": 8}],
        }
        full_msg = _make_ws_message("full", pkt_data)

        async def _aiter_one():
            yield full_msg

        mock_ws = AsyncMock()
        mock_ws.subscribe = AsyncMock()
        mock_ws.messages = _aiter_one

        results = []
        with patch(
            "brokers.broker.dhan.application.services.streaming_service.DhanWebSocketClient",
            return_value=mock_ws,
        ):
            async for pkt in svc.stream_full([inst]):
                results.append(pkt)

        assert len(results) == 1
        pkt = results[0]
        # stream_full yields FullPacket domain objects, not raw dicts.
        assert pkt.ltp == 55.5
        assert pkt.depth_bids == ({"price": 55.0, "qty": 10},)
        assert pkt.depth_asks == ({"price": 56.0, "qty": 8},)
        assert pkt.symbol == "CRUDEOIL CE"
        assert pkt.timestamp == full_msg.timestamp

    @pytest.mark.asyncio
    async def test_stream_full_uses_mcx_segment(self):
        inst = Instrument(symbol="CRUDEOIL CE", exchange=Exchange.MCX, security_id="499142")
        svc = _make_streaming_service({"499142": inst})

        captured = {}

        async def _fake_subscribe(sids, feed_type, exchange_segments=None):
            captured["segments"] = exchange_segments

        mock_ws = AsyncMock()
        mock_ws.subscribe = _fake_subscribe

        async def _aiter_empty():
            return
            yield

        mock_ws.messages = _aiter_empty

        with patch(
            "brokers.broker.dhan.application.services.streaming_service.DhanWebSocketClient",
            return_value=mock_ws,
        ):
            async for _ in svc.stream_full([inst]):
                break

        assert captured.get("segments") == ["MCX_COMM"]


class TestDhanBrokerLoopLock:
    """_loop_lock must be per-instance, not class-level."""

    def test_loop_lock_is_instance_attribute(self):
        from brokers.broker.dhan.application.broker import DhanBroker
        from brokers.broker.dhan.application.config import DhanConfig

        cfg = DhanConfig(client_id="A", access_token="B")
        b1 = DhanBroker(config=cfg)
        b2 = DhanBroker(config=cfg)

        assert hasattr(b1, "_loop_lock")
        assert hasattr(b2, "_loop_lock")
        assert b1._loop_lock is not b2._loop_lock, "Each instance must have its own lock"


class TestPerServiceCircuitBreakers:
    """One shared breaker lets a WS/quote failure starve history.

    Prod incident 2026-09-04: a startup 429 burst tripped the single shared
    DhanCircuitBreaker and it never recovered (half-open needs 3 consecutive
    successes; any background failure re-opens). All history fetches then
    failed fast while the API itself was healthy.
    """

    def test_factory_gives_each_service_its_own_breaker(self):
        from brokers.broker.dhan.application.broker import DhanBroker
        from brokers.broker.dhan.application.config import DhanConfig
        from brokers.broker.dhan.infrastructure.resilience import DhanCircuitBreaker

        cfg = DhanConfig(client_id="A", access_token="B")
        made: dict = {}

        def factory(category: str):
            cb = DhanCircuitBreaker()
            made[category] = cb
            return cb

        b = DhanBroker(config=cfg, circuit_breaker_factory=factory)

        assert set(made) == {
            "market_data", "historical", "streaming",
            "options", "orders", "portfolio",
        }
        assert b._historical._circuit_breaker is not b._market_data._circuit_breaker

    def test_market_data_trip_does_not_starve_history(self):
        import asyncio
        from brokers.broker.dhan.application.broker import DhanBroker
        from brokers.broker.dhan.application.config import DhanConfig
        from brokers.broker.dhan.infrastructure.resilience import DhanCircuitBreaker

        cfg = DhanConfig(client_id="A", access_token="B")
        b = DhanBroker(
            config=cfg,
            circuit_breaker_factory=lambda category: DhanCircuitBreaker(),
        )

        md_cb = b._market_data._circuit_breaker
        hist_cb = b._historical._circuit_breaker
        for _ in range(5):
            md_cb.record_failure()
        assert md_cb.is_open

        async def _ok():
            return "history-flows"

        async def probe():
            return await hist_cb.execute(lambda: _ok())

        assert asyncio.run(probe()) == "history-flows"
        assert hist_cb.is_closed
