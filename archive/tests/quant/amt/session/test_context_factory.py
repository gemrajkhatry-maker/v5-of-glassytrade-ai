"""Unit tests for SessionContextFactory.

Ported from backend/tests/unit/test_session_context_factory.py.
"""

import pytest

from quant.amt.session.context_factory import SessionContextFactory
from quant.contracts.exchange_config import ExchangeConfig
from quant.amt.session.symbol_registry import SymbolRegistry


@pytest.fixture
def mcx_factory():
    """Factory configured for MCX."""
    cfg = ExchangeConfig.for_exchange("MCX")
    reg = SymbolRegistry()
    return SessionContextFactory(exchange_config=cfg, symbol_registry=reg)


@pytest.fixture
def nse_factory():
    """Factory configured for NSE."""
    cfg = ExchangeConfig.for_exchange("NSE")
    reg = SymbolRegistry()
    return SessionContextFactory(exchange_config=cfg, symbol_registry=reg)


class TestSessionContextFactory:
    """Test suite for DIP-compliant SessionContextFactory."""

    def test_normalize_market_nfo(self):
        assert SessionContextFactory._normalize_market("NFO") == "NSE"

    def test_normalize_market_bse(self):
        assert SessionContextFactory._normalize_market("BSE") == "NSE"

    def test_normalize_market_nse(self):
        assert SessionContextFactory._normalize_market("NSE") == "NSE"

    def test_normalize_market_mcx(self):
        assert SessionContextFactory._normalize_market("MCX") == "MCX"

    def test_get_exchange_for_symbol_mcx(self, mcx_factory):
        assert mcx_factory.get_exchange_for_symbol("CRUDEOIL 17 MAR 6100 CALL") == "MCX"
        assert mcx_factory.get_exchange_for_symbol("GOLD 100 CE") == "MCX"
        assert mcx_factory.get_exchange_for_symbol("NATURALGAS 280 PE") == "MCX"

    def test_get_exchange_for_symbol_nse(self, nse_factory):
        assert nse_factory.get_exchange_for_symbol("NIFTY 22500 CE") == "NSE"
        assert nse_factory.get_exchange_for_symbol("BANKNIFTY 47000 PE") == "NSE"

    def test_get_exchange_for_symbol_with_prefix(self, mcx_factory):
        assert mcx_factory.get_exchange_for_symbol("NSE:NIFTY 24 DEC 25000 CE") == "NSE"
        assert (
            mcx_factory.get_exchange_for_symbol("MCX:CRUDEOIL 17 MAR 6100 CE") == "MCX"
        )

    def test_get_exchange_for_symbol_unknown(self, mcx_factory):
        result = mcx_factory.get_exchange_for_symbol("UNKNOWN_SYMBOL")
        assert result == "MCX"

    def test_factory_stores_config(self):
        cfg = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry()
        factory = SessionContextFactory(exchange_config=cfg, symbol_registry=reg)
        assert factory._config is cfg
        assert factory._registry is reg
