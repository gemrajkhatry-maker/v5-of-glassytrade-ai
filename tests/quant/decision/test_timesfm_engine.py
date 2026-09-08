"""Unit tests for native TimesFM 3.0 Quantitative Decision Engine."""

from unittest.mock import Mock, patch

import pytest
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_engine import (
    TimesFMEngine,
    reset_timesfm_model_cache,
)


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


def test_timesfm_engine_warmup_success():
    """warmup() returns True when model loads successfully."""
    reset_timesfm_model_cache()
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.return_value = object()
        assert engine.warmup() is True
        assert engine.is_healthy() is True
        mock_load.assert_called_once_with("cpu")


def test_timesfm_engine_warmup_failure():
    """warmup() returns False and engine degrades to fallback mode on failure."""
    reset_timesfm_model_cache()
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("Model not found")
        assert engine.warmup() is False
        assert engine.is_healthy() is False


def test_timesfm_engine_warmup_idempotent():
    """warmup() is safe to call multiple times."""
    reset_timesfm_model_cache()
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.return_value = object()
        assert engine.warmup() is True
        assert engine.warmup() is True  # second call should be no-op
        mock_load.assert_called_once()  # model loaded only once


def test_timesfm_engine_health_check_healthy():
    """health_check() returns healthy status when model loads."""
    reset_timesfm_model_cache()
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.return_value = object()
        result = TimesFMEngine.health_check()
        assert result["status"] == "healthy"
        assert result["model_loaded"] is True
        assert result["error"] is None


def test_timesfm_engine_health_check_unavailable():
    """health_check() returns unavailable status when model fails."""
    reset_timesfm_model_cache()
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = ImportError("timesfm not installed")
        result = TimesFMEngine.health_check()
        assert result["status"] == "unavailable"
        assert result["model_loaded"] is False
        assert result["error"] is not None


def test_timesfm_engine_session_gate_blocked():
    """analyze() returns FLAT with SESSION_GATE_BLOCKED when session gate denies entry."""
    ctx = DecisionContext(
        symbol="NIFTY",
        time_str="16:45",
        market="NSE",
        session_phase="CLOSE_PROTECTION",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.session_allow_entry") as mock_gate:
        mock_gate.return_value = False
        res = engine.analyze(ctx)
        mock_gate.assert_called_once_with("16:45", "NSE")
        assert res["action"] == "FLAT"
        assert res["direction"] == "FLAT"
        assert res["reason"] == "SESSION_GATE_BLOCKED"
        assert res["confidenceScore"] == 0.0


def test_timesfm_engine_session_gate_allows():
    """analyze() proceeds past session gate when entry is allowed."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        time_str="10:30",
        market="MCX",
        session_phase="PRIMARY",
        cvd_slope=2.1,
        absorption_side="BUY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.session_allow_entry") as mock_gate:
        mock_gate.return_value = True
        with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
            # Use a Mock that raises on predict to trigger fallback path
            mock_model = Mock()
            mock_model.predict.side_effect = RuntimeError("inference error")
            mock_load.return_value = mock_model
            res = engine.analyze(ctx)
            mock_gate.assert_called_once_with("10:30", "MCX")


def test_timesfm_engine_fallback_mode_returns_valid_payload():
    """When model fails to load, analyze() returns a valid fallback decision payload."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=2.1,
        absorption_side="BUY",
        session_phase="PRIMARY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("timesfm package not installed")
        res = engine.analyze(ctx)

        # Verify valid fallback payload
        assert res["source"] == "TIMESFM_FALLBACK"
        assert res["reason"] == "TIMESFM_FALLBACK"
        assert res["setup"] == "RULE_BASED_FALLBACK"
        assert res["confidence"] == "Low"
        assert res["confidenceScore"] == 0.2
        assert res["direction"] == "LONG"  # cvd_slope > 0 and absorption_side == "BUY"
        assert res["action"] == "ENTER_LONG"
        assert res["role"] == "SCANNING"
        assert len(res["forecastSteps"]) == 32
        assert res["meanForecast"] == 6460.0
        assert "TimesFM unavailable" in res["rationale"]
        assert res["modelVersions"]["timesfm"] == "unavailable"
        assert res["modelVersions"]["engine"] == "rule_based_fallback"


def test_timesfm_engine_fallback_mode_flat_when_no_edge():
    """Fallback returns FLAT direction when no AMT edge is present."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=0.0,
        absorption_side="",
        session_phase="PRIMARY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("model load failed")
        res = engine.analyze(ctx)

        assert res["direction"] == "FLAT"
        assert res["action"] == "FLAT"
        assert all(s == "FLAT" for s in res["forecastSteps"])


def test_timesfm_engine_fallback_mode_short_edge():
    """Fallback returns SHORT direction when AMT signals are bearish."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=-3.5,
        absorption_side="SELL",
        session_phase="PRIMARY",
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("model load failed")
        res = engine.analyze(ctx)

        assert res["direction"] == "SHORT"
        assert res["action"] == "ENTER_SHORT"


def test_timesfm_engine_fallback_mode_position_open():
    """Fallback returns HOLD action when position is open."""
    bar = Bar("2026-09-08T15:30:00", 6450.0, 6465.0, 6445.0, 6460.0, 2500, 350)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=6455.0,
        vah=6465.0,
        val=6445.0,
        cvd_slope=2.1,
        absorption_side="BUY",
        session_phase="PRIMARY",
        position_open=True,
        position_side="LONG",
        position_entry_price=6450.0,
    )
    engine = TimesFMEngine(target_horizon=32)
    with patch("quant.decision.timesfm_engine.get_timesfm_model") as mock_load:
        mock_load.side_effect = RuntimeError("model load failed")
        res = engine.analyze(ctx)

        assert res["role"] == "POSITION_MANAGEMENT"
        assert res["action"] == "HOLD"
