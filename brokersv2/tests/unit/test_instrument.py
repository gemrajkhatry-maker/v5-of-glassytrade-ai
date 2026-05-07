"""Tests for canonical instrument models."""

import pytest
from datetime import date
from decimal import Decimal

from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, Segment, InstrumentType, OptionType


class TestCanonicalInstrument:
    """Tests for CanonicalInstrument."""
    
    def test_create_equity(self):
        """Test equity instrument creation."""
        inst = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
        
        assert inst.symbol == "RELIANCE"
        assert inst.exchange == Exchange.NSE
        assert inst.segment == Segment.EQUITY
        assert inst.instrument_type == InstrumentType.EQUITY
        assert inst.lot_size == 1
        assert inst.tick_size == Decimal("0.01")
    
    def test_create_option(self):
        """Test option instrument creation."""
        expiry = date(2024, 4, 25)
        inst = CanonicalInstrument.create_option(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry=expiry,
            strike=Decimal("25000"),
            option_type=OptionType.CALL,
            lot_size=25,
        )
        
        assert inst.symbol == "NIFTY"
        assert inst.is_option() is True
        assert inst.expiry == expiry
        assert inst.strike == Decimal("25000")
        assert inst.option_type == OptionType.CALL
        assert inst.lot_size == 25
    
    def test_create_future(self):
        """Test future instrument creation."""
        expiry = date(2024, 5, 30)
        inst = CanonicalInstrument.create_future(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry=expiry,
            lot_size=25,
        )
        
        assert inst.symbol == "NIFTY"
        assert inst.is_future() is True
        assert inst.expiry == expiry
        assert inst.strike is None
    
    def test_canonical_symbol(self):
        """Test canonical symbol format."""
        inst = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        assert inst.canonical_symbol() == "NSE:RELIANCE"
    
    def test_equality_by_internal_uid(self):
        """Test that instruments are equal by internal_uid."""
        inst1 = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        inst2 = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        
        # Different internal_uid means not equal
        assert inst1 != inst2
        
        # Same internal_uid means equal
        inst3 = CanonicalInstrument(
            internal_uid=inst1.internal_uid,
            symbol="TCS",
            exchange=Exchange.NSE,
            segment=Segment.EQUITY,
            instrument_type=InstrumentType.EQUITY,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
        assert inst1 == inst3
    
    def test_hash_by_internal_uid(self):
        """Test that hash is based on internal_uid for O(1) lookups."""
        inst1 = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        inst2 = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        
        # Can be used in sets/dicts
        instrument_set = {inst1, inst2}
        assert len(instrument_set) == 2  # Different UIDs
        
        # Same UID should deduplicate
        inst3 = CanonicalInstrument(
            internal_uid=inst1.internal_uid,
            symbol="TCS",
            exchange=Exchange.NSE,
            segment=Segment.EQUITY,
            instrument_type=InstrumentType.EQUITY,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
        instrument_set = {inst1, inst3}
        assert len(instrument_set) == 1  # Same UID