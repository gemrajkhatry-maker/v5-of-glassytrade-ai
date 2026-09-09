import numpy as np
import pytest

from quant.modeling.contracts import ForecastStatus
from quant.modeling.forecast_provider import ForecastProvider


class FakeModel:
    def __init__(self):
        self.calls = 0

    def predict(self, *, context, horizon, return_quantiles):
        self.calls += 1
        p50 = np.full((horizon, 9), float(context[-1]))
        p50[:, 4] += 1.0
        return type("Result", (), {"quantiles": p50})()


def test_provider_reuses_snapshot_for_same_decision_sequence():
    model = FakeModel()
    provider = ForecastProvider(model_loader=lambda: model, horizon=4)

    first = provider.forecast("NIFTY", [100.0, 101.0], decision_sequence=7)
    second = provider.forecast("NIFTY", [100.0, 101.0], decision_sequence=7)

    assert first is second
    assert first.status is ForecastStatus.AVAILABLE
    assert first.model_version == "timesfm"
    assert model.calls == 1


def test_provider_returns_typed_unavailable_snapshot():
    provider = ForecastProvider(model_loader=lambda: (_ for _ in ()).throw(RuntimeError("missing")), horizon=4)

    snapshot = provider.forecast("NIFTY", [100.0], decision_sequence=8)

    assert snapshot.status is ForecastStatus.UNAVAILABLE
    assert "missing" in snapshot.failure_reason
    assert snapshot.to_dict()["status"] == "UNAVAILABLE"
