"""Tests for dual-feed futures architecture.

These tests validate the core components for futures data flow:
- UnderlyingFuturesProvider mapping
- Futures routing build
- SessionCache underlying data management
- AMT service data source selection
"""

import pytest
from datetime import datetime, timedelta

from app.domain.services.underlying_futures_provider import (
    UnderlyingFuturesProvider,
    DualFeedMapping,
    InstrumentConfig,
)
from app.application.services.session_cache import SessionCache


class TestUnderlyingFuturesProvider:
    """Test futures mapping and routing."""

    @pytest.fixture
    def provider(self):
        return UnderlyingFuturesProvider()

    def test_mapping_crudeoil_call(self, provider):
        """Test CRUDEOIL option maps to correct futures."""
        mapping = provider.get_mapping("CRUDEOIL 14 MAY 10150 CALL")
        assert mapping is not None
        assert mapping.underlying_symbol == "CRUDEOIL25MAYFUT"
        assert mapping.underlying == "CRUDEOIL"
        assert mapping.exchange == "MCX"

    def test_mapping_nifty_call(self, provider):
        """Test NIFTY option maps to correct futures."""
        mapping = provider.get_mapping("NIFTY 22 MAY 24000 CALL")
        assert mapping is not None
        assert mapping.underlying_symbol == "NIFTY25MAYFUT"
        assert mapping.underlying == "NIFTY"
        assert mapping.exchange == "NSE"

    def test_mapping_gold_call(self, provider):
        """Test GOLD option maps to correct futures."""
        mapping = provider.get_mapping("GOLD 14 MAY 8900 CALL")
        assert mapping is not None
        assert mapping.underlying_symbol == "GOLD25MAYFUT"
        assert mapping.underlying == "GOLD"
        assert mapping.exchange == "MCX"

    def test_mapping_put_option(self, provider):
        """Test PUT option maps correctly."""
        mapping = provider.get_mapping("CRUDEOIL 16 MAY 10200 PUT")
        assert mapping is not None
        assert mapping.underlying_symbol == "CRUDEOIL25MAYFUT"

    def test_build_futures_routing(self, provider):
        """Test building futures to options routing map."""
        symbols = [
            "CRUDEOIL 14 MAY 10150 CALL",
            "CRUDEOIL 16 MAY 10200 PUT",
            "NIFTY 22 MAY 24000 CALL",
        ]
        fut_to_opts, futures_list = provider.build_futures_routing(symbols)

        assert "CRUDEOIL25MAYFUT" in futures_list
        assert "NIFTY25MAYFUT" in futures_list
        assert set(fut_to_opts["CRUDEOIL25MAYFUT"]) == {
            "CRUDEOIL 14 MAY 10150 CALL",
            "CRUDEOIL 16 MAY 10200 PUT",
        }

    def test_mapping_unknown_underlying(self, provider):
        """Test unknown underlying returns None."""
        mapping = provider.get_mapping("UNKNOWN 14 MAY 100 CALL")
        assert mapping is None


