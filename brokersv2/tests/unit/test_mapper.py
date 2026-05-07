"""Tests for instrument mapper."""

import pytest
from datetime import date
from decimal import Decimal

from brokersv2.infrastructure.dhan_adapter.mapper import (
    InstrumentMapper,
    InstrumentRegistry,
    BrokerInstrumentMapping,
)
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, Segment, InstrumentType, OptionType, SecurityId


class TestInstrumentMapper:
    """Tests for InstrumentMapper O(1) lookups."""
    
    @pytest.fixture
    def mapper(self):
        return InstrumentMapper()
    
    @pytest.fixture
    def equity(self):
        return CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            lot_size=1,
        )
    
    @pytest.fixture
    def option(self):
        return CanonicalInstrument.create_option(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry=date(2024, 4, 25),
            strike=Decimal("25000"),
            option_type=OptionType.CALL,
            lot_size=25,
        )
    
    def test_register_and_lookup_security_id(self, mapper, equity):
        """Test registration and security_id lookup."""
        security_id = SecurityId("12345")
        
        mapper.register(
            canonical=equity,
            security_id=security_id,
            exchange_segment="NSE_EQ",
        )
        
        # O(1) lookup
        result = mapper.security_id_to_canonical(security_id)
        assert result == equity
    
    def test_canonical_to_security_id(self, mapper, equity):
        """Test canonical to security_id translation."""
        security_id = SecurityId("12345")
        
        mapper.register(
            canonical=equity,
            security_id=security_id,
            exchange_segment="NSE_EQ",
        )
        
        result = mapper.canonical_to_security_id(equity)
        assert result == security_id
    
    def test_symbol_to_canonical(self, mapper, equity):
        """Test symbol + exchange to canonical lookup."""
        security_id = SecurityId("12345")
        
        mapper.register(
            canonical=equity,
            security_id=security_id,
            exchange_segment="NSE_EQ",
        )
        
        result = mapper.symbol_to_canonical("RELIANCE", Exchange.NSE)
        assert result == equity
    
    def test_broker_mapping(self, mapper, equity):
        """Test broker mapping retrieval."""
        security_id = SecurityId("12345")
        
        mapper.register(
            canonical=equity,
            security_id=security_id,
            exchange_segment="NSE_EQ",
            broker_symbol="RELIANCE",
        )
        
        mapping = mapper.canonical_to_broker_mapping(equity)
        assert mapping is not None
        assert mapping.security_id == security_id
        assert mapping.exchange_segment == "NSE_EQ"
    
    def test_ws_symbol_registration(self, mapper, equity):
        """Test websocket symbol registration."""
        security_id = SecurityId("12345")
        
        mapper.register(
            canonical=equity,
            security_id=security_id,
            exchange_segment="NSE_EQ",
        )
        
        mapper.register_ws_symbol("RELIANCE_EQ", equity)
        
        result = mapper.ws_symbol_to_canonical("RELIANCE_EQ")
        assert result == equity
    
    def test_get_all_instruments(self, mapper, equity, option):
        """Test getting all registered instruments."""
        mapper.register(equity, SecurityId("1"), "NSE_EQ")
        mapper.register(option, SecurityId("2"), "NSE_FNO")
        
        all_instruments = mapper.get_all_instruments()
        assert len(all_instruments) == 2
        assert equity in all_instruments
        assert option in all_instruments


class TestInstrumentRegistry:
    """Tests for InstrumentRegistry."""
    
    def test_load_static_nse(self):
        """Test loading static NSE instruments."""
        mapper = InstrumentMapper()
        registry = InstrumentRegistry(mapper)
        
        count = registry.load_static_nse()
        
        assert count == 10  # Number of hardcoded equities
        assert mapper.symbol_to_canonical("RELIANCE", Exchange.NSE) is not None
        assert mapper.symbol_to_canonical("NIFTY", Exchange.NSE) is not None