import pytest
from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer, AggressivePrintRegistry, AMTConfig
from app.domain.trading.models.value_objects import OHLC, AggressivePrint

class TestAggressivePrintRegistry:
    def test_register_and_retest(self):
        registry = AggressivePrintRegistry(proximity_pct=0.001)
        p1 = AggressivePrint(price=100.0, time="t1", volume=1000, delta=100, side="BUY")
        p2 = AggressivePrint(price=200.0, time="t2", volume=1000, delta=-100, side="SELL")
        
        registry.register([p1, p2])
        assert len(registry.prints) == 2
        
        # Exact price
        retests = registry.get_retests(100.0)
        assert len(retests) == 1
        assert retests[0].time == "t1"
        
        # Near price (0.05% distance)
        retests = registry.get_retests(100.05)
        assert len(retests) == 1
        
        # Far price (0.5% distance)
        retests = registry.get_retests(100.5)
        assert len(retests) == 0

    def test_duplicate_registration_ignored(self):
        registry = AggressivePrintRegistry()
        p1 = AggressivePrint(price=100.0, time="t1", volume=1000, delta=100, side="BUY")
        
        registry.register([p1])
        registry.register([p1])
        assert len(registry.prints) == 1

class TestAMTAnalyzerAggressiveRegistry:
    def test_analyze_identifies_retests(self):
        analyzer = AMTAnalyzer()
        # Seed the registry with a historical bubble
        old_print = AggressivePrint(price=100.0, time="2024-01-01T00:00:00Z", volume=5000, delta=500, side="BUY")
        analyzer._bubble_registry.register([old_print])
        
        # Current data near that bubble
        data = [
            OHLC(time=f"2024-01-01T00:0{i}:00Z", open=100, high=101, low=99, close=100.05, volume=100)
            for i in range(10)
        ]
        
        result = analyzer.analyze(data)
        assert len(result.bubble_retests) == 1
        assert result.bubble_retests[0].price == 100.0
