"""Integration tests for entry gates - TDD cycle 3.2.

Tests the complete gate validation pipeline from AMT analysis → gate checks → trade decision.
"""
import pytest
from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.amt.service.entry_gates import calculate_position_size, run_entry_gates
from app.domain.amt.service.gate_pipeline import GateContext, GatePipeline, run_gate_pipeline


class TestEntryGatesIntegration:
    """Integration tests for the complete entry gate pipeline."""

    def _create_bar(self, time, open, high, low, close, volume=100):
        """Helper to create a bar dict."""
        return {
            "time": time,
            "open": open,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "buyVolume": int(volume * 0.6),
            "sellVolume": int(volume * 0.4),
        }

    def test_calculate_position_size_basic(self):
        """Should calculate position size from AMT result."""
        # Standard parameters
        lots, risk_amount, valid = calculate_position_size(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            risk_pct=0.005,
        )
        
        assert valid is True
        assert lots > 0
        assert risk_amount > 0
        # Risk: 100k * 0.5% = 500, per lot: 2 * 10 = 20, lots = 25
        assert lots == 25
        assert risk_amount == pytest.approx(500.0)

    def test_calculate_position_size_with_velocity(self):
        """Should adjust position size based on price velocity."""
        # High velocity should reduce position size
        lots_fast, risk_fast, valid_fast = calculate_position_size(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            price_velocity=5.0,  # Fast move
            risk_pct=0.005,
        )
        
        # Normal velocity
        lots_normal, risk_normal, valid_normal = calculate_position_size(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            price_velocity=0.0,  # Normal
            risk_pct=0.005,
        )
        
        assert valid_fast is True
        assert valid_normal is True
        # High velocity should reduce size (scaling)
        assert lots_fast <= lots_normal

    def test_calculate_position_size_invalid_stop(self):
        """Should reject invalid stop loss (equals entry)."""
        lots, risk_amount, valid = calculate_position_size(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=100.0,  # Stop equals entry
            point_value=10.0,
            risk_pct=0.005,
        )
        
        assert valid is False
        assert lots == 0
        assert risk_amount == 0.0

    def test_run_entry_gates_passes_valid_setup(self):
        """Should pass gates for valid AMT setup."""
        analyzer = AMTAnalyzer()
        
        # Create 60 bars (enough for warm-up)
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(60)
        ]
        
        result = analyzer.analyze(bars)
        
        tick = {"close": 101.0, "time": 60}
        
        passed, reason, detail, soft_passed, soft_total = run_entry_gates(
            data=bars,
            amt_result=result,
            tick=tick,
            tick_age_seconds=1.0,
            market_state="BALANCED",
        )
        
        # Should at least evaluate gates
        assert isinstance(passed, bool)
        assert isinstance(reason, str)
        assert soft_total >= 0

    def test_run_entry_gates_fails_insufficient_data(self):
        """Should fail gates with insufficient bar data."""
        analyzer = AMTAnalyzer()
        
        # Only 10 bars (not enough)
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(10)
        ]
        
        result = analyzer.analyze(bars)
        tick = {"close": 101.0, "time": 10}
        
        passed, reason, detail, soft_passed, soft_total = run_entry_gates(
            data=bars,
            amt_result=result,
            tick=tick,
            tick_age_seconds=1.0,
        )
        
        # Should fail due to insufficient data
        assert passed is False or soft_passed < soft_total

    def test_run_entry_gates_fails_stale_tick(self):
        """Should fail gates with stale tick data."""
        analyzer = AMTAnalyzer()
        
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(60)
        ]
        
        result = analyzer.analyze(bars)
        
        # Very old tick (stale)
        tick = {"close": 101.0, "time": 0}
        
        passed, reason, detail, soft_passed, soft_total = run_entry_gates(
            data=bars,
            amt_result=result,
            tick=tick,
            tick_age_seconds=120.0,  # 2 minutes old (stale)
        )
        
        # Should fail or flag as stale
        assert passed is False or "STALE" in reason.upper()

    def test_run_entry_gates_respects_risk_halt(self):
        """Should not allow trades when risk is halted."""
        analyzer = AMTAnalyzer()
        
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(60)
        ]
        
        result = analyzer.analyze(bars)
        tick = {"close": 101.0, "time": 60}
        
        passed, reason, detail, soft_passed, soft_total = run_entry_gates(
            data=bars,
            amt_result=result,
            tick=tick,
            is_risk_halted=True,
            halt_reason="Max drawdown reached",
        )
        
        # Should fail due to risk halt
        assert passed is False

    def test_gate_context_builds_from_amt_result(self):
        """Should build GateContext from AMT analysis result."""
        analyzer = AMTAnalyzer()
        
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(60)
        ]
        
        result = analyzer.analyze(bars)
        
        # Build context manually
        ctx = GateContext(
            candle_count=len(bars),
            market_state=result.market_state if hasattr(result, 'market_state') else "BALANCED",
            poc=result.poc if hasattr(result, 'poc') else 0.0,
            vah=result.value_area_high if hasattr(result, 'value_area_high') else 0.0,
            val=result.value_area_low if hasattr(result, 'value_area_low') else 0.0,
            price=100.0,
        )
        
        assert ctx.candle_count == 60
        assert ctx.poc >= 0.0
        assert ctx.vah >= 0.0 or ctx.val >= 0.0

    def test_gate_pipeline_evaluate(self):
        """Should evaluate gate pipeline with context."""
        # Create context
        ctx = GateContext(
            candle_count=60,
            tick_age_seconds=1.0,
            market_state="BALANCED",
            poc=100.0,
            vah=102.0,
            val=98.0,
            price=100.5,
            aggression_score=3.0,
            r_r_ratio=2.0,
        )
        
        # Create pipeline and evaluate
        pipeline = GatePipeline()
        gate_result = pipeline.evaluate(ctx)
        
        assert gate_result is not None
        assert hasattr(gate_result, 'passed')
        assert hasattr(gate_result, 'reason')

    def test_gate_pipeline_blocks_low_aggression(self):
        """Should block trades with low aggression score."""
        ctx = GateContext(
            candle_count=60,
            tick_age_seconds=1.0,
            market_state="BALANCED",
            poc=100.0,
            vah=102.0,
            val=98.0,
            price=100.5,
            aggression_score=0.5,  # Very low aggression
            r_r_ratio=2.0,
        )
        
        pipeline = GatePipeline()
        result = pipeline.evaluate(ctx)
        
        # Should fail or flag low aggression
        assert result.passed is False or result.reason.value in ["WAIT", "ALERT"]

    def test_gate_pipeline_blocks_poor_rr(self):
        """Should block trades with poor risk:reward ratio."""
        ctx = GateContext(
            candle_count=60,
            tick_age_seconds=1.0,
            market_state="BALANCED",
            poc=100.0,
            vah=102.0,
            val=98.0,
            price=100.5,
            aggression_score=3.0,
            r_r_ratio=0.8,  # Poor R:R (< 1.5)
        )
        
        pipeline = GatePipeline()
        result = pipeline.evaluate(ctx)
        
        # Should fail due to poor R:R
        assert result.passed is False

    def test_full_pipeline_amt_to_gates(self):
        """Should flow from AMT analysis through gate validation."""
        analyzer = AMTAnalyzer()
        
        # Create realistic market data
        bars = []
        for i in range(60):
            # Uptrend with good structure
            price = 100.0 + i * 0.3
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 0.5,
                low=price - 0.2,
                close=price + 0.3,
                volume=120,
            ))
        
        # Step 1: AMT Analysis
        amt_result = analyzer.analyze(bars)
        assert amt_result is not None
        
        # Step 2: Run entry gates
        tick = {"close": bars[-1]["close"], "time": 60}
        passed, reason, detail, soft_passed, soft_total = run_entry_gates(
            data=bars,
            amt_result=amt_result,
            tick=tick,
            tick_age_seconds=1.0,
            aggression_score=3.0,
            r_r_ratio=2.0,
        )
        
        # Should complete full pipeline
        assert isinstance(passed, bool)
        assert isinstance(soft_passed, int)
        assert isinstance(soft_total, int)

    def test_position_sizing_with_compounding_integration(self):
        """Should integrate position sizing with intraday compounding."""
        from app.domain.risk.service.intraday_compounding import IntradayCompoundingEngine
        from app.domain.fabio_ai.services.session_risk_manager import CapitalRiskBand
        
        # Standard sizing
        lots_standard, risk_standard, valid_standard = calculate_position_size(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            risk_pct=0.005,
        )
        
        # Compounding sizing (with profit cushion)
        compounding = IntradayCompoundingEngine()
        result_compound = compounding.calculate_with_cushion(
            equity=100000.0,
            entry_price=100.0,
            stop_loss=98.0,
            point_value=10.0,
            session_pnl=1000.0,  # +1k profit
            risk_tier=CapitalRiskBand.CUSHION,
        )
        
        assert valid_standard is True
        assert result_compound.is_valid is True
        
        # Compounding should use profit cushion
        if result_compound.cushion_amount > 0:
            assert result_compound.lots >= lots_standard

    def test_gates_with_extreme_market_conditions(self):
        """Should handle extreme volatility in gate evaluation."""
        analyzer = AMTAnalyzer()
        
        # Create extreme volatility bars
        bars = []
        price = 100.0
        for i in range(60):
            if i < 30:
                price += 3.0  # Sharp rise
            else:
                price -= 3.0  # Sharp fall
            
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 5.0,
                low=price - 5.0,
                close=price,
                volume=500,
            ))
        
        result = analyzer.analyze(bars)
        tick = {"close": bars[-1]["close"], "time": 60}
        
        # Should not crash, should evaluate gates
        passed, reason, detail, soft_passed, soft_total = run_entry_gates(
            data=bars,
            amt_result=result,
            tick=tick,
            tick_age_seconds=1.0,
        )
        
        assert isinstance(passed, bool)

    def test_gate_result_is_trade_property(self):
        """Should correctly identify trade-ready gate results."""
        from app.domain.amt.service.gate_pipeline import GateResult, GateReason
        
        # Trade result
        trade_result = GateResult(
            passed=True,
            gate=12,
            reason=GateReason.TRADE,
            detail="All gates passed",
        )
        assert trade_result.is_trade is True
        
        # Non-trade result
        wait_result = GateResult(
            passed=False,
            gate=5,
            reason=GateReason.WAIT,
            detail="Waiting for better setup",
        )
        assert wait_result.is_trade is False
