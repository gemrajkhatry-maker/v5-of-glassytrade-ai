"""Tests for LightGBM probability adapter schema handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter


def test_estimate_uses_model_feature_names_and_ignores_runtime_extras():
    adapter = LGBMProbabilityAdapter.__new__(LGBMProbabilityAdapter)
    adapter._ready = True
    adapter._feature_names = ("close_vs_poc_pct", "book_imbalance_l1")
    adapter._calibrators = {}
    adapter._mfe_long = None
    adapter._mfe_short = None
    adapter._calibrate = lambda value, direction: value

    model_long = MagicMock()
    model_short = MagicMock()
    model_long.predict.return_value = np.array([0.7])
    model_short.predict.return_value = np.array([0.2])
    adapter._model_long = model_long
    adapter._model_short = model_short

    estimate = adapter.estimate(
        {
            "close_vs_poc_pct": 0.1,
            "book_imbalance_l1": 0.3,
            "book_imbalance_l20": 0.9,
        }
    )

    assert estimate.p_long_target == 0.7
    assert estimate.p_short_target == 0.2

    long_arr = model_long.predict.call_args.args[0]
    assert long_arr.shape == (1, 2)
    assert float(long_arr[0, 0]) == 0.1
    assert float(long_arr[0, 1]) == 0.3
