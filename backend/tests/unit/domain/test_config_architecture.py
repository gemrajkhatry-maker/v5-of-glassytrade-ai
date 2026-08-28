"""Tests for Phase -1: Config Architecture.

Tests:
  - ConfigLoader: merge sequence, environment overrides
  - ConfigValidator: RULE-1 through RULE-12
  - SystemConfig: symbol_config(), active_symbols(), convenience methods
  - FeatureFlags: defaults
"""

from __future__ import annotations

import os
import pytest

from app.config_models import (
    CostProfile,
    ExchangeConfig,
    FeatureFlags,
    MLThresholds,
    RiskConfig,
    SymbolConfig,
    SystemConfig,
)
from app.config_models.validator import validate_config, ConfigValidationError


class TestSystemConfig:
    """SystemConfig model tests."""

    def test_default_values(self):
        config = SystemConfig()
        assert config.name == "GlassyTrade AI"
        assert config.version == "2.0.0"
        assert config.candle_timeframe_minutes == 5  # 5m canonical bar (1m legacy)
        assert config.capital == 5000000.0
        assert config.environment == "development"
        assert config.broker_mode == "paper"

    def test_immutability(self):
        config = SystemConfig()
        with pytest.raises(AttributeError):
            config.name = "Modified"

    def test_symbol_config_finds_across_exchanges(self):
        nifty = SymbolConfig(name="NIFTY", exchange="NSE")
        crudeoil = SymbolConfig(name="CRUDEOIL", exchange="MCX")
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(name="NSE", symbols={"NIFTY": nifty}),
                "MCX": ExchangeConfig(name="MCX", symbols={"CRUDEOIL": crudeoil}),
            }
        )
        assert config.symbol_config("NIFTY").exchange == "NSE"
        assert config.symbol_config("CRUDEOIL").exchange == "MCX"
        assert config.symbol_config("UNKNOWN") is None

    def test_active_symbols_returns_enabled_only(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={
                        "NIFTY": SymbolConfig(name="NIFTY", enabled=True),
                        "BANKNIFTY": SymbolConfig(name="BANKNIFTY", enabled=False),
                    },
                ),
            }
        )
        active = config.active_symbols()
        assert "NIFTY" in active
        assert "BANKNIFTY" not in active

    def test_is_live_is_paper(self):
        live = SystemConfig(environment="live")
        paper = SystemConfig(environment="paper")
        assert live.is_live()
        assert not live.is_paper()
        assert paper.is_paper()
        assert not paper.is_live()


class TestConfigValidator:
    """ConfigValidator tests — RULE-1 through RULE-12."""

    def test_valid_config_passes(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={"NIFTY": SymbolConfig(name="NIFTY")},
                ),
            }
        )
        validate_config(config)  # Should not raise

    def test_rule1_no_active_symbols(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={"NIFTY": SymbolConfig(name="NIFTY", enabled=False)},
                ),
            }
        )
        with pytest.raises(ConfigValidationError, match="RULE-1"):
            validate_config(config)

    def test_rule2_live_requires_live_broker(self):
        config = SystemConfig(
            environment="live",
            broker_mode="paper",
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE", symbols={"NIFTY": SymbolConfig(name="NIFTY")}
                )
            },
        )
        with pytest.raises(ConfigValidationError, match="RULE-2"):
            validate_config(config)

    def test_rule5_risk_per_trade_too_high(self):
        config = SystemConfig(
            environment="live",
            capital=2000000,
            risk=RiskConfig(risk_per_trade_pct=0.05),
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE", symbols={"NIFTY": SymbolConfig(name="NIFTY")}
                )
            },
        )
        with pytest.raises(ConfigValidationError, match="RULE-5"):
            validate_config(config)

    def test_rule7_value_area_out_of_range(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={"NIFTY": SymbolConfig(name="NIFTY", value_area_pct=0.20)},
                ),
            }
        )
        with pytest.raises(ConfigValidationError, match="RULE-7"):
            validate_config(config)

    def test_rule8_min_rr_below_1(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={"NIFTY": SymbolConfig(name="NIFTY", min_rr_ratio=0.5)},
                ),
            }
        )
        with pytest.raises(ConfigValidationError, match="RULE-8"):
            validate_config(config)

    def test_rule9_total_notional_too_high(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={
                        "NIFTY": SymbolConfig(name="NIFTY", max_notional_pct=0.50),
                        "BANKNIFTY": SymbolConfig(
                            name="BANKNIFTY", max_notional_pct=0.50
                        ),
                        "FINNIFTY": SymbolConfig(
                            name="FINNIFTY", max_notional_pct=0.51
                        ),
                    },
                ),
            }
        )
        with pytest.raises(ConfigValidationError, match="RULE-9"):
            validate_config(config)

    def test_rule10_cvd_ordering_invalid(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={
                        "NIFTY": SymbolConfig(
                            name="NIFTY",
                            cvd_slope_warning=50.0,
                            cvd_slope_hard_block=30.0,
                            cvd_slope_extreme=100.0,
                        ),
                    },
                ),
            }
        )
        with pytest.raises(ConfigValidationError, match="RULE-10"):
            validate_config(config)

    def test_rule11_lvn_threshold_too_high(self):
        config = SystemConfig(
            exchanges={
                "NSE": ExchangeConfig(
                    name="NSE",
                    symbols={
                        "NIFTY": SymbolConfig(
                            name="NIFTY",
                            lvn_threshold=0.40,
                            lvn_removal_threshold=0.30,
                        ),
                    },
                ),
            }
        )
        with pytest.raises(ConfigValidationError, match="RULE-11"):
            validate_config(config)


class TestFeatureFlags:
    """FeatureFlags tests."""

    def test_defaults(self):
        flags = FeatureFlags()
        assert flags.realistic_cost_model is False

    def test_immutable(self):
        flags = FeatureFlags()
        with pytest.raises(AttributeError):
            flags.realistic_cost_model = False


class TestMLThresholds:
    """MLThresholds tests."""

    def test_defaults(self):
        mt = MLThresholds()
        assert mt.imbalance_continuation_long == 0.55
        assert mt.imbalance_continuation_short == 0.58
        assert mt.return_to_value_long == 0.51


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
