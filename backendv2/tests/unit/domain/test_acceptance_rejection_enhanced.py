"""Enhanced Acceptance/Rejection tests with time accumulation and wick analysis."""
import pytest

from app.domain.amt.service.acceptance_rejection import ARState, WickAnalysis, AcceptanceRejectionEngine, analyze_wick
from app.domain.amt.service.acceptance_rejection import AcceptanceRejectionEngine


class TestAcceptanceRejectionEngine:
    """Tests for enhanced AR engine with time accumulation."""
    
    @pytest.fixture
    def engine(self):
        """Create AR engine instance."""
        return AcceptanceRejectionEngine(time_threshold=120.0, vol_ratio=1.2)
    
    def test_initial_state(self, engine):
        """Test initial state values."""
        assert engine._time_above_vah == 0.0
        assert engine._time_below_val == 0.0
    
    def test_time_accumulation_above_vah(self, engine):
        """Test time accumulation above VAH."""
        for i in range(5):
            bar = {'high': 100, 'low': 99, 'close': 101, 'volume': 100,
                   'open': 100, 'time': f'09:{i:02d}:00'}
            engine.update(bar, vah=100.5, val=99.5, baseline_vol=100)
        
        assert engine._time_above_vah > 0
    
    def test_time_accumulation_below_val(self, engine):
        """Test time accumulation below VAL."""
        for i in range(5):
            bar = {'high': 98, 'low': 97, 'close': 98, 'volume': 100,
                   'open': 99, 'time': f'09:{i:02d}:00'}
            engine.update(bar, vah=100.5, val=99.5, baseline_vol=100)
        
        assert engine._time_below_val > 0
    
    def test_acceptance_above_threshold(self, engine):
        """Test acceptance is detected after time threshold."""
        # Run enough bars to exceed time threshold
        for i in range(150):
            bar = {'high': 101, 'low': 100, 'close': 101, 'volume': 200,
                   'open': 100.5, 'time': f'09:{i:02d}:00'}
            result = engine.update(bar, vah=100, val=99, baseline_vol=100)
        
        assert result.accepted_above == True
    
    def test_acceptance_below_threshold(self, engine):
        """Test acceptance below VAL after time threshold."""
        for i in range(150):
            bar = {'high': 98, 'low': 97, 'close': 98, 'volume': 200,
                   'open': 99, 'time': f'09:{i:02d}:00'}
            result = engine.update(bar, vah=101, val=98.5, baseline_vol=100)
        
        assert result.accepted_below == True
    
    def test_rejection_at_high(self, engine):
        """Test rejection detection at VAH."""
        # Price tests VAH with upper wick rejection - need upper wick > body
        bar = {'high': 110, 'low': 101, 'close': 101.5, 'volume': 200,
               'open': 101.5, 'time': '09:00:00'}
        result = engine.update(bar, vah=101, val=99, baseline_vol=100)
        
        # upper_wick = 110 - 101.5 = 8.5, body = 0, so wick dominates
        assert result.rejected_at_high == True
    
    def test_rejection_at_low(self, engine):
        """Test rejection detection at VAL."""
        bar = {'high': 97, 'low': 94, 'close': 97, 'volume': 200,
               'open': 96, 'time': '09:00:00'}
        result = engine.update(bar, vah=101, val=96.5, baseline_vol=100)
        
        # lower_wick = 96.5 - 94 = 2.5, body = 1, so wick dominates
        assert result.rejected_at_low == True


class TestWickAnalysis:
    """Tests for wick analysis."""
    
    def test_bullish_engulfing_wick(self):
        """Test upper wick dominance detection."""
        bar = {'high': 105, 'low': 100, 'close': 101, 'open': 103}
        analysis = analyze_wick(bar)
        
        # upper_wick = 105 - 103 = 2, body = 2
        assert analysis.upper_wick == 2
        assert analysis.body_size == 2
    
    def test_bearish_engulfing_wick(self):
        """Test lower wick detection."""
        bar = {'high': 102, 'low': 98, 'close': 99, 'open': 101}
        analysis = analyze_wick(bar)
        
        # lower_wick = 99 - 98 = 1, body = 2
        assert analysis.lower_wick == 1
        assert analysis.body_size == 2
    
    def test_upper_wick_dominant(self):
        """Test bar where upper wick clearly dominates."""
        bar = {'high': 110, 'low': 100, 'close': 101, 'open': 101}
        analysis = analyze_wick(bar)
        
        # upper_wick = 110 - 101 = 9, body = 0, lower_wick = 1
        assert analysis.upper_wick > analysis.body_size
        assert analysis.is_upper_wick_dominant == True
    
    def test_small_wick(self):
        """Test bar with small wicks."""
        bar = {'high': 101, 'low': 100, 'close': 100.5, 'open': 100.5}
        analysis = analyze_wick(bar)
        
        assert analysis.upper_wick == 0.5
        assert analysis.lower_wick == 0.5
        assert analysis.body_size == 0
        assert not analysis.is_upper_wick_dominant
        assert not analysis.is_lower_wick_dominant


class TestARState:
    """Tests for ARState dataclass."""
    
    def test_frozen_dataclass(self):
        """Test that ARState is frozen."""
        state = ARState(time_above_vah=100.0, time_below_val=50.0,
                        last_time="09:00:00", price_velocity=1.5)
        with pytest.raises(AttributeError):
            state.time_above_vah = 200.0
    
    def test_wick_analysis_frozen(self):
        """Test WickAnalysis is frozen."""
        wick = WickAnalysis(upper_wick=2.0, lower_wick=1.0, body_size=1.0,
                            is_upper_wick_dominant=True, is_lower_wick_dominant=False)
        with pytest.raises(AttributeError):
            wick.upper_wick = 3.0