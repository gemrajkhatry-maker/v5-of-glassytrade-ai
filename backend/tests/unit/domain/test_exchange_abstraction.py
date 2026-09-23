"""Tests for the new exchange abstraction layer.

Tests:
  - ExchangeConfig value object (immutability, factory methods, YAML parsing)
  - SymbolRegistry (exchange detection, deduplication)
  - Canonical ExchangeConfig bridge (quant.contracts.exchange_config)
"""

from __future__ import annotations

import pytest
from datetime import timezone, timedelta

from quant.contracts.exchange_config import ExchangeConfig
from quant.amt.session.symbol_registry import SymbolRegistry
from quant.contracts.instrument_registry import UnknownInstrumentError

_IST = timezone(timedelta(hours=5, minutes=30))


# ======================================================================
# ExchangeConfig Tests
# ======================================================================


class TestExchangeConfig:
    """ExchangeConfig value object tests."""

    def test_nse_defaults(self):
        cfg = ExchangeConfig.for_exchange("NSE")
        assert cfg.exchange == "NSE"
        assert "NIFTY" in cfg.underlyings
        assert "BANKNIFTY" in cfg.underlyings
        assert "FINNIFTY" in cfg.underlyings
        assert cfg.cvd_block_threshold == 5000.0
        assert cfg.aggression_sigma == 2.5
        assert cfg.balance_ratio_threshold == 0.70
        assert cfg.big_trade_multiplier == 3.0
        assert cfg.is_nse()
        assert not cfg.is_mcx()

    def test_mcx_defaults(self):
        cfg = ExchangeConfig.for_exchange("MCX")
        assert cfg.exchange == "MCX"
        assert "CRUDEOIL" in cfg.underlyings
        assert "GOLD" in cfg.underlyings
        assert "NATURALGAS" in cfg.underlyings
        assert "COPPER" in cfg.underlyings
        assert cfg.cvd_block_threshold == 50.0
        assert cfg.aggression_sigma == 2.0
        assert cfg.balance_ratio_threshold == 0.55
        assert cfg.big_trade_multiplier == 5.0
        assert cfg.is_mcx()
        assert not cfg.is_nse()
        assert "CRUDEOIL" in cfg.eia_symbols
        assert "NATURALGAS" in cfg.eia_symbols

    def test_case_insensitive(self):
        assert ExchangeConfig.for_exchange("mcx").exchange == "MCX"
        assert ExchangeConfig.for_exchange("nSe").exchange == "NSE"

    def test_immutability(self):
        cfg = ExchangeConfig.for_exchange("MCX")
        with pytest.raises(AttributeError):
            cfg.exchange = "NSE"  # type: ignore

    def test_from_dict_partial_override(self):
        """from_dict should merge partial YAML data with defaults."""
        yaml_data = {
            "aggression_sigma": 3.0,
            "big_trade_multiplier": 8.0,
            "underlyings": ["CRUDEOIL", "GOLD"],
        }
        cfg = ExchangeConfig.from_dict("MCX", yaml_data)
        assert cfg.aggression_sigma == 3.0  # overridden
        assert cfg.big_trade_multiplier == 8.0  # overridden
        assert cfg.underlyings == frozenset({"CRUDEOIL", "GOLD"})  # overridden
        # Defaults preserved for non-overridden fields
        assert cfg.cvd_block_threshold == 50.0  # default
        assert cfg.balance_ratio_threshold == 0.55  # default

    def test_from_dict_empty_uses_defaults(self):
        cfg = ExchangeConfig.from_dict("NSE", {})
        assert cfg == ExchangeConfig.for_exchange("NSE")

    def test_from_dict_eia_symbols(self):
        yaml_data = {
            "eia_symbols": ["CRUDEOIL"],
            "eia_suppression_minutes": 30,
        }
        cfg = ExchangeConfig.from_dict("MCX", yaml_data)
        assert cfg.eia_symbols == frozenset({"CRUDEOIL"})
        assert cfg.eia_suppression_minutes == 30

    def test_is_underlying(self):
        mcx = ExchangeConfig.for_exchange("MCX")
        assert mcx.is_underlying("CRUDEOIL 19 MAR 6000 CALL")
        assert mcx.is_underlying("MCX:GOLD")
        assert not mcx.is_underlying("NIFTY 27 FEB 25500 CALL")

        nse = ExchangeConfig.for_exchange("NSE")
        assert nse.is_underlying("NIFTY 27 FEB 25500 CALL")
        assert nse.is_underlying("BANKNIFTY-WED-FUT")
        assert not nse.is_underlying("CRUDEOIL 19 MAR 6000 CALL")


# ======================================================================
# SymbolRegistry Tests
# ======================================================================


