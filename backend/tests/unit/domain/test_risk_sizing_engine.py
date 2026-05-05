"""Tests for RiskSizingEngine."""

import pytest
from datetime import datetime

from app.domain.services.risk_sizing_engine import (
    RiskSizingEngine,
    KellySizingTier,
    ExchangeConfig,
    DefaultExchangeConfig,
    SessionPhase,
    get_nse_session_phase,
)


class TestExchangeConfig:
    """Test ExchangeConfig for lot sizes."""

    def test_default_exchange_config_nifty(self):
        """NIFTY options lot size is 25."""
        config = DefaultExchangeConfig()
        assert config.get_lot_size("NIFTY") == 25

    def test_default_exchange_config_banknifty(self):
        """BANKNIFTY options lot size is 15."""
        config = DefaultExchangeConfig()
        assert config.get_lot_size("BANKNIFTY") == 15

    def test_default_exchange_config_unknown(self):
        """Unknown symbols default to 1."""
        config = DefaultExchangeConfig()
        assert config.get_lot_size("UNKNOWN") == 1


class TestRiskSizingEngine:
    """Test deterministic position sizing."""

    def test_standard_sizing(self):
        """Standard sizing with normal parameters."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,  # 1M sufficient for NIFTY lots=25 (corrected)
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,  # 100 point stop
            target_price=24400,  # 400 points target
            direction="LONG",
        )
        assert result.allowed
        assert result.lots >= 1
        assert result.rr_ratio == 4.0  # 400 / 100

    def test_consecutive_losses_reduced_risk(self):
        """2+ consecutive losses reduces risk tier."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=2,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24120,
            direction="LONG",
        )
        assert result.risk_tier == KellySizingTier.REDUCED
        assert result.risk_pct == 0.0025  # Min risk

    def test_session_pnl_elevated_risk(self):
        """Positive session PnL increases risk tier."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=50000,  # 5% session win
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24120,
            direction="LONG",
        )
        assert result.risk_tier == KellySizingTier.ELEVATED
        assert result.risk_pct >= 0.0030

    def test_invalid_stop_rejected(self):
        """Stop below entry for LONG is invalid."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=24100,  # Above entry - invalid for LONG
            target_price=24120,
            direction="LONG",
        )
        assert not result.allowed
        assert "Invalid stop" in result.reason

    def test_rr_below_minimum_rejected(self):
        """RR below 2.0 is rejected."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24050,  # Only 1:1 RR
            direction="LONG",
        )
        assert not result.allowed
        assert "R:R=" in result.reason

    def test_insufficient_risk_for_1_lot(self):
        """Very small equity returns 0 lots."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000,  # Very small
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24120,
            direction="LONG",
        )
        assert not result.allowed
        assert "Insufficient risk" in result.reason

    def test_short_position_sizing(self):
        """Short position sizing works correctly."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=24100,  # 100 point stop above entry
            target_price=23600,  # 400 points below
            direction="SHORT",
        )
        assert result.allowed
        assert result.stop_points == 100  # 24100 - 24000
        assert result.target_points == 400  # 24000 - 23600

    def test_theta_adjustment(self):
        """High theta reduces lot size."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23950,
            target_price=24120,
            direction="LONG",
            theta=50.0,  # High theta
            expected_hold_minutes=30,
        )
        assert result.holding_cost_ratio > 0

    def test_scale_in_plan(self):
        """Scale-in plan follows 40/30/30 rule."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,  # 100 point stop
            target_price=24400,  # 400 points
            direction="LONG",
        )
        assert result.allowed
        # 40/30/30 split
        total = result.scale_in_1 + result.scale_in_2 + result.scale_in_3
        assert total == result.lots
        assert result.scale_in_1 >= result.scale_in_2

    def test_mcx_lot_sizes(self):
        """MCX instruments use correct lot sizes."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="CRUDEOIL",
            entry_price=6000,
            stop_price=5980,  # 20 point stop (CRUDEOIL lots = 100)
            target_price=6280,  # 280 points
            direction="LONG",
        )
        assert result.allowed

    def test_exchange_config_integration(self):
        """RiskSizingEngine uses ExchangeConfig for lot sizes."""
        # Custom exchange config (simulating broker's instrument cache)
        class BrokerExchangeConfig:
            def get_lot_size(self, underlying: str) -> int:
                lot_sizes = {"NIFTY": 25, "BANKNIFTY": 15}
                return lot_sizes.get(underlying, 1)
        
        engine = RiskSizingEngine(exchange_config=BrokerExchangeConfig())
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
        )
        assert result.allowed
        assert result.lots >= 1

    def test_breakeven_result_fields(self):
        """SizingResult includes breakeven fields."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
        )
        assert result.allowed
        assert result.breakeven_points > 0
        assert result.breakeven_minutes == 1

    def test_breakeven_trigger_on_1r_move(self):
        """Breakeven triggers when price moves 1R in favor."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,  # 100 point stop
            target_price=24400,  # 400 point target
            direction="LONG",
        )
        
        # Price moves 1R (100 points) in favor - should trigger breakeven
        action = engine.check_breakeven(
            sizing_result=result,
            entry_price=24000,
            current_price=24100,  # 100 points in favor
            direction="LONG",
        )
        assert action.move_to_breakeven
        assert action.trigger_reason == "1R"
        assert action.new_stop_price > 24000  # Above entry

    def test_breakeven_trigger_on_cushion(self):
        """Breakeven triggers when floating PnL > original risk."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
        )
        
        # No 1R move yet, but cushion condition met
        original_risk = 10000  # 0.1% of 1M
        action = engine.check_breakeven(
            sizing_result=result,
            entry_price=24000,
            current_price=24020,  # Only 20 points move
            direction="LONG",
            floating_pnl=original_risk * 1.5,  # 1.5x original risk
            original_risk_amount=original_risk,
        )
        assert action.move_to_breakeven
        assert action.trigger_reason == "cushion"

    def test_breakeven_not_triggered_early(self):
        """Breakeven not triggered before 1R or cushion."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
        )
        
        # Small move - no trigger
        action = engine.check_breakeven(
            sizing_result=result,
            entry_price=24000,
            current_price=24030,  # Only 30 points
            direction="LONG",
        )
        assert not action.move_to_breakeven

    def test_breakeven_short_position(self):
        """Breakeven works for short positions."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=24100,  # 100 point stop above
            target_price=23600,  # 400 point target below
            direction="SHORT",
        )
        
        # Price moves against entry for shorts (down)
        action = engine.check_breakeven(
            sizing_result=result,
            entry_price=24000,
            current_price=23900,  # 100 points in favor for short
            direction="SHORT",
        )
        assert action.move_to_breakeven
        assert action.trigger_reason == "1R"
        assert action.new_stop_price < 24000  # Below entry for short


class TestSessionPhase:
    """Test session phase enforcement per Rule 1."""

    def test_session_phase_opening_noise(self):
        """Opening Noise phase (09:15-09:30) blocks trades."""
        from datetime import datetime, timezone
        
        # 09:20 IST
        time_0920 = datetime(2026, 1, 15, 9, 20, tzinfo=timezone.utc)
        phase = get_nse_session_phase(time_0920)
        assert phase == SessionPhase.OPENING_NOISE
        
    def test_session_phase_primary_window(self):
        """Primary Window (09:30-11:30) allows trades."""
        from datetime import datetime, timezone
        
        # 10:00 IST
        time_1000 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        phase = get_nse_session_phase(time_1000)
        assert phase == SessionPhase.PRIMARY_WINDOW

    def test_session_phase_close_protection(self):
        """Close Protection (15:15-15:30) blocks new entries."""
        from datetime import datetime, timezone
        
        # 15:20 IST
        time_1520 = datetime(2026, 1, 15, 15, 20, tzinfo=timezone.utc)
        phase = get_nse_session_phase(time_1520)
        assert phase == SessionPhase.CLOSE_PROTECTION

    def test_trade_blocked_in_opening_noise(self):
        """Trading during Opening Noise returns not allowed."""
        from datetime import datetime, timezone
        
        engine = RiskSizingEngine()
        time_0920 = datetime(2026, 1, 15, 9, 20, tzinfo=timezone.utc)
        
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=time_0920,
        )
        assert not result.allowed
        assert "Opening Noise" in result.reason

    def test_trade_blocked_in_close_protection(self):
        """Trading during Close Protection returns not allowed."""
        from datetime import datetime, timezone
        
        engine = RiskSizingEngine()
        time_1520 = datetime(2026, 1, 15, 15, 20, tzinfo=timezone.utc)
        
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=time_1520,
        )
        assert not result.allowed
        assert "Close Protection" in result.reason

    def test_trade_allowed_in_primary_window(self):
        """Trading during Primary Window is allowed."""
        from datetime import datetime, timezone
        
        engine = RiskSizingEngine()
        time_1000 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=time_1000,
        )
        assert result.allowed

    def test_trade_blocked_monday_opening_noise_extended(self):
        """Trading on Monday 09:30-09:45 should be blocked (gap risk)."""
        from datetime import datetime, timezone
        
        engine = RiskSizingEngine()
        # Monday 09:40 - should be blocked due to extended opening noise
        time_monday_0940 = datetime(2026, 1, 5, 9, 40, tzinfo=timezone.utc)  # Jan 5, 2026 is a Monday
        
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=time_monday_0940,
        )
        assert not result.allowed
        assert "Opening Noise" in result.reason


class TestBidAskSpread:
    """Test bid-ask spread validation per Rule B5."""

    def test_spread_ok_when_below_threshold(self):
        """Spread < 2% is accepted."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            premium=200.0,  # ₹200 premium
            bid_ask_spread=2.0,  # ₹2 spread = 1% of premium
        )
        assert result.allowed
        assert result.bid_ask_spread_ok
        assert result.spread_pct == 0.01  # 1%

    def test_spread_flagged_when_above_threshold(self):
        """Spread > 2% is flagged."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            premium=200.0,  # ₹200 premium
            bid_ask_spread=6.0,  # ₹6 spread = 3% of premium (too wide)
        )
        assert result.allowed  # Still allowed, but flagged
        assert not result.bid_ask_spread_ok
        assert result.spread_pct == 0.03  # 3%

    def test_no_spread_validation_without_premium(self):
        """Without premium data, spread validation is skipped."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            bid_ask_spread=10.0,  # Wide spread, but no premium
        )
        assert result.allowed
        assert result.bid_ask_spread_ok  # Default to True when no premium


