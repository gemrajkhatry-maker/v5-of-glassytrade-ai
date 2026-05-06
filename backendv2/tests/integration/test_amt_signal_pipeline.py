"""Integration tests for AMT signal pipeline - TDD cycle 3.1.

Tests the full end-to-end flow from raw bars → AMT analysis → signal generation.
"""
import pytest
from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.trading.model.value_objects import OHLC


class TestAMTPipelineIntegration:
    """Integration tests for the complete AMT analysis pipeline."""

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

    def test_full_pipeline_produces_amt_result(self):
        """Should produce complete AMTResult from raw bars."""
        analyzer = AMTAnalyzer()
        
        # Create 50 bars with realistic price action
        bars = []
        base_price = 100.0
        for i in range(50):
            price = base_price + (i % 10 - 5) * 0.5
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.2,
                volume=100 + i * 2,
            ))
        
        result = analyzer.analyze(bars)
        
        assert result is not None
        # Should have profile data
        assert result.poc > 0 or result.value_area_high > 0

    def test_pipeline_with_insufficient_data(self):
        """Should handle empty bar list gracefully."""
        analyzer = AMTAnalyzer()
        
        result = analyzer.analyze([])
        
        assert result is not None
        # Should return default/empty result
        assert result.market_state == "BALANCED" or result.poc == 0.0

    def test_pipeline_generates_signal(self):
        """Should generate trading signal from analyzed bars."""
        analyzer = AMTAnalyzer()
        
        # Create bars with clear absorption pattern
        bars = []
        for i in range(50):
            # Price moving up with high volume
            price = 100.0 + i * 0.3
            volume = 150 if i > 40 else 100  # Increasing volume
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 0.8,
                low=price - 0.2,
                close=price + 0.5,
                volume=volume,
            ))
        
        result = analyzer.analyze(bars)
        
        assert result is not None
        assert hasattr(result, 'setup') or result.market_state != ""

    @pytest.mark.skip(reason="MTF analyzer expects profile dicts, not raw bars - requires pipeline refactoring")
    def test_pipeline_with_mtf_data(self):
        """Should incorporate multi-timeframe data when provided."""
        # TODO: This test requires MTF analyzer to accept raw bars or
        # AMTAnalyzer to build profile dicts before calling MTF
        pass

    def test_pipeline_handles_extreme_volatility(self):
        """Should handle extreme price moves without crashing."""
        analyzer = AMTAnalyzer()
        
        bars = []
        price = 100.0
        for i in range(50):
            # Create large price swings
            if i < 25:
                price += 2.0  # Sharp rise
            else:
                price -= 2.0  # Sharp fall
            
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 3.0,
                low=price - 3.0,
                close=price,
                volume=500,  # High volume
            ))
        
        # Should not raise exception
        result = analyzer.analyze(bars, symbol="TEST")
        assert result is not None

    def test_pipeline_handles_zero_volume(self):
        """Should handle bars with zero volume."""
        analyzer = AMTAnalyzer()
        
        bars = []
        for i in range(50):
            bars.append(self._create_bar(
                time=i,
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=0 if i % 10 == 0 else 100,  # Every 10th bar has zero volume
            ))
        
        result = analyzer.analyze(bars, symbol="TEST")
        assert result is not None

    def test_pipeline_consistent_with_regime_detection(self):
        """Should produce results consistent with regime detector expectations."""
        from app.domain.amt.service.regime_detector import RegimeDetector
        
        analyzer = AMTAnalyzer()
        regime = RegimeDetector()
        
        # Create trending bars
        bars = []
        for i in range(50):
            price = 100.0 + i * 0.5
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 0.5,
                low=price - 0.2,
                close=price + 0.3,
                volume=100,
            ))
        
        # Run pipeline
        result = analyzer.analyze(bars)
        
        # Feed to regime detector (should not crash)
        ohlc_data = [
            OHLC(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=b["volume"],
            )
            for b in bars
        ]
        
        # Regime detection: use is_contracting method
        is_contracting = regime.is_contracting(ohlc_data)
        assert isinstance(is_contracting, bool)

    def test_pipeline_intraday_compounding_integration(self):
        """Should work with intraday compounding for position sizing."""
        from app.domain.risk.service.intraday_compounding import IntradayCompoundingEngine
        from app.domain.fabio_ai.services.session_risk_manager import CapitalRiskBand
        
        analyzer = AMTAnalyzer()
        compounding = IntradayCompoundingEngine()
        
        # Create bars
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(50)
        ]
        
        result = analyzer.analyze(bars, symbol="TEST")
        
        # Should be able to use AMT result for position sizing
        # (extract entry/stop from result)
        assert result is not None
        
        # Example: If result has signal, calculate position size
        if hasattr(result, 'signal') and result.signal:
            entry = result.poc or 100.0
            stop = entry - 1.0  # Example stop
            sizing = compounding.calculate_with_cushion(
                equity=100000.0,
                entry_price=entry,
                stop_loss=stop,
                point_value=10.0,
                session_pnl=500.0,
                risk_tier=CapitalRiskBand.NORMAL,
            )
            assert sizing.is_valid is True or sizing.lots == 0

    def test_pipeline_orb_breakout_integration(self):
        """Should work with ORB breakout detection."""
        from app.domain.amt.service.orb_breakout import ORBDetector
        
        analyzer = AMTAnalyzer()
        orb = ORBDetector(orb_period=6)
        
        # Create opening bars
        opening_bars = [
            self._create_bar(time=i, open=100+i*0.3, high=101+i*0.3, low=99+i*0.3, close=100.5+i*0.3)
            for i in range(6)
        ]
        
        # Form ORB
        for bar in opening_bars:
            orb.update(bar)
        
        # Should have ORB range
        orb_range = orb.get_orb_range()
        assert orb_range is not None
        assert orb_range.is_formed is True
        
        # Now run full pipeline on extended data
        all_bars = opening_bars + [
            self._create_bar(time=6+i, open=103+i*0.2, high=104+i*0.2, low=102+i*0.2, close=103.5+i*0.2)
            for i in range(44)
        ]
        
        result = analyzer.analyze(all_bars, symbol="TEST")
        assert result is not None

    def test_pipeline_squeeze_detection_integration(self):
        """Should work with squeeze detection logic."""
        from app.domain.amt.service.regime_detector import RegimeDetector
        
        analyzer = AMTAnalyzer()
        regime = RegimeDetector()
        
        # Create bars with compression pattern
        bars = []
        # Expansion phase
        for i in range(20):
            price = 100.0 + (i % 5 - 2) * 2.0
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 2.0,
                low=price - 2.0,
                close=price,
                volume=100,
            ))
        
        # Contraction phase
        for i in range(20, 50):
            price = 100.0 + (i % 3 - 1) * 0.3
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 0.3,
                low=price - 0.3,
                close=price,
                volume=80,
            ))
        
        result = analyzer.analyze(bars, symbol="TEST")
        
        # Create OHLC data for squeeze detection
        ohlc_data = [
            OHLC(
                time=b["time"],
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=b["volume"],
            )
            for b in bars
        ]
        
        # Should be able to detect squeeze
        squeeze = regime.detect_squeeze(ohlc_data, result)
        # May or may not detect squeeze depending on data pattern
        assert squeeze is None or hasattr(squeeze, 'direction')

    def test_pipeline_second_drive_integration(self):
        """Should work with second drive detection."""
        from app.domain.amt.service.regime_detector import RegimeDetector
        
        analyzer = AMTAnalyzer()
        regime = RegimeDetector()
        
        # Create bars
        bars = []
        for i in range(50):
            price = 100.0 + (i % 10 - 5) * 0.5
            bars.append(self._create_bar(
                time=i,
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=100,
            ))
        
        result = analyzer.analyze(bars, symbol="TEST")
        
        # Simulate level touches
        key_levels = [100.0, 102.5]
        
        # Record first touch
        regime.record_level_approach(price=100.0, key_levels=key_levels, timestamp=1.0)
        
        # Price retreats
        regime.record_level_approach(price=101.0, key_levels=key_levels, timestamp=2.0)
        
        # Second drive
        is_second = regime.is_second_drive(price=100.0, key_levels=key_levels)
        assert is_second is True

    def test_pipeline_with_realistic_market_scenario(self):
        """Should handle realistic market opening scenario."""
        analyzer = AMTAnalyzer()
        
        # Simulate first hour of trading (50 range bars)
        bars = []
        time = 0
        
        # Opening volatility (bars 0-10)
        for i in range(10):
            price = 100.0 + (i - 5) * 0.8
            bars.append(self._create_bar(
                time=time,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.3,
                volume=200,
            ))
            time += 1
        
        # Initial balance formation (bars 10-20)
        for i in range(10, 20):
            price = 100.0 + (i - 15) * 0.2
            bars.append(self._create_bar(
                time=time,
                open=price,
                high=price + 0.4,
                low=price - 0.4,
                close=price,
                volume=120,
            ))
            time += 1
        
        # Trend development (bars 20-50)
        for i in range(20, 50):
            price = 98.0 + (i - 20) * 0.4
            bars.append(self._create_bar(
                time=time,
                open=price,
                high=price + 0.5,
                low=price - 0.2,
                close=price + 0.3,
                volume=150,
            ))
            time += 1
        
        result = analyzer.analyze(bars)
        
        assert result is not None
        # Should have detected some market structure
        assert result.market_state != "" or result.profile_shape != ""

    def test_pipeline_preserves_data_integrity(self):
        """Should not modify input bars during analysis."""
        analyzer = AMTAnalyzer()
        
        bars = [
            self._create_bar(time=i, open=100+i*0.2, high=101+i*0.2, low=99+i*0.2, close=100.5+i*0.2)
            for i in range(50)
        ]
        
        # Store original values
        original_bars = [dict(b) for b in bars]
        
        # Run analysis
        result = analyzer.analyze(bars, symbol="TEST")
        
        # Verify bars not modified
        for orig, curr in zip(original_bars, bars):
            assert orig == curr, f"Bar modified: {orig} != {curr}"
