"""Execution topology configuration contract tests."""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.config_models import SystemConfig
from app.config_models.validator import ConfigValidationError, validate_config


def test_system_config_defaults_to_independent_execution():
    assert SystemConfig().execution_model == "independent"


def test_loaded_strategy_topology_is_independent():
    from app.config_models.loader import load_config

    config = load_config(strategy="nse_options")
    assert config.execution_model == "independent"


def test_legacy_translation_is_rejected_for_live_configuration():
    config = SystemConfig(
        environment="live",
        broker_mode="live",
        execution_model="legacy_translated",
    )
    with pytest.raises(ConfigValidationError, match="RULE-16"):
        validate_config(config)


def test_unknown_execution_topology_is_rejected():
    config = replace(SystemConfig(), execution_model="futures_to_options")
    with pytest.raises(ConfigValidationError, match="RULE-16"):
        validate_config(config)
