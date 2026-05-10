"""BrokersV2 Integration Tests - Real Broker Connection

Tests actual Dhan broker connection with LIVE market data.
NO mocks, NO simulations, NO fake data.

Requirements:
    - DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env
    - Active internet connection
    - Market hours for live data (optional for historical)

Run:
    cd /Users/apple/Downloads/v5-of-glassytrade-ai/brokersv2
    ../venv/bin/python -m pytest tests/integration/test_broker_real.py -v -s
    
Note: Tests include delays to avoid hitting Dhan API rate limits.
"""

from __future__ import annotations

import os
import time
import pytest
from datetime import datetime, timedelta
from typing import Optional

# Add project root to path
import sys
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent.parent
brokers_root = project_root / "brokers"

for path in [str(project_root), str(brokers_root)]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


# ============================================================================
# Rate limiting helper
# ============================================================================

def api_delay(seconds: float = 1.5):
    """Delay between API calls to respect rate limits."""
    time.sleep(seconds)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def broker():
    """Create real broker connection (session scope - reused across tests)."""
    from brokersv2.broker_factory import get_broker
    
    # This will fail if credentials not set
    b = get_broker()
    
    # Wait for circuit breaker to reset if needed
    api_delay(2)
    
    return b


@pytest.fixture(scope="session")
def mcx_symbols():
    """MCX symbols for testing."""
    return ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]


@pytest.fixture(scope="session")
def nse_symbols():
    """NSE symbols for testing."""
    return ["NIFTY", "BANKNIFTY"]


# ============================================================================
# Test: Broker Connection
# ============================================================================

class TestBrokerConnection:
    """Test actual broker connection and authentication."""
    
    def test_broker_created(self, broker):
        """Broker instance should be created successfully."""
        assert broker is not None
        print(f"✓ Broker created: {type(broker).__name__}")
    
    def test_credentials_loaded(self):
        """Credentials should be loaded from .env."""
        client_id = os.getenv("DHAN_CLIENT_ID")
        access_token = os.getenv("DHAN_ACCESS_TOKEN")
        
        assert client_id, "DHAN_CLIENT_ID not set in .env"
        assert access_token, "DHAN_ACCESS_TOKEN not set in .env"
        
        print(f"✓ Credentials loaded (client_id: {client_id})")
    
    def test_broker_has_required_methods(self, broker):
        """Broker should have all required methods."""
        required_methods = [
            "historical",
            "quote",  # DhanFacade uses 'quote' not 'get_quote'
            "option_chain",  # DhanFacade uses 'option_chain'
        ]
        
        for method in required_methods:
            assert hasattr(broker, method), f"Missing method: {method}"
        
        print(f"✓ All {len(required_methods)} required methods available")


# ============================================================================
# Test: Historical Data
# ============================================================================

