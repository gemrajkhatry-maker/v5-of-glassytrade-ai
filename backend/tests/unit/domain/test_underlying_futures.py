"""Tests for UnderlyingFuturesProvider and instrument mapping config."""

import json
import tempfile
from pathlib import Path

import pytest

from app.domain.services.underlying_futures_provider import (
    InstrumentConfig,
    DualFeedMapping,
    UnderlyingFuturesProvider,
    build_futures_symbol,
    extract_option_date,
)


@pytest.fixture
def provider(tmp_path):
    """Create a provider with test instrument config."""
    config = {
        "MCX": {
            "CRUDEOIL": {
                "underlying_symbol": "CRUDEOIL25APRFUT",
                "underlying_segment": "MCX_COMM",
                "options_segment": "MCX_COMM",
                "strike_step": 50,
                "lot_size": 100,
                "tick_size": 1.0,
                "session_start": "09:00",
                "session_end": "23:30",
                "ib_window_minutes": 30,
                "big_order_filter_lots": 30,
                "range_bar_size": 20,
                "dead_volume_pct": 5,
            },
            "NATURALGAS": {
                "underlying_symbol": "NATURALGAS25APRFUT",
                "underlying_segment": "MCX_COMM",
                "options_segment": "MCX_COMM",
                "strike_step": 5,
                "lot_size": 1250,
                "tick_size": 0.10,
                "session_start": "09:00",
                "session_end": "23:30",
                "ib_window_minutes": 30,
                "big_order_filter_lots": 20,
                "range_bar_size": 2,
                "dead_volume_pct": 5,
            },
        },
        "NSE": {
            "NIFTY": {
                "underlying_symbol": "NIFTY25APRFUT",
                "underlying_segment": "NSE_FNO",
                "options_segment": "NSE_FNO",
                "strike_step": 50,
                "lot_size": 75,
                "tick_size": 0.05,
                "session_start": "09:15",
                "session_end": "15:30",
                "ib_window_minutes": 30,
                "big_order_filter_lots": 50,
                "range_bar_size": 20,
                "dead_volume_pct": 5,
            },
        },
    }
    config_file = tmp_path / "instruments.json"
    config_file.write_text(json.dumps(config))
    return UnderlyingFuturesProvider(config_path=config_file)


class TestUnderlyingFuturesProvider:
    def test_load_config(self, provider):
        assert len(provider._instruments) == 2
        assert "MCX" in provider._instruments
        assert "NSE" in provider._instruments

    def test_get_mapping_crudeoil(self, provider):
        mapping = provider.get_mapping("CRUDEOIL 16 APR 8900 CALL")
        assert mapping is not None
        # Dynamic: derived from option date "16 APR" → CRUDEOIL1604FUT
        assert mapping.underlying_symbol == "CRUDEOIL1604FUT"
        assert mapping.underlying == "CRUDEOIL"
        assert mapping.exchange == "MCX"

    def test_get_mapping_nifty(self, provider):
        mapping = provider.get_mapping("NIFTY 30 MAR 23300 PUT")
        assert mapping is not None
        # Dynamic: derived from option date "30 MAR" → NIFTY3003FUT
        assert mapping.underlying_symbol == "NIFTY3003FUT"
        assert mapping.underlying == "NIFTY"
        assert mapping.exchange == "NSE"

    def test_get_mapping_unknown(self, provider):
        mapping = provider.get_mapping("UNKNOWN 01 JAN 1000 CALL")
        assert mapping is None

    def test_get_underlying_symbol(self, provider):
        assert (
            provider.get_underlying_symbol("CRUDEOIL 16 APR 8900 CALL")
            == "CRUDEOIL1604FUT"
        )
        assert (
            provider.get_underlying_symbol("NIFTY 30 MAR 23300 PUT") == "NIFTY3003FUT"
        )

    def test_get_config(self, provider):
        cfg = provider.get_config("CRUDEOIL", "MCX")
        assert cfg is not None
        assert cfg.strike_step == 50
        assert cfg.lot_size == 100
        assert cfg.tick_size == 1.0
        assert cfg.big_order_filter_lots == 30

    def test_get_all_underlyings(self, provider):
        mcx = provider.get_all_underlyings("MCX")
        assert "CRUDEOIL" in mcx
        assert "NATURALGAS" in mcx

    def test_dual_feed_mapping(self, provider):
        mapping = provider.get_mapping("CRUDEOIL 16 APR 8850 PE")
        assert mapping.option_symbol == "CRUDEOIL 16 APR 8850 PE"
        assert mapping.underlying_symbol == "CRUDEOIL1604FUT"
        assert mapping.config.ib_window_minutes == 30
        assert mapping.config.session_start == "09:00"

    def test_instrument_config_fields(self, provider):
        cfg = provider.get_config("NIFTY", "NSE")
        assert cfg.underlying_symbol == "NIFTY25APRFUT"
        assert cfg.session_start == "09:15"
        assert cfg.session_end == "15:30"
        assert cfg.range_bar_size == 20


class TestDynamicFuturesDerivation:
    def test_build_futures_symbol_mcx(self):
        assert build_futures_symbol("CRUDEOIL", "16", "APR") == "CRUDEOIL1604FUT"
        assert build_futures_symbol("GOLD", "20", "APR") == "GOLD2004FUT"
        assert build_futures_symbol("NATURALGAS", "6", "APR") == "NATURALGAS0604FUT"

    def test_build_futures_symbol_nse(self):
        assert build_futures_symbol("NIFTY", "27", "FEB") == "NIFTY2702FUT"
        assert build_futures_symbol("BANKNIFTY", "10", "MAR") == "BANKNIFTY1003FUT"

    def test_build_futures_symbol_single_digit_day(self):
        # Single digit days should be zero-padded
        assert build_futures_symbol("CRUDEOIL", "6", "APR") == "CRUDEOIL0604FUT"

    def test_extract_option_date(self):
        result = extract_option_date("CRUDEOIL 16 APR 9000 CALL")
        assert result == ("CRUDEOIL", "16", "APR")

    def test_extract_option_date_with_exchange_prefix(self):
        result = extract_option_date("MCX:CRUDEOIL 16 APR 9000 CALL")
        assert result == ("CRUDEOIL", "16", "APR")

        result = extract_option_date("NSE:NIFTY 27 MAR 23000 PUT")
        assert result == ("NIFTY", "27", "MAR")

    def test_extract_option_date_ce_pe_format(self):
        result = extract_option_date("NIFTY 10 MAR 22000 CE")
        assert result == ("NIFTY", "10", "MAR")

        result = extract_option_date("BANKNIFTY 15 APR 48000 PE")
        assert result == ("BANKNIFTY", "15", "APR")

    def test_extract_option_date_invalid(self):
        assert extract_option_date("CRUDEOIL25APRFUT") is None
        assert extract_option_date("SOME_RANDOM_SYMBOL") is None
