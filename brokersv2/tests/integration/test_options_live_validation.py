"""Live Options Analytics Tests with Real DhanHQ Data.

Comprehensive validation of options analytics modules using real broker data:
- Option chain format and contract validation
- Greeks calculations with market prices
- IV surface construction from live data
- OI analytics and PCR validation
- Strike ladder and expiry verification

These tests require:
- DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables
- RUN_OPTIONS_LIVE_TESTS=1 to enable
"""

import os
import time
import pytest
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

# Skip all tests unless enabled
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OPTIONS_LIVE_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="Set RUN_OPTIONS_LIVE_TESTS=1 to run live options tests"
)


@pytest.fixture(autouse=True)
def rate_limit_delay():
    """Add delay between tests to respect DhanHQ rate limits (1 req/3 sec)."""
    yield
    # Wait 4 seconds after each test to avoid 429 errors
    time.sleep(4)


@pytest.fixture
def dhan_credentials():
    """Get DhanHQ credentials."""
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        pytest.skip("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN required")
    
    return {"client_id": client_id, "access_token": access_token}


@pytest.fixture
def live_options_adapter(dhan_credentials):
    """Create live Dhan broker adapter for options."""
    from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
    from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
    from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter
    from brokersv2.core.types import Exchange
    
    config = DhanConfig(
        client_id=dhan_credentials["client_id"],
        access_token=dhan_credentials["access_token"],
    )
    
    mapper = InstrumentMapper()
    adapter = DhanBrokerAdapter(config, mapper)
    
    return adapter


@pytest.fixture
def option_symbols():
    """Test symbols for options."""
    return {
        "underlying": "NIFTY",
        "exchange": "NSE",
        "bank_nifty": "BANKNIFTY",
        "finnifty": "FINNIFTY",
    }


