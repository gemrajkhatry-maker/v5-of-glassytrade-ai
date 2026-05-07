"""Tests for InstrumentResolver."""

import pytest
from datetime import date
from decimal import Decimal

from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.domain.instrument.resolver import InstrumentResolver
from brokersv2.domain.instrument.registry import InstrumentRegistry
from brokersv2.core.types import Exchange, OptionType, SecurityId


class TestInstrumentResolver:
    """Tests for InstrumentResolver."""

    def test_resolve_equity(self):
        """Test resolving equity instrument."""
        registry = InstrumentRegistry()
        resolver = InstrumentResolver(registry)
        
        inst = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        registry.register(inst, SecurityId("12345"), "NSE_EQ")
        
        resolved = resolver.resolve("NSE:RELIANCE")
        assert resolved is not None
        assert resolved.symbol == "RELIANCE"

    def test_resolve_option_from_symbol(self):
        """Test resolving option from symbol string."""
        registry = InstrumentRegistry()
        resolver = InstrumentResolver(registry)
        
        inst = CanonicalInstrument.create_option(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry=date(2024, 4, 25),
            strike=Decimal("22000"),
            option_type=OptionType.CALL,
            lot_size=25,
        )
        registry.register(inst, SecurityId("52175"), "NSE_FNO")
        
        resolved = resolver.resolve_option("NIFTY", date(2024, 4, 25), Decimal("22000"), OptionType.CALL)
        assert resolved is not None
        assert resolved.strike == Decimal("22000")

    def test_resolve_nearest_expiry(self):
        """Test resolving nearest expiry."""
        registry = InstrumentRegistry()
        resolver = InstrumentResolver(registry)
        
        expiries = [
            date(2024, 4, 25),
            date(2024, 5, 30),
            date(2024, 6, 27),
        ]
        
        for expiry in expiries:
            inst = CanonicalInstrument.create_option(
                symbol="NIFTY",
                exchange=Exchange.NSE,
                expiry=expiry,
                strike=Decimal("22000"),
                option_type=OptionType.CALL,
                lot_size=25,
            )
            registry.register(inst, SecurityId(f"52175_{expiry}"), "NSE_FNO")
        
        # Should return nearest expiry
        result = resolver.resolve_option("NIFTY", None, Decimal("22000"), OptionType.CALL)
        assert result is not None
        assert result.expiry == date(2024, 4, 25)

    def test_resolve_nonexistent(self):
        """Test resolving nonexistent instrument returns None."""
        registry = InstrumentRegistry()
        resolver = InstrumentResolver(registry)
        
        assert resolver.resolve("NSE:NONEXISTENT") is None

    def test_get_atm_strike(self):
        """Test getting ATM strike from options chain."""
        registry = InstrumentRegistry()
        resolver = InstrumentResolver(registry)
        
        expiry = date(2024, 4, 25)
        underlying_price = Decimal("22150")
        
        # Create options chain
        for strike in range(21000, 23001, 500):
            for opt_type in [OptionType.CALL, OptionType.PUT]:
                inst = CanonicalInstrument.create_option(
                    symbol="NIFTY",
                    exchange=Exchange.NSE,
                    expiry=expiry,
                    strike=Decimal(str(strike)),
                    option_type=opt_type,
                    lot_size=25,
                )
                registry.register(inst, SecurityId(f"{strike}_{opt_type.value}"), "NSE_FNO")
        
        atm_strike = resolver.get_atm_strike("NIFTY", Exchange.NSE, expiry, underlying_price)
        assert atm_strike == Decimal("22000")  # Nearest to 22150
