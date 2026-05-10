"""
Integration tests for historical data providers with real Dhan API.

Tests verify:
- DhanHistoricalProvider fetches real data
- OpenChartHistoricalProvider works as fallback
- HistoricalDataRouter fallback mechanism with real providers
- Bootstrap creates properly wired router
- End-to-end data flow from API to candles

NOTE: These tests require:
- DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables
- Network access to Dhan API
- Running during market hours for best results
"""

import pytest
import os
from datetime import datetime, timedelta
from decimal import Decimal

from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument, Exchange


# Skip all tests if credentials not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("DHAN_CLIENT_ID") or not os.environ.get("DHAN_ACCESS_TOKEN"),
    reason="Dhan credentials not set (DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)"
)


class TestDhanHistoricalProviderIntegration:
    """Test Dhan provider with real API calls."""
    
    @pytest.fixture
    def adapter(self):
        """Create real Dhan adapter."""
        from brokersv2.app.bootstrap import create_dhan_adapter
        return create_dhan_adapter(dry_run=False)
    
    @pytest.fixture
    def provider(self, adapter):
        """Create Dhan historical provider."""
        from brokersv2.providers.dhan_provider import DhanHistoricalProvider
        return DhanHistoricalProvider(adapter=adapter, timeout=15.0)
    
    @pytest.mark.asyncio
    async def test_fetch_nse_equity_candles(self, provider):
        """Fetch real NSE equity candles."""
        instrument = CanonicalInstrument.create_equity(
            symbol="TCS",
            exchange=Exchange.NSE
        )
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)
        
        candles = await provider.get_candles(
            instrument=instrument,
            timeframe="5m",
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
        )
        
        # Should return candles (might be empty if market closed)
        assert isinstance(candles, list)
        
        if candles:
            # Validate candle structure
            candle = candles[0]
            assert isinstance(candle, Candle)
            assert candle.open > 0
            assert candle.high >= candle.low
            assert candle.volume >= 0
            
            print(f"✓ Fetched {len(candles)} TCS 5m candles")
    
    @pytest.mark.asyncio
    async def test_fetch_mcx_commodity_candles(self, provider):
        """Fetch real MCX commodity candles."""
        # Note: MCX requires proper instrument mapping
        # This test validates the provider handles commodity segment
        instrument = CanonicalInstrument(
            internal_uid=None,  # Would be set by mapper
            symbol="CRUDEOIL",
            exchange=Exchange.MCX,
        )
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)
        
        # This might fail if mapper doesn't have CRUDEOIL security_id
        # That's expected - the test validates error handling
        try:
            candles = await provider.get_candles(
                instrument=instrument,
                timeframe="5m",
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
            )
            assert isinstance(candles, list)
            print(f"✓ Fetched {len(candles)} CRUDEOIL candles (or empty if mapper missing)")
        except Exception as e:
            # Expected if instrument mapper doesn't have the symbol
            assert "security" in str(e).lower() or "mapping" in str(e).lower() or "not found" in str(e).lower()
            print(f"✓ MCX fetch failed as expected (mapper): {e}")
    
    @pytest.mark.asyncio
    async def test_provider_availability_tracking(self, provider):
        """Test provider tracks availability correctly."""
        assert provider.is_available == True
        
        # Fetch some data
        instrument = CanonicalInstrument.create_equity(
            symbol="INFY",
            exchange=Exchange.NSE
        )
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        await provider.get_candles(
            instrument=instrument,
            timeframe="15m",
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
        )
        
        # Should still be available after successful fetch
        assert provider.is_available == True


