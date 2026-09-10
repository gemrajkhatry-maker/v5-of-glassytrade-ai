"""D-18: one owner for the quantile -> TimesFMForecast conversion."""

import numpy as np
import pytest

from quant.decision.timesfm_forecast_factory import (
    P10_INDEX,
    P50_INDEX,
    P90_INDEX,
    QUANTILE_COUNT,
    build_forecast,
)


def test_contract_constants():
    assert (P10_INDEX, P50_INDEX, P90_INDEX, QUANTILE_COUNT) == (0, 4, 8, 9)


def test_builds_from_quantiles():
    horizon = 4
    q = np.zeros((horizon, QUANTILE_COUNT), dtype=np.float32)
    q[:, P10_INDEX] = 99.0
    q[:, P50_INDEX] = 100.0
    q[:, P90_INDEX] = 101.0

    fc = build_forecast(q, curr_price=100.0, horizon=horizon, lat_ms=2.0)
    assert fc.p50_path.shape == (horizon,)
    assert fc.p10_path[0] == pytest.approx(99.0)
    assert fc.q_spread == pytest.approx(2.0)
    assert fc.mean_forecast == pytest.approx(100.0)


def test_rejects_a_quantile_count_it_does_not_understand():
    """The (H, 9) contract was asserted by comment in four places and checked
    nowhere; a model change would silently corrupt every consumer."""
    q = np.zeros((4, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="expected 9 quantiles"):
        build_forecast(q, curr_price=100.0, horizon=4, lat_ms=1.0)


def test_degenerate_quantiles_fall_back_to_a_flat_path():
    fc = build_forecast(None, curr_price=100.0, horizon=4, lat_ms=1.0)
    assert np.allclose(fc.p50_path, 100.0)
    assert fc.q_spread == 0.0


def test_steps_are_flat_aware():
    from quant.decision.timesfm_forecast_factory import make_steps

    steps = make_steps([99.0, 100.0, 101.0], curr_price=100.0)
    assert steps == ["SHORT", "FLAT", "LONG"]


def test_no_producer_emits_binary_only_steps():
    """Every TimesFMForecast construction must go through the factory, so no
    site can emit a LONG/SHORT-only series that consumers cannot test for."""
    import pathlib
    import re

    root = pathlib.Path("quant")
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "timesfm_forecast_factory.py":
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"LONG" if p > curr_price else "SHORT"', text):
            offenders.append(f"{path}:{text[:m.start()].count(chr(10)) + 1}")
    assert not offenders, f"binary-only step labels remain: {offenders}"
