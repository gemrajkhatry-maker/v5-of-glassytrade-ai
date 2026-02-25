"""
Tests for MCX Futures Resolution.
"""

import pandas as pd
import pytest
from datetime import datetime, timedelta

from brokers.broker.mcx_futures import MCXFuturesResolver, FuturesContract
from brokers.broker.types import Exchange


class TestFuturesContract:
    """Test the FuturesContract dataclass."""

    def test_contract_creation(self):
        """Test basic contract creation."""
        expiry = datetime.now() + timedelta(days=30)
        contract = FuturesContract(
            symbol="GOLD26FEB25FUT",
            security_id="12345",
            underlying="GOLD",
            exchange=Exchange.MCX,
            expiry_date=expiry,
            expiry_code=1,
            lot_size=100,
        )

        assert contract.symbol == "GOLD26FEB25FUT"
        assert contract.security_id == "12345"
        assert contract.underlying == "GOLD"
        assert contract.exchange == Exchange.MCX
        assert contract.lot_size == 100
        assert not contract.is_expired
        # Allow +/- 1 day for timing issues
        assert 29 <= contract.days_to_expiry <= 30

    def test_expired_contract(self):
        """Test expired contract detection."""
        expiry = datetime.now() - timedelta(days=5)
        contract = FuturesContract(
            symbol="GOLD26JAN25FUT",
            security_id="12345",
            underlying="GOLD",
            exchange=Exchange.MCX,
            expiry_date=expiry,
        )

        assert contract.is_expired
        assert contract.days_to_expiry == 0

    def test_no_expiry(self):
        """Test contract without expiry date."""
        contract = FuturesContract(
            symbol="GOLD", security_id="12345", underlying="GOLD", exchange=Exchange.MCX
        )

        assert not contract.is_expired
        assert contract.days_to_expiry is None


class TestMCXFuturesResolver:
    """Test MCX futures resolution."""

    @pytest.fixture
    def sample_instrument_df(self):
        """Create sample instrument DataFrame."""
        today = datetime.now()
        return pd.DataFrame(
            {
                "SEM_EXM_EXCH_ID": ["MCX", "MCX", "MCX", "NSE", "MCX"],
                "SEM_INSTRUMENT_NAME": ["FUTCOM", "FUTCOM", "FUTCOM", "EQ", "FUTCOM"],
                "SM_SYMBOL_NAME": ["GOLD", "GOLD", "GOLD", "RELIANCE", "SILVER"],
                "SEM_CUSTOM_SYMBOL": [
                    "GOLD26FEB25FUT",
                    "GOLD26MAR25FUT",
                    "GOLD26APR25FUT",
                    "RELIANCE-EQ",
                    "SILVER26FEB25FUT",
                ],
                "SEM_TRADING_SYMBOL": [
                    "GOLDFEB25FUT",
                    "GOLDMAR25FUT",
                    "GOLDAPR25FUT",
                    "RELIANCE",
                    "SILVERFEB25FUT",
                ],
                "SEM_SMST_SECURITY_ID": [1001, 1002, 1003, 2001, 1004],
                "SEM_EXPIRY_DATE": [
                    today + timedelta(days=10),
                    today + timedelta(days=40),
                    today + timedelta(days=70),
                    None,
                    today + timedelta(days=15),
                ],
                "SEM_LOT_SIZE": [100, 100, 100, 1, 30],
                "SEM_EXPIRY_CODE": [1, 2, 3, 0, 1],
            }
        )

    def test_get_nearest_contract(self, sample_instrument_df):
        """Test getting nearest futures contract."""
        resolver = MCXFuturesResolver()
        contract = resolver.get_nearest_contract("GOLD", sample_instrument_df)

        assert contract is not None
        assert contract.symbol == "GOLD26FEB25FUT"
        assert contract.underlying == "GOLD"
        assert contract.exchange == Exchange.MCX
        assert contract.lot_size == 100

    def test_get_nearest_contract_case_insensitive(self, sample_instrument_df):
        """Test case-insensitive symbol matching."""
        resolver = MCXFuturesResolver()
        contract = resolver.get_nearest_contract("gold", sample_instrument_df)

        assert contract is not None
        assert contract.underlying == "GOLD"

    def test_get_nearest_contract_not_found(self, sample_instrument_df):
        """Test when no contract is found."""
        resolver = MCXFuturesResolver()
        contract = resolver.get_nearest_contract("CRUDEOIL", sample_instrument_df)

        assert contract is None

    def test_caching(self, sample_instrument_df):
        """Test contract caching."""
        resolver = MCXFuturesResolver()

        # First call
        contract1 = resolver.get_nearest_contract("GOLD", sample_instrument_df)

        # Second call should use cache
        contract2 = resolver.get_nearest_contract("GOLD", sample_instrument_df)

        assert contract1.symbol == contract2.symbol

    def test_cache_expiry(self, sample_instrument_df):
        """Test cache doesn't return expired contracts."""
        resolver = MCXFuturesResolver()

        # Get contract
        contract = resolver.get_nearest_contract("GOLD", sample_instrument_df)

        # Manually expire the cache by setting expiry to past
        resolver._cache["GOLD_MCX"].expiry_date = datetime.now() - timedelta(days=1)

        # Next call should re-resolve
        contract2 = resolver.get_nearest_contract("GOLD", sample_instrument_df)
        assert contract2 is not None

    def test_get_all_contracts(self, sample_instrument_df):
        """Test getting all available contracts."""
        resolver = MCXFuturesResolver()
        contracts = resolver.get_all_contracts("GOLD", sample_instrument_df, limit=5)

        assert len(contracts) == 3
        # Should be sorted by expiry
        assert contracts[0].symbol == "GOLD26FEB25FUT"
        assert contracts[1].symbol == "GOLD26MAR25FUT"
        assert contracts[2].symbol == "GOLD26APR25FUT"

    def test_get_all_contracts_limit(self, sample_instrument_df):
        """Test contract limit."""
        resolver = MCXFuturesResolver()
        contracts = resolver.get_all_contracts("GOLD", sample_instrument_df, limit=2)

        assert len(contracts) == 2

    def test_clear_cache(self, sample_instrument_df):
        """Test cache clearing."""
        resolver = MCXFuturesResolver()

        # Add to cache
        resolver.get_nearest_contract("GOLD", sample_instrument_df)
        assert len(resolver._cache) > 0

        # Clear cache
        resolver.clear_cache()
        assert len(resolver._cache) == 0

    def test_is_commodity(self):
        """Test commodity detection."""
        resolver = MCXFuturesResolver()

        assert resolver.is_commodity("GOLD") is True
        assert resolver.is_commodity("SILVER") is True
        assert resolver.is_commodity("CRUDEOIL") is True
        assert resolver.is_commodity("RELIANCE") is False
        assert resolver.is_commodity("NIFTY") is False

    def test_no_data_source(self):
        """Test behavior when no data source available."""
        resolver = MCXFuturesResolver()
        contract = resolver.get_nearest_contract("GOLD")

        assert contract is None

    def test_invalid_dataframe(self):
        """Test handling of invalid DataFrame."""
        resolver = MCXFuturesResolver()

        # Empty DataFrame
        df = pd.DataFrame()
        contract = resolver.get_nearest_contract("GOLD", df)
        assert contract is None

        # DataFrame with missing columns
        df = pd.DataFrame({"col1": [1, 2, 3]})
        contract = resolver.get_nearest_contract("GOLD", df)
        assert contract is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