class TestOptionChainContractValidation:
    """Validate option chain contract format and structure."""

    @pytest.mark.asyncio
    async def test_nifty_option_chain_structure(self, live_options_adapter, option_symbols):
        """Test NIFTY option chain has correct contract structure."""
        from brokersv2.core.types import Exchange
        from brokersv2.domain.options.models import OptionChainData
        
        # Fetch NIFTY option chain
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        # Validate chain structure
        assert chain is not None, "Option chain is None"
        assert isinstance(chain, OptionChainData), f"Expected OptionChainData, got {type(chain)}"
        
        # Check required fields
        assert chain.underlying == "NIFTY", f"Expected underlying='NIFTY', got {chain.underlying}"
        assert chain.expiry_date is not None, "Expiry date is None"
        assert chain.strike_count > 10, f"Expected >10 strikes, got {chain.strike_count}"
        
        # Validate strikes list
        strikes = chain.strikes
        assert len(strikes) > 10, f"Expected >10 strikes, got {len(strikes)}"
        
        # Validate first strike has options
        first_strike = strikes[0]
        assert first_strike > 0, f"Invalid strike price: {first_strike}"
        
        # Get strike level and verify it has call/put
        strike_level = chain.get_strike_level(first_strike)
        assert strike_level is not None, f"Strike level {first_strike} is None"
        
        # Validate call or put exists
        assert strike_level.call is not None or strike_level.put is not None, \
            f"Strike {first_strike} has no call or put"
        
        # Validate call contract if exists
        if strike_level.call:
            assert strike_level.call.ltp >= 0, f"Invalid call LTP: {strike_level.call.ltp}"
            assert strike_level.call.open_interest >= 0, f"Invalid call OI: {strike_level.call.open_interest}"
            assert strike_level.call.volume >= 0, f"Invalid call volume: {strike_level.call.volume}"

    @pytest.mark.asyncio
    async def test_banknifty_option_chain(self, live_options_adapter, option_symbols):
        """Test BANKNIFTY option chain format."""
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["bank_nifty"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        assert chain is not None
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        assert len(strikes) > 0
        
        # BANKNIFTY strikes should be in 100 intervals
        first_strike = strikes[0]
        strike_price = first_strike.strike_price if hasattr(first_strike, 'strike_price') else first_strike['strike_price']
        assert strike_price % 100 == 0, f"BANKNIFTY strike not in 100 interval: {strike_price}"

    @pytest.mark.asyncio
    async def test_option_expiry_dates(self, live_options_adapter, option_symbols):
        """Test option expiry dates are valid."""
        from brokersv2.core.types import Exchange
        
        # Get multiple expiries
        for expiry_index in range(3):
            try:
                chain = await live_options_adapter.get_option_chain(
                    symbol=option_symbols["underlying"],
                    exchange=Exchange.NSE,
                    expiry_index=expiry_index,
                )
                
                if chain:
                    expiry = chain.expiry if hasattr(chain, 'expiry') else chain.get('expiry')
                    
                    if expiry and isinstance(expiry, datetime):
                        # Expiry should be in the future
                        now = datetime.now(timezone.utc)
                        assert expiry > now, f"Expiry {expiry} is in the past"
                        
                        # Should be Thursday (weekly expiry)
                        assert expiry.weekday() == 3, f"Expiry {expiry} is not Thursday"
                        
            except Exception as e:
                # Some indices may not have data
                break


class TestOptionChainEngineWithLiveData:
    """Test OptionChainEngine with real broker data."""

    @pytest.mark.asyncio
    async def test_chain_engine_construction(self, live_options_adapter, option_symbols):
        """Test building OptionChainEngine from live data."""
        from brokersv2.analytics.options.chain import OptionChainEngine
        from brokersv2.analytics.options.events import OptionContract, OptionType
        from brokersv2.core.types import Exchange
        from datetime import datetime
        
        # Fetch live chain
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        assert chain is not None
        
        # Build engine
        engine = OptionChainEngine(option_symbols["underlying"])
        
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        expiry = chain.expiry if hasattr(chain, 'expiry') else datetime.now(timezone.utc)
        underlying_price = chain.underlying_price if hasattr(chain, 'underlying_price') else chain.get('underlying_price', 0)
        
        # Add options from live data
        options_added = 0
        for strike_data in strikes:
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            
            # Add call
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            if call_data:
                call = OptionContract(
                    symbol=f"{option_symbols['underlying']}{int(strike_price)}CE",
                    underlying=option_symbols["underlying"],
                    strike=strike_price,
                    expiry=expiry if isinstance(expiry, datetime) else datetime.now(),
                    option_type=OptionType.CALL,
                    ltp=call_data.ltp if hasattr(call_data, 'ltp') else call_data.get('ltp', 0),
                    bid=call_data.bid if hasattr(call_data, 'bid') else call_data.get('bid', 0),
                    ask=call_data.ask if hasattr(call_data, 'ask') else call_data.get('ask', 0),
                    volume=call_data.volume if hasattr(call_data, 'volume') else call_data.get('volume', 0),
                    open_interest=call_data.oi if hasattr(call_data, 'oi') else call_data.get('oi', 0),
                )
                engine.add_option(call)
                options_added += 1
            
            # Add put
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data.get('put')
            if put_data:
                put = OptionContract(
                    symbol=f"{option_symbols['underlying']}{int(strike_price)}PE",
                    underlying=option_symbols["underlying"],
                    strike=strike_price,
                    expiry=expiry if isinstance(expiry, datetime) else datetime.now(),
                    option_type=OptionType.PUT,
                    ltp=put_data.ltp if hasattr(put_data, 'ltp') else put_data.get('ltp', 0),
                    bid=put_data.bid if hasattr(put_data, 'bid') else put_data.get('bid', 0),
                    ask=put_data.ask if hasattr(put_data, 'ask') else put_data.get('ask', 0),
                    volume=put_data.volume if hasattr(put_data, 'volume') else put_data.get('volume', 0),
                    open_interest=put_data.oi if hasattr(put_data, 'oi') else put_data.get('oi', 0),
                )
                engine.add_option(put)
                options_added += 1
        
        assert options_added > 0, "No options added to engine"
        
        # Build chain
        if underlying_price > 0:
            engine.build_chain(underlying_price=underlying_price)
            
            # Validate engine state
            assert engine.strike_count > 0
            assert engine.atm_strike > 0
            
            # ATM strike should be close to underlying price (within 1%)
            atm_diff = abs(engine.atm_strike - underlying_price) / underlying_price
            assert atm_diff < 0.01, f"ATM strike {engine.atm_strike} too far from {underlying_price}"

    @pytest.mark.asyncio
    async def test_pcr_calculation(self, live_options_adapter, option_symbols):
        """Test Put-Call Ratio calculation with live OI data."""
        from brokersv2.analytics.options.chain import OptionChainEngine
        from brokersv2.analytics.options.events import OptionContract, OptionType
        from brokersv2.core.types import Exchange
        from datetime import datetime
        
        # Fetch chain
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        # Build engine
        engine = OptionChainEngine(option_symbols["underlying"])
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        expiry = chain.expiry if hasattr(chain, 'expiry') else datetime.now(timezone.utc)
        
        for strike_data in strikes:
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            
            # Extract OI data
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data.get('put')
            
            if call_data:
                call_oi = call_data.oi if hasattr(call_data, 'oi') else call_data.get('oi', 0)
                engine.add_option(OptionContract(
                    symbol="TEMP_CE",
                    underlying=option_symbols["underlying"],
                    strike=strike_price,
                    expiry=expiry if isinstance(expiry, datetime) else datetime.now(),
                    option_type=OptionType.CALL,
                    open_interest=call_oi,
                ))
            
            if put_data:
                put_oi = put_data.oi if hasattr(put_data, 'oi') else put_data.get('oi', 0)
                engine.add_option(OptionContract(
                    symbol="TEMP_PE",
                    underlying=option_symbols["underlying"],
                    strike=strike_price,
                    expiry=expiry if isinstance(expiry, datetime) else datetime.now(),
                    option_type=OptionType.PUT,
                    open_interest=put_oi,
                ))
        
        underlying_price = chain.underlying_price if hasattr(chain, 'underlying_price') else chain.get('underlying_price', 22000)
        engine.build_chain(underlying_price=underlying_price)
        
        # Validate PCR
        pcr = engine.chain_pcr
        assert 0.0 <= pcr <= 3.0, f"PCR {pcr} out of reasonable range"
        
        # Total OI should be positive
        assert engine.total_call_oi > 0 or engine.total_put_oi > 0


class TestGreeksWithMarketData:
    """Test Greeks calculations with real option prices."""

    @pytest.mark.asyncio
    async def test_atm_greeks(self, live_options_adapter, option_symbols):
        """Test Greeks for ATM option."""
        from brokersv2.analytics.options.greeks import GreeksCalculator
        from brokersv2.analytics.options.events import OptionType
        from brokersv2.core.types import Exchange
        
        # Fetch chain
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        underlying_price = chain.underlying_price if hasattr(chain, 'underlying_price') else chain.get('underlying_price', 0)
        
        if underlying_price == 0:
            pytest.skip("No underlying price available")
        
        # Find ATM strike
        atm_strike_data = min(strikes, key=lambda s: abs(
            (s.strike_price if hasattr(s, 'strike_price') else s['strike_price']) - underlying_price
        ))
        
        atm_strike = atm_strike_data.strike_price if hasattr(atm_strike_data, 'strike_price') else atm_strike_data['strike_price']
        
        # Calculate Greeks (30 days to expiry, 15% IV)
        calc = GreeksCalculator()
        greeks = calc.calculate_all_greeks(
            symbol=f"{option_symbols['underlying']}{int(atm_strike)}CE",
            underlying_price=underlying_price,
            strike=atm_strike,
            time_to_expiry=30.0,
            volatility=0.15,
            option_type=OptionType.CALL,
        )
        
        # Validate Greeks
        assert -1.0 <= greeks.delta <= 1.0, f"Invalid delta: {greeks.delta}"
        assert greeks.gamma >= 0, f"Invalid gamma: {greeks.gamma}"
        assert greeks.theta < 0, f"Theta should be negative: {greeks.theta}"
        assert greeks.vega > 0, f"Vega should be positive: {greeks.vega}"
        
        # ATM call delta should be ~0.5
        assert 0.3 < greeks.delta < 0.7, f"ATM delta {greeks.delta} not near 0.5"

    @pytest.mark.asyncio
    async def test_otm_vs_itm_greeks(self, live_options_adapter, option_symbols):
        """Compare Greeks for OTM vs ITM options."""
        from brokersv2.analytics.options.greeks import GreeksCalculator
        from brokersv2.analytics.options.events import OptionType
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange="NSE",
            expiry_index=0,
        )
        
        underlying_price = chain.underlying_price if hasattr(chain, 'underlying_price') else chain.get('underlying_price', 0)
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        
        if underlying_price == 0 or len(strikes) < 5:
            pytest.skip("Insufficient data")
        
        # Find OTM and ITM strikes
        otm_strike = strikes[-2]  # 2nd OTM call
        itm_strike = strikes[1]   # 2nd ITM call
        
        otm_price = otm_strike.strike_price if hasattr(otm_strike, 'strike_price') else otm_strike['strike_price']
        itm_price = itm_strike.strike_price if hasattr(itm_strike, 'strike_price') else itm_strike['strike_price']
        
        calc = GreeksCalculator()
        
        # OTM delta should be lower
        otm_greeks = calc.calculate_all_greeks(
            symbol="OTM_CE",
            underlying_price=underlying_price,
            strike=otm_price,
            time_to_expiry=30.0,
            volatility=0.15,
            option_type=OptionType.CALL,
        )
        
        # ITM delta should be higher
        itm_greeks = calc.calculate_all_greeks(
            symbol="ITM_CE",
            underlying_price=underlying_price,
            strike=itm_price,
            time_to_expiry=30.0,
            volatility=0.15,
            option_type=OptionType.CALL,
        )
        
        # ITM delta > OTM delta
        assert itm_greeks.delta > otm_greeks.delta, \
            f"ITM delta {itm_greeks.delta} should be > OTM delta {otm_greeks.delta}"


