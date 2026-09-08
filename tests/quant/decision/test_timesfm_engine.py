"""Unit tests for native TimesFM 3.0 Quantitative Decision Engine."""

import pytest
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_engine import TimesFMEngine


@pytest.fixture
def sample_context():
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    return DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=2.1,
        absorption_side="BUY",
        session_phase="PRIMARY",
    )


def test_timesfm_engine_padding(sample_context):
    engine = TimesFMEngine(target_horizon=32)
    prices = engine.add_context(sample_context)
    assert len(prices) == 32
    assert all(p == 6460.0 for p in prices)


def test_timesfm_engine_risk_halted():
    ctx = DecisionContext(symbol="GOLDM", risk_halted=True)
    engine = TimesFMEngine(target_horizon=32)
    res = engine.analyze(ctx)

    assert res["action"] == "FLAT"
    assert res["direction"] == "FLAT"
    assert res["setup"] == "NO_EDGE"
    assert "Daily risk threshold reached" in res["rationale"]


def test_timesfm_engine_opening_noise():
    ctx = DecisionContext(symbol="SILVERM", session_phase="OPENING_NOISE")
    engine = TimesFMEngine(target_horizon=32)
    res = engine.analyze(ctx)

    assert res["action"] == "FLAT"
    assert res["direction"] == "FLAT"
    assert "Opening noise" in res["rationale"]