class TestLiquidityFilters:
    """Test liquidity filters per Rule B1 (min OI, min volume)."""

    def test_liquidity_ok_when_oi_and_volume_meet_thresholds(self):
        """Trade allowed when OI >= 10 lakh and volume >= 50k."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            oi=1500000,  # 15 lakh OI (above 10 lakh threshold)
            volume=75000,  # 75k volume (above 50k threshold)
        )
        assert result.allowed
        assert result.liquidity_ok
        assert result.oi_ok
        assert result.volume_ok

    def test_liquidity_flagged_when_oi_below_threshold(self):
        """OI flag when below 10 lakh for NIFTY."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            oi=800000,  # 8 lakh OI (below 10 lakh threshold)
            volume=75000,
        )
        assert result.allowed  # Still allowed, but flagged
        assert not result.liquidity_ok
        assert not result.oi_ok
        assert result.volume_ok

    def test_liquidity_flagged_when_volume_below_threshold(self):
        """Volume flag when below 50k."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            oi=1500000,
            volume=30000,  # 30k volume (below 50k threshold)
        )
        assert result.allowed
        assert not result.liquidity_ok
        assert result.oi_ok
        assert not result.volume_ok

    def test_banKNIFTY_lower_oi_threshold(self):
        """BANKNIFTY requires only 5 lakh OI."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="BANKNIFTY",
            entry_price=50000,
            stop_price=49800,
            target_price=50400,
            direction="LONG",
            oi=600000,  # 6 lakh OI (above 5 lakh threshold for BANKNIFTY)
            volume=60000,
        )
        assert result.allowed
        assert result.liquidity_ok
        assert result.oi_ok  # Passes because BANKNIFTY threshold is 5 lakh

    def test_no_liquidity_filter_without_data(self):
        """Without OI/volume data, liquidity validation is skipped."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            oi=0,  # No OI data
            volume=0,  # No volume data
        )
        assert result.allowed
        assert result.liquidity_ok  # Default to True when no data


class TestExpirySelection:
    """Test expiry selection logic per Rule B2 (min 3 days to expiry)."""

    def test_trade_allowed_with_3_days_to_expiry(self):
        """Trade allowed when exactly 3 days to expiry."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            days_to_expiry=3,
        )
        assert result.allowed

    def test_trade_allowed_with_more_than_3_days(self):
        """Trade allowed when more than 3 days to expiry."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            days_to_expiry=5,
        )
        assert result.allowed

    def test_trade_blocked_with_2_days_to_expiry(self):
        """Trade blocked when only 2 days to expiry."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            days_to_expiry=2,
        )
        assert not result.allowed
        assert "minimum 3 required" in result.reason

    def test_trade_blocked_with_1_day_to_expiry(self):
        """Trade blocked when only 1 day to expiry."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="BANKNIFTY",
            entry_price=50000,
            stop_price=49800,
            target_price=50400,
            direction="LONG",
            days_to_expiry=1,
        )
        assert not result.allowed
        assert "Expiry risk" in result.reason


class TestIVEventFilter:
    """Test IV crush event filter per Rule B6."""

    def test_normal_size_when_no_iv_event(self):
        """Full position allowed when no IV event."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            iv_event=False,
        )
        assert result.allowed
        assert result.lots > 0
        assert not result.iv_event_risk

    def test_reduced_size_near_iv_event(self):
        """Position reduced by 50% around IV crush events."""
        engine = RiskSizingEngine()
        # Use larger equity to get more lots (so 50% reduction is visible)
        result_normal = engine.calculate(
            equity=5000000,  # 50 lakh equity
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            iv_event=False,
        )
        result_event = engine.calculate(
            equity=5000000,  # Same equity
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            iv_event=True,  # RBI policy day, budget, elections
        )
        assert result_event.allowed
        assert result_event.iv_event_risk
        assert result_event.iv_reduced_lots < result_normal.lots
        assert result_event.iv_reduced_lots == result_event.lots
        assert "IV event" in result_event.reason

    def test_iv_event_flag_set(self):
        """IV event flag is properly set in result."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            iv_event=True,
        )
        assert result.iv_event_risk
        assert result.iv_reduced_lots > 0


class TestDayOfWeekFilters:
    """Test day-of-week filters per Rule B8."""

    def test_no_friday_trading(self):
        """Friday trading is blocked entirely."""
        engine = RiskSizingEngine()
        # Friday (weekday=4)
        friday = datetime(2024, 3, 1, 10, 0)  # This is a Friday
        result = engine.calculate(
            equity=1000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=friday,
        )
        assert not result.allowed
        assert "Friday" in result.reason

    def test_reduced_size_on_thursday_expiry(self):
        """Position reduced by 50% on expiry Thursday."""
        engine = RiskSizingEngine()
        # Thursday (weekday=3)
        thursday = datetime(2024, 2, 29, 10, 0)  # This is a Thursday
        result_normal = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=datetime(2024, 2, 28, 10, 0),  # Wednesday
        )
        result_thursday = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=thursday,
        )
        assert result_thursday.allowed
        assert result_thursday.weekday_risk
        assert result_thursday.weekday_reduced_lots < result_normal.lots
        assert "Expiry Thursday" in result_thursday.reason

    def test_normal_trading_monday_wednesday(self):
        """Normal position size on Monday and Wednesday."""
        engine = RiskSizingEngine()
        # Monday (weekday=0)
        monday = datetime(2024, 3, 4, 10, 0)
        result = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=monday,
        )
        assert result.allowed
        assert not result.weekday_risk

        # Wednesday (weekday=2)
        wednesday = datetime(2024, 3, 6, 10, 0)
        result_wed = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            current_time=wednesday,
        )
        assert result_wed.allowed
        assert not result_wed.weekday_risk


class TestOIWallIntegration:
    """Test OI wall integration with RiskSizingEngine."""

    def test_oi_walls_passed_in_result(self):
        """OI wall levels are passed through in SizingResult."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
            oi_wall_support=24200.0,
            oi_wall_resistance=24800.0,
        )
        assert result.allowed
        assert result.oi_wall_support == 24200.0
        assert result.oi_wall_resistance == 24800.0

    def test_none_oi_walls_default(self):
        """When no OI walls provided, defaults to None."""
        engine = RiskSizingEngine()
        result = engine.calculate(
            equity=5000000,
            session_pnl=0,
            consecutive_losses=0,
            underlying="NIFTY",
            entry_price=24000,
            stop_price=23900,
            target_price=24400,
            direction="LONG",
        )
        assert result.allowed
        assert result.oi_wall_support is None
        assert result.oi_wall_resistance is None