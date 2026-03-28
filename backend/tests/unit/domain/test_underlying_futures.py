"""Tests for UnderlyingFuturesProvider and instrument mapping config."""

import json
import tempfile
from pathlib import Path

import pytest

from app.domain.services.underlying_futures_provider import (
    InstrumentConfig,
    DualFeedMapping,
    UnderlyingFuturesProvider,
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
        assert mapping.underlying_symbol == "CRUDEOIL25APRFUT"
        assert mapping.underlying == "CRUDEOIL"
        assert mapping.exchange == "MCX"

    def test_get_mapping_nifty(self, provider):
        mapping = provider.get_mapping("NIFTY 30 MAR 23300 PUT")
        assert mapping is not None
        assert mapping.underlying_symbol == "NIFTY25APRFUT"
        assert mapping.underlying == "NIFTY"
        assert mapping.exchange == "NSE"

    def test_get_mapping_unknown(self, provider):
        mapping = provider.get_mapping("UNKNOWN 01 JAN 1000 CALL")
        assert mapping is None

    def test_get_underlying_symbol(self, provider):
        assert (
            provider.get_underlying_symbol("CRUDEOIL 16 APR 8900 CALL")
            == "CRUDEOIL25APRFUT"
        )
        assert (
            provider.get_underlying_symbol("NIFTY 30 MAR 23300 PUT") == "NIFTY25APRFUT"
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
        assert mapping.underlying_symbol == "CRUDEOIL25APRFUT"
        assert mapping.config.ib_window_minutes == 30
        assert mapping.config.session_start == "09:00"

    def test_instrument_config_fields(self, provider):
        cfg = provider.get_config("NIFTY", "NSE")
        assert cfg.underlying_symbol == "NIFTY25APRFUT"
        assert cfg.session_start == "09:15"
        assert cfg.session_end == "15:30"
        assert cfg.range_bar_size == 20
