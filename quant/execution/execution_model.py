"""Explicit execution topology for instrument-isolated trading."""
from __future__ import annotations

from enum import StrEnum


class ExecutionModel(StrEnum):
    """How a decision may relate to the contract it trades."""

    INDEPENDENT = "independent"
    CROSS_CONFIRMED = "cross_confirmed"
    LEGACY_TRANSLATED = "legacy_translated"


def validate_execution_model(value: str | ExecutionModel | None) -> ExecutionModel:
    """Normalize and validate topology; missing configuration is independent."""
    if value is None or str(value).strip() == "":
        return ExecutionModel.INDEPENDENT
    try:
        return ExecutionModel(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError(f"unsupported execution_model: {value!r}") from exc


def independent_execution_allowed(model: str | ExecutionModel | None) -> bool:
    """Return whether local same-contract execution is enabled."""
    return validate_execution_model(model) is ExecutionModel.INDEPENDENT


def signal_matches_contract(signal_symbol: str | None, contract_symbol: str) -> bool:
    """Ensure an execution intent cannot cross an engine contract boundary."""
    return bool(signal_symbol and contract_symbol and str(signal_symbol).strip() == str(contract_symbol).strip())
