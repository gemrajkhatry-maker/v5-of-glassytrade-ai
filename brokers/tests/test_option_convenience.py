"""
Tests for option convenience methods and market_info module.

Uses PaperBroker (no credentials needed) to test:
- find_atm_options, find_otm_options, find_itm_options
- get_lot_size, get_step_size
- market_info utility functions
"""

import pytest
from brokers.gateway import BrokerGateway
from brokers.broker.market_info import (
    get_lot_size,
    get_step_size,
    get_expiry_weekday,
    normalize_symbol,
    get_market_info,
    is_premium_in_range,
    LOT_SIZES,
    STEP_SIZES,
    EXPIRY_WEEKDAY,
)
from brokers.broker.types import Exchange


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def paper_broker():
    """Paper broker via BrokerGateway."""
    gw = BrokerGateway.paper()
    return gw.broker


# =============================================================================
# market_info module tests
# =============================================================================

class TestMarketInfoConstants:
    def test_lot_sizes_indices(self):
        assert get_lot_size("NIFTY") == 25
        assert get_lot_size("BANKNIFTY") == 15
        assert get_lot_size("FINNIFTY") == 25
        assert get_lot_size("MIDCPNIFTY") == 50
        assert get_lot_size("SENSEX") == 10

    def test_lot_sizes_mcx(self):
        assert get_lot_size("GOLD") == 100
        assert get_lot_size("SILVER") == 30
        assert get_lot_size("CRUDEOIL") == 100

    def test_lot_size_unknown_returns_1(self):
        assert get_lot_size("UNKNOWN_SYMBOL") == 1

    def test_lot_size_case_insensitive(self):
        assert get_lot_size("nifty") == 25
        assert get_lot_size("Nifty") == 25

    def test_step_sizes_indices(self):
        assert get_step_size("NIFTY") == 50.0
        assert get_step_size("BANKNIFTY") == 100.0
        assert get_step_size("FINNIFTY") == 50.0
        assert get_step_size("SENSEX") == 100.0

    def test_step_sizes_mcx(self):
        assert get_step_size("GOLD") == 100.0
        assert get_step_size("CRUDEOIL") == 50.0
        assert get_step_size("NATURALGAS") == 5.0

    def test_step_size_default_for_stocks(self):
        assert get_step_size("RELIANCE") == 5.0
        assert get_step_size("UNKNOWN") == 5.0

    def test_expiry_weekday(self):
        assert get_expiry_weekday("NIFTY") == 3      # Thursday
        assert get_expiry_weekday("BANKNIFTY") == 2   # Wednesday
        assert get_expiry_weekday("FINNIFTY") == 1    # Tuesday
        assert get_expiry_weekday("MIDCPNIFTY") == 0  # Monday
        assert get_expiry_weekday("SENSEX") == 4      # Friday

    def test_expiry_weekday_default(self):
        assert get_expiry_weekday("UNKNOWN") == 3  # Thursday default


class TestNormalizeSymbol:
    def test_alias_normalization(self):
        assert normalize_symbol("NIFTY BANK") == "BANKNIFTY"
        assert normalize_symbol("NIFTY 50") == "NIFTY"
        assert normalize_symbol("NIFTY FIN SERVICE") == "FINNIFTY"
        assert normalize_symbol("NIFTY MID SELECT") == "MIDCPNIFTY"

    def test_passthrough(self):
        assert normalize_symbol("NIFTY") == "NIFTY"
        assert normalize_symbol("GOLD") == "GOLD"

    def test_case_insensitive(self):
        assert normalize_symbol("nifty bank") == "BANKNIFTY"


class TestPremiumRange:
    def test_in_range(self):
        assert is_premium_in_range(100.0) is True
        assert is_premium_in_range(80.0) is True
        assert is_premium_in_range(250.0) is True

    def test_out_of_range(self):
        assert is_premium_in_range(79.0) is False
        assert is_premium_in_range(251.0) is False

    def test_custom_range(self):
        assert is_premium_in_range(50.0, min_premium=40.0, max_premium=60.0) is True
        assert is_premium_in_range(50.0, min_premium=55.0, max_premium=60.0) is False