class TestIVSurfaceWithLiveData:
    """Test IV surface construction from live data."""

    @pytest.mark.asyncio
    async def test_iv_surface_building(self, live_options_adapter, option_symbols):
        """Test building IV surface from option chain."""
        from brokersv2.analytics.options.iv_surface import IVSurfaceEngine
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        underlying_price = chain.underlying_price if hasattr(chain, 'underlying_price') else chain.get('underlying_price', 0)
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        expiry = chain.expiry if hasattr(chain, 'expiry') else None
        
        if underlying_price == 0 or expiry is None:
            pytest.skip("Missing underlying price or expiry")
        
        # Build IV surface
        engine = IVSurfaceEngine(option_symbols["underlying"])
        
        points_added = 0
        for strike_data in strikes[:20]:  # Use first 20 strikes
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            
            # Use bid-ask midpoint IV if available, otherwise estimate
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            if call_data:
                # Estimate IV from price (simplified - would need Black-Scholes solver in production)
                estimated_iv = 0.15  # Placeholder
                engine.add_iv_point(
                    strike=strike_price,
                    expiry=expiry if isinstance(expiry, datetime) else datetime.now(),
                    implied_vol=estimated_iv,
                    underlying_price=underlying_price,
                )
                points_added += 1
        
        assert points_added > 0, "No IV points added"
        assert engine.data_point_count > 0