class TestSessionCacheUnderlyingData:
    """Test SessionCache underlying data management."""

    @pytest.fixture
    def simple_session(self):
        """Create a simple session object with real lock."""
        from threading import Lock

        class SimpleSession:
            def __init__(self):
                self.data = []
                self._lock = Lock()

        return SimpleSession()

    @pytest.fixture
    def cache(self, simple_session):
        return SessionCache(simple_session)

    def test_underlying_data_not_present_initially(self, cache):
        """Test has_underlying_data returns False when no data."""
        assert cache.has_underlying_data(5) is False

    def test_underlying_data_after_update(self, cache):
        """Test has_underlying_data returns True after update."""
        from app.domain.trading.models.value_objects import OHLC

        # Add 5 underlying candles
        for i in range(5):
            ohlc = OHLC(
                time=datetime.now().isoformat(),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000 + i * 100,
            )
            cache.update_underlying_data(ohlc)

        assert cache.has_underlying_data(5) is True

    def test_underlying_data_insufficient(self, cache):
        """Test has_underlying_data returns False with insufficient data."""
        from app.domain.trading.models.value_objects import OHLC

        # Add only 3 underlying candles (less than 5 required)
        for i in range(3):
            ohlc = OHLC(
                time=datetime.now().isoformat(),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000 + i * 100,
            )
            cache.update_underlying_data(ohlc)

        assert cache.has_underlying_data(5) is False

    def test_get_underlying_data_returns_list(self, cache):
        """Test get_underlying_data returns the stored data."""
        from app.domain.trading.models.value_objects import OHLC

        ohlc = OHLC(
            time=datetime.now().isoformat(),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
        )
        cache.update_underlying_data(ohlc)

        data = cache.get_underlying_data()
        assert data is not None
        assert len(data) == 1
        assert data[0] == ohlc

    def test_get_option_data_returns_session_data(self, simple_session, cache):
        """Test get_option_data returns session candle buffer."""
        from app.domain.trading.models.value_objects import OHLC

        # Add option candles
        for i in range(3):
            ohlc = OHLC(
                time=datetime.now().isoformat(),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000 + i * 100,
            )
            simple_session.data.append(ohlc)

        option_data = cache.get_option_data()
        assert len(option_data) == 3


class TestAMTServiceDataSource:
    """Test AMT service data source selection."""

    @pytest.fixture
    def simple_session(self):
        """Create a simple session object with real lock."""
        from threading import Lock

        class SimpleSession:
            def __init__(self):
                self.data = []
                self._lock = Lock()

        return SimpleSession()

    @pytest.fixture
    def cache_no_underlying(self, simple_session):
        """Cache with no underlying data."""
        return SessionCache(simple_session)

    @pytest.fixture
    def cache_with_underlying(self, simple_session):
        """Cache with underlying data."""
        from app.domain.trading.models.value_objects import OHLC

        cache = SessionCache(simple_session)

        # Add 5 underlying candles
        for i in range(5):
            ohlc = OHLC(
                time=datetime.now().isoformat(),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1000 + i * 100,
            )
            cache.update_underlying_data(ohlc)

        return cache

    def test_select_data_source_underlying(self, cache_with_underlying):
        """Test selects underlying data when available."""
        from app.application.services.amt_service import AMTService

        service = AMTService()
        data, source = service._select_amt_data_source(cache_with_underlying, 5)

        assert source == "underlying"
        assert len(data) >= 5

    def test_select_data_source_option(self, cache_no_underlying):
        """Test selects option data when no underlying."""
        from app.application.services.amt_service import AMTService

        service = AMTService()
        data, source = service._select_amt_data_source(cache_no_underlying, 5)

        assert source == "option"
        assert data == []


class TestDualFeedIntegration:
    """Integration tests for the complete dual-feed flow."""

    def test_complete_flow(self):
        """Test complete flow from option symbol to underlying data selection."""
        provider = UnderlyingFuturesProvider()
        symbols = ["CRUDEOIL 14 MAY 10150 CALL", "NIFTY 22 MAY 24000 CALL"]

        # 1. Get futures mapping
        mappings = {}
        for sym in symbols:
            m = provider.get_mapping(sym)
            assert m is not None
            mappings[sym] = m

        # 2. Build routing
        fut_to_opts, futures_list = provider.build_futures_routing(symbols)

        # 3. Verify routing
        assert len(futures_list) == 2  # One for each underlying
        assert "CRUDEOIL25MAYFUT" in futures_list
        assert "NIFTY25MAYFUT" in futures_list

        # 4. Verify each option maps to correct futures
        for sym, mapping in mappings.items():
            assert fut_to_opts[mapping.underlying_symbol] is not None
            assert sym in fut_to_opts[mapping.underlying_symbol]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])