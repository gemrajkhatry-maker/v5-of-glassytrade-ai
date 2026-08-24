"""Tests for DhanExchangeResolver and ResolvedExchange.

Moved out of test_facade.py when the dead DhanFacade layer was removed;
the resolver is a live production dependency of DhanBroker.
"""

import pytest

from brokers.broker.dhan.application.exchange_resolver import (
    DhanExchangeResolver,
    ResolvedExchange,
)
from brokers.broker.dhan.domain import ExchangeSegment
from brokers.broker.types import Exchange


# =============================================================================
# DhanExchangeResolver Tests
# =============================================================================

class TestDhanExchangeResolver:
    """Tests for DhanExchangeResolver."""

    def test_resolve_nifty_index(self):
        """Test resolving NIFTY as NFO index."""
        result = DhanExchangeResolver.resolve("NIFTY")

        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "index"

    def test_resolve_banknifty_index(self):
        """Test resolving BANKNIFTY as NFO index."""
        result = DhanExchangeResolver.resolve("BANKNIFTY")

        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "index"

    def test_resolve_sensex_index(self):
        """Test resolving SENSEX as BFO index (SENSEX is a BSE index)."""
        result = DhanExchangeResolver.resolve("SENSEX")

        assert result.exchange == Exchange.BFO
        assert result.segment == ExchangeSegment.BSE_FNO
        assert result.symbol_type == "index"

    def test_resolve_reliance_equity(self):
        """Test resolving RELIANCE as NSE equity."""
        result = DhanExchangeResolver.resolve("RELIANCE")

        assert result.exchange == Exchange.NSE
        assert result.segment == ExchangeSegment.NSE_EQ
        assert result.symbol_type == "equity"

    def test_resolve_tcs_equity(self):
        """Test resolving TCS as NSE equity."""
        result = DhanExchangeResolver.resolve("TCS")

        assert result.exchange == Exchange.NSE
        assert result.segment == ExchangeSegment.NSE_EQ
        assert result.symbol_type == "equity"

    def test_resolve_crudeoil_commodity(self):
        """Test resolving CRUDEOIL as MCX commodity."""
        result = DhanExchangeResolver.resolve("CRUDEOIL")

        assert result.exchange == Exchange.MCX
        assert result.segment == ExchangeSegment.MCX
        assert result.symbol_type == "commodity"

    def test_resolve_gold_commodity(self):
        """Test resolving GOLD as MCX commodity."""
        result = DhanExchangeResolver.resolve("GOLD")

        assert result.exchange == Exchange.MCX
        assert result.segment == ExchangeSegment.MCX
        assert result.symbol_type == "commodity"

    def test_resolve_option_symbol(self):
        """Test resolving option symbol pattern."""
        result = DhanExchangeResolver.resolve("NIFTY23FEB18000CE")

        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "index_option"

    def test_resolve_futures_symbol(self):
        """Test resolving futures symbol pattern."""
        result = DhanExchangeResolver.resolve("NIFTY23FEBFUT")

        assert result.exchange == Exchange.NFO
        assert result.segment == ExchangeSegment.NSE_FNO
        assert result.symbol_type == "future"

    def test_resolve_unknown_symbol_defaults_to_nse(self):
        """Test that unknown symbols default to NSE equity."""
        result = DhanExchangeResolver.resolve("UNKNOWNSYMBOL")

        assert result.exchange == Exchange.NSE
        assert result.segment == ExchangeSegment.NSE_EQ
        assert result.symbol_type == "equity"

    def test_resolve_with_explicit_exchange(self):
        """Test that explicit exchange overrides auto-detection."""
        result = DhanExchangeResolver.resolve("NIFTY", Exchange.MCX)

        assert result.exchange == Exchange.MCX
        assert result.segment == ExchangeSegment.MCX

    def test_resolve_case_insensitive(self):
        """Test that symbol resolution is case insensitive."""
        result_lower = DhanExchangeResolver.resolve("nifty")
        result_upper = DhanExchangeResolver.resolve("NIFTY")
        result_mixed = DhanExchangeResolver.resolve("NiFtY")

        assert result_lower.exchange == result_upper.exchange == result_mixed.exchange

    def test_extract_underlying_from_option(self):
        """Test extracting underlying from option symbol."""
        underlying = DhanExchangeResolver._extract_underlying("NIFTY23FEB18000CE")
        assert underlying == "NIFTY"

        underlying = DhanExchangeResolver._extract_underlying("BANKNIFTY23FEB40000PE")
        assert underlying == "BANKNIFTY"

    def test_extract_underlying_from_futures(self):
        """Test extracting underlying from futures symbol."""
        underlying = DhanExchangeResolver._extract_underlying("NIFTY23FEBFUT")
        assert underlying == "NIFTY"


# =============================================================================
# ResolvedExchange Tests
# =============================================================================

class TestResolvedExchange:
    """Tests for ResolvedExchange dataclass."""

    def test_resolved_exchange_creation(self):
        """Test creating ResolvedExchange."""
        resolved = ResolvedExchange(
            exchange=Exchange.NFO,
            segment=ExchangeSegment.NSE_FNO,
            symbol_type="index"
        )

        assert resolved.exchange == Exchange.NFO
        assert resolved.segment == ExchangeSegment.NSE_FNO
        assert resolved.symbol_type == "index"

    def test_resolved_exchange_frozen(self):
        """Test that ResolvedExchange is immutable."""
        resolved = ResolvedExchange(
            exchange=Exchange.NFO,
            segment=ExchangeSegment.NSE_FNO,
            symbol_type="index"
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            resolved.exchange = Exchange.NSE
