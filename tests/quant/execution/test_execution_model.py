"""Independent execution topology tests."""
from __future__ import annotations

import pytest

from quant.execution.execution_model import (
    ExecutionModel,
    independent_execution_allowed,
    validate_execution_model,
)


def test_missing_topology_defaults_to_independent():
    assert validate_execution_model(None) is ExecutionModel.INDEPENDENT
    assert independent_execution_allowed("")


def test_topology_values_are_explicit():
    assert validate_execution_model("independent") is ExecutionModel.INDEPENDENT
    assert validate_execution_model("CROSS_CONFIRMED") is ExecutionModel.CROSS_CONFIRMED
    assert validate_execution_model("legacy_translated") is ExecutionModel.LEGACY_TRANSLATED


def test_unknown_topology_fails_closed():
    with pytest.raises(ValueError, match="execution_model"):
        validate_execution_model("futures_to_options")


def test_only_independent_mode_allows_local_only_contract_execution():
    assert independent_execution_allowed(ExecutionModel.INDEPENDENT)
    assert not independent_execution_allowed(ExecutionModel.CROSS_CONFIRMED)
    assert not independent_execution_allowed(ExecutionModel.LEGACY_TRANSLATED)
