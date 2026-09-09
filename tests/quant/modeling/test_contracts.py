from dataclasses import FrozenInstanceError

import pytest

from quant.modeling.contracts import ForecastSnapshot, ForecastStatus, StrategyMode
from quant.modeling.mode import ModeController


def test_available_snapshot_requires_model_version():
    with pytest.raises(ValueError, match="model_version"):
        ForecastSnapshot(symbol="NIFTY", decision_sequence=1, status=ForecastStatus.AVAILABLE)


def test_unavailable_snapshot_is_serializable_and_explicit():
    snapshot = ForecastSnapshot(
        symbol="NIFTY",
        decision_sequence=2,
        status=ForecastStatus.UNAVAILABLE,
        failure_reason="timesfm missing",
    )
    assert snapshot.to_dict()["status"] == "UNAVAILABLE"
    assert snapshot.to_dict()["failure_reason"] == "timesfm missing"
    with pytest.raises(FrozenInstanceError):
        snapshot.symbol = "BANKNIFTY"


@pytest.mark.parametrize(
    ("mode", "status", "expected"),
    [
        (StrategyMode.TIMESFM_PRIMARY, ForecastStatus.UNAVAILABLE, StrategyMode.SAFE_HALT),
        (StrategyMode.TIMESFM_PRIMARY, ForecastStatus.INFERENCE_FAILED, StrategyMode.SAFE_HALT),
        (StrategyMode.TIMESFM_ASSISTED, ForecastStatus.UNAVAILABLE, StrategyMode.DETERMINISTIC),
        (StrategyMode.DETERMINISTIC, ForecastStatus.UNAVAILABLE, StrategyMode.DETERMINISTIC),
    ],
)
def test_mode_controller_maps_model_failure(mode, status, expected):
    assert ModeController(mode).next_mode(status) is expected


def test_available_model_keeps_configured_mode():
    assert ModeController(StrategyMode.TIMESFM_PRIMARY).next_mode(ForecastStatus.AVAILABLE) is StrategyMode.TIMESFM_PRIMARY
