"""
Tests for DhanFacade and related functionality.

This module tests:
- DhanFacade one-liner methods
- DhanExchangeResolver auto-detection
- Batch operations
- Convenience methods
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import pandas as pd

from brokers.broker.dhan.application.facade import (
    DhanFacade,
    Trade,
    PnLReport,
)
from brokers.broker.dhan.application.exchange_resolver import (
    DhanExchangeResolver,
    ResolvedExchange,
    NSE_FNO_INDEX_SYMBOLS,
    MCX_COMMODITY_SYMBOLS,
    NSE_EQUITY_SYMBOLS,
)
from brokers.broker.dhan.domain import (
    ExchangeSegment,
    InstrumentTypeEnum,
    DhanInstrument,
    DhanQuote,
    DhanOption,
    DhanOptionChain,
)
from brokers.broker.types import Exchange, OrderSide


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_broker():
    """Create a mock DhanBroker."""
    broker = Mock()
    broker._http_client = AsyncMock()
    broker._symbol_mapper = AsyncMock()
    broker._instrument_cache = {}
    
    # Mock initialize
    broker.initialize = AsyncMock()
    
    # Mock symbol mapper
    broker._symbol_mapper.get_security_id = AsyncMock(return_value="12345")
    
    return broker


@pytest.fixture
def mock_instrument():
    """Create a mock DhanInstrument."""
    return DhanInstrument(
        security_id="12345",
        trading_symbol="NIFTY23FEB18000CE",
        symbol="NIFTY",
        exchange_segment=ExchangeSegment.NSE_FNO,
        instrument_type=InstrumentTypeEnum.INDEX_OPTION,
        expiry_date=date(2024, 2, 23),
        strike=18000.0,
    )


@pytest.fixture
def mock_quote():
    """Create a mock DhanQuote."""
    return DhanQuote(
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


# =============================================================================
# DhanExchangeResolver Tests
# =============================================================================

class TestDhanExchangeResolver:
    """Tests for DhanExchangeResolver."""
    
    def test_resolve_nifty_index(self):
        """Test resolving NIFTY as NFO index."""
        result = DhanExchangeResolver.resolve("NIFTY")
        
        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "index"
    
    def test_resolve_banknifty_index(self):
        """Test resolving BANKNIFTY as NFO index."""
        result = DhanExchangeResolver.resolve("BANKNIFTY")
        
        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "index"
    
    def test_resolve_sensex_index(self):
        """Test resolving SENSEX as BFO index (SENSEX is a BSE index)."""
        result = DhanExchangeResolver.resolve("SENSEX")

        assert result.exchange == Exchange.BFO
        assert result.segment == ExchangeSegment.BSE_FNO
        assert result.symbol_type == "index"
    
    def test_resolve_reliance_equity(self):
        """Test resolving RELIANCE as NSE equity."""
        result = DhanExchangeResolver.resolve("RELIANCE")
        
        assert result.exchange == Exchange.NSE
        assert result.segment == ExchangeSegment.NSE_EQ
        assert result.symbol_type == "equity"
    
    def test_resolve_tcs_equity(self):
        """Test resolving TCS as NSE equity."""
        result = DhanExchangeResolver.resolve("TCS")
        
        assert result.exchange == Exchange.NSE
        assert result.segment == ExchangeSegment.NSE_EQ
        assert result.symbol_type == "equity"
    
    def test_resolve_crudeoil_commodity(self):
        """Test resolving CRUDEOIL as MCX commodity."""
        result = DhanExchangeResolver.resolve("CRUDEOIL")
        
        assert result.exchange == Exchange.MCX
        assert result.segment == ExchangeSegment.MCX
        assert result.symbol_type == "commodity"
    
    def test_resolve_gold_commodity(self):
        """Test resolving GOLD as MCX commodity."""
        result = DhanExchangeResolver.resolve("GOLD")
        
        assert result.exchange == Exchange.MCX
        assert result.segment == ExchangeSegment.MCX
        assert result.symbol_type == "commodity"
    
    def test_resolve_option_symbol(self):
        """Test resolving option symbol pattern."""
        result = DhanExchangeResolver.resolve("NIFTY23FEB18000CE")
        
        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "index_option"
    
    def test_resolve_futures_symbol(self):
        """Test resolving futures symbol pattern."""
        result = DhanExchangeResolver.resolve("NIFTY23FEBFUT")
        
        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "future"
    
    def test_resolve_unknown_symbol_defaults_to_nse(self):
        """Test that unknown symbols default to NSE equity."""
        result = DhanExchangeResolver.resolve("UNKNOWNSYMBOL")
        
        assert result.exchange == Exchange.NSE
        assert result.segment == ExchangeSegment.NSE_EQ
        assert result.symbol_type == "equity"
    
    def test_resolve_with_explicit_exchange(self):
        """Test that explicit exchange overrides auto-detection."""
        result = DhanExchangeResolver.resolve("NIFTY", Exchange.MCX)
        
        assert result.exchange == Exchange.MCX
        assert result.segment == ExchangeSegment.MCX
    
    def test_resolve_case_insensitive(self):
        """Test that symbol resolution is case insensitive."""
        result_lower = DhanExchangeResolver.resolve("nifty")
        result_upper = DhanExchangeResolver.resolve("NIFTY")
        result_mixed = DhanExchangeResolver.resolve("NiFtY")
        
        assert result_lower.exchange == result_upper.exchange == result_mixed.exchange
    
    def test_extract_underlying_from_option(self):
        """Test extracting underlying from option symbol."""
        underlying = DhanExchangeResolver._extract_underlying("NIFTY23FEB18000CE")
        assert underlying == "NIFTY"
        
        underlying = DhanExchangeResolver._extract_underlying("BANKNIFTY23FEB40000PE")
        assert underlying == "BANKNIFTY"
    
    def test_extract_underlying_from_futures(self):
        """Test extracting underlying from futures symbol."""
        underlying = DhanExchangeResolver._extract_underlying("NIFTY23FEBFUT")
        assert underlying == "NIFTY"


# =============================================================================
# ResolvedExchange Tests
# =============================================================================

class TestResolvedExchange:
    """Tests for ResolvedExchange dataclass."""
    
    def test_resolved_exchange_creation(self):
        """Test creating ResolvedExchange."""
        resolved = ResolvedExchange(
            exchange=Exchange.NFO,
            segment=ExchangeSegment.NSE_FNO,
            symbol_type="index"
        )
        
        assert resolved.exchange == Exchange.NFO
        assert resolved.segment == ExchangeSegment.NSE_FNO
        assert resolved.symbol_type == "index"
    
    def test_resolved_exchange_frozen(self):
        """Test that ResolvedExchange is immutable."""
        resolved = ResolvedExchange(
            exchange=Exchange.NFO,
            segment=ExchangeSegment.NSE_FNO,
            symbol_type="index"
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            resolved.exchange = Exchange.NSE


# =============================================================================
# Trade Tests
# =============================================================================

class TestTrade:
    """Tests for Trade dataclass."""
    
    def test_trade_creation(self):
        """Test creating a Trade."""
        trade = Trade(
            trade_id="T12345",
            order_id="O12345",
            symbol="NIFTY",
            exchange=Exchange.NFO,
            side=OrderSide.BUY,
            quantity=50,
            price=18000.0,
            timestamp=datetime.now()
        )
        
        assert trade.trade_id == "T12345"
        assert trade.side == OrderSide.BUY
        assert trade.quantity == 50
        assert trade.price == 18000.0
    
    def test_trade_value(self):
        """Test trade value calculation."""
        trade = Trade(
            trade_id="T12345",
            order_id="O12345",
            symbol="NIFTY",
            exchange=Exchange.NFO,
            side=OrderSide.BUY,
            quantity=50,
            price=18000.0,
            timestamp=datetime.now()
        )
        
        assert trade.value == 900000.0  # 50 * 18000


# =============================================================================
# PnLReport Tests
# =============================================================================

class TestPnLReport:
    """Tests for PnLReport dataclass."""
    
    def test_pnl_report_creation(self):
        """Test creating a PnLReport."""
        pnl = PnLReport(
            realized_pnl=10000.0,
            unrealized_pnl=5000.0,
            total_pnl=15000.0
        )
        
        assert pnl.realized_pnl == 10000.0
        assert pnl.unrealized_pnl == 5000.0
        assert pnl.total_pnl == 15000.0
    
    def test_pnl_report_trade_count(self):
        """Test PnLReport trade count."""
        trade = Trade(
            trade_id="T1",
            order_id="O1",
            symbol="NIFTY",
            exchange=Exchange.NFO,
            side=OrderSide.BUY,
            quantity=50,
            price=18000.0,
            timestamp=datetime.now()
        )
        
        pnl = PnLReport(trades=[trade])
        assert pnl.trade_count == 1


# =============================================================================
# DhanFacade Tests
# =============================================================================

class TestDhanFacade:
    """Tests for DhanFacade."""
    
    def test_facade_init_with_credentials(self):
        """Test DhanFacade initialization with explicit credentials."""
        with patch.dict('os.environ', {}, clear=True):
            facade = DhanFacade(
                client_id="test_client",
                access_token="test_token"
            )
            
            assert facade._client_id == "test_client"
            assert facade._access_token == "test_token"
    
    def test_facade_init_from_environment(self):
        """Test DhanFacade initialization from environment variables."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'env_client',
            'DHAN_ACCESS_TOKEN': 'env_token'
        }):
            facade = DhanFacade()
            
            assert facade._client_id == "env_client"
            assert facade._access_token == "env_token"
    
    def test_facade_init_missing_credentials(self):
        """Test DhanFacade raises error when credentials are missing."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                DhanFacade()
            
            assert "credentials required" in str(exc_info.value).lower()
    
    def test_facade_detect_exchange(self):
        """Test DhanFacade.detect_exchange method."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            result = facade.detect_exchange("NIFTY")
            assert result.exchange == Exchange.NFO
            
            result = facade.detect_exchange("RELIANCE")
            assert result.exchange == Exchange.NSE
            
            result = facade.detect_exchange("GOLD")
            assert result.exchange == Exchange.MCX
    
    @pytest.mark.asyncio
    async def test_facade_get_broker(self):
        """Test DhanFacade._get_broker lazy initialization."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            # Broker should be None initially
            assert facade._broker is None
            
            # Mock DhanBroker.create - patch where it's imported (inside the method)
            with patch('brokers.broker.dhan.application.broker.DhanBroker.create') as mock_create:
                mock_broker = Mock()
                mock_broker.initialize = AsyncMock()
                mock_create.return_value = mock_broker
                
                broker = await facade._get_broker()
                
                assert broker == mock_broker
                mock_create.assert_called_once()
                mock_broker.initialize.assert_called_once()
    
    def test_facade_repr(self):
        """Test DhanFacade string representation."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test_client',
            'DHAN_ACCESS_TOKEN': 'test_token'
        }):
            facade = DhanFacade()
            repr_str = repr(facade)
            
            assert "DhanFacade" in repr_str
            assert "test_client" in repr_str