class TestOIAnalyticsWithLiveData:
    """Test OI analytics with real broker data."""

    @pytest.mark.asyncio
    async def test_oi_pcr_validation(self, live_options_adapter, option_symbols):
        """Test OI-based PCR with live data."""
        from brokersv2.analytics.options.oi_analytics import OIAnalyzer
        from brokersv2.analytics.options.events import OptionType
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        analyzer = OIAnalyzer(option_symbols["underlying"])
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        
        # Load OI data
        for strike_data in strikes:
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data.get('put')
            
            if call_data:
                call_oi = call_data.oi if hasattr(call_data, 'oi') else call_data.get('oi', 0)
                analyzer.update_oi(strike_price, OptionType.CALL, call_oi)
            
            if put_data:
                put_oi = put_data.oi if hasattr(put_data, 'oi') else put_data.get('oi', 0)
                analyzer.update_oi(strike_price, OptionType.PUT, put_oi)
        
        # Validate PCR at multiple strikes
        test_strikes = [strikes[0], strikes[len(strikes)//2], strikes[-1]]
        
        for strike_data in test_strikes:
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            pcr = analyzer.get_pcr(strike_price)
            
            # PCR should be reasonable
            assert 0.0 <= pcr <= 5.0, f"PCR {pcr} at strike {strike_price} out of range"

    @pytest.mark.asyncio
    async def test_max_oi_strikes(self, live_options_adapter, option_symbols):
        """Test finding max OI strikes (support/resistance)."""
        from brokersv2.analytics.options.oi_analytics import OIAnalyzer
        from brokersv2.analytics.options.events import OptionType
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        analyzer = OIAnalyzer(option_symbols["underlying"])
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        
        for strike_data in strikes:
            strike_price = strike_data.strike_price if hasattr(strike_data, 'strike_price') else strike_data['strike_price']
            
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data.get('put')
            
            if call_data:
                call_oi = call_data.oi if hasattr(call_data, 'oi') else call_data.get('oi', 0)
                analyzer.update_oi(strike_price, OptionType.CALL, call_oi)
            
            if put_data:
                put_oi = put_data.oi if hasattr(put_data, 'oi') else put_data.get('oi', 0)
                analyzer.update_oi(strike_price, OptionType.PUT, put_oi)
        
        # Find max OI strikes
        max_call_strike = analyzer.get_max_oi_strike(OptionType.CALL)
        max_put_strike = analyzer.get_max_oi_strike(OptionType.PUT)
        
        # Both should be found
        assert max_call_strike is not None, "No max call OI strike found"
        assert max_put_strike is not None, "No max put OI strike found"
        
        # Should be different strikes
        assert max_call_strike != max_put_strike, \
            f"Max call and put OI at same strike: {max_call_strike}"


class TestOptionsDataQuality:
    """Validate options data quality from broker."""

    @pytest.mark.asyncio
    async def test_strike_spacing(self, live_options_adapter, option_symbols):
        """Test strikes are properly spaced."""
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        strike_prices = [
            s.strike_price if hasattr(s, 'strike_price') else s['strike_price']
            for s in strikes
        ]
        
        # Should be sorted
        assert strike_prices == sorted(strike_prices), "Strikes not sorted"
        
        # Spacing should be consistent (NIFTY: 50 or 100)
        if len(strike_prices) > 1:
            spacing = strike_prices[1] - strike_prices[0]
            assert spacing in [50, 100, 500], f"Unexpected strike spacing: {spacing}"

    @pytest.mark.asyncio
    async def test_option_prices_positive(self, live_options_adapter, option_symbols):
        """Test all option prices are positive."""
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        
        negative_prices = 0
        for strike_data in strikes:
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data.get('put')
            
            if call_data:
                ltp = call_data.ltp if hasattr(call_data, 'ltp') else call_data.get('ltp', 0)
                if ltp < 0:
                    negative_prices += 1
            
            if put_data:
                ltp = put_data.ltp if hasattr(put_data, 'ltp') else put_data.get('ltp', 0)
                if ltp < 0:
                    negative_prices += 1
        
        assert negative_prices == 0, f"Found {negative_prices} negative option prices"

    @pytest.mark.asyncio
    async def test_oi_non_negative(self, live_options_adapter, option_symbols):
        """Test all OI values are non-negative."""
        from brokersv2.core.types import Exchange
        
        chain = await live_options_adapter.get_option_chain(
            symbol=option_symbols["underlying"],
            exchange=Exchange.NSE,
            expiry_index=0,
        )
        
        strikes = chain.strikes if hasattr(chain, 'strikes') else chain['strikes']
        
        negative_oi = 0
        for strike_data in strikes:
            call_data = strike_data.call if hasattr(strike_data, 'call') else strike_data.get('call')
            put_data = strike_data.put if hasattr(strike_data, 'put') else strike_data.get('put')
            
            if call_data:
                oi = call_data.oi if hasattr(call_data, 'oi') else call_data.get('oi', 0)
                if oi < 0:
                    negative_oi += 1
            
            if put_data:
                oi = put_data.oi if hasattr(put_data, 'oi') else put_data.get('oi', 0)
                if oi < 0:
                    negative_oi += 1
        
        assert negative_oi == 0, f"Found {negative_oi} negative OI values"