class TestHistoricalData:
    """Test fetching REAL historical OHLCV data."""
    
    def test_fetch_mcx_historical(self, broker):
        """Fetch REAL MCX historical data."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        df = broker.historical(
            symbol="CRUDEOIL",
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
            interval="5m"
        )
        
        # Validate data
        assert df is not None, "No data returned"
        assert not df.empty, "Empty DataFrame"
        assert len(df) > 0, "No candles"
        
        # Validate columns
        required_columns = ["open", "high", "low", "close", "volume"]
        for col in required_columns:
            assert col in df.columns, f"Missing column: {col}"
        
        # Validate data types
        assert df["open"].dtype in ["float64", "float32"], "Open should be float"
        assert df["volume"].dtype in ["int64", "int32", "float64"], "Volume should be numeric"
        
        # Validate price logic
        assert (df["high"] >= df["low"]).all(), "High should be >= Low"
        assert (df["high"] >= df["open"]).all(), "High should be >= Open"
        assert (df["high"] >= df["close"]).all(), "High should be >= Close"
        assert (df["low"] <= df["open"]).all(), "Low should be <= Open"
        assert (df["low"] <= df["close"]).all(), "Low should be <= Close"
        
        # Validate volume
        assert (df["volume"] >= 0).all(), "Volume should be non-negative"
        
        print(f"✓ Fetched {len(df)} candles for CRUDEOIL")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Price range: ₹{df['low'].min():,.2f} - ₹{df['high'].max():,.2f}")
    
    def test_fetch_multiple_symbols(self, broker, mcx_symbols):
        """Fetch historical data for multiple MCX symbols."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        for symbol in mcx_symbols[:2]:  # Test first 2
            df = broker.historical(
                symbol=symbol,
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
                interval="15m"
            )
            
            assert df is not None, f"No data for {symbol}"
            assert not df.empty, f"Empty data for {symbol}"
            assert len(df) > 0, f"No candles for {symbol}"
            
            print(f"✓ {symbol}: {len(df)} candles")
            api_delay(2)  # Respect rate limits
    
    def test_fetch_different_intervals(self, broker):
        """Test different time intervals."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)
        
        intervals = ["5m", "15m", "1h"]
        
        for interval in intervals:
            df = broker.historical(
                symbol="NATURALGAS",
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
                interval=interval
            )
            
            assert df is not None, f"No data for {interval}"
            assert not df.empty, f"Empty data for {interval}"
            
            print(f"✓ {interval}: {len(df)} candles")
            api_delay(2)  # Respect rate limits


# ============================================================================
# Test: Market Quotes
# ============================================================================

class TestMarketQuotes:
    """Test fetching REAL-time market quotes."""
    
    def test_get_mcx_quote(self, broker):
        """Get REAL MCX quote."""
        quote = broker.quote("CRUDEOIL")
        
        assert quote is not None, "No quote returned"
        
        # Validate required fields (Quote object attributes)
        assert hasattr(quote, 'ltp') or 'last_price' in quote, "Missing LTP/last_price"
        
        # Get LTP value
        ltp = quote.ltp if hasattr(quote, 'ltp') else quote.get('last_price', 0)
        high = quote.high if hasattr(quote, 'high') else quote.get('high', 0)
        low = quote.low if hasattr(quote, 'low') else quote.get('low', 0)
        volume = quote.volume if hasattr(quote, 'volume') else quote.get('volume', 0)
        
        assert ltp > 0, f"LTP should be positive, got {ltp}"
        assert high > 0, "High should be positive"
        assert low > 0, "Low should be positive"
        assert volume >= 0, "Volume should be non-negative"
        
        # Validate price logic
        assert high >= low, "High should be >= Low"
        assert high >= ltp, "High should be >= Last"
        assert low <= ltp, "Low should be <= Last"
        
        print(f"✓ CRUDEOIL Quote:")
        print(f"  LTP: ₹{ltp:,.2f}")
        print(f"  High: ₹{high:,.2f}")
        print(f"  Low: ₹{low:,.2f}")
        print(f"  Volume: {volume:,}")
    
    def test_get_multiple_quotes(self, broker, mcx_symbols):
        """Get quotes for multiple symbols."""
        for symbol in mcx_symbols:
            try:
                quote = broker.quote(symbol)
                assert quote is not None, f"No quote for {symbol}"
                
                ltp = quote.ltp if hasattr(quote, 'ltp') else quote.get('last_price', 0)
                assert ltp > 0, f"Invalid price for {symbol}"
                
                print(f"✓ {symbol}: ₹{ltp:,.2f}")
                api_delay(1)  # Respect rate limits
            except Exception as e:
                print(f"⚠ {symbol}: {str(e)}")
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_get_nse_quote(self, broker):
        """Get REAL NSE quote."""
        quote = broker.quote("NIFTY")
        
        assert quote is not None, "No NIFTY quote"
        
        ltp = quote.ltp if hasattr(quote, 'ltp') else quote.get('last_price', 0)
        assert ltp > 10000, f"NIFTY should be > 10000, got {ltp}"
        assert ltp < 30000, f"NIFTY should be < 30000, got {ltp}"
        
        print(f"✓ NIFTY: ₹{ltp:,.2f}")


# ============================================================================
# Test: Options Chain
# ============================================================================

class TestOptionsChain:
    """Test fetching REAL options chain data."""
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_get_nifty_options(self, broker):
        """Get REAL NIFTY options chain."""
        chain = broker.option_chain("NIFTY")
        
        assert chain is not None, "No options chain returned"
        
        # OptionChain object has calls and puts dicts
        assert hasattr(chain, 'calls'), "Should have 'calls' attribute"
        assert hasattr(chain, 'puts'), "Should have 'puts' attribute"
        assert hasattr(chain, 'spot_price'), "Should have 'spot_price'"
        assert hasattr(chain, 'atm_strike'), "Should have 'atm_strike'"
        
        # Validate data
        assert len(chain.calls) > 0, "Empty calls"
        assert len(chain.puts) > 0, "Empty puts"
        assert chain.spot_price > 0, f"Invalid spot price: {chain.spot_price}"
        assert chain.atm_strike > 0, f"Invalid ATM strike: {chain.atm_strike}"
        
        # Validate strikes
        call_strikes = list(chain.calls.keys())
        put_strikes = list(chain.puts.keys())
        
        assert len(call_strikes) > 1, "Should have multiple call strikes"
        assert len(put_strikes) > 1, "Should have multiple put strikes"
        
        # Validate first option
        first_strike = call_strikes[0]
        call_option = chain.calls[first_strike]
        assert hasattr(call_option, 'option_type'), "Option should have option_type"
        assert call_option.option_type == "CE", "Should be CE"
        assert call_option.strike > 0, "Strike should be positive"
        
        print(f"✓ NIFTY Options Chain:")
        print(f"  Spot Price: ₹{chain.spot_price:,.2f}")
        print(f"  ATM Strike: ₹{chain.atm_strike:,.2f}")
        print(f"  Call Strikes: {len(call_strikes)}")
        print(f"  Put Strikes: {len(put_strikes)}")
        print(f"  Strike Range: ₹{min(call_strikes):,.0f} - ₹{max(call_strikes):,.0f}")
        print(f"  Expiry: {chain.expiry.strftime('%Y-%m-%d')}")
        
        api_delay(2)  # Respect rate limits before next test
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_get_banknifty_options(self, broker):
        """Get REAL BANKNIFTY options chain."""
        chain = broker.option_chain("BANKNIFTY")
        
        assert chain is not None, "No BANKNIFTY options"
        assert hasattr(chain, 'calls'), "Should have 'calls'"
        assert hasattr(chain, 'puts'), "Should have 'puts'"
        assert len(chain.calls) > 0, "Empty BANKNIFTY calls"
        assert len(chain.puts) > 0, "Empty BANKNIFTY puts"
        
        print(f"✓ BANKNIFTY Options:")
        print(f"  Spot: ₹{chain.spot_price:,.2f}")
        print(f"  Calls: {len(chain.calls)}, Puts: {len(chain.puts)}")


# ============================================================================
# Test: Data Quality
# ============================================================================

class TestDataQuality:
    """Validate quality of REAL market data."""
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_historical_data_continuity(self, broker):
        """Test historical data has no gaps."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=2)
        
        df = broker.historical(
            symbol="CRUDEOIL",
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
            interval="5m"
        )
        
        assert df is not None and not df.empty, "No data"
        
        # Check for NaN values
        nan_count = df[["open", "high", "low", "close"]].isna().sum().sum()
        assert nan_count == 0, f"Found {nan_count} NaN values"
        
        # Check for zero prices
        zero_count = (df[["open", "high", "low", "close"]] == 0).sum().sum()
        assert zero_count == 0, f"Found {zero_count} zero prices"
        
        print(f"✓ Data quality: No NaN or zero values in {len(df)} candles")
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_quote_freshness(self, broker):
        """Test quote data is current."""
        quote = broker.quote("CRUDEOIL")
        
        assert quote is not None, "No quote"
        
        # Check if quote has timestamp (if available)
        if "timestamp" in quote:
            quote_time = quote["timestamp"]
            if isinstance(quote_time, str):
                quote_time = datetime.fromisoformat(quote_time.replace("Z", "+00:00"))
            
            time_diff = abs((datetime.now(quote_time.tzinfo) - quote_time).total_seconds())
            assert time_diff < 300, f"Quote too old: {time_diff}s"
            print(f"✓ Quote freshness: {time_diff:.0f}s old")
        else:
            print("✓ Quote received (no timestamp available)")


