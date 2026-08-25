"""
TDD Tests for Broker Interfaces.

Run with: pytest brokers/tests/test_broker_interface.py -v
"""
import pytest
from datetime import datetime
import sys


class TestTypes:
    """Test type definitions."""
    
    def test_exchange_enum_values(self):
        """Exchange must have required values."""
        from brokers.broker.types import Exchange
        assert Exchange.NSE.value == "NSE"
        assert Exchange.NFO.value == "NFO"
        assert Exchange.MCX.value == "MCX"
        assert Exchange.INDEX.value == "INDEX"
    
    def test_option_type_enum(self):
        """OptionType must have CALL and PUT."""
        from brokers.broker.types import OptionType
        assert OptionType.CALL.value == "CE"
        assert OptionType.PUT.value == "PE"
    
    def test_order_side_enum(self):
        """OrderSide must have BUY and SELL."""
        from brokers.broker.types import OrderSide
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
    
    def test_order_status_enum(self):
        """OrderStatus must have required values."""
        from brokers.broker.types import OrderStatus
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"


class TestInstrument:
    """Test Instrument entity."""
    
    def test_create_instrument(self):
        """Can create an Instrument."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange
        
        inst = Instrument(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            security_id="2885"
        )
        assert inst.symbol == "RELIANCE"
        assert inst.exchange == Exchange.NSE
    
    def test_instrument_is_immutable(self):
        """Instrument must be immutable (frozen=True)."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange
        
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        with pytest.raises(AttributeError):
            inst.symbol = "TCS"
    
    def test_instrument_is_option(self):
        """is_option() returns correct value."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange, OptionType
        
        opt = Instrument(
            symbol="NIFTY",
            exchange=Exchange.NFO,
            security_id="",
            option_type=OptionType.CALL,
            strike=25000.0
        )
        assert opt.is_option() is True
        
        eq = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        assert eq.is_option() is False
    
    def test_instrument_is_index(self):
        """is_index() returns correct value."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange
        
        idx = Instrument(symbol="NIFTY", exchange=Exchange.INDEX, security_id="999920000")
        assert idx.is_index() is True
        
        eq = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        assert eq.is_index() is False


class TestQuote:
    """Test Quote entity."""
    
    def test_create_quote(self):
        """Can create a Quote."""
        from brokers.broker.entities import Quote, Instrument
        from brokers.broker.types import Exchange
        
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        quote = Quote(
            instrument=inst,
            ltp=2500.0,
            bid=2499.0,
            ask=2501.0,
            volume=1000000,
            open=2480.0,
            high=2510.0,
            low=2475.0,
            close=2495.0
        )
        assert quote.ltp == 2500.0


class TestTick:
    """Test Tick entity."""
    
    def test_create_tick(self):
        """Can create a Tick."""
        from brokers.broker.entities import Tick, Instrument
        from brokers.broker.types import Exchange
        
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        tick = Tick(instrument=inst, price=2500.0, volume=1000)
        assert tick.price == 2500.0


class TestOrder:
    """Test Order entity."""
    
    def test_create_order(self):
        """Can create an Order."""
        from brokers.broker.entities import Order, Instrument
        from brokers.broker.types import Exchange, OrderSide, OrderType
        
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        order = Order(
            order_id="ORDER_001",
            instrument=inst,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            price=None
        )
        assert order.order_id == "ORDER_001"
        assert order.side == OrderSide.BUY


class TestIBrokerPort:
    """Test IBrokerPort interface."""
    
    def test_broker_port_is_abstract(self):
        """IBrokerPort must be abstract."""
        from brokers.broker.ports import IBrokerPort
        assert hasattr(IBrokerPort, '__abstractmethods__')
        assert len(IBrokerPort.__abstractmethods__) > 0
    
    def test_broker_port_has_required_methods(self):
        """IBrokerPort must have required methods."""
        from brokers.broker.ports import IBrokerPort
        
        required_methods = [
            'get_quote',
            'get_quotes_batch',
            'get_historical',
            'stream_ticker',
            'stream_quotes',
            'stream_depth',
            'get_option_chain',
            'get_expiry_list',
            'place_order',
            'cancel_order',
            'get_order_status',
            'get_positions',
            'get_orderbook',
        ]
        
        for method in required_methods:
            assert method in IBrokerPort.__abstractmethods__