class TestGetMarketInfo:
    def test_returns_all_keys(self):
        info = get_market_info("NIFTY")
        assert "symbol" in info
        assert "lot_size" in info
        assert "step_size" in info
        assert "expiry_weekday" in info
        assert "is_expiry_day" in info
        assert "is_market_open" in info
        assert info["lot_size"] == 25
        assert info["step_size"] == 50.0


# =============================================================================
# IBrokerPort convenience method tests (via PaperBroker)
# =============================================================================

class TestFindATMOptions:
    def test_returns_ce_pe_and_strike(self, paper_broker):
        ce, pe, atm_strike = paper_broker.find_atm_options("NIFTY", Exchange.NFO)

        assert ce is not None, "ATM CE should not be None"
        assert pe is not None, "ATM PE should not be None"
        assert atm_strike > 0

        assert ce.option_type == "CE"
        assert pe.option_type == "PE"
        assert ce.strike == atm_strike
        assert pe.strike == atm_strike

    def test_atm_strike_is_rounded(self, paper_broker):
        _, _, atm_strike = paper_broker.find_atm_options("NIFTY", Exchange.NFO)
        # ATM strike should be a multiple of step_size (50 for NIFTY)
        assert atm_strike % 50 == 0

    def test_banknifty_atm(self, paper_broker):
        ce, pe, atm = paper_broker.find_atm_options("BANKNIFTY", Exchange.NFO)
        assert ce is not None
        assert pe is not None
        assert atm % 100 == 0  # BANKNIFTY step = 100


class TestFindOTMOptions:
    def test_otm_distance_1(self, paper_broker):
        ce, pe, ce_strike, pe_strike = paper_broker.find_otm_options(
            "NIFTY", Exchange.NFO, distance=1
        )
        _, _, atm = paper_broker.find_atm_options("NIFTY", Exchange.NFO)

        assert ce_strike == atm + 50   # 1 step above ATM
        assert pe_strike == atm - 50   # 1 step below ATM
        assert ce is not None
        assert pe is not None
        assert ce.option_type == "CE"
        assert pe.option_type == "PE"

    def test_otm_distance_2(self, paper_broker):
        ce, pe, ce_strike, pe_strike = paper_broker.find_otm_options(
            "NIFTY", Exchange.NFO, distance=2
        )
        _, _, atm = paper_broker.find_atm_options("NIFTY", Exchange.NFO)

        assert ce_strike == atm + 100
        assert pe_strike == atm - 100


class TestFindITMOptions:
    def test_itm_distance_1(self, paper_broker):
        ce, pe, ce_strike, pe_strike = paper_broker.find_itm_options(
            "NIFTY", Exchange.NFO, distance=1
        )
        _, _, atm = paper_broker.find_atm_options("NIFTY", Exchange.NFO)

        assert ce_strike == atm - 50   # 1 step below ATM (ITM call)
        assert pe_strike == atm + 50   # 1 step above ATM (ITM put)
        assert ce is not None
        assert pe is not None
        assert ce.option_type == "CE"
        assert pe.option_type == "PE"


class TestGetLotSizeViaBroker:
    def test_lot_size_nifty(self, paper_broker):
        assert paper_broker.get_lot_size("NIFTY") == 25

    def test_lot_size_banknifty(self, paper_broker):
        assert paper_broker.get_lot_size("BANKNIFTY") == 15

    def test_lot_size_gold(self, paper_broker):
        assert paper_broker.get_lot_size("GOLD") == 100

    def test_lot_size_unknown(self, paper_broker):
        assert paper_broker.get_lot_size("FOOBAR") == 1


class TestGetStepSizeViaBroker:
    def test_step_size_nifty(self, paper_broker):
        assert paper_broker.get_step_size("NIFTY") == 50.0

    def test_step_size_banknifty(self, paper_broker):
        assert paper_broker.get_step_size("BANKNIFTY") == 100.0

    def test_step_size_stock(self, paper_broker):
        assert paper_broker.get_step_size("RELIANCE") == 5.0
