"""Tests for symbol parser."""

import pytest
from datetime import date
from decimal import Decimal

from brokersv2.domain.instrument.parser import (
    parse_option_symbol,
    parse_future_symbol,
    parse_symbol,
    _last_thursday_of_month,
)
from brokersv2.core.types import Exchange, InstrumentType, OptionType


class TestSymbolParser:
    """Tests for symbol parsing."""
    
    def test_parse_option_symbol_call(self):
        """Test parsing call option symbol."""
        result = parse_option_symbol("NIFTY24APR25000CE")
        
        assert result is not None
        assert result.symbol == "NIFTY"
        assert result.is_option() is True
        assert result.option_type == OptionType.CALL
        assert result.strike == Decimal("25000")
    
    def test_parse_option_symbol_put(self):
        """Test parsing put option symbol."""
        result = parse_option_symbol("BANKNIFTY24JAN48000PE")
        
        assert result is not None
        assert result.symbol == "BANKNIFTY"
        assert result.is_option() is True
        assert result.option_type == OptionType.PUT
    
    def test_parse_option_invalid(self):
        """Test invalid option symbol returns None."""
        assert parse_option_symbol("INVALID") is None
    
    def test_parse_future_symbol(self):
        """Test parsing future symbol."""
        result = parse_future_symbol("NIFTY24APR")
        
        assert result is not None
        assert result.symbol == "NIFTY"
        assert result.is_future() is True
    
    def test_parse_symbol_equity(self):
        """Test parsing equity symbol."""
        result = parse_symbol("RELIANCE")
        
        assert result is not None
        assert result.symbol == "RELIANCE"
        assert result.is_equity() is True
    
    def test_parse_symbol_option_first(self):
        """Test that parse_symbol tries option first."""
        result = parse_symbol("NIFTY24APR25000CE")
        assert result is not None
        assert result.is_option() is True
    
    def test_last_thursday_calculation(self):
        """Test last Thursday calculation."""
        # April 2024 - last Thursday is 25th
        result = _last_thursday_of_month(2024, 4)
        assert result.day == 25
        assert result.month == 4
        assert result.year == 2024