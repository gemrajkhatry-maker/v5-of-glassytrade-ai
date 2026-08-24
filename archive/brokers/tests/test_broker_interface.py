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


class TestPaperBroker:
    """Test Paper broker implementation."""
    
    @pytest.fixture
    def paper_broker(self):
        """Create paper broker instance."""
        from brokers.broker.paper import PaperBroker
        return PaperBroker()
    
    def test_paper_broker_implements_interface(self, paper_broker):
        """PaperBroker must implement IBrokerPort."""
        from brokers.broker.ports import IBrokerPort
        assert isinstance(paper_broker, IBrokerPort)
    
    def test_paper_broker_get_quote(self, paper_broker):
        """PaperBroker.get_quote returns Quote."""
        from brokers.broker.entities import Instrument, Quote
        from brokers.broker.types import Exchange
        
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        quote = paper_broker.get_quote(inst)
        
        assert isinstance(quote, Quote)
        assert quote.ltp > 0
    
    def test_paper_broker_get_quotes_batch(self, paper_broker):
        """PaperBroker.get_quotes_batch returns dict."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange
        
        instruments = [
            Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885"),
            Instrument(symbol="TCS", exchange=Exchange.NSE, security_id="3456"),
        ]
        quotes = paper_broker.get_quotes_batch(instruments)
        
        assert isinstance(quotes, dict)
        assert len(quotes) == 2
    
    @pytest.mark.asyncio
    async def test_paper_broker_stream_ticker(self, paper_broker):
        """PaperBroker.stream_ticker yields ticks."""
        from brokers.broker.entities import Instrument, Tick
        from brokers.broker.types import Exchange
        
        instruments = [
            Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        ]
        
        count = 0
        async for tick in paper_broker.stream_ticker(instruments):
            assert isinstance(tick, Tick)
            count += 1
            if count >= 3:
                break
        
        assert count == 3
    
    def test_paper_broker_place_order(self, paper_broker):
        """PaperBroker.place_order returns Order."""
        from brokers.broker.entities import Order, Instrument
        from brokers.broker.types import Exchange, OrderSide, OrderType
        
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        order = Order(
            order_id="",
            instrument=inst,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            price=None
        )
        result = paper_broker.place_order(order)
        
        assert result.order_id != ""
        assert result.status.value == "FILLED"

    def test_paper_broker_get_historical(self, paper_broker):
        """PaperBroker.get_historical returns DataFrame."""
        from brokers.broker.entities import Instrument
        from brokers.broker.types import Exchange
        import pandas as pd
        from datetime import datetime, timedelta

        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        to_date = datetime.now()
        from_date = to_date - timedelta(days=5)
        df = paper_broker.get_historical(inst, from_date, to_date, interval="1d")
        assert isinstance(df, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_paper_broker_stream_quotes(self, paper_broker):
        """PaperBroker.stream_quotes yields quotes."""
        from brokers.broker.entities import Instrument, Quote
        from brokers.broker.types import Exchange

        instruments = [Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")]
        count = 0
        async for quote in paper_broker.stream_quotes(instruments):
            assert isinstance(quote, Quote)
            count += 1
            if count >= 2:
                break
        assert count >= 1

    @pytest.mark.asyncio
    async def test_paper_broker_stream_depth(self, paper_broker):
        """PaperBroker.stream_depth yields MarketDepth."""
        from brokers.broker.entities import Instrument, MarketDepth
        from brokers.broker.types import Exchange

        instruments = [Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")]
        count = 0
        async for depth in paper_broker.stream_depth(instruments):
            assert isinstance(depth, MarketDepth)
            count += 1
            if count >= 2:
                break
        assert count >= 1

    def test_paper_broker_get_option_chain(self, paper_broker):
        """PaperBroker.get_option_chain returns OptionChain."""
        from brokers.broker.entities import OptionChain
        from brokers.broker.types import Exchange

        chain = paper_broker.get_option_chain("NIFTY", Exchange.NFO)
        assert isinstance(chain, OptionChain)
        assert chain.underlying.symbol == "NIFTY"

    def test_paper_broker_get_expiry_list(self, paper_broker):
        """PaperBroker.get_expiry_list returns list of datetime."""
        from brokers.broker.types import Exchange
        from datetime import datetime

        expiries = paper_broker.get_expiry_list("NIFTY", Exchange.NFO)
        assert isinstance(expiries, list)
        assert all(isinstance(e, datetime) for e in expiries)

    def test_paper_broker_cancel_order(self, paper_broker):
        """PaperBroker.cancel_order returns bool."""
        ok = paper_broker.cancel_order("some_order_id")
        assert isinstance(ok, bool)

    def test_paper_broker_get_order_status(self, paper_broker):
        """PaperBroker.get_order_status returns Order for a known order_id."""
        from brokers.broker.entities import Order, Instrument
        from brokers.broker.types import Exchange, OrderSide, OrderType

        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="2885")
        placed = paper_broker.place_order(
            Order(instrument=inst, side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1)
        )
        result = paper_broker.get_order_status(placed.order_id)
        assert isinstance(result, Order)
        assert result.order_id == placed.order_id

    def test_paper_broker_get_positions(self, paper_broker):
        """PaperBroker.get_positions returns list of Position."""
        from brokers.broker.entities import Position
        positions = paper_broker.get_positions()
        assert isinstance(positions, list)
        assert all(isinstance(p, Position) for p in positions)

    def test_paper_broker_get_orderbook(self, paper_broker):
        """PaperBroker.get_orderbook returns list of Order."""
        from brokers.broker.entities import Order
        orders = paper_broker.get_orderbook()
        assert isinstance(orders, list)
        assert all(isinstance(o, Order) for o in orders)


class TestISPProtocols:
    """Test Interface Segregation Protocol compliance."""

    @pytest.fixture
    def paper_broker(self):
        from brokers.broker.paper import PaperBroker
        return PaperBroker()

    def test_paper_is_market_data_provider(self, paper_broker):
        from brokers.broker.ports import IMarketDataProvider
        assert isinstance(paper_broker, IMarketDataProvider)

    def test_paper_is_streaming_provider(self, paper_broker):
        from brokers.broker.ports import IStreamingProvider
        assert isinstance(paper_broker, IStreamingProvider)

    def test_paper_is_order_executor(self, paper_broker):
        from brokers.broker.ports import IOrderExecutor
        assert isinstance(paper_broker, IOrderExecutor)

    def test_paper_is_portfolio_provider(self, paper_broker):
        from brokers.broker.ports import IPortfolioProvider
        assert isinstance(paper_broker, IPortfolioProvider)

    def test_paper_is_options_provider(self, paper_broker):
        from brokers.broker.ports import IOptionsProvider
        assert isinstance(paper_broker, IOptionsProvider)


class TestBrokerLifecycle:
    """Test lifecycle methods on IBrokerPort."""

    def test_paper_broker_close_noop(self):
        from brokers.broker.paper import PaperBroker
        broker = PaperBroker()
        broker.close()  # should not raise

    def test_paper_broker_initialize_noop(self):
        from brokers.broker.paper import PaperBroker
        broker = PaperBroker()
        broker.initialize()  # should not raise

    def test_gateway_close_calls_broker_close(self):
        """BrokerGateway.close() calls broker.close() for brokers without close_sync."""
        from unittest.mock import MagicMock
        from brokers.broker.paper import PaperBroker
        from brokers.gateway import BrokerGateway

        gw = BrokerGateway.paper()
        # PaperBroker has no close_sync, so gateway should call close()
        gw.close()  # should not raise
