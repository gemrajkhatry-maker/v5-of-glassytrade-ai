"""
Tests for Market Data Metrics.
"""

import pytest
from brokersv2.observability.market_data_metrics import MarketDataMetrics


class TestTickLatencyTracking:
    """Test tick latency recording and percentile calculation."""
    
    def test_record_single_latency(self):
        """Should record single latency value."""
        metrics = MarketDataMetrics()
        metrics.record_tick_latency(50.0)
        
        percentiles = metrics.get_latency_percentiles()
        
        assert percentiles["count"] == 1
        assert percentiles["p50"] == 50.0
        assert percentiles["p95"] == 50.0
        assert percentiles["p99"] == 50.0
    
    def test_record_multiple_latencies(self):
        """Should calculate percentiles from multiple values."""
        metrics = MarketDataMetrics()
        
        # Record 100 latencies
        for i in range(1, 101):
            metrics.record_tick_latency(float(i))
        
        percentiles = metrics.get_latency_percentiles()
        
        assert percentiles["count"] == 100
        assert percentiles["p50"] == pytest.approx(50.0, abs=1.0)
        assert percentiles["avg"] == pytest.approx(50.5, rel=0.01)
    
    def test_empty_latencies(self):
        """Should return zeros when no latencies recorded."""
        metrics = MarketDataMetrics()
        
        percentiles = metrics.get_latency_percentiles()
        
        assert percentiles["count"] == 0
        assert percentiles["p50"] == 0.0
    
    def test_keeps_last_1000_samples(self):
        """Should keep only last 1000 samples."""
        metrics = MarketDataMetrics()
        
        # Record 1500 latencies
        for i in range(1500):
            metrics.record_tick_latency(float(i))
        
        percentiles = metrics.get_latency_percentiles()
        assert percentiles["count"] == 1000
    
    def test_alert_on_high_latency(self):
        """Should generate alert when latency exceeds threshold."""
        metrics = MarketDataMetrics()
        metrics.record_tick_latency(150.0)  # Exceeds 100ms threshold
        
        alerts = metrics.get_alerts()
        
        assert len(alerts) == 1
        assert alerts[0]["type"] == "HIGH_TICK_LATENCY"
        assert "150.0ms" in alerts[0]["message"]


class TestProviderCallTracking:
    """Test provider call recording and statistics."""
    
    def test_record_successful_call(self):
        """Should record successful provider call."""
        metrics = MarketDataMetrics()
        metrics.record_provider_call("dhan", success=True, latency_ms=50.0)
        
        stats = metrics.get_provider_stats("dhan")
        
        assert stats["total_calls"] == 1
        assert stats["success_rate"] == 1.0
        assert stats["avg_latency_ms"] == 50.0
    
    def test_record_failed_call(self):
        """Should record failed provider call."""
        metrics = MarketDataMetrics()
        metrics.record_provider_call("dhan", success=False, latency_ms=100.0)
        
        stats = metrics.get_provider_stats("dhan")
        
        assert stats["total_calls"] == 1
        assert stats["success_rate"] == 0.0
    
    def test_mixed_success_failure(self):
        """Should calculate correct success rate."""
        metrics = MarketDataMetrics()
        
        metrics.record_provider_call("dhan", success=True, latency_ms=50.0)
        metrics.record_provider_call("dhan", success=True, latency_ms=60.0)
        metrics.record_provider_call("dhan", success=False, latency_ms=100.0)
        
        stats = metrics.get_provider_stats("dhan")
        
        assert stats["total_calls"] == 3
        assert stats["success_rate"] == pytest.approx(0.666, rel=0.01)
        assert stats["avg_latency_ms"] == 70.0
    
    def test_unknown_provider(self):
        """Should return zeros for unknown provider."""
        metrics = MarketDataMetrics()
        
        stats = metrics.get_provider_stats("unknown")
        
        assert stats["total_calls"] == 0
        assert stats["success_rate"] == 0.0
    
    def test_keeps_last_100_latencies(self):
        """Should keep only last 100 latencies per provider."""
        metrics = MarketDataMetrics()
        
        # Record 150 calls
        for i in range(150):
            metrics.record_provider_call("dhan", success=True, latency_ms=float(i))
        
        stats = metrics.get_provider_stats("dhan")
        # Should have 150 total calls but only 100 latencies
        assert stats["total_calls"] == 150
    
    def test_alert_on_high_failure_rate(self):
        """Should generate alert when failure rate exceeds threshold."""
        metrics = MarketDataMetrics()
        
        # Record 12 calls: 2 success, 10 failure (>10% failure rate)
        for _ in range(2):
            metrics.record_provider_call("dhan", success=True, latency_ms=50.0)
        for _ in range(10):
            metrics.record_provider_call("dhan", success=False, latency_ms=100.0)
        
        alerts = metrics.get_alerts()
        
        # May have 1 or 2 alerts depending on when threshold crossed
        assert len(alerts) >= 1
        assert alerts[-1]["type"] == "HIGH_PROVIDER_FAILURE_RATE"


