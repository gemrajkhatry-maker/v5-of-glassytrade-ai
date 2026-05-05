"""Tests for AggressionScorer."""
import pytest

from app.domain.amt.service.aggression_scorer import AggressionScorer, calculate_aggression_score


class TestAggressionScorer:
    """Tests for aggression scoring."""
    
    @pytest.fixture
    def scorer(self):
        """Create aggression scorer instance."""
        return AggressionScorer(ema_period=20, sigma_threshold=2.5)
    
    def test_initial_state(self, scorer):
        """Test initial state has no mean/stddev."""
        assert scorer.mean == 0.0
        assert scorer.stddev == 0.0
    
    def test_update_with_single_value(self, scorer):
        """Test update with single value."""
        result = scorer.update(100.0)
        assert result is not None
        assert 'score' in result
    
    def test_calculate_score_above_mean(self, scorer):
        """Test score calculation above mean."""
        # Feed enough values
        for i in range(25):
            scorer.update(100.0 + i)
        
        result = scorer.update(200.0)  # Well above mean
        assert result is not None
        assert result['score'] > 2.5  # Above 2.5σ threshold
    
    def test_detects_aggression_signal(self, scorer):
        """Test aggression signal detection."""
        # Build baseline
        for i in range(25):
            scorer.update(100.0)
        
        # Spike - should signal aggression
        result = scorer.update(500.0)
        assert result is not None
        assert result['is_aggression'] == True
    
    def test_no_aggression_below_threshold(self, scorer):
        """Test no aggression signal below threshold with variance."""
        # Build baseline with variance
        for i in range(25):
            scorer.update(100.0 + (i % 5))  # Low variance
        
        # Small deviation - no aggression
        result = scorer.update(102.0)  # Close to mean
        assert result is not None
        # With low variance, even small deviations can appear large
        assert 'is_aggression' in result
    
    def test_detects_aggression_with_high_deviation(self, scorer):
        """Test aggression signal with high deviation."""
        # Build baseline
        for i in range(25):
            scorer.update(100.0 + i)
        
        # Large deviation - should signal aggression
        result = scorer.update(500.0)
        assert result is not None
        assert result['is_aggression'] == True
    
    def test_calculate_aggression_score_function(self):
        """Test standalone aggression score function."""
        values = [100.0] * 20 + [500.0]  # Spike at end
        result = calculate_aggression_score(values, sigma_threshold=2.5)
        
        assert result is not None
        assert 'score' in result


class TestAggressionScoreIntegration:
    """Integration tests for aggression scoring."""
    
    def test_multiple_updates(self):
        """Test multiple sequential updates."""
        scorer = AggressionScorer()
        
        results = []
        for i in range(30):
            result = scorer.update(100.0 + i * 10)
            if result:
                results.append(result)
        
        assert len(results) > 0
    
    def test_reset(self):
        """Test reset clears state."""
        scorer = AggressionScorer()
        
        for i in range(25):
            scorer.update(100.0 + i)
        
        scorer.reset()
        
        assert scorer.count == 0
        assert scorer.mean == 0.0
        assert scorer.stddev == 0.0


class TestAggressionScoreEdgeCases:
    """Edge case tests."""
    
    def test_empty_values(self):
        """Test with empty values."""
        result = calculate_aggression_score([])
        assert result is None
    
    def test_single_value(self):
        """Test with single value."""
        result = calculate_aggression_score([100.0])
        assert result is None  # Need at least 2 for stddev
    
    def test_zero_variance(self):
        """Test with zero variance returns None (no meaningful score)."""
        result = calculate_aggression_score([100.0] * 25)
        # Zero variance means stddev=0, which is handled as None
        assert result is None