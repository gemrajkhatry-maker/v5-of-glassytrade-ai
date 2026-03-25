"""Tests for WalkForwardValidator, VolatilityFeatureProvider, and Watchdog."""

import asyncio
import pytest

from app.domain.services.walk_forward_validator import (
    WalkForwardValidator,
    WalkForwardWindow,
    ValidationResult,
)
from app.domain.services.volatility_features import (
    VolatilityFeatureProvider,
    VolatilityFeatures,
    VIXRegime,
)
from app.domain.services.watchdog import Watchdog, SessionWatchEntry


# ===== Walk-Forward Validator =====


class TestWalkForwardValidator:
    def test_pass_all_windows(self):
        validator = WalkForwardValidator()
        windows = [
            WalkForwardWindow(
                iteration=i,
                train_start="2024-01",
                train_end="2024-03",
                test_start="2024-04",
                test_end="2024-04",
                train_samples=5000,
                test_samples=1700,
                accuracy=0.62,
                precision=0.60,
                recall=0.58,
                f1_score=0.59,
                brier_score=0.20,
                profit_factor=1.6,
                top_features=[("feat1", 0.05), ("feat2", 0.02)],
                precision_pass=True,
                profit_factor_pass=True,
                brier_pass=True,
            )
            for i in range(3)
        ]
        result = validator.validate("lgbm_long", "LONG", windows)
        assert result.overall_result == ValidationResult.PASS

    def test_fail_precision(self):
        validator = WalkForwardValidator()
        windows = [
            WalkForwardWindow(
                iteration=0,
                train_start="2024-01",
                train_end="2024-03",
                test_start="2024-04",
                test_end="2024-04",
                train_samples=5000,
                test_samples=1700,
                accuracy=0.55,
                precision=0.52,
                recall=0.50,
                f1_score=0.51,
                brier_score=0.20,
                profit_factor=1.5,
                top_features=[("feat1", 0.05)],
                precision_pass=False,
                profit_factor_pass=True,
                brier_pass=True,
            )
        ]
        result = validator.validate("lgbm_long", "LONG", windows)
        assert result.overall_result == ValidationResult.FAIL

    def test_empty_windows(self):
        validator = WalkForwardValidator()
        result = validator.validate("lgbm", "LONG", [])
        assert result.overall_result == ValidationResult.FAIL

    def test_brier_score(self):
        validator = WalkForwardValidator()
        score = validator.compute_brier_score(
            predicted_probs=[0.8, 0.3, 0.9],
            actual_outcomes=[1, 0, 1],
        )
        assert score < 0.1  # perfect predictions → low Brier

    def test_profit_factor(self):
        validator = WalkForwardValidator()
        pf = validator.compute_profit_factor(
            predicted_probs=[0.7, 0.8, 0.6, 0.7],
            actual_outcomes=[1, 1, 0, 1],
            threshold=0.55,
        )
        assert pf == 3.0  # 3 wins / 1 loss

    def test_feature_pruning(self):
        validator = WalkForwardValidator()
        windows = [
            WalkForwardWindow(
                iteration=0,
                train_start="2024-01",
                train_end="2024-03",
                test_start="2024-04",
                test_end="2024-04",
                train_samples=5000,
                test_samples=1700,
                accuracy=0.60,
                precision=0.60,
                recall=0.58,
                f1_score=0.59,
                brier_score=0.20,
                profit_factor=1.5,
                top_features=[("good", 0.05), ("noise", 0.0005)],
                precision_pass=True,
                profit_factor_pass=True,
                brier_pass=True,
            )
        ]
        result = validator.validate("lgbm", "LONG", windows)
        assert "noise" in result.pruned_features
        assert "good" not in result.pruned_features


# ===== Volatility Feature Provider =====


class TestVolatilityFeatureProvider:
    def test_vix_regime_low(self):
        provider = VolatilityFeatureProvider()
        features = provider.get_features("NIFTY", vix_value=10.0)
        assert features.vix_regime_name == "LOW"
        assert features.vix_regime == VIXRegime.LOW

    def test_vix_regime_spike(self):
        provider = VolatilityFeatureProvider()
        features = provider.get_features("NIFTY", vix_value=30.0)
        assert features.vix_regime_name == "SPIKE"
        assert features.vix_regime == VIXRegime.SPIKE

    def test_vix_normalized(self):
        provider = VolatilityFeatureProvider()
        features = provider.get_features("NIFTY", vix_value=20.0)
        assert features.india_vix_normalized == 1.0

    def test_pcr_computation(self):
        provider = VolatilityFeatureProvider()
        features = provider.get_features(
            "NIFTY",
            total_put_oi=120000,
            total_call_oi=100000,
        )
        assert features.pcr_oi == 1.2
        assert features.pcr_signal_normalized > 0

    def test_iv_rank(self):
        provider = VolatilityFeatureProvider()
        # Build 20-day IV history
        for i in range(20):
            provider.update_iv("NIFTY", 15.0 + i)
        features = provider.get_features("NIFTY", current_iv=25.0)
        assert features.iv_rank > 50  # above median

    def test_feature_dict(self):
        provider = VolatilityFeatureProvider()
        features = provider.get_features("NIFTY", vix_value=18.0)
        d = features.to_feature_dict()
        assert "india_vix_normalized" in d
        assert "vix_regime" in d
        assert isinstance(d["vix_regime"], float)

    def test_risk_adjustments_spike(self):
        provider = VolatilityFeatureProvider()
        adj = provider.get_risk_adjustments(VIXRegime.SPIKE)
        assert adj["block_tier_a"] is True
        assert adj["sl_multiplier"] == 1.5

    def test_risk_adjustments_low(self):
        provider = VolatilityFeatureProvider()
        adj = provider.get_risk_adjustments(VIXRegime.LOW)
        assert adj["ml_threshold_adjust"] == 0.05
        assert adj["size_multiplier"] == 0.80


# ===== Watchdog =====


class TestWatchdog:
    def test_register_session(self):
        watchdog = Watchdog()
        watchdog.register_session("NIFTY", task=None)
        assert "NIFTY" in watchdog._sessions

    def test_unregister_session(self):
        watchdog = Watchdog()
        watchdog.register_session("NIFTY", task=None)
        watchdog.unregister_session("NIFTY")
        assert "NIFTY" not in watchdog._sessions

    def test_get_status(self):
        watchdog = Watchdog()
        watchdog.register_session("NIFTY", task=None)
        status = watchdog.get_status()
        assert "sessions" in status
        assert "NIFTY" in status["sessions"]

    def test_alerts(self):
        watchdog = Watchdog()
        watchdog._alerts.append(
            {
                "symbol": "NIFTY",
                "error": "test",
                "timestamp": "2024-01-01T00:00:00",
            }
        )
        alerts = watchdog.get_alerts()
        assert len(alerts) == 1

    def test_stop(self):
        watchdog = Watchdog()
        watchdog.stop()
        assert watchdog._running is False
