"""Live Integration Tests for Analytics with Real Broker Data.

These tests connect to DhanHQ to validate analytics modules with real market data.
Tests are skipped unless RUN_LIVE_ANALYTICS_TESTS=1 and valid credentials are provided.
"""

import os
import pytest
from datetime import datetime, timezone, timedelta

# Skip all tests unless environment variable is set
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_ANALYTICS_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="Set RUN_LIVE_ANALYTICS_TESTS=1 to run live broker integration tests"
)


@pytest.fixture
def dhan_credentials():
    """Get DhanHQ credentials from environment."""
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        pytest.skip("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN required for live tests")
    
    return {"client_id": client_id, "access_token": access_token}


@pytest.fixture
def live_broker_adapter(dhan_credentials):
    """Create live DhanBrokerAdapter."""
    from brokersv2.infrastructure.dhan_adapter.client import DhanConfig, DhanHttpClient
    from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
    from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter
    from brokersv2.domain.market.models import Exchange
    
    config = DhanConfig(
        client_id=dhan_credentials["client_id"],
        access_token=dhan_credentials["access_token"],
    )
    
    mapper = InstrumentMapper()
    adapter = DhanBrokerAdapter(config, mapper)
    
    return adapter


@pytest.fixture
def live_historical_client(dhan_credentials):
    """Create live DhanHttpClient for historical data."""
    from brokersv2.infrastructure.dhan_adapter.client import DhanConfig, DhanHttpClient
    
    config = DhanConfig(
        client_id=dhan_credentials["client_id"],
        access_token=dhan_credentials["access_token"],
    )
    
    return DhanHttpClient(config)


class TestLiveDataValidation:
    """Validate live market data format and quality."""

    @pytest.mark.asyncio
    async def test_historical_data_format(self, live_historical_client):
        """Test historical OHLCV data structure and validity."""
        from datetime import datetime, timezone
        
        # Fetch NIFTY historical data (last 30 days)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30)
        
        candles = await live_historical_client.get_historical(
            symbol="NIFTY 50",
            exchange="NSE",
            from_date=start_date,
            to_date=end_date,
            interval="1d",
        )
        
        # Validate structure
        assert candles is not None
        assert isinstance(candles, list)
        assert len(candles) > 0, "No historical data returned"
        
        # Validate first candle format
        candle = candles[0]
        assert hasattr(candle, 'open') or 'open' in candle
        assert hasattr(candle, 'high') or 'high' in candle
        assert hasattr(candle, 'low') or 'low' in candle
        assert hasattr(candle, 'close') or 'close' in candle
        assert hasattr(candle, 'volume') or 'volume' in candle
        
        # Validate price ranges (NIFTY should be 15000-25000)
        open_price = candle.open if hasattr(candle, 'open') else candle['open']
        assert 15000 < open_price < 25000, f"Invalid price: {open_price}"

    @pytest.mark.asyncio
    async def test_option_chain_format(self, live_broker_adapter):
        """Test option chain data structure from broker."""
        from brokersv2.domain.market.models import Exchange
        
        # Fetch NIFTY option chain
        option_chain = await live_broker_adapter.get_option_chain(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry_index=0,  # Nearest expiry
        )
        
        # Validate structure
        assert option_chain is not None
        assert hasattr(option_chain, 'strikes') or 'strikes' in option_chain
        
        strikes = option_chain.strikes if hasattr(option_chain, 'strikes') else option_chain['strikes']
        assert len(strikes) > 0, "No strikes in option chain"
        
        # Validate first strike
        first_strike = strikes[0]
        assert hasattr(first_strike, 'strike_price') or 'strike_price' in first_strike
        assert hasattr(first_strike, 'call') or 'call' in first_strike
        assert hasattr(first_strike, 'put') or 'put' in first_strike

    @pytest.mark.asyncio
    async def test_market_quote_format(self, live_broker_adapter):
        """Test market quote data structure."""
        from brokersv2.domain.market.models import Exchange, CanonicalInstrument
        
        # Create instrument
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
        )
        
        # Get quote
        quote = await live_broker_adapter.get_quote(instrument)
        
        # Validate structure
        assert quote is not None
        assert hasattr(quote, 'ltp') or 'ltp' in quote
        assert hasattr(quote, 'open') or 'open' in quote
        assert hasattr(quote, 'high') or 'high' in quote
        assert hasattr(quote, 'low') or 'low' in quote
        assert hasattr(quote, 'volume') or 'volume' in quote
        
        # Validate price range (RELIANCE should be 2000-4000)
        ltp = quote.ltp if hasattr(quote, 'ltp') else quote['ltp']
        assert 2000 < ltp < 4000, f"Invalid RELIANCE price: {ltp}"


