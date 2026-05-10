"""
Tests for Provider Health Monitor.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from brokersv2.providers.health_monitor import ProviderHealthMonitor


class TestHealthScoreCalculation:
    """Test health score calculation."""
    
    def test_initial_scores(self):
        """Should start with default scores of 50."""
        providers = {"dhan": Mock(), "opencart": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        assert monitor.get_health_score("dhan") == 50.0
        assert monitor.get_health_score("opencart") == 50.0
    
    def test_record_success_increases_score(self):
        """Should increase score on success."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        monitor.record_success("dhan")
        
        assert monitor.get_health_score("dhan") == 55.0
    
    def test_record_failure_decreases_score(self):
        """Should decrease score on failure."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        monitor.record_failure("dhan")
        
        assert monitor.get_health_score("dhan") == 40.0
    
    def test_score_capped_at_100(self):
        """Should not exceed 100."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        # Record many successes
        for _ in range(20):
            monitor.record_success("dhan")
        
        assert monitor.get_health_score("dhan") <= 100.0
    
    def test_score_floored_at_0(self):
        """Should not go below 0."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        # Record many failures
        for _ in range(20):
            monitor.record_failure("dhan")
        
        assert monitor.get_health_score("dhan") >= 0.0


class TestFailoverDecisions:
    """Test failover decision logic."""
    
    def test_should_failover_on_low_score(self):
        """Should recommend failover when score < 30."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        # Degrade score below 30
        for _ in range(5):
            monitor.record_failure("dhan")
        
        assert monitor.should_failover("dhan") is True
    
    def test_should_failover_on_consecutive_failures(self):
        """Should recommend failover on threshold failures."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers, failure_threshold=3)
        
        # Record 3 consecutive failures
        monitor.record_failure("dhan")
        monitor.record_failure("dhan")
        monitor.record_failure("dhan")
        
        assert monitor.should_failover("dhan") is True
    
    def test_should_not_failover_when_healthy(self):
        """Should not recommend failover when healthy."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        # Record some successes
        for _ in range(3):
            monitor.record_success("dhan")
        
        assert monitor.should_failover("dhan") is False
    
    def test_get_healthy_provider(self):
        """Should return healthiest provider."""
        providers = {"dhan": Mock(), "opencart": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        # Degrade dhan
        monitor.record_failure("dhan")
        
        # Improve opencart
        monitor.record_success("opencart")
        
        healthy = monitor.get_healthy_provider()
        assert healthy == "opencart"
    
    def test_is_healthy(self):
        """Should correctly identify healthy providers."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        # Degrade (starting at 50, need to get below 30)
        monitor.record_failure("dhan")
        monitor.record_failure("dhan")
        assert monitor.is_healthy("dhan") is False
        
        # Improve (need to get above 70, starting from ~30)
        for _ in range(10):
            monitor.record_success("dhan")
        # Score should be > 70 now (30 + 10*5 = 80)
        assert monitor.get_health_score("dhan") > 70
        assert monitor.is_healthy("dhan") is True


class TestStatusReporting:
    """Test status reporting."""
    
    def test_get_status(self):
        """Should return comprehensive status."""
        providers = {"dhan": Mock(), "opencart": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        status = monitor.get_status()
        
        assert "dhan" in status
        assert "opencart" in status
        assert "health_score" in status["dhan"]
        assert "status" in status["dhan"]
        assert status["dhan"]["status"] == "degraded"  # 50 is degraded
    
    def test_status_healthy(self):
        """Should show healthy status."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        for _ in range(5):
            monitor.record_success("dhan")
        
        status = monitor.get_status()
        assert status["dhan"]["status"] == "healthy"
    
    def test_status_unhealthy(self):
        """Should show unhealthy status."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        for _ in range(10):
            monitor.record_failure("dhan")
        
        status = monitor.get_status()
        assert status["dhan"]["status"] == "unhealthy"
    
    def test_get_all_scores(self):
        """Should return all scores."""
        providers = {"dhan": Mock(), "opencart": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        scores = monitor.get_all_scores()
        
        assert len(scores) == 2
        assert "dhan" in scores
        assert "opencart" in scores


class TestMonitoringLoop:
    """Test background monitoring loop."""
    
    @pytest.mark.asyncio
    async def test_start_monitoring(self):
        """Should start monitoring loop."""
        mock_provider = Mock()
        mock_provider.get_candles = AsyncMock()
        
        providers = {"dhan": mock_provider}
        monitor = ProviderHealthMonitor(
            providers=providers,
            check_interval=1,  # Fast for testing
        )
        
        await monitor.start_monitoring()
        
        assert monitor._monitoring is True
        assert monitor._monitor_task is not None
        
        await monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_stop_monitoring(self):
        """Should stop monitoring loop."""
        mock_provider = Mock()
        mock_provider.get_candles = AsyncMock()
        
        providers = {"dhan": mock_provider}
        monitor = ProviderHealthMonitor(providers=providers, check_interval=1)
        
        await monitor.start_monitoring()
        await monitor.stop_monitoring()
        
        assert monitor._monitoring is False
        assert monitor._monitor_task is None
    
    @pytest.mark.asyncio
    async def test_monitoring_performs_health_checks(self):
        """Should perform health checks during monitoring."""
        mock_provider = Mock()
        mock_provider.get_candles = AsyncMock()
        
        providers = {"dhan": mock_provider}
        monitor = ProviderHealthMonitor(providers=providers, check_interval=1)
        
        await monitor.start_monitoring()
        
        # Wait for at least one check
        await asyncio.sleep(1.5)
        
        await monitor.stop_monitoring()
        
        # Should have called get_candles at least once
        assert mock_provider.get_candles.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_monitoring_handles_provider_failure(self):
        """Should handle provider failure gracefully."""
        mock_provider = Mock()
        mock_provider.get_candles = AsyncMock(side_effect=Exception("API Error"))
        
        providers = {"dhan": mock_provider}
        monitor = ProviderHealthMonitor(providers=providers, check_interval=1)
        
        await monitor.start_monitoring()
        
        # Wait for check
        await asyncio.sleep(1.5)
        
        await monitor.stop_monitoring()
        
        # Score should have decreased
        assert monitor.get_health_score("dhan") < 50.0


class TestConsecutiveTracking:
    """Test consecutive success/failure tracking."""
    
    def test_consecutive_successes_reset_on_failure(self):
        """Should reset success count on failure."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        monitor.record_success("dhan")
        monitor.record_success("dhan")
        monitor.record_failure("dhan")
        
        status = monitor.get_status()
        assert status["dhan"]["consecutive_successes"] == 0
    
    def test_consecutive_failures_reset_on_success(self):
        """Should reset failure count on success."""
        providers = {"dhan": Mock()}
        monitor = ProviderHealthMonitor(providers=providers)
        
        monitor.record_failure("dhan")
        monitor.record_failure("dhan")
        monitor.record_success("dhan")
        
        status = monitor.get_status()
        assert status["dhan"]["consecutive_failures"] == 0