# =============================================================================
# DhanFacade One-Liner Method Tests
# =============================================================================

class TestDhanFacadeOneLiners:
    """Tests for DhanFacade one-liner methods."""
    
    @pytest.fixture
    def facade_with_mock_broker(self):
        """Create a DhanFacade with mocked broker."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            # Mock the broker — facade now calls public get_quote()
            from brokers.broker.entities import Quote as BrokerQuote, Instrument as BrokerInstrument
            from brokers.broker.types import Exchange as BrokerExchange

            mock_quote = BrokerQuote(
                instrument=BrokerInstrument(symbol="NIFTY", exchange=BrokerExchange.NFO, security_id="12345"),
                ltp=18050.50,
                open=18000.00,
                high=18100.00,
                low=17950.00,
                close=17980.00,
                volume=1000000,
                bid=18050.00,
                ask=18051.00,
            )
            mock_broker = Mock()
            mock_broker.initialize = AsyncMock()
            mock_broker.get_quote = Mock(return_value=mock_quote)
            mock_broker._get_quote_async = AsyncMock(return_value=DhanQuote(
                security_id="12345",
                ltp=18050.50,
                open=18000.00,
                high=18100.00,
                low=17950.00,
                close=17980.00,
                volume=1000000,
                bid=18050.00,
                ask=18051.00,
            ))
            mock_broker._symbol_mapper = Mock()
            mock_broker._symbol_mapper.get_security_id = AsyncMock(return_value="12345")
            
            facade._broker = mock_broker
            
            return facade
    
    def test_get_ltp(self, facade_with_mock_broker):
        """Test DhanFacade.get_ltp one-liner."""
        facade = facade_with_mock_broker
        
        ltp = facade.get_ltp("NIFTY")
        
        assert ltp == 18050.50
    
    def test_parse_date_string(self):
        """Test DhanFacade._parse_date with string input."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            result = facade._parse_date("2024-01-15")
            
            assert result.year == 2024
            assert result.month == 1
            assert result.day == 15
    
    def test_parse_date_datetime(self):
        """Test DhanFacade._parse_date with datetime input."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            input_dt = datetime(2024, 1, 15, 10, 30)
            result = facade._parse_date(input_dt)
            
            assert result == input_dt
    
    def test_parse_date_date(self):
        """Test DhanFacade._parse_date with date input."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            input_date = date(2024, 1, 15)
            result = facade._parse_date(input_date)
            
            assert result.year == 2024
            assert result.month == 1
            assert result.day == 15