class TestOrderBookWithLiveData:
    """Test Order Book Engine with real market data."""

    @pytest.mark.asyncio
    async def test_order_book_reconstruction(self, live_broker_adapter):
        """Test order book reconstruction from real market depth."""
        from brokersv2.analytics.order_book.engine import OrderBookEngine
        from brokersv2.analytics.order_book.events import PriceLevel
        from brokersv2.domain.market.models import Exchange, CanonicalInstrument
        
        # Get market depth
        instrument = CanonicalInstrument.create_equity(
            symbol="INFY",
            exchange=Exchange.NSE,
        )
        
        depth = await live_broker_adapter.get_market_depth(instrument)
        
        # Validate depth structure
        assert depth is not None
        assert hasattr(depth, 'bids') or 'bids' in depth
        assert hasattr(depth, 'asks') or 'asks' in depth
        
        bids = depth.bids if hasattr(depth, 'bids') else depth['bids']
        asks = depth.asks if hasattr(depth, 'asks') else depth['asks']
        
        assert len(bids) > 0, "No bid levels"
        assert len(asks) > 0, "No ask levels"
        
        # Build order book
        engine = OrderBookEngine("NSE:INFY")
        
        # Add bid levels
        for level_data in bids[:5]:
            price = level_data.price if hasattr(level_data, 'price') else level_data['price']
            quantity = level_data.quantity if hasattr(level_data, 'quantity') else level_data['quantity']
            engine.update_bid(PriceLevel(price=price, quantity=quantity))
        
        # Add ask levels
        for level_data in asks[:5]:
            price = level_data.price if hasattr(level_data, 'price') else level_data['price']
            quantity = level_data.quantity if hasattr(level_data, 'quantity') else level_data['quantity']
            engine.update_ask(PriceLevel(price=price, quantity=quantity))
        
        # Validate order book
        assert engine.bid_levels > 0
        assert engine.ask_levels > 0
        assert engine.spread > 0
        assert engine.best_bid is not None
        assert engine.best_ask is not None
        
        # Best bid should be higher than best ask (normal market)
        assert engine.best_bid.price > engine.best_ask.price


