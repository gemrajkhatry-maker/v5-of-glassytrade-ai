"""Signal generation stage tests - TDD for hardcoded threshold fixes."""
import pytest
from app.runtime.pipeline.signal import SignalGeneration
from app.runtime.pipeline.events import FeatureVector, OrderFlowMetrics, MicrostructureMetrics, MarketStructureResult


def _make_feature(vwap=100.0, vwap_upper_1sigma=101.0, vwap_upper_2sigma=102.0,
                  vwap_lower_1sigma=99.0, vwap_lower_2sigma=98.0,
                  rolling_volume_avg_20=1000.0, timestamp=1000000000,
                  atr_14=1.0, rsi_14=50.0):
    return FeatureVector(
        symbol="TEST",
        timestamp=timestamp,
        vwap=vwap,
        vwap_upper_1sigma=vwap_upper_1sigma,
        vwap_upper_2sigma=vwap_upper_2sigma,
        vwap_lower_1sigma=vwap_lower_1sigma,
        vwap_lower_2sigma=vwap_lower_2sigma,
        atr_14=atr_14,
        rsi_14=rsi_14,
        rolling_volume_avg_20=rolling_volume_avg_20,
    )


def _make_orderflow(ofi=0.0, timestamp=1000000000):
    return OrderFlowMetrics(
        symbol="TEST",
        timestamp=timestamp,
        cumulative_delta=ofi * 100,
        bid_volume=500.0,
        ask_volume=500.0,
        ofi=ofi,
        big_trades=0,
        volume_bubble=False,
        absorption_detected=False,
        absorption_side="",
        absorption_strength=0.0,
    )


def _make_market_structure(market_state="BALANCED", timestamp=1000000000):
    return MarketStructureResult(
        symbol="TEST",
        timestamp=timestamp,
        poc=100.0,
        vah=102.0,
        val=98.0,
        market_state=market_state,
    )


class TestSignalGenerationHardcodedThresholds:
    """Test that signal confidence and thresholds are not hardcoded.
    
    Critical bug: The original implementation used hardcoded OFI thresholds
    (-0.3, 0.15) and fixed confidence values (0.55, 0.7) instead of computing
    them from actual market data.
    """

    def test_signal_confidence_scales_with_ofi_magnitude(self):
        """Signal confidence should scale with OFI magnitude, not use hardcoded constants."""
        stage = SignalGeneration()
        
        # Weak OFI should produce low confidence
        stage.ingest_orderflow(_make_orderflow(ofi=0.16))  # Just above 0.15 threshold
        signals = stage.process(_make_feature())
        
        if signals and signals[0].type == "LONG":
            # Confidence should be low for weak OFI
            assert signals[0].confidence < 0.6, (
                f"Confidence {signals[0].confidence} too high for weak OFI (0.16). "
                "Confidence should scale with OFI magnitude."
            )

    def test_strong_ofi_produces_high_confidence(self):
        """Strong OFI should produce high confidence signal."""
        stage = SignalGeneration()
        
        # Strong OFI should produce high confidence
        stage.ingest_orderflow(_make_orderflow(ofi=0.8))
        signals = stage.process(_make_feature())
        
        if signals and signals[0].type == "LONG":
            # Confidence should be high for strong OFI
            assert signals[0].confidence > 0.75, (
                f"Confidence {signals[0].confidence} too low for strong OFI (0.8). "
                "Confidence should scale with OFI magnitude."
            )

    def test_short_signal_confidence_scales_with_negative_ofi(self):
        """Short signal confidence should scale with negative OFI magnitude."""
        stage = SignalGeneration()
        stage.ingest_market_structure(_make_market_structure(market_state="BEARISH"))
        
        # Weak negative OFI
        stage.ingest_orderflow(_make_orderflow(ofi=-0.31))  # Just below -0.3
        signals = stage.process(_make_feature())
        
        if signals and signals[0].type == "SHORT":
            # Confidence should be lower for weak negative OFI
            assert signals[0].confidence < 0.6, (
                f"Confidence {signals[0].confidence} too high for weak negative OFI (-0.31)"
            )

    def test_no_trade_when_ofi_below_threshold(self):
        """Should return NO_TRADE when OFI is below meaningful threshold."""
        stage = SignalGeneration()
        
        # Very weak OFI - should not generate signal
        stage.ingest_orderflow(_make_orderflow(ofi=0.05))
        signals = stage.process(_make_feature())
        
        # Should be NO_TRADE or very low confidence
        if signals:
            assert signals[0].type == "NO_TRADE" or signals[0].confidence < 0.3, (
                f"Generated {signals[0].type} with confidence {signals[0].confidence} "
                f"for very weak OFI (0.05). Should be NO_TRADE or low confidence."
            )

    def test_hardcoded_thresholds_replaced_with_configurable_params(self):
        """Verify that OFI thresholds are configurable, not hardcoded.
        
        The original code had:
        - Line 67: ofi.ofi < -0.3 (hardcoded short threshold)
        - Line 80: ofi.ofi > 0.15 (hardcoded long threshold)
        
        These should be replaced with configurable parameters.
        """
        stage = SignalGeneration()
        
        # Check that the stage has configurable thresholds
        # (This test will fail until the fix is applied)
        assert hasattr(stage, '_ofi_long_threshold') or hasattr(stage, '_ofi_short_threshold'), (
            "SignalGeneration should have configurable OFI thresholds, not hardcoded values. "
            "Add _ofi_long_threshold and _ofi_short_threshold attributes."
        )
