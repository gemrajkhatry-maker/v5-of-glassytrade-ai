"""Tests for Gate 13: Session Strategy Filter."""

import pytest
from app.domain.fabio_ai.services.gate_pipeline import (
    GatePipeline,
    GateContext,
    GateReason,
)
from app.domain.trading.models.enums import MarketState


class TestGate13SessionStrategyFilter:
    """Gate 13: Session strategy filter per Fabio's timing rules.

    - Phase 3 (11:30-14:00): MEAN_REVERSION only
    - TREND_MODEL blocked when session favors MEAN_REVERSION
    - All models allowed in NEUTRAL sessions
    """

    def _base_ctx(self, **overrides) -> GateContext:
        """Base context with all hard gates passing."""
        base = dict(
            candle_count=10,
            tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=2.5,
            cushion_ticks=5,
            r_r_ratio=2.0,
            position_size_ok=True,
            eia_window_active=False,
            setup_type="MEAN_REVERSION",
        )
        base.update(overrides)
        return GateContext(**base)

    def test_trend_model_blocked_in_mean_reversion_session(self):
        """TREND_MODEL in MEAN_REVERSION-favored session → BLOCKED."""
        ctx = self._base_ctx(
            setup_type="TREND_MODEL",
            favor_strategy="MEAN_REVERSION",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 13
        assert result.reason == GateReason.BLOCKED
        assert "blocked" in result.detail.lower()

    def test_mean_reversion_allowed_in_neutral_session(self):
        """MEAN_REVERSION in NEUTRAL session → allowed."""
        ctx = self._base_ctx(
            setup_type="MEAN_REVERSION",
            favor_strategy="NEUTRAL",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.reason == GateReason.TRADE

    def test_trend_model_allowed_in_trend_session(self):
        """TREND_MODEL in TREND_CONTINUATION-favored session → allowed."""
        ctx = self._base_ctx(
            setup_type="TREND_MODEL",
            favor_strategy="TREND_CONTINUATION",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.reason == GateReason.TRADE

    def test_no_setup_passes_filter(self):
        """NONE setup passes session filter (NEUTRAL)."""
        ctx = self._base_ctx(
            setup_type="NONE",
            favor_strategy="MEAN_REVERSION",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.reason == GateReason.TRADE