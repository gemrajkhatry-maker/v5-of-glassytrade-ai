"""Tests for deterministic engine components — CHANGE 1-5."""

from datetime import datetime

import pytest

from quant.execution.risk_sizing import (
    RiskSizingEngine,
    KellySizingTier,
)


# ===== Risk Sizing Engine =====


class TestRiskSizingEngine:
    def test_standard_lots(self):
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=10000000,  # Increased to get 1+ lots with 65-unit size
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,  # 50 points risk
            target_price=24250,  # 250 points reward
            direction="LONG",
        )
        assert result.allowed
        assert result.lots >= 1

    def test_rr_too_low_blocks(self):
        engine = RiskSizingEngine(min_rr=2.0)
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24025,
            direction="LONG",  # only 0.5R target
        )
        assert not result.allowed
        assert "R:R" in result.reason

    def test_consecutive_loss_reduces(self):
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=-5000,
            consecutive_losses=3,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24250,
            direction="LONG",
        )
        assert result.risk_tier == KellySizingTier.REDUCED
        assert result.risk_pct == 0.0025  # minimum

    def test_winning_session_elevates(self):
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=10000,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24250,
            direction="LONG",
        )
        assert result.risk_tier == KellySizingTier.ELEVATED
        assert result.risk_pct >= 0.0030

    def test_banknifty_lots(self):
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="BANKNIFTY",
            entry_price=51000,
            stop_price=50900,
            target_price=51500,
            direction="LONG",
        )
        assert result.allowed
        assert result.lots >= 1

    def test_scale_in_plan(self):
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24250,
            direction="LONG",
        )
        assert result.scale_in_1 + result.scale_in_2 + result.scale_in_3 == result.lots

    def test_mcx_lot_sizes(self):
        """Test MCX lot sizes are correctly applied."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=5000000,  # Higher equity for MCX lots
            session_pnl=0,
            consecutive_losses=0,
            underlying="CRUDEOIL",
            entry_price=6000,
            stop_price=5950,  # 50 points risk
            target_price=6200,  # 200 points reward
            direction="LONG",
        )
        assert result.allowed
        assert result.lots >= 1