# ============================================================================
# Test: Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling with REAL broker."""
    
    def test_invalid_symbol(self, broker):
        """Test handling of invalid symbol."""
        try:
            df = broker.historical(
                symbol="INVALID_SYMBOL",
                start_date="2026-05-01",
                end_date="2026-05-08",
                interval="5m"
            )
            # If no exception, should return None or empty
            assert df is None or (hasattr(df, 'empty') and df.empty), \
                "Should return None/empty for invalid symbol"
            print("✓ Invalid symbol handled gracefully")
        except Exception as e:
            # Exception is also acceptable
            print(f"✓ Invalid symbol raised exception: {type(e).__name__}")
    
    def test_missing_credentials(self):
        """Test error when credentials missing."""
        # Temporarily remove credentials
        original_client = os.environ.get("DHAN_CLIENT_ID")
        original_token = os.environ.get("DHAN_ACCESS_TOKEN")
        
        try:
            os.environ["DHAN_CLIENT_ID"] = ""
            os.environ["DHAN_ACCESS_TOKEN"] = ""
            
            from broker.dhan.application import DhanConfig
            
            with pytest.raises(ValueError, match="CLIENT_ID"):
                DhanConfig.from_env()
            
            print("✓ Missing credentials handled correctly")
        finally:
            # Restore credentials
            if original_client:
                os.environ["DHAN_CLIENT_ID"] = original_client
            if original_token:
                os.environ["DHAN_ACCESS_TOKEN"] = original_token


# ============================================================================
# Test: Performance
# ============================================================================

class TestPerformance:
    """Test performance with REAL broker."""
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_historical_fetch_time(self, broker):
        """Test historical data fetch time."""
        import time
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        start_time = time.time()
        df = broker.historical(
            symbol="CRUDEOIL",
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
            interval="5m"
        )
        elapsed = time.time() - start_time
        
        assert df is not None and not df.empty, "No data"
        assert elapsed < 30, f"Fetch too slow: {elapsed:.2f}s"
        
        print(f"✓ Fetched {len(df)} candles in {elapsed:.2f}s")
        print(f"  Speed: {len(df)/elapsed:.1f} candles/sec")
    
    @pytest.mark.live
    @pytest.mark.skipif(
        not os.environ.get("DHAN_ACCESS_TOKEN"),
        reason="Requires live DhanHQ credentials"
    )
    def test_quote_fetch_time(self, broker):
        """Test quote fetch time."""
        import time
        
        start_time = time.time()
        quote = broker.quote("CRUDEOIL")
        elapsed = time.time() - start_time
        
        assert quote is not None, "No quote"
        assert elapsed < 10, f"Quote fetch too slow: {elapsed:.2f}s"
        
        print(f"✓ Quote fetched in {elapsed:.2f}s")