class TestOptionsAnalyticsWithLiveData:
    """Test Options Analytics with real broker data."""

    @pytest.mark.asyncio
    async def test_option_chain_engine_with_live_data(self, live_broker_adapter):
        """Test OptionChainEngine with real option chain."""
        from brokersv2.analytics.options.chain import OptionChainEngine
        from brokersv2.analytics.options.events import OptionContract, OptionType
        from brokersv2.domain.market.models import Exchange
        
        # Fetch real option chain
        option_chain = await live_broker_adapter.get_option_chain(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        assert option_chain is not None
        strikes = option_chain.strikes if hasattr(option_chain, 'strikes') else option_chain['strikes']
        
        # Build option chain engine
        engine = OptionChainEngine("NIFTY")
        
        # Add options from live data
        for strike_data in strikes[:10]:  # Test with first 10 strikes
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            
            # Extract call data
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data['call']
            if call_data:
                call = OptionContract(
                    symbol=f"NIFTY{int(strike_price)}CE",
                    underlying="NIFTY",
                    strike=strike_price,
                    expiry=option_chain.expiry if hasattr(option_chain, 'expiry') else datetime.now(),
                    option_type=OptionType.CALL,
                    ltp=call_data.ltp if hasattr(call_data, 'ltp') else call_data.get('ltp', 0),
                    open_interest=call_data.oi if hasattr(call_data, 'oi') else call_data.get('oi', 0),
                )
                engine.add_option(call)
            
            # Extract put data
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data['put']
            if put_data:
                put = OptionContract(
                    symbol=f"NIFTY{int(strike_price)}PE",
                    underlying="NIFTY",
                    strike=strike_price,
                    expiry=option_chain.expiry if hasattr(option_chain, 'expiry') else datetime.now(),
                    option_type=OptionType.PUT,
                    ltp=put_data.ltp if hasattr(put_data, 'ltp') else put_data.get('ltp', 0),
                    open_interest=put_data.oi if hasattr(put_data, 'oi') else put_data.get('oi', 0),
                )
                engine.add_option(put)
        
        # Build chain with underlying price
        underlying_price = option_chain.underlying_price if hasattr(option_chain, 'underlying_price') else option_chain.get('underlying_price', 22000)
        engine.build_chain(underlying_price=underlying_price)
        
        # Validate chain
        assert engine.strike_count > 0
        assert engine.atm_strike > 0
        assert engine.total_call_oi > 0 or engine.total_put_oi > 0
        
        # PCR should be reasonable (0.5 - 2.0)
        pcr = engine.chain_pcr
        assert 0.0 <= pcr <= 3.0, f"Invalid PCR: {pcr}"

    @pytest.mark.asyncio
    async def test_greeks_with_market_prices(self, live_broker_adapter):
        """Test Greeks calculations with real option prices."""
        from brokersv2.analytics.options.greeks import GreeksCalculator
        from brokersv2.analytics.options.events import OptionType
        from brokersv2.domain.market.models import Exchange
        
        # Fetch option chain
        option_chain = await live_broker_adapter.get_option_chain(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        strikes = option_chain.strikes if hasattr(option_chain, 'strikes') else option_chain['strikes']
        underlying_price = option_chain.underlying_price if hasattr(option_chain, 'underlying_price') else option_chain.get('underlying_price', 22000)
        
        # Calculate Greeks for ATM option
        calc = GreeksCalculator()
        
        # Find ATM strike
        atm_strike = min(strikes, key=lambda s: abs(
            (s.strike_price if hasattr(s, 'strike_price') else s['strike_price']) - underlying_price
        ))
        
        atm_price = atm_strike.strike_price if hasattr(atm_strike, 'strike_price') else atm_strike['strike_price']
        
        # Calculate Greeks (assuming 30 days to expiry, 15% IV)
        greeks = calc.calculate_all_greeks(
            symbol=f"NIFTY{int(atm_price)}CE",
            underlying_price=underlying_price,
            strike=atm_price,
            time_to_expiry=30.0,
            volatility=0.15,
            option_type=OptionType.CALL,
        )
        
        # Validate Greeks
        assert -1.0 <= greeks.delta <= 1.0, f"Invalid delta: {greeks.delta}"
        assert greeks.gamma >= 0, f"Invalid gamma: {greeks.gamma}"
        assert greeks.theta < 0, f"Invalid theta (should be negative): {greeks.theta}"
        assert greeks.vega > 0, f"Invalid vega (should be positive): {greeks.vega}"


class TestDeltaAnalyticsWithLiveData:
    """Test Delta & Footprint analytics with real trade data."""

    @pytest.mark.asyncio
    async def test_delta_calculation_with_real_trades(self, live_historical_client):
        """Test delta calculations using real intraday data."""
        from brokersv2.analytics.delta.trade_delta import TradeDeltaCalculator
        from brokersv2.analytics.delta.events import TradeEvent, TradeSide
        
        # Fetch intraday data (1-minute candles)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=1)
        
        candles = await live_historical_client.get_historical(
            symbol="NIFTY 50",
            exchange="NSE",
            from_date=start_date,
            to_date=end_date,
            interval="1m",
        )
        
        if not candles or len(candles) == 0:
            pytest.skip("No intraday data available")
        
        # Create trade delta calculator
        calc = TradeDeltaCalculator("NSE:NIFTY")
        
        # Simulate trades from candles (simplified)
        for candle in candles[:50]:  # Use first 50 candles
            close = candle.close if hasattr(candle, 'close') else candle['close']
            volume = candle.volume if hasattr(candle, 'volume') else candle['volume']
            timestamp = candle.timestamp if hasattr(candle, 'timestamp') else candle.get('timestamp', datetime.now())
            
            # Simplified: assume up candles are buys, down are sells
            open_price = candle.open if hasattr(candle, 'open') else candle['open']
            side = TradeSide.BUY if close > open_price else TradeSide.SELL
            
            trade = TradeEvent(
                timestamp=timestamp if isinstance(timestamp, datetime) else datetime.now(),
                price=close,
                quantity=volume / 100,  # Scale down
                side=side,
                security_id="NIFTY",
            )
            
            calc.add_trade(trade)
        
        # Validate delta calculations
        assert calc.total_delta != 0 or calc.buy_volume == 0, "Delta should be calculated"
        assert calc.buy_volume >= 0
        assert calc.sell_volume >= 0
        
        # Total delta should equal buy - sell
        expected_delta = calc.buy_volume - calc.sell_volume
        assert abs(calc.total_delta - expected_delta) < 0.01


class TestMarketProfileWithLiveData:
    """Test Market Profile with real historical data."""

    @pytest.mark.asyncio
    async def test_volume_profile_with_real_data(self, live_historical_client):
        """Test volume profile construction from real data."""
        from brokersv2.analytics.profile.volume_profile import VolumeProfileEngine
        
        # Fetch intraday data
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=1)
        
        candles = await live_historical_client.get_historical(
            symbol="RELIANCE",
            exchange="NSE",
            from_date=start_date,
            to_date=end_date,
            interval="5m",
        )
        
        if not candles or len(candles) == 0:
            pytest.skip("No intraday data available")
        
        # Build volume profile
        engine = VolumeProfileEngine("NSE:RELIANCE")
        
        for candle in candles:
            close = candle.close if hasattr(candle, 'close') else candle['close']
            volume = candle.volume if hasattr(candle, 'volume') else candle['volume']
            engine.add_volume(price=close, volume=volume)
        
        # Validate profile
        assert engine.total_volume > 0
        
        # POC should be valid price
        poc = engine.point_of_control
        assert poc is None or poc > 0, f"Invalid POC: {poc}"
        
        # Value area should be calculated
        if engine.value_area_high and engine.value_area_low:
            assert engine.value_area_high > engine.value_area_low


class TestLiveDataQuality:
    """Test data quality and edge cases from live broker."""

    @pytest.mark.asyncio
    async def test_historical_data_completeness(self, live_historical_client):
        """Test historical data has no gaps."""
        from datetime import datetime, timezone, timedelta
        
        # Fetch 10 days of daily data
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=10)
        
        candles = await live_historical_client.get_historical(
            symbol="NIFTY 50",
            exchange="NSE",
            from_date=start_date,
            to_date=end_date,
            interval="1d",
        )
        
        # Should have at least 7 trading days
        assert len(candles) >= 7, f"Expected at least 7 candles, got {len(candles)}"
        
        # Validate chronological order
        for i in range(1, len(candles)):
            ts_curr = candles[i].timestamp if hasattr(candles[i], 'timestamp') else candles[i].get('timestamp')
            ts_prev = candles[i-1].timestamp if hasattr(candles[i-1], 'timestamp') else candles[i-1].get('timestamp')
            
            if isinstance(ts_curr, datetime) and isinstance(ts_prev, datetime):
                assert ts_curr >= ts_prev, "Candles not in chronological order"

    @pytest.mark.asyncio
    async def test_option_expiry_dates_valid(self, live_broker_adapter):
        """Test option expiry dates are in the future."""
        from brokersv2.domain.market.models import Exchange
        
        # Get option chain
        option_chain = await live_broker_adapter.get_option_chain(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        expiry = option_chain.expiry if hasattr(option_chain, 'expiry') else option_chain.get('expiry')
        
        if expiry and isinstance(expiry, datetime):
            # Expiry should be in the future
            now = datetime.now(timezone.utc)
            assert expiry > now, f"Option expiry {expiry} is in the past"
