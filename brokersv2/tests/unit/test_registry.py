"""Tests for InstrumentRegistry."""

import pytest
from datetime import date
from decimal import Decimal

from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.domain.instrument.registry import InstrumentRegistry
from brokersv2.core.types import Exchange, Segment, InstrumentType, OptionType, InternalUid, SecurityId


class TestInstrumentRegistry:
    """Tests for InstrumentRegistry."""

    def test_empty_registry(self):
        """Test that new registry is empty."""
        registry = InstrumentRegistry()
        assert registry.instrument_count == 0
        assert registry.lookup_by_symbol("RELIANCE", Exchange.NSE) is None

    def test_register_equity(self):
        """Test registering equity instrument."""
        registry = InstrumentRegistry()
        instrument = CanonicalInstrument.create_equity(
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            lot_size=1,
            tick_size=Decimal("0.01"),
        )
        
        registry.register(
            instrument=instrument,
            security_id=SecurityId("12345"),
            exchange_segment="NSE_EQ",
        )
        
        assert registry.instrument_count == 1
        assert registry.lookup_by_symbol("RELIANCE", Exchange.NSE) is not None

    def test_lookup_by_security_id(self):
        """Test O(1) lookup by security ID."""
        registry = InstrumentRegistry()
        instrument = CanonicalInstrument.create_equity(
            symbol="TCS",
            exchange=Exchange.NSE,
            lot_size=1,
        )
        
        security_id = SecurityId("52146")
        registry.register(instrument, security_id, "NSE_EQ")
        
        result = registry.lookup_by_security_id(security_id)
        assert result is not None
        assert result.symbol == "TCS"
        assert result.exchange == Exchange.NSE

    def test_lookup_by_symbol_case_insensitive(self):
        """Test symbol lookup is case-insensitive."""
        registry = InstrumentRegistry()
        instrument = CanonicalInstrument.create_equity("INFY", Exchange.NSE)
        registry.register(instrument, SecurityId("500209"), "NSE_EQ")
        
        assert registry.lookup_by_symbol("INFY", Exchange.NSE) is not None
        assert registry.lookup_by_symbol("infy", Exchange.NSE) is not None
        assert registry.lookup_by_symbol("Infy", Exchange.NSE) is not None

    def test_lookup_nonexistent_returns_none(self):
        """Test lookup returns None for nonexistent instrument."""
        registry = InstrumentRegistry()
        assert registry.lookup_by_symbol("UNKNOWN", Exchange.NSE) is None
        assert registry.lookup_by_security_id(SecurityId("999999")) is None

    def test_register_multiple_instruments(self):
        """Test registering multiple instruments."""
        registry = InstrumentRegistry()
        
        instruments = [
            ("RELIANCE", SecurityId("12345")),
            ("TCS", SecurityId("52146")),
            ("INFY", SecurityId("500209")),
        ]
        
        for symbol, sec_id in instruments:
            inst = CanonicalInstrument.create_equity(symbol, Exchange.NSE)
            registry.register(inst, sec_id, "NSE_EQ")
        
        assert registry.instrument_count == 3
        
        for symbol, sec_id in instruments:
            assert registry.lookup_by_symbol(symbol, Exchange.NSE) is not None
            assert registry.lookup_by_security_id(sec_id) is not None

    def test_register_option(self):
        """Test registering option instrument."""
        registry = InstrumentRegistry()
        instrument = CanonicalInstrument.create_option(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry=date(2024, 4, 25),
            strike=Decimal("22000"),
            option_type=OptionType.CALL,
            lot_size=25,
        )
        
        registry.register(
            instrument,
            SecurityId("52175"),
            "NSE_FNO",
            broker_symbol="NIFTY24APR22000CE",
        )
        
        result = registry.lookup_by_security_id(SecurityId("52175"))
        assert result is not None
        assert result.is_option()
        assert result.strike == Decimal("22000")

    def test_register_future(self):
        """Test registering future instrument."""
        registry = InstrumentRegistry()
        instrument = CanonicalInstrument.create_future(
            symbol="NIFTY",
            exchange=Exchange.NSE,
            expiry=date(2024, 5, 30),
            lot_size=25,
        )
        
        registry.register(instrument, SecurityId("52176"), "NSE_FNO")
        
        result = registry.lookup_by_security_id(SecurityId("52176"))
        assert result is not None
        assert result.is_future()

    def test_get_options_chain(self):
        """Test getting options chain for underlying."""
        registry = InstrumentRegistry()
        expiry = date(2024, 4, 25)
        
        # Register multiple options
        for strike in [21000, 21500, 22000, 22500, 23000]:
            for opt_type in [OptionType.CALL, OptionType.PUT]:
                instrument = CanonicalInstrument.create_option(
                    symbol="NIFTY",
                    exchange=Exchange.NSE,
                    expiry=expiry,
                    strike=Decimal(str(strike)),
                    option_type=opt_type,
                    lot_size=25,
                )
                registry.register(
                    instrument,
                    SecurityId(f"{strike}_{opt_type.value}"),
                    "NSE_FNO",
                )
        
        chain = registry.get_options_chain("NIFTY", Exchange.NSE, expiry)
        assert len(chain) == 10  # 5 strikes × 2 types

    def test_get_expiries(self):
        """Test getting available expiries for underlying."""
        registry = InstrumentRegistry()
        
        expiries = [
            date(2024, 4, 25),
            date(2024, 5, 30),
            date(2024, 6, 27),
        ]
        
        for expiry in expiries:
            instrument = CanonicalInstrument.create_option(
                symbol="BANKNIFTY",
                exchange=Exchange.NSE,
                expiry=expiry,
                strike=Decimal("48000"),
                option_type=OptionType.CALL,
                lot_size=15,
            )
            registry.register(instrument, SecurityId(f"BN_{expiry}"), "NSE_FNO")
        
        available = registry.get_expiries("BANKNIFTY", Exchange.NSE)
        assert len(available) == 3
        assert date(2024, 4, 25) in available

    def test_update_snapshot(self):
        """Test updating registry with new snapshot."""
        registry = InstrumentRegistry()
        
        # Initial instruments
        inst1 = CanonicalInstrument.create_equity("RELIANCE", Exchange.NSE)
        registry.register(inst1, SecurityId("1001"), "NSE_EQ")
        
        # Update with new instruments
        inst2 = CanonicalInstrument.create_equity("TCS", Exchange.NSE)
        new_instruments = [inst2]
        
        # In real implementation, this would replace snapshot
        # For now, just test registration
        for inst in new_instruments:
            registry.register(inst, SecurityId("1002"), "NSE_EQ")
        
        assert registry.instrument_count == 2

    def test_thread_safety(self):
        """Test thread-safe concurrent access."""
        import threading
        
        registry = InstrumentRegistry()
        errors = []
        
        def register_instruments(start_idx: int, count: int):
            try:
                for i in range(start_idx, start_idx + count):
                    inst = CanonicalInstrument.create_equity(
                        f"STOCK{i}", Exchange.NSE
                    )
                    registry.register(inst, SecurityId(f"{i}"), "NSE_EQ")
            except Exception as e:
                errors.append(e)
        
        # Multiple threads registering simultaneously
        threads = [
            threading.Thread(target=register_instruments, args=(i * 100, 100))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert registry.instrument_count == 500

    def test_clear_registry(self):
        """Test clearing all instruments."""
        registry = InstrumentRegistry()
        
        for i in range(10):
            inst = CanonicalInstrument.create_equity(f"STOCK{i}", Exchange.NSE)
            registry.register(inst, SecurityId(f"{i}"), "NSE_EQ")
        
        assert registry.instrument_count == 10
        
        registry.clear()
        
        assert registry.instrument_count == 0
        assert registry.lookup_by_symbol("STOCK0", Exchange.NSE) is None

    def test_get_all_instruments(self):
        """Test getting all registered instruments."""
        registry = InstrumentRegistry()
        
        symbols = ["RELIANCE", "TCS", "INFY"]
        for symbol in symbols:
            inst = CanonicalInstrument.create_equity(symbol, Exchange.NSE)
            registry.register(inst, SecurityId(symbol), "NSE_EQ")
        
        all_instruments = registry.get_all_instruments()
        assert len(all_instruments) == 3
        
        instrument_symbols = {inst.symbol for inst in all_instruments}
        assert instrument_symbols == set(symbols)