# =============================================================================
# Batch Operations Tests
# =============================================================================

class TestBatchOperations:
    """Tests for batch operations."""
    
    @pytest.fixture
    def facade_with_mock(self):
        """Create a DhanFacade with mocked broker for batch tests."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            mock_broker = Mock()
            mock_broker.initialize = AsyncMock()
            mock_broker._symbol_mapper = Mock()
            mock_broker._symbol_mapper.get_security_id = AsyncMock(return_value="12345")
            
            facade._broker = mock_broker
            
            return facade
    
    def test_get_ltp_batch(self, facade_with_mock):
        """Test DhanFacade.get_ltp_batch."""
        facade = facade_with_mock
        
        # Mock get_quotes_batch
        mock_quotes = {
            "NIFTY": DhanQuote(
                security_id="1",
                ltp=18000.0,
                open=17900.0,
                high=18100.0,
                low=17800.0,
                close=17900.0,
                volume=1000000,
                bid=18000.0,
                ask=18001.0,
            ),
            "BANKNIFTY": DhanQuote(
                security_id="2",
                ltp=42000.0,
                open=41900.0,
                high=42100.0,
                low=41800.0,
                close=41900.0,
                volume=500000,
                bid=42000.0,
                ask=42001.0,
            ),
        }
        
        with patch.object(facade, 'get_quotes_batch', return_value=mock_quotes):
            ltps = facade.get_ltp_batch(["NIFTY", "BANKNIFTY"])
            
            assert ltps["NIFTY"] == 18000.0
            assert ltps["BANKNIFTY"] == 42000.0


# =============================================================================
# Symbol Sets Tests
# =============================================================================

class TestSymbolSets:
    """Tests for symbol sets used in exchange detection."""
    
    def test_nse_fno_index_symbols(self):
        """Test NSE F&O index symbol set."""
        assert "NIFTY" in NSE_FNO_INDEX_SYMBOLS
        assert "BANKNIFTY" in NSE_FNO_INDEX_SYMBOLS
        assert "FINNIFTY" in NSE_FNO_INDEX_SYMBOLS
        assert "SENSEX" in NSE_FNO_INDEX_SYMBOLS
        assert "BANKEX" in NSE_FNO_INDEX_SYMBOLS
    
    def test_mcx_commodity_symbols(self):
        """Test MCX commodity symbol set."""
        assert "CRUDEOIL" in MCX_COMMODITY_SYMBOLS
        assert "GOLD" in MCX_COMMODITY_SYMBOLS
        assert "SILVER" in MCX_COMMODITY_SYMBOLS
        assert "NATURALGAS" in MCX_COMMODITY_SYMBOLS
        assert "COPPER" in MCX_COMMODITY_SYMBOLS
    
    def test_nse_equity_symbols(self):
        """Test NSE equity symbol set."""
        assert "RELIANCE" in NSE_EQUITY_SYMBOLS
        assert "TCS" in NSE_EQUITY_SYMBOLS
        assert "INFY" in NSE_EQUITY_SYMBOLS
        assert "HDFCBANK" in NSE_EQUITY_SYMBOLS


# =============================================================================
# Integration Tests (with mocked HTTP)
# =============================================================================

class TestFacadeIntegration:
    """Integration tests for DhanFacade with mocked HTTP."""
    
    @pytest.mark.asyncio
    async def test_quote_integration(self):
        """Test quote retrieval integration."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            from brokers.broker.entities import Quote as BrokerQuote, Instrument as BrokerInstrument
            from brokers.broker.types import Exchange as BrokerExchange

            facade = DhanFacade()
            
            mock_quote = BrokerQuote(
                instrument=BrokerInstrument(symbol="NIFTY", exchange=BrokerExchange.NFO, security_id="12345"),
                ltp=18050.50,
                open=18000.00,
                high=18100.00,
                low=17950.00,
                close=17980.00,
                volume=1000000,
                bid=18050.00,
                ask=18051.00,
            )
            mock_broker = Mock()
            mock_broker.initialize = AsyncMock()
            mock_broker.get_quote = Mock(return_value=mock_quote)
            
            facade._broker = mock_broker
            
            quote = facade.quote("NIFTY")
            
            assert quote.ltp == 18050.50
            assert quote.bid == 18050.00
            assert quote.ask == 18051.00
    
    @pytest.mark.asyncio
    async def test_option_chain_integration(self):
        """Test option chain retrieval integration."""
        with patch.dict('os.environ', {
            'DHAN_CLIENT_ID': 'test',
            'DHAN_ACCESS_TOKEN': 'test'
        }):
            facade = DhanFacade()
            
            # Mock the broker
            mock_broker = Mock()
            mock_broker.initialize = AsyncMock()
            mock_broker.get_option_chain_async = AsyncMock(return_value=Mock(
                underlying=Mock(symbol="NIFTY"),
                expiry=datetime(2024, 2, 22),
                spot_price=18000.0,
                calls={},
                puts={},
            ))
            
            facade._broker = mock_broker
            
            chain = facade.option_chain("NIFTY")
            
            assert chain.spot_price == 18000.0


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
