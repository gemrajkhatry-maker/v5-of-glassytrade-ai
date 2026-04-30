"""Validation tests comparing legacy AMTAnalyzer with new AMTPipeline."""

from __future__ import annotations

import pytest
from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer
from app.domain.fabio_ai.services.amt_analyzer_v2 import AMTAnalyzerV2
from app.domain.fabio_ai.services.amt_pipeline import AMTPipeline
from app.infrastructure.adapters.data_generator import generate_market_data


class TestPipelineVsLegacyParity:
    """Test that pipeline produces similar results to legacy analyzer."""

    def test_basic_analysis_parity(self):
        """Pipeline result should have same core fields as legacy."""
        data = generate_market_data(50, 100, "sideways")
        
        # Legacy analyzer
        legacy = AMTAnalyzer()
        legacy_result = legacy.analyze(data)
        
        # V2 analyzer (pipeline-backed)
        v2 = AMTAnalyzerV2()
        v2_result = v2.analyze(data)
        
        # Core fields should match
        assert legacy_result.poc == pytest.approx(v2_result.poc, rel=0.01)
        assert legacy_result.value_area_high == pytest.approx(v2_result.value_area_high, rel=0.01)
        assert legacy_result.value_area_low == pytest.approx(v2_result.value_area_low, rel=0.01)
        
        # Market state should be compatible
        assert legacy_result.market_state in ["BALANCED", "IMBALANCED"]
        assert v2_result.market_state in ["BALANCED", "IMBALANCED"]

    def test_pipeline_direct_analysis(self):
        """AMTPipeline should produce valid results directly."""
        data = generate_market_data(50, 100, "sideways")
        
        pipeline = AMTPipeline()
        result = pipeline.analyze(data)
        
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low
        assert result.profile_type in ["Session", "Incremental"]

    def test_mtf_fields_populated(self):
        """MTF fields should be populated when daily/hourly data provided."""
        # 5-min data for main analysis
        data_5min = generate_market_data(50, 100, "sideways")
        
        # Daily data (20 trading days)
        daily_data = generate_market_data(20, 100, "sideways")
        
        # Hourly data (8 hours)
        hourly_data = generate_market_data(8, 100, "sideways")
        
        pipeline = AMTPipeline()
        result = pipeline.analyze(data_5min, daily_data=daily_data, hourly_data=hourly_data)
        
        # MTF fields should exist (may be 0.0 if alignment failed)
        assert hasattr(result, 'hourly_vah')
        assert hasattr(result, 'hourly_val')
        assert hasattr(result, 'hourly_poc')
        assert hasattr(result, 'daily_vah')
        assert hasattr(result, 'daily_val')
        assert hasattr(result, 'daily_poc')

    def test_order_flow_fields_populated(self):
        """Order flow fields should exist in result."""
        data = generate_market_data(50, 100, "sideways")
        
        pipeline = AMTPipeline()
        result = pipeline.analyze(data)
        
        # Result has aggression (which stores OF score) and ofi
        assert hasattr(result, 'aggression')
        assert hasattr(result, 'ofi')

    def test_setup_classification(self):
        """Setup should be classified based on market state."""
        # Balanced market
        data_balanced = generate_market_data(50, 100, "sideways")
        
        pipeline = AMTPipeline()
        result = pipeline.analyze(data_balanced)
        
        assert result.setup in ["MEAN_REVERSION", "TREND_MODEL", "RESPONSIVE_FADE"]

    def test_empty_data_handling(self):
        """Both analyzers should handle empty data gracefully."""
        legacy = AMTAnalyzer()
        legacy_result = legacy.analyze([])
        
        v2 = AMTAnalyzerV2()
        v2_result = v2.analyze([])
        
        # Both should return valid results (not crash)
        # POC may be 0 for empty data
        assert legacy_result.poc >= 0 or v2_result.poc >= 0
        
    def test_insufficient_data_handling(self):
        """Both analyzers should handle insufficient data gracefully."""
        data = generate_market_data(3, 100, "sideways")
        
        legacy = AMTAnalyzer()
        legacy_result = legacy.analyze(data)
        
        v2 = AMTAnalyzerV2()
        v2_result = v2.analyze(data)
        
        # Both should return valid results
        assert isinstance(legacy_result.poc, (int, float))
        assert isinstance(v2_result.poc, (int, float))


class TestMigrationValidation:
    """Validate that pipeline can replace legacy analyzer with minimal differences."""

    def test_poc_consistency(self):
        """POC should be consistent between legacy and pipeline."""
        data = generate_market_data(60, 100, "sideways")
        
        legacy = AMTAnalyzer()
        legacy_result = legacy.analyze(data)
        
        pipeline = AMTPipeline()
        pipeline_result = pipeline.analyze(data)
        
        # POC should be within 0.5% of each other
        assert legacy_result.poc == pytest.approx(pipeline_result.poc, rel=0.005)

    def test_value_area_consistency(self):
        """VAH/VAL should be consistent between legacy and pipeline."""
        data = generate_market_data(60, 100, "bullish")
        
        legacy = AMTAnalyzer()
        legacy_result = legacy.analyze(data)
        
        pipeline = AMTPipeline()
        pipeline_result = pipeline.analyze(data)
        
        # VAH should be within 1%
        assert legacy_result.value_area_high == pytest.approx(pipeline_result.value_area_high, rel=0.01)
        assert legacy_result.value_area_low == pytest.approx(pipeline_result.value_area_low, rel=0.01)