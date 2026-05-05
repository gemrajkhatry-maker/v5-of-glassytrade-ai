"""Enhanced CVD tests for divergence detection, session boundaries, z-score."""
import pytest

from app.domain.amt.model.amt_models import CVDState, DivergenceSignal
from app.domain.amt.service.cvd_tracker import CVDTracker, CVDState


class TestCVDTrackerEnhanced:
    """Tests for enhanced CVDTracker with divergence detection."""
    
    @pytest.fixture
    def tracker(self):
        """Create CVDTracker instance."""
        return CVDTracker(slope_window=20)
    
    def test_initial_state(self, tracker):
        """Test initial state values."""
        assert tracker.cumulative_delta == 0.0
    
    def test_update_accumulates_delta(self, tracker):
        """Test that update accumulates delta correctly."""
        bar = {'high': 100, 'low': 99, 'close': 99.5, 'volume': 100, 
               'buyVolume': 60, 'sellVolume': 40, 'time': '09:00:00'}
        
        state = tracker.update_bar(bar)
        assert state.value == 20.0  # 60 - 40
    
    def test_detects_bullish_divergence(self, tracker):
        """Test bullish divergence detection."""
        # Build history where price falls but CVD rises
        for i in range(25):
            bar = {'high': 100 - i, 'low': 100 - i - 1, 'close': 100 - i - 0.5,
                   'volume': 100, 'buyVolume': 70 + i, 'sellVolume': 30,
                   'time': f'09:{i:02d}:00'}
            tracker.update_bar(bar)
        
        # Price going down, CVD going up = bullish divergence
        state = tracker.state()
        assert state.has_divergence == True
        assert state.divergence_type == "BULLISH_DIV"
    
    def test_detects_bearish_divergence(self, tracker):
        """Test bearish divergence detection."""
        # Build history where price rises but CVD falls
        for i in range(25):
            bar = {'high': 95 + i, 'low': 95 + i, 'close': 95 + i,
                   'volume': 100, 'buyVolume': 30, 'sellVolume': 70 - i,
                   'time': f'09:{i:02d}:00'}
            tracker.update_bar(bar)
        
        # Price going up, CVD going down = bearish divergence
        state = tracker.state()
        assert state.has_divergence == True
        assert state.divergence_type == "BEARISH_DIV"
    
    def test_session_boundary_resets(self, tracker):
        """Test that time going backwards resets the tracker."""
        # Build some history
        for i in range(10):
            bar = {'high': 100, 'low': 99, 'close': 99.5, 'volume': 100,
                   'buyVolume': 60, 'sellVolume': 40, 'time': f'09:{i:02d}:00'}
            tracker.update_bar(bar)
        
        assert tracker.cumulative_delta != 0.0
        
        # Time goes backwards (new session)
        bar = {'high': 100, 'low': 99, 'close': 99.5, 'volume': 100,
               'buyVolume': 60, 'sellVolume': 40, 'time': '09:00:00'}  # Earlier time
        tracker.update_bar(bar)
        
        # Should have reset
        assert tracker.cumulative_delta == 20.0  # Only the last bar
    
    def test_z_score_calculation(self, tracker):
        """Test z-score is calculated."""
        for i in range(25):
            bar = {'high': 100, 'low': 99, 'close': 99.5, 'volume': 100,
                   'buyVolume': 50, 'sellVolume': 50, 'time': f'09:{i:02d}:00'}
            tracker.update_bar(bar)
        
        state = tracker.state()
        assert isinstance(state.z_score, float)
    
    def test_slope_calculation(self, tracker):
        """Test slope is calculated via linear regression."""
        # Create upward trending CVD
        for i in range(25):
            bar = {'high': 100, 'low': 99, 'close': 99.5, 'volume': 100,
                   'buyVolume': 70 + i, 'sellVolume': 30, 'time': f'09:{i:02d}:00'}
            tracker.update_bar(bar)
        
        state = tracker.state()
        assert state.slope > 0  # Should be positive (rising CVD)
    
    def test_max_history_limit(self, tracker):
        """Test that history is capped at MAX_HISTORY."""
        tracker = CVDTracker(slope_window=20, max_history=50)
        
        # Add more than max history
        for i in range(60):
            bar = {'high': 100, 'low': 99, 'close': 99.5, 'volume': 100,
                   'buyVolume': 60, 'sellVolume': 40, 'time': f'09:{i:02d}:00'}
            tracker.update_bar(bar)
        
        # History should be capped
        assert len(tracker._history) <= 50


class TestCVDState:
    """Tests for CVDState dataclass."""
    
    def test_frozen_dataclass(self):
        """Test that CVDState is frozen (immutable)."""
        state = CVDState(value=100, slope=1.5, has_divergence=True, 
                         divergence_type="BULLISH_DIV", z_score=2.5)
        with pytest.raises(AttributeError):
            state.value = 200
    
    def test_divergence_signal(self):
        """Test DivergenceSignal dataclass."""
        signal = DivergenceSignal(detected=True, type="BULLISH_DIV",
                                  z_score=2.5, price_slope=-0.5, cvd_slope=1.0)
        assert signal.z_score == 2.5