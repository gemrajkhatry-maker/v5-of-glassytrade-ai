"""Tests for UnderlyingFuturesProvider and instrument mapping config."""

import json
from pathlib import Path

import pytest

from quant.amt.session.futures_provider import (
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
        # Dynamic derivation from the option's expiry month — Dhan custom-symbol form
        assert mapping.underlying_symbol == "CRUDEOIL APR FUT"
        assert mapping.underlying == "CRUDEOIL"
        assert mapping.exchange == "MCX"

    def test_get_mapping_nifty(self, provider):
        mapping = provider.get_mapping("NIFTY 30 MAR 23300 PUT")
        assert mapping is not None
        assert mapping.underlying_symbol == "NIFTY MAR FUT"
        assert mapping.underlying == "NIFTY"
        assert mapping.exchange == "NSE"

    def test_get_mapping_unknown(self, provider):
        mapping = provider.get_mapping("UNKNOWN 01 JAN 1000 CALL")
        assert mapping is None

    def test_get_underlying_symbol(self, provider):
        assert (
            provider.get_underlying_symbol("CRUDEOIL 16 APR 8900 CALL")
            == "CRUDEOIL APR FUT"
        )
        assert (
            provider.get_underlying_symbol("NIFTY 30 MAR 23300 PUT") == "NIFTY MAR FUT"
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
        assert mapping.underlying_symbol == "CRUDEOIL APR FUT"
        assert mapping.config.ib_window_minutes == 30
        assert mapping.config.session_start == "09:00"

    def test_build_futures_routing(self, provider):
        opts = [
            "CRUDEOIL 16 APR 8900 CALL",
            "CRUDEOIL 16 APR 8800 PUT",
            "NIFTY 30 MAR 23300 PUT",
        ]
        fut_map, futs = provider.build_futures_routing(opts)
        assert set(futs) == {"CRUDEOIL APR FUT", "NIFTY MAR FUT"}
        assert len(fut_map["CRUDEOIL APR FUT"]) == 2
        assert len(fut_map["NIFTY MAR FUT"]) == 1

    def test_instrument_config_fields(self, provider):
        cfg = provider.get_config("NIFTY", "NSE")
        assert cfg.session_start == "09:15"
        assert cfg.session_end == "15:30"
        assert cfg.range_bar_size == 20


class TestDynamicFuturesDerivation:
    def test_build_futures_symbol_mcx(self):
        assert build_futures_symbol("CRUDEOIL", "16", "APR") == "CRUDEOIL APR FUT"
        assert build_futures_symbol("GOLD", "20", "APR") == "GOLD APR FUT"
        assert build_futures_symbol("NATURALGAS", "6", "APR") == "NATURALGAS APR FUT"

    def test_build_futures_symbol_nse(self):
        assert build_futures_symbol("NIFTY", "27", "FEB") == "NIFTY FEB FUT"
        assert build_futures_symbol("BANKNIFTY", "10", "MAR") == "BANKNIFTY MAR FUT"

    def test_build_futures_symbol_single_digit_day(self):
        # Single digit days are irrelevant to the Dhan custom-symbol form
        assert build_futures_symbol("CRUDEOIL", "6", "APR") == "CRUDEOIL APR FUT"

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


def test_repo_instruments_json_maps_goldm_silverm_mini_options():
    """GOLDM/SILVERM must exist in config/instruments.json for dual feed + history."""
    cfg = Path(__file__).resolve().parents[3] / "config" / "instruments.json"
    provider = UnderlyingFuturesProvider(config_path=cfg)
    goldm = provider.get_mapping("GOLDM 21 APR 85000 CALL")
    assert goldm is not None
    assert goldm.underlying == "GOLDM"
    assert "GOLDM" in goldm.underlying_symbol.upper()
    assert goldm.underlying_symbol.upper().startswith("GOLDM ")
    silvm = provider.get_mapping("SILVERM 21 APR 260000 PUT")
    assert silvm is not None
    assert silvm.underlying == "SILVERM"
    assert "SILVERM" in silvm.underlying_symbol.upper()
    assert silvm.underlying_symbol.upper().startswith("SILVERM ")
