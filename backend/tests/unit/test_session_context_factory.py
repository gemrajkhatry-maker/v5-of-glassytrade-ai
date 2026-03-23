"""Unit tests for SessionContextFactory.

Tests the centralized session info retrieval that eliminates DRY violations.
"""

import pytest
from unittest.mock import MagicMock, patch


from app.domain.fabio_ai.services.session_context_factory import SessionContextFactory


class TestSessionContextFactory:
    """Test suite for SessionContextFactory."""

    def test_normalize_market_nfo(self):
        """NFO should normalize to NSE."""
        assert SessionContextFactory._normalize_market("NFO") == "NSE"

    def test_normalize_market_bse(self):
        """BSE should normalize to NSE."""
        assert SessionContextFactory._normalize_market("BSE") == "NSE"

    def test_normalize_market_nse(self):
        """NSE should remain NSE."""
        assert SessionContextFactory._normalize_market("NSE") == "NSE"

    def test_normalize_market_mcx(self):
        """MCX should remain MCX."""
        assert SessionContextFactory._normalize_market("MCX") == "MCX"

    @patch('app.domain.fabio_ai.services.session_context_factory.Settings')
    def test_get_exchange_for_symbol_mcx(self, mock_settings):
        """MCX underlyings should return MCX."""
        mock_settings.return_value.DEFAULT_EXCHANGE = "MCX"
        assert SessionContextFactory.get_exchange_for_symbol("CRUDEOIL 17 MAR 6100 CALL") == "MCX"
        assert SessionContextFactory.get_exchange_for_symbol("GOLD 100 CE") == "MCX"
        assert SessionContextFactory.get_exchange_for_symbol("NATURALGAS 280 PE") == "MCX"

    @patch('app.domain.fabio_ai.services.session_context_factory.Settings')
    def test_get_exchange_for_symbol_nse(self, mock_settings):
        """NSE underlyings should return NSE."""
        mock_settings.return_value.DEFAULT_EXCHANGE = "NSE"
        assert SessionContextFactory.get_exchange_for_symbol("NIFTY 22500 CE") == "NSE"
        assert SessionContextFactory.get_exchange_for_symbol("BANKNIFTY 47000 PE") == "NSE"

    @patch('app.domain.fabio_ai.services.session_context_factory.Settings')
    def test_get_exchange_for_symbol_with_prefix(self, mock_settings):
        """Should handle exchange prefixes."""
        mock_settings.return_value.DEFAULT_EXCHANGE = "MCX"
        # Note: symbol format "NSE:NIFTY 24 DEC 25000 CE" (with spaces) works
        assert SessionContextFactory.get_exchange_for_symbol("NSE:NIFTY 24 DEC 25000 CE") == "NSE"
        assert SessionContextFactory.get_exchange_for_symbol("MCX:CRUDEOIL 17 MAR 6100 CE") == "MCX"

    @patch('app.domain.fabio_ai.services.session_context_factory.Settings')
    def test_get_exchange_for_symbol_unknown(self, mock_settings):
        """Unknown symbol should fallback to settings default."""
        mock_settings.return_value.DEFAULT_EXCHANGE = "MCX"
        result = SessionContextFactory.get_exchange_for_symbol("UNKNOWN_SYMBOL")
        # Should return settings default (not crash)
        assert result == "MCX"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])