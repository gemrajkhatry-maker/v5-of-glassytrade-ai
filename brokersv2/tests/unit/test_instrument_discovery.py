"""Tests for Instrument Discovery - high-level search and filtering APIs."""
import pytest
from datetime import date, timedelta
from decimal import Decimal
from brokersv2.domain.instrument.discovery import (
    InstrumentDiscovery,
    SearchFilter,
    SearchResult,
    DiscoveryError,
)
from brokersv2.domain.instrument.registry import InstrumentRegistry
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, SecurityId, InstrumentType, OptionType


@pytest.fixture
def registry():
    """Create registry with test instruments."""
    reg = InstrumentRegistry()
    
    # Add equities
    for symbol in ["RELIANCE", "TCS", "INFY", "HDFC", "ICICI"]:
        instrument = CanonicalInstrument.create_equity(
            symbol=symbol,
            exchange=Exchange.NSE,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
        reg.register(
            instrument=instrument,
            security_id=SecurityId(f"EQ_{symbol}"),
            exchange_segment="NSE_EQ",
        )
    
    # Add NIFTY options chain for multiple expiries
    base_expiry = date(2026, 1, 29)
    strikes = [23000, 23500, 24000, 24500, 25000]
    
    for i, expiry_offset in enumerate([0, 7, 14]):  # Weekly expiries
        expiry = base_expiry + timedelta(days=expiry_offset)
        for strike in strikes:
            for opt_type in ["CE", "PE"]:
                symbol = f"NIFTY{expiry.strftime('%d%b').upper()}{strike}{opt_type}"
                instrument = CanonicalInstrument.create_option(
                    symbol=symbol,
                    exchange=Exchange.NFO,
                    expiry=expiry,
                    strike=Decimal(str(strike)),
                    option_type=OptionType.CALL if opt_type == "CE" else OptionType.PUT,
                    lot_size=75,
                    tick_size=Decimal("0.05"),
                )
                reg.register(
                    instrument=instrument,
                    security_id=SecurityId(f"OPT_{symbol}"),
                    exchange_segment="NSE_FNO",
                )
    
    # Add NIFTY futures
    for expiry_offset in [0, 30, 60]:
        expiry = base_expiry + timedelta(days=expiry_offset)
        symbol = f"NIFTY{expiry.strftime('%d%b').upper()}FUT"
        instrument = CanonicalInstrument.create_future(
            symbol=symbol,
            exchange=Exchange.NFO,
            expiry=expiry,
            lot_size=75,
            tick_size=Decimal("0.05"),
        )
        reg.register(
            instrument=instrument,
            security_id=SecurityId(f"FUT_{symbol}"),
            exchange_segment="NSE_FNO",
        )
    
    return reg


@pytest.fixture
def discovery(registry):
    """Create InstrumentDiscovery instance."""
    return InstrumentDiscovery(registry)


class TestSearchFilter:
    """Test search filter value object."""

    def test_default_filter(self):
        """Test default search filter."""
        filt = SearchFilter()
        
        assert filt.exchange is None
        assert filt.instrument_type is None
        assert filt.query is None
        assert filt.limit == 100

    def test_filter_with_exchange(self):
        """Test filter with exchange."""
        filt = SearchFilter(exchange=Exchange.NSE)
        assert filt.exchange == Exchange.NSE

    def test_filter_with_type(self):
        """Test filter with instrument type."""
        filt = SearchFilter(instrument_type=InstrumentType.OPTION)
        assert filt.instrument_type == InstrumentType.OPTION

    def test_filter_with_query(self):
        """Test filter with search query."""
        filt = SearchFilter(query="RELIANCE")
        assert filt.query == "RELIANCE"


class TestInstrumentDiscovery:
    """Test high-level instrument discovery APIs."""

    def test_find_equity_by_symbol(self, discovery):
        """Test finding equity by symbol."""
        result = discovery.find_equity("RELIANCE", Exchange.NSE)
        
        assert result is not None
        assert result.symbol == "RELIANCE"
        assert result.exchange == Exchange.NSE

    def test_find_equity_not_found(self, discovery):
        """Test finding non-existent equity."""
        result = discovery.find_equity("NONEXISTENT", Exchange.NSE)
        assert result is None

    def test_find_option_by_strike(self, discovery):
        """Test finding specific option by strike."""
        expiry = date(2026, 1, 29)
        
        call = discovery.find_option(
            underlying="NIFTY",
            expiry=expiry,
            strike=Decimal("24000"),
            option_type="CE",
            exchange=Exchange.NFO,
        )
        
        assert call is not None
        assert "24000" in call.symbol
        assert "CE" in call.symbol

        put = discovery.find_option(
            underlying="NIFTY",
            expiry=expiry,
            strike=Decimal("24000"),
            option_type="PE",
            exchange=Exchange.NFO,
        )
        
        assert put is not None
        assert "24000" in put.symbol
        assert "PE" in put.symbol

    def test_find_option_not_found(self, discovery):
        """Test finding non-existent option."""
        expiry = date(2026, 1, 29)
        
        result = discovery.find_option(
            underlying="NIFTY",
            expiry=expiry,
            strike=Decimal("99999"),
            option_type="CE",
            exchange=Exchange.NFO,
        )
        
        assert result is None

    def test_get_option_chain(self, discovery):
        """Test getting full options chain."""
        expiry = date(2026, 1, 29)
        
        chain = discovery.get_option_chain("NIFTY", Exchange.NFO, expiry)
        
        assert len(chain) == 10  # 5 strikes x 2 types (CE/PE)
        
        # Verify both calls and puts
        calls = [c for c in chain if "CE" in c.symbol]
        puts = [c for c in chain if "PE" in c.symbol]
        assert len(calls) == 5
        assert len(puts) == 5

    def test_get_option_chain_empty(self, discovery):
        """Test getting options chain for non-existent expiry."""
        expiry = date(2030, 1, 1)
        
        chain = discovery.get_option_chain("NIFTY", Exchange.NFO, expiry)
        assert len(chain) == 0

    def test_get_nearest_expiry(self, discovery):
        """Test finding nearest expiry."""
        current_date = date(2026, 1, 29)
        
        nearest = discovery.get_nearest_expiry("NIFTY", Exchange.NFO, current_date)
        
        assert nearest is not None
        assert nearest == date(2026, 1, 29)  # Should be the base expiry

    def test_get_all_expiries(self, discovery):
        """Test getting all available expiries."""
        expiries = discovery.get_all_expiries("NIFTY", Exchange.NFO)
        
        assert len(expiries) >= 3  # At least 3 expiries
        assert expiries[0] < expiries[-1]  # Sorted ascending

    def test_get_atm_strike(self, discovery):
        """Test calculating ATM strike."""
        # NIFTY strikes: 23000, 23500, 24000, 24500, 25000
        atm = discovery.get_atm_strike("NIFTY", Decimal("24100"), Exchange.NFO)
        
        assert atm == Decimal("24000")  # Closest to 24100

    def test_get_atm_strike_exact_match(self, discovery):
        """Test ATM strike with exact match."""
        atm = discovery.get_atm_strike("NIFTY", Decimal("24000"), Exchange.NFO)
        assert atm == Decimal("24000")

    def test_get_atm_strike_midway(self, discovery):
        """Test ATM strike when LTP is midway between strikes."""
        # 24250 is midway between 24000 and 24500, should round down
        atm = discovery.get_atm_strike("NIFTY", Decimal("24250"), Exchange.NFO)
        assert atm in [Decimal("24000"), Decimal("24500")]

    def test_search_instruments_by_query(self, discovery):
        """Test searching instruments by query string."""
        results = discovery.search_instruments(query="RELIANCE")
        
        assert len(results) >= 1
        assert any(r.symbol == "RELIANCE" for r in results)

    def test_search_instruments_by_exchange(self, discovery):
        """Test searching instruments by exchange."""
        results = discovery.search_instruments(exchange=Exchange.NFO)
        
        assert len(results) > 5  # Options + futures
        assert all(r.exchange == Exchange.NFO for r in results)

    def test_search_instruments_by_type(self, discovery):
        """Test searching instruments by type."""
        results = discovery.search_instruments(instrument_type=InstrumentType.OPTION)
        
        assert len(results) == 30  # 5 strikes x 3 expiries x 2 types
        assert all("CE" in r.symbol or "PE" in r.symbol for r in results)

    def test_search_instruments_combined_filters(self, discovery):
        """Test searching with multiple filters."""
        results = discovery.search_instruments(
            query="NIFTY",
            exchange=Exchange.NFO,
            instrument_type=InstrumentType.FUTURE,
        )
        
        assert len(results) >= 1
        assert all("FUT" in r.symbol for r in results)

    def test_search_with_limit(self, discovery):
        """Test search with result limit."""
        results = discovery.search_instruments(limit=5)
        
        assert len(results) <= 5

    def test_search_case_insensitive(self, discovery):
        """Test case-insensitive search."""
        results_lower = discovery.search_instruments(query="reliance")
        results_upper = discovery.search_instruments(query="RELIANCE")
        
        assert len(results_lower) == len(results_upper)

    def test_get_underlying_symbols(self, discovery):
        """Test getting all underlying symbols."""
        underlyings = discovery.get_underlying_symbols(exchange=Exchange.NFO)
        
        assert "NIFTY" in underlyings
        assert len(underlyings) >= 1

    def test_get_futures_chain(self, discovery):
        """Test getting futures chain."""
        futures = discovery.get_futures_chain("NIFTY", Exchange.NFO)
        
        assert len(futures) >= 3  # At least 3 monthly expiries
        
        # Verify sorted by expiry
        for i in range(len(futures) - 1):
            assert futures[i].expiry <= futures[i + 1].expiry

    def test_filter_active_instruments(self, discovery):
        """Test filtering to only active instruments."""
        # All our test instruments are "active"
        active = discovery.get_active_instruments(Exchange.NSE)
        
        assert len(active) >= 5  # 5 equities

    def test_get_lot_size(self, discovery):
        """Test getting lot size for instrument."""
        lot_size = discovery.get_lot_size("RELIANCE", Exchange.NSE)
        assert lot_size == 1
        
        # Options should have lot size 75
        expiry = date(2026, 1, 29)
        option = discovery.find_option("NIFTY", expiry, Decimal("24000"), "CE", Exchange.NFO)
        assert option is not None
        assert option.lot_size == 75

    def test_get_tick_size(self, discovery):
        """Test getting tick size for instrument."""
        tick_size = discovery.get_tick_size("RELIANCE", Exchange.NSE)
        assert tick_size == Decimal("0.01")

    def test_discovery_error_handling(self):
        """Test error handling with empty registry."""
        empty_reg = InstrumentRegistry()
        disc = InstrumentDiscovery(empty_reg)
        
        # Should return None, not raise error
        result = disc.find_equity("RELIANCE", Exchange.NSE)
        assert result is None

    def test_performance_search_large_dataset(self, discovery):
        """Test search performance with reasonable dataset."""
        import time
        
        # Search should be fast (O(1) lookups)
        start = time.time()
        for _ in range(100):
            discovery.search_instruments(query="NIFTY", exchange=Exchange.NFO)
        elapsed = time.time() - start
        
        assert elapsed < 1.0  # 100 searches should take <1 second


class TestSearchResult:
    """Test SearchResult value object."""

    def test_search_result_creation(self):
        """Test creating search result."""
        instrument = CanonicalInstrument.create_equity(
            symbol="TEST",
            exchange=Exchange.NSE,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
        
        result = SearchResult(
            instrument=instrument,
            match_score=1.0,
            match_reason="exact_symbol",
        )
        
        assert result.instrument == instrument
        assert result.match_score == 1.0
        assert result.match_reason == "exact_symbol"

    def test_search_result_sorting(self):
        """Test search results sorted by match score."""
        results = [
            SearchResult(instrument=None, match_score=0.5, match_reason="partial"),
            SearchResult(instrument=None, match_score=1.0, match_reason="exact"),
            SearchResult(instrument=None, match_score=0.8, match_reason="contains"),
        ]
        
        # Sort by match_score descending
        sorted_results = sorted(results, key=lambda r: r.match_score, reverse=True)
        
        assert sorted_results[0].match_score == 1.0
        assert sorted_results[1].match_score == 0.8
        assert sorted_results[2].match_score == 0.5