class TestSymbolRegistry:
    """SymbolRegistry tests — single source of truth for exchange detection."""

    def test_mcx_detection(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("CRUDEOIL 19 MAR 6000 CALL") == "MCX"
        assert reg.exchange_for("GOLD 25 APR 72000 PUT") == "MCX"
        assert reg.exchange_for("NATURALGAS 25 APR 200 CALL") == "MCX"
        assert reg.exchange_for("COPPER 25 APR 850 CALL") == "MCX"

    def test_nse_detection(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("NIFTY 27 FEB 25500 CALL") == "NSE"
        assert reg.exchange_for("BANKNIFTY-WED-FUT") == "NSE"
        assert reg.exchange_for("FINNIFTY 27 FEB 25500 PUT") == "NSE"

    def test_is_mcx_is_nse(self):
        reg = SymbolRegistry()
        assert reg.is_mcx("CRUDEOIL 19 MAR 6000 CALL")
        assert not reg.is_mcx("NIFTY 27 FEB 25500 CALL")
        assert reg.is_nse("NIFTY 27 FEB 25500 CALL")
        assert not reg.is_nse("CRUDEOIL 19 MAR 6000 CALL")

    def test_is_option(self):
        reg = SymbolRegistry()
        assert reg.is_option("CRUDEOIL 19 MAR 6000 CALL")
        assert reg.is_option("NIFTY 27 FEB 25500 PUT")
        assert not reg.is_option("CRUDEOIL")

    def test_prefix_stripping(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("MCX:CRUDEOIL") == "MCX"
        assert reg.exchange_for("NSE:NIFTY") == "NSE"

    def test_unknown_raises_instead_of_defaulting_to_mcx(self):
        # Phase 3: an unrecognized root must fail loudly, not silently
        # route to MCX.
        reg = SymbolRegistry()
        with pytest.raises(UnknownInstrumentError):
            reg.exchange_for("UNKNOWN_THING 99")

    def test_all_underlyings(self):
        reg = SymbolRegistry()
        all_u = reg.all_underlyings()
        assert "CRUDEOIL" in all_u
        assert "NIFTY" in all_u
        assert "GOLD" in all_u

    def test_from_exchange_configs(self):
        nse_cfg = ExchangeConfig.for_exchange("NSE")
        mcx_cfg = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry.from_exchange_configs({"NSE": nse_cfg, "MCX": mcx_cfg})
        assert reg.exchange_for("NIFTY 27 FEB 25500 CALL") == "NSE"
        assert reg.exchange_for("CRUDEOIL 19 MAR 6000 CALL") == "MCX"

    def test_deduplicated_with_dhan_adapter(self):
        """Verify registry MCX underlyings superset includes dhan_adapter's set."""
        reg = SymbolRegistry()
        dhan_mcx = {
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "NATURALGAS",
            "GOLDM",
            "SILVERM",
            "CRUDEOILM",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
            "LEAD",
            "NICKEL",
            "COTTONCANDY",
        }
        assert dhan_mcx.issubset(reg.mcx_underlyings)


# ======================================================================
# Canonical ExchangeConfig (quant.contracts) bridge tests
# ======================================================================


class TestExchangeConfigBridge:
    """Canonical ExchangeConfig (quant.contracts) — the single exchange-config source."""

    def test_for_exchange_returns_valid_config(self):
        mcx = ExchangeConfig.for_exchange("MCX")
        assert mcx.exchange == "MCX"
        assert "CRUDEOIL" in mcx.underlyings

        nse = ExchangeConfig.for_exchange("NSE")
        assert nse.exchange == "NSE"
        assert "NIFTY" in nse.underlyings

    def test_for_exchange_idempotent(self):
        a = ExchangeConfig.for_exchange("MCX")
        b = ExchangeConfig.for_exchange("MCX")
        assert a == b  # same values

    def test_from_dict_overrides_defaults(self):
        """from_dict builds from YAML dict, falling back to exchange defaults."""
        cfg = ExchangeConfig.from_dict("MCX", {"aggression_sigma": 1.5})
        assert cfg.exchange == "MCX"
        assert cfg.aggression_sigma == 1.5
        assert "CRUDEOIL" in cfg.underlyings

    def test_from_dict_nfo_maps_to_nse_defaults(self):
        """Non-MCX exchange keys (e.g. NFO) resolve to NSE defaults."""
        cfg = ExchangeConfig.for_exchange("NFO")
        assert cfg.exchange == "NSE"
        assert "NIFTY" in cfg.underlyings


# ======================================================================
# Integration: Strategy ↔ Config ↔ Registry consistency
# ======================================================================


class TestAbstractionLayerConsistency:
    """Verify the full abstraction layer works end-to-end."""


    def test_registry_matches_config_underlyings(self):
        """SymbolRegistry should match ExchangeConfig underlyings."""
        mcx_cfg = ExchangeConfig.for_exchange("MCX")
        nse_cfg = ExchangeConfig.for_exchange("NSE")
        reg = SymbolRegistry.from_exchange_configs({"NSE": nse_cfg, "MCX": mcx_cfg})

        for underlying in mcx_cfg.underlyings:
            assert reg.exchange_for(f"{underlying} 19 MAR 6000 CALL") == "MCX"

        for underlying in nse_cfg.underlyings:
            assert reg.exchange_for(f"{underlying} 27 FEB 25500 CALL") == "NSE"

    def test_di_container_wiring(self):
        """DIContainer should compose successfully without the dead exchange-strategy port."""
        from app.application.di.composition_root import compose_container
        from app.config import settings

        mode = settings.get_mode_config()
        config = mode.system_config if mode is not None else None
        container = compose_container(config)

        # The dead exchange-strategy port was deleted in Phase C3 — container
        # composition is the assertion now.
        assert container is not None
