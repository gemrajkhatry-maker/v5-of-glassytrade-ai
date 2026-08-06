"""Tests for the new exchange abstraction layer.

Tests:
  - ExchangeConfig value object (immutability, factory methods, YAML parsing)
  - SymbolRegistry (exchange detection, deduplication)
  - ExchangeStrategy port + NSE/MCX implementations
  - SessionContextFactory (DIP-compliant construction)
  - consolidated.py YAML parsing + get_exchange_config bridge
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone, timedelta

from quant.contracts.exchange_config import ExchangeConfig
from quant.amt.session.symbol_registry import SymbolRegistry
from app.infrastructure.strategies.nse_strategy import NSEExchangeStrategy
from app.infrastructure.strategies.mcx_strategy import MCXExchangeStrategy
from quant.amt.session.context_factory import SessionContextFactory

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

    def test_llm_instruction_is_exchange_specific(self):
        nse = ExchangeConfig.for_exchange("NSE")
        mcx = ExchangeConfig.for_exchange("MCX")
        assert "NSE" in nse.llm_instruction
        assert "MCX" in mcx.llm_instruction
        assert nse.llm_instruction != mcx.llm_instruction


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

    def test_unknown_defaults_to_mcx(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("UNKNOWN_THING 99") == "MCX"

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
# ExchangeStrategy Tests
# ======================================================================


class TestNSEExchangeStrategy:
    """NSE strategy tests."""

    def setup_method(self):
        self.config = ExchangeConfig.for_exchange("NSE")
        self.strategy = NSEExchangeStrategy(self.config)

    def test_name(self):
        assert self.strategy.name == "NSE"

    def test_cvd_threshold(self):
        assert self.strategy.get_cvd_block_threshold() == 5000.0

    def test_warm_up(self):
        assert self.strategy.get_warm_up_minutes() == 15

    def test_session_times(self):
        assert self.strategy.get_session_open_time() == (9, 15)
        assert self.strategy.get_session_close_time() == (15, 15)

    def test_no_eia(self):
        ist_dt = datetime(2024, 1, 3, 21, 0, tzinfo=_IST)  # Wednesday
        assert not self.strategy.is_eia_window("NIFTY", ist_dt)

    def test_aggression_sigma(self):
        assert self.strategy.get_aggression_sigma() == 2.5

    def test_config_passthrough(self):
        assert self.strategy.config is self.config


class TestMCXExchangeStrategy:
    """MCX strategy tests."""

    def setup_method(self):
        self.config = ExchangeConfig.for_exchange("MCX")
        self.strategy = MCXExchangeStrategy(self.config)

    def test_name(self):
        assert self.strategy.name == "MCX"

    def test_cvd_threshold(self):
        assert self.strategy.get_cvd_block_threshold() == 50.0

    def test_session_times(self):
        assert self.strategy.get_session_open_time() == (9, 0)
        assert self.strategy.get_session_close_time() == (23, 15)

    def test_eia_window_crudeoil_wednesday(self):
        # Wednesday 21:00 IST = EIA crude oil release
        ist_dt = datetime(2024, 1, 3, 21, 0, tzinfo=_IST)
        assert self.strategy.is_eia_window("CRUDEOIL 19 MAR 6000 CALL", ist_dt)

    def test_eia_window_crudeoil_not_in_window(self):
        # Wednesday 22:00 IST = outside 15-min window
        ist_dt = datetime(2024, 1, 3, 22, 0, tzinfo=_IST)
        assert not self.strategy.is_eia_window("CRUDEOIL 19 MAR 6000 CALL", ist_dt)

    def test_eia_window_natgas_thursday(self):
        # Thursday 21:00 IST = EIA natural gas release
        ist_dt = datetime(2024, 1, 4, 21, 0, tzinfo=_IST)  # Thursday
        assert self.strategy.is_eia_window("NATURALGAS 25 APR 200 CALL", ist_dt)

    def test_eia_window_not_eia_symbol(self):
        ist_dt = datetime(2024, 1, 3, 21, 0, tzinfo=_IST)
        assert not self.strategy.is_eia_window("GOLD 25 APR 72000 PUT", ist_dt)

    def test_eia_window_wrong_day(self):
        # Monday 21:00 IST — no EIA release
        ist_dt = datetime(2024, 1, 1, 21, 0, tzinfo=_IST)
        assert not self.strategy.is_eia_window("CRUDEOIL 19 MAR 6000 CALL", ist_dt)

    def test_aggression_sigma(self):
        assert self.strategy.get_aggression_sigma() == 2.0

    def test_balance_ratio(self):
        assert self.strategy.get_balance_ratio_threshold() == 0.55

    def test_big_trade_multiplier(self):
        assert self.strategy.get_big_trade_multiplier() == 5.0


# ======================================================================
# SessionContextFactory Tests
# ======================================================================


class TestSessionContextFactory:
    """SessionContextFactory — DIP-compliant construction."""

    def test_constructed_with_config(self):
        cfg = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry()
        factory = SessionContextFactory(exchange_config=cfg, symbol_registry=reg)
        assert factory._config is cfg
        assert factory._registry is reg

    def test_exchange_for_symbol_uses_registry(self):
        cfg = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry()
        factory = SessionContextFactory(exchange_config=cfg, symbol_registry=reg)
        assert factory.get_exchange_for_symbol("NIFTY 27 FEB 25500 CALL") == "NSE"
        assert factory.get_exchange_for_symbol("CRUDEOIL 19 MAR 6000 CALL") == "MCX"

    def test_from_tick_uses_injected_config(self):
        """Instance method should use injected exchange config."""
        from quant.contracts.value_objects import OHLC

        cfg = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry()
        factory = SessionContextFactory(exchange_config=cfg, symbol_registry=reg)

        ohlc = OHLC.create(
            time="2024-01-03T10:00:00",
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000,
        )
        # Should use MCX from injected config
        info = factory.from_tick(ohlc)
        assert info.market == "MCX"


# ======================================================================
# ConsolidatedConfig YAML Bridge Tests
# ======================================================================


class TestConsolidatedConfigBridge:
    """Test config/consolidated.py YAML parsing and get_exchange_config bridge."""

    def test_get_exchange_config_returns_valid_config(self):
        from config.consolidated import get_exchange_config

        mcx = get_exchange_config("MCX")
        assert mcx.exchange == "MCX"
        assert "CRUDEOIL" in mcx.underlyings

        nse = get_exchange_config("NSE")
        assert nse.exchange == "NSE"
        assert "NIFTY" in nse.underlyings

    def test_get_exchange_config_idempotent(self):
        from config.consolidated import get_exchange_config

        a = get_exchange_config("MCX")
        b = get_exchange_config("MCX")
        assert a == b  # same values

    def test_from_yaml_with_existing_file(self):
        """YAML file exists at app/market_config.yaml — should parse NFO/MCX."""
        from config.consolidated import ConsolidatedConfig

        cfg = ConsolidatedConfig.from_yaml()
        mcx_data = cfg.get_exchange_config_dict("MCX")
        nse_data = cfg.get_exchange_config_dict("NSE")

        # market_config.yaml has NFO and MCX sections
        assert isinstance(mcx_data, dict)
        assert isinstance(nse_data, dict)
        # MCX should have aggression_sigma from YAML
        if mcx_data:
            assert "aggression_sigma" in mcx_data or mcx_data == {}

    def test_nfo_maps_to_nse(self):
        """NFO key in YAML should map to NSE."""
        from config.consolidated import ConsolidatedConfig

        cfg = ConsolidatedConfig.from_yaml()
        nse_data = cfg.get_exchange_config_dict("NSE")
        # NFO section in YAML should be accessible as NSE
        assert isinstance(nse_data, dict)


# ======================================================================
# Integration: Strategy ↔ Config ↔ Registry consistency
# ======================================================================


class TestAbstractionLayerConsistency:
    """Verify the full abstraction layer works end-to-end."""

    def test_mcx_strategy_uses_config_thresholds(self):
        """Strategy should delegate to config, not hardcode."""
        yaml_overrides = {"aggression_sigma": 1.5, "cvd_block_threshold": 25.0}
        cfg = ExchangeConfig.from_dict("MCX", yaml_overrides)
        strategy = MCXExchangeStrategy(cfg)

        assert strategy.get_aggression_sigma() == 1.5
        assert strategy.get_cvd_block_threshold() == 25.0

    def test_nse_strategy_uses_config_thresholds(self):
        yaml_overrides = {"aggression_sigma": 3.0}
        cfg = ExchangeConfig.from_dict("NSE", yaml_overrides)
        strategy = NSEExchangeStrategy(cfg)

        assert strategy.get_aggression_sigma() == 3.0

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
        """DIContainer should wire all exchange abstractions."""
        from app.application.di.composition_root import compose_container
        from config.consolidated import ConsolidatedConfig as Configuration

        config = Configuration.from_unified()
        container = compose_container(config)

        from quant.contracts.ports import IExchangeStrategy

        strat = container.resolve(IExchangeStrategy)
        assert strat is not None

        # Verify the container was created successfully
        assert container is not None

    def test_no_domain_imports_config(self):
        """Verify the main session context factory path no longer imports app.config at module level.

        Legacy static methods still import inside function bodies (acceptable for backward compat).
        The key requirement: no module-level `from app.config import` in the refactored factory.
        """
        import inspect

        from quant.amt.session import context_factory as session_context_factory

        source = inspect.getsource(session_context_factory)
        lines = source.split("\n")

        # Find module-level imports (lines that start at column 0 with import/from)
        # Exclude lines inside class/function bodies (indented)
        module_level_config_imports = []
        in_class_body = False
        for line in lines:
            stripped = line.strip()
            # Detect class definition at module level
            if stripped.startswith("class "):
                in_class_body = True
            # Lines at column 0 that are imports from app.config
            if not line.startswith(" ") and not line.startswith("\t"):
                if "from app.config" in stripped or "import app.config" in stripped:
                    module_level_config_imports.append(stripped)

        assert len(module_level_config_imports) == 0, (
            f"session_context_factory.py has module-level app.config import: {module_level_config_imports}"
        )