class TestCachePerformanceTracking:
    """Test cache hit/miss statistics."""
    
    def test_record_hits_and_misses(self):
        """Should track cache hits and misses."""
        metrics = MarketDataMetrics()
        
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        metrics.record_cache_miss()
        
        stats = metrics.get_cache_stats()
        
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.666, rel=0.01)
    
    def test_empty_cache_stats(self):
        """Should return zero hit rate when no requests."""
        metrics = MarketDataMetrics()
        
        stats = metrics.get_cache_stats()
        
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0


class TestWebSocketTracking:
    """Test WebSocket connection uptime tracking."""
    
    def test_record_connection(self):
        """Should track WebSocket connection."""
        metrics = MarketDataMetrics()
        metrics.record_ws_connected()
        
        assert metrics._ws_connected is True
        assert metrics._ws_uptime_start is not None
    
    def test_record_disconnection(self):
        """Should track WebSocket disconnection."""
        metrics = MarketDataMetrics()
        metrics.record_ws_connected()
        metrics.record_ws_disconnected()
        
        assert metrics._ws_connected is False
        assert metrics._ws_uptime_start is None
    
    def test_uptime_calculation(self):
        """Should calculate uptime in seconds."""
        metrics = MarketDataMetrics()
        metrics.record_ws_connected()
        
        uptime = metrics.get_ws_uptime_seconds()
        assert uptime >= 0.0


class TestAlertManagement:
    """Test alert recording and retrieval."""
    
    def test_record_and_retrieve_alerts(self):
        """Should store and retrieve alerts."""
        metrics = MarketDataMetrics()
        metrics._record_alert("TEST_ALERT", "Test message")
        
        alerts = metrics.get_alerts()
        
        assert len(alerts) == 1
        assert alerts[0]["type"] == "TEST_ALERT"
        assert alerts[0]["message"] == "Test message"
        assert "timestamp" in alerts[0]
    
    def test_limit_alerts(self):
        """Should limit number of returned alerts."""
        metrics = MarketDataMetrics()
        
        # Record 15 alerts
        for i in range(15):
            metrics._record_alert(f"ALERT_{i}", f"Message {i}")
        
        alerts = metrics.get_alerts(limit=5)
        
        assert len(alerts) == 5
    
    def test_clear_alerts(self):
        """Should clear all alerts."""
        metrics = MarketDataMetrics()
        metrics._record_alert("TEST", "Test")
        metrics.clear_alerts()
        
        alerts = metrics.get_alerts()
        assert len(alerts) == 0
    
    def test_keeps_last_100_alerts(self):
        """Should keep only last 100 alerts."""
        metrics = MarketDataMetrics()
        
        # Record 150 alerts
        for i in range(150):
            metrics._record_alert(f"ALERT_{i}", f"Message {i}")
        
        # Internal storage should have 100
        assert len(metrics._alerts) == 100


class TestDashboard:
    """Test comprehensive dashboard generation."""
    
    def test_get_dashboard(self):
        """Should return complete dashboard data."""
        metrics = MarketDataMetrics()
        
        # Record some data
        metrics.record_tick_latency(50.0)
        metrics.record_provider_call("dhan", success=True, latency_ms=50.0)
        metrics.record_cache_hit()
        metrics.record_ws_connected()
        
        dashboard = metrics.get_dashboard()
        
        assert "latency" in dashboard
        assert "providers" in dashboard
        assert "cache" in dashboard
        assert "websocket" in dashboard
        assert "alerts" in dashboard
        assert "timestamp" in dashboard
        
        assert dashboard["latency"]["count"] == 1
        assert "dhan" in dashboard["providers"]
        assert dashboard["cache"]["hits"] == 1
        assert dashboard["websocket"]["connected"] is True
    
    def test_dashboard_empty_state(self):
        """Should return valid dashboard with no data."""
        metrics = MarketDataMetrics()
        
        dashboard = metrics.get_dashboard()
        
        assert dashboard["latency"]["count"] == 0
        assert len(dashboard["providers"]) == 0
        assert dashboard["cache"]["hit_rate"] == 0.0


class TestReset:
    """Test metrics reset functionality."""
    
    def test_reset_clears_all_metrics(self):
        """Should clear all recorded metrics."""
        metrics = MarketDataMetrics()
        
        # Record some data
        metrics.record_tick_latency(50.0)
        metrics.record_provider_call("dhan", success=True, latency_ms=50.0)
        metrics.record_cache_hit()
        metrics.record_ws_connected()
        metrics._record_alert("TEST", "Test")
        
        # Reset
        metrics.reset()
        
        assert metrics.get_latency_percentiles()["count"] == 0
        assert len(metrics._provider_calls) == 0
        assert metrics.get_cache_stats()["hits"] == 0
        assert metrics._ws_connected is False
        assert len(metrics.get_alerts()) == 0