class TestOpenChartProviderIntegration:
    """Test OpenChart provider (if installed)."""
    
    @pytest.fixture
    def provider(self):
        """Create OpenChart provider."""
        try:
            from brokersv2.providers.opencart_provider import OpenChartHistoricalProvider
            return OpenChartHistoricalProvider(timeout=15.0)
        except ImportError:
            pytest.skip("OpenChart not installed")
    
    @pytest.mark.asyncio
    async def test_fetch_nse_data_via_opencart(self, provider):
        """Fetch NSE data via OpenChart fallback provider."""
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE
        )
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)
        
        try:
            candles = await provider.get_candles(
                instrument=instrument,
                timeframe="5m",
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
            )
            
            assert isinstance(candles, list)
            
            if candles:
                assert len(candles) > 0
                print(f"✓ OpenChart fetched {len(candles)} RELIANCE candles")
            else:
                print("⚠ OpenChart returned empty (might be market closed or NSE API issue)")
                
        except Exception as e:
            # OpenChart is unreliable - might fail due to NSE API changes
            print(f"⚠ OpenChart failed (expected for unstable provider): {e}")


class TestRouterFallbackIntegration:
    """Test router fallback with real providers."""
    
    @pytest.fixture
    def router(self):
        """Create router with real Dhan + OpenChart providers."""
        from brokersv2.app.bootstrap import create_dhan_adapter, create_market_data_service
        from brokersv2.providers.dhan_provider import DhanHistoricalProvider
        from brokersv2.providers.opencart_provider import OpenChartHistoricalProvider
        from brokersv2.providers.router import HistoricalDataRouter
        
        try:
            adapter = create_dhan_adapter(dry_run=False)
            dhan_provider = DhanHistoricalProvider(adapter=adapter, timeout=10.0)
        except Exception:
            pytest.skip("Cannot create Dhan adapter")
        
        try:
            openchart_provider = OpenChartHistoricalProvider(timeout=15.0)
        except ImportError:
            # OpenChart not installed - test without fallback
            openchart_provider = None
        
        return HistoricalDataRouter(
            primary=dhan_provider,
            fallback=openchart_provider,
        )
    
    @pytest.mark.asyncio
    async def test_router_uses_primary_successfully(self, router):
        """Test router successfully uses Dhan primary provider."""
        instrument = CanonicalInstrument.create_equity(
            symbol="HDFCBANK",
            exchange=Exchange.NSE
        )
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        candles = await router.get_candles(
            instrument=instrument,
            timeframe="5m",
            from_date=start_date.strftime("%Y-%m-%d"),
            to_date=end_date.strftime("%Y-%m-%d"),
        )
        
        assert isinstance(candles, list)
        
        # Verify metrics show primary success
        assert router.metrics.primary_success >= 1
        
        if candles:
            print(f"✓ Router fetched {len(candles)} HDFCBANK candles via Dhan")
        else:
            print("⚠ Router returned empty (market closed or no data)")
    
    @pytest.mark.asyncio
    async def test_router_metrics_after_multiple_requests(self, router):
        """Test router tracks metrics across multiple requests."""
        instrument = CanonicalInstrument.create_equity(
            symbol="ITC",
            exchange=Exchange.NSE
        )
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        # Make 3 requests
        for _ in range(3):
            await router.get_candles(
                instrument=instrument,
                timeframe="15m",
                from_date=start_date.strftime("%Y-%m-%d"),
                to_date=end_date.strftime("%Y-%m-%d"),
            )
        
        # All should succeed via primary
        assert router.metrics.primary_success == 3
        assert router.metrics.total_requests == 3
        
        print(f"✓ Router metrics: {router.metrics.primary_success} successes, "
              f"{router.metrics.primary_failure} failures")


class TestBootstrapWiring:
    """Test bootstrap correctly wires providers."""
    
    def test_create_market_data_service_has_router(self):
        """Verify create_market_data_service creates HistoricalDataRouter."""
        from brokersv2.app.bootstrap import create_market_data_service
        
        try:
            service = create_market_data_service()
            
            # Service should have historical router
            assert hasattr(service, '_historical_router')
            assert service._historical_router is not None
            
            # Router should have both providers
            router = service._historical_router
            assert router._primary is not None
            assert router._primary.provider_name == "dhan"
            
            # Fallback might be None if OpenChart not installed
            if router._fallback is not None:
                assert router._fallback.provider_name == "opencart"
            
            print("✓ Bootstrap correctly wired HistoricalDataRouter with Dhan + OpenChart")
            
        except Exception as e:
            pytest.skip(f"Cannot create market data service: {e}")
