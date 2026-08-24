"""
End-to-end tests: historical data, option chains, expiries for NSE and MCX.

Uses PaperBroker so no real API is required. Validates that:
- BrokerGateway exposes and delegates get_historical, get_option_chain, get_expiries
- NSE (equity/index) and NFO (index options) flows work
- MCX (commodity) flows work
- Return types and shapes are correct for both exchanges.
"""

import pytest
from datetime import datetime, timedelta

from brokers.gateway import BrokerGateway
from brokers.broker.types import Exchange
from brokers.broker.entities import Quote, OptionChain


# -----------------------------------------------------------------------------
# NSE / NFO (equity and index options)
# -----------------------------------------------------------------------------


class TestE2ENSE:
    """End-to-end via BrokerGateway for NSE equity and NFO options."""

    @pytest.fixture
    def gateway(self):
        return BrokerGateway.paper()

    def test_nse_quote(self, gateway):
        """Gateway get_quote for NSE equity."""
        quote = gateway.get_quote("RELIANCE", Exchange.NSE)
        assert quote is not None
        assert isinstance(quote, Quote)
        assert quote.instrument.symbol == "RELIANCE"
        assert quote.instrument.exchange == Exchange.NSE
        assert quote.ltp > 0

    def test_nse_historical(self, gateway):
        """Gateway get_historical for NSE equity."""
        to_date = datetime.now()
        from_date = to_date - timedelta(days=10)
        df = gateway.get_historical("RELIANCE", Exchange.NSE, from_date, to_date, "1d")
        assert df is not None
        assert hasattr(df, "columns")
        for col in ("open", "high", "low", "close", "volume"):
            assert col in df.columns or col in [c.lower() for c in df.columns], f"missing {col}"
        assert len(df) >= 1

    def test_nfo_option_chain(self, gateway):
        """Gateway get_option_chain for NFO (NIFTY)."""
        chain = gateway.get_option_chain("NIFTY", Exchange.NFO, expiry_index=0)
        assert chain is not None
        assert isinstance(chain, OptionChain)
        assert chain.underlying.symbol == "NIFTY"
        assert chain.underlying.exchange == Exchange.NFO
        assert chain.spot_price > 0
        assert isinstance(chain.calls, dict)
        assert isinstance(chain.puts, dict)
        assert len(chain.calls) >= 1
        assert len(chain.puts) >= 1

    def test_nfo_expiries(self, gateway):
        """Gateway get_expiries for NFO."""
        expiries = gateway.get_expiries("NIFTY", Exchange.NFO)
        assert expiries is not None
        assert isinstance(expiries, list)
        assert all(isinstance(e, datetime) for e in expiries)
        assert len(expiries) >= 1


# -----------------------------------------------------------------------------
# MCX (commodity)
# -----------------------------------------------------------------------------


class TestE2EMCX:
    """End-to-end via BrokerGateway for MCX commodity."""

    @pytest.fixture
    def gateway(self):
        return BrokerGateway.paper()

    def test_mcx_quote(self, gateway):
        """Gateway get_quote for MCX commodity."""
        quote = gateway.get_quote("GOLD", Exchange.MCX)
        assert quote is not None
        assert isinstance(quote, Quote)
        assert quote.instrument.exchange == Exchange.MCX
        assert quote.ltp > 0

    def test_mcx_historical(self, gateway):
        """Gateway get_historical for MCX."""
        to_date = datetime.now()
        from_date = to_date - timedelta(days=5)
        df = gateway.get_historical("GOLD", Exchange.MCX, from_date, to_date, "1d")
        assert df is not None
        assert hasattr(df, "columns")
        assert len(df) >= 1

    def test_mcx_option_chain(self, gateway):
        """Gateway get_option_chain for MCX underlying."""
        chain = gateway.get_option_chain("GOLD", Exchange.MCX, expiry_index=0)
        assert chain is not None
        assert isinstance(chain, OptionChain)
        assert chain.underlying.symbol == "GOLD"
        assert chain.underlying.exchange == Exchange.MCX
        assert chain.spot_price > 0
        assert isinstance(chain.calls, dict)
        assert isinstance(chain.puts, dict)

    def test_mcx_expiries(self, gateway):
        """Gateway get_expiries for MCX."""
        expiries = gateway.get_expiries("GOLD", Exchange.MCX)
        assert expiries is not None
        assert isinstance(expiries, list)
        assert all(isinstance(e, datetime) for e in expiries)
        assert len(expiries) >= 1


# -----------------------------------------------------------------------------
# Cross-exchange consistency
# -----------------------------------------------------------------------------


class TestE2ECrossExchange:
    """Same API works for NSE and MCX."""

    @pytest.fixture
    def gateway(self):
        return BrokerGateway.paper()

    def test_historical_nse_and_mcx(self, gateway):
        """get_historical works for both NSE and MCX."""
        to_date = datetime.now()
        from_date = to_date - timedelta(days=3)
        df_nse = gateway.get_historical("RELIANCE", Exchange.NSE, from_date, to_date, "1d")
        df_mcx = gateway.get_historical("SILVER", Exchange.MCX, from_date, to_date, "1d")
        assert df_nse is not None and len(df_nse) >= 1
        assert df_mcx is not None and len(df_mcx) >= 1

    def test_option_chain_nfo_and_mcx(self, gateway):
        """get_option_chain works for NFO and MCX."""
        chain_nfo = gateway.get_option_chain("BANKNIFTY", Exchange.NFO)
        chain_mcx = gateway.get_option_chain("CRUDEOIL", Exchange.MCX)
        assert chain_nfo.underlying.exchange == Exchange.NFO
        assert chain_mcx.underlying.exchange == Exchange.MCX
        assert chain_nfo.spot_price > 0
        assert chain_mcx.spot_price > 0
