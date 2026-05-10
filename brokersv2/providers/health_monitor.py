"""
Provider Health Monitor - Active health monitoring and automatic failover.

Monitors market data provider health and triggers failover on degradation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ProviderHealthMonitor:
    """
    Active health monitoring for market data providers.
    
    Features:
    - Periodic health checks (configurable interval)
    - Health score calculation (0-100 scale)
    - Consecutive failure tracking
    - Automatic failover decisions
    - Recovery detection
    
    Usage:
        monitor = ProviderHealthMonitor(
            providers={"dhan": dhan_provider, "opencart": opencart_provider},
            check_interval=30,
            failure_threshold=3,
            test_symbol="RELIANCE",
        )
        await monitor.start_monitoring()
        
        # Check if should failover
        if monitor.should_failover("dhan"):
            healthy = monitor.get_healthy_provider()
            # Switch to healthy provider
    """
    
    def __init__(
        self,
        providers: Dict[str, Any],
        check_interval: int = 30,
        failure_threshold: int = 3,
        recovery_threshold: int = 2,
        test_symbol: Optional[str] = None,
    ):
        """
        Initialize health monitor.
        
        Args:
            providers: Dict mapping provider name to provider instance
            check_interval: Seconds between health checks
            failure_threshold: Consecutive failures before recommending failover
            recovery_threshold: Consecutive successes before marking as recovered
        """
        self._providers = providers
        self._check_interval = check_interval
        self._failure_threshold = failure_threshold
        self._recovery_threshold = recovery_threshold
        self._test_symbol = test_symbol or os.environ.get("HEALTH_CHECK_SYMBOL", "RELIANCE")
        
        # Health tracking
        self._health_scores: Dict[str, float] = {name: 50.0 for name in providers}
        self._consecutive_failures: Dict[str, int] = {name: 0 for name in providers}
        self._consecutive_successes: Dict[str, int] = {name: 0 for name in providers}
        
        # Monitoring state
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Last check times
        self._last_check_times: Dict[str, Optional[datetime]] = {
            name: None for name in providers
        }
    
    # -------------------------------------------------------------------------
    # Monitoring Lifecycle
    # -------------------------------------------------------------------------
    
    async def start_monitoring(self):
        """Start background health monitoring."""
        if self._monitoring:
            logger.warning("Health monitoring already running")
            return
        
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Started health monitoring for {len(self._providers)} providers")
    
    async def stop_monitoring(self):
        """Stop health monitoring."""
        if not self._monitoring:
            return
        
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        logger.info("Stopped health monitoring")
    
    async def _monitor_loop(self):
        """Background monitoring loop."""
        while self._monitoring:
            try:
                for provider_name, provider in self._providers.items():
                    await self._check_provider_health(provider_name, provider)
                
                # Wait for next check interval
                await asyncio.sleep(self._check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}")
                await asyncio.sleep(self._check_interval)
    
    # -------------------------------------------------------------------------
    # Health Checking
    # -------------------------------------------------------------------------
    
    async def _check_provider_health(self, name: str, provider: Any):
        """
        Check single provider health.
        
        Args:
            name: Provider name
            provider: Provider instance
        """
        try:
            # Attempt test request (fetch recent 1m candles)
            start = time.time()
            
            # This is a simplified health check - in production, use a lightweight endpoint
            # For now, we'll just check if provider is accessible
            await self._perform_health_check(provider)
            
            response_time = time.time() - start
            
            # Record success
            self._consecutive_failures[name] = 0
            self._consecutive_successes[name] = self._consecutive_successes.get(name, 0) + 1
            
            # Update health score (+10 for success, cap at 100)
            self._health_scores[name] = min(100.0, self._health_scores.get(name, 50) + 10)
            
            self._last_check_times[name] = datetime.now()
            
            logger.debug(f"Provider {name} health check passed ({response_time:.2f}s)")
            
        except Exception as e:
            # Record failure
            self._consecutive_successes[name] = 0
            self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
            
            # Update health score (-20 for failure, floor at 0)
            self._health_scores[name] = max(0.0, self._health_scores.get(name, 50) - 20)
            
            self._last_check_times[name] = datetime.now()
            
            logger.warning(
                f"Provider {name} health check failed "
                f"(failures: {self._consecutive_failures[name]}, "
                f"score: {self._health_scores[name]:.0f}): {e}"
            )
    
    async def _perform_health_check(self, provider: Any):
        """
        Perform actual health check on provider.
        
        Args:
            provider: Provider instance to check
            
        Raises:
            Exception if provider is unhealthy
        """
        # Try to call a simple method on provider
        # This will be adapted based on actual provider interface
        if hasattr(provider, 'get_candles'):
            # Try fetching minimal data
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Use configurable test instrument for health check
            # Set via test_symbol parameter or HEALTH_CHECK_SYMBOL env var
            await provider.get_candles(
                instrument=self._test_symbol,
                timeframe="1m",
                from_date=yesterday,
                to_date=today,
            )
        else:
            # Provider doesn't have expected interface - assume unhealthy
            raise ValueError(f"Provider {provider} has no get_candles method")
    
    # -------------------------------------------------------------------------
    # Health Queries
    # -------------------------------------------------------------------------
    
    def get_health_score(self, provider_name: str) -> float:
        """
        Get current health score for provider.
        
        Args:
            provider_name: Provider name
            
        Returns:
            Health score (0-100, higher is better)
        """
        return self._health_scores.get(provider_name, 50.0)
    
    def get_healthy_provider(self) -> Optional[str]:
        """
        Get healthiest provider name.
        
        Returns:
            Name of provider with highest health score, or None
        """
        if not self._health_scores:
            return None
        
        return max(self._health_scores.items(), key=lambda x: x[1])[0]
    
    def should_failover(self, current_provider: str) -> bool:
        """
        Check if should failover from current provider.
        
        Args:
            current_provider: Current provider name
            
        Returns:
            True if failover is recommended
        """
        score = self._health_scores.get(current_provider, 50)
        failures = self._consecutive_failures.get(current_provider, 0)
        
        # Failover if score < 30 OR consecutive failures >= threshold
        return score < 30 or failures >= self._failure_threshold
    
    def is_healthy(self, provider_name: str) -> bool:
        """
        Check if provider is considered healthy.
        
        Args:
            provider_name: Provider name
            
        Returns:
            True if provider is healthy
        """
        return self.get_health_score(provider_name) > 70
    
    def get_status(self) -> Dict:
        """
        Get comprehensive health status for all providers.
        
        Returns:
            Dict with status for each provider
        """
        status = {}
        for provider in self._providers.keys():
            score = self._health_scores.get(provider, 50)
            failures = self._consecutive_failures.get(provider, 0)
            successes = self._consecutive_successes.get(provider, 0)
            
            if score > 70:
                provider_status = "healthy"
            elif score > 30:
                provider_status = "degraded"
            else:
                provider_status = "unhealthy"
            
            status[provider] = {
                "health_score": score,
                "consecutive_failures": failures,
                "consecutive_successes": successes,
                "status": provider_status,
                "last_check": self._last_check_times.get(provider),
            }
        
        return status
    
    def get_all_scores(self) -> Dict[str, float]:
        """
        Get health scores for all providers.
        
        Returns:
            Dict mapping provider name to health score
        """
        return dict(self._health_scores)
    
    # -------------------------------------------------------------------------
    # Manual Updates
    # -------------------------------------------------------------------------
    
    def record_success(self, provider_name: str):
        """
        Manually record provider success.
        
        Args:
            provider_name: Provider name
        """
        self._consecutive_failures[provider_name] = 0
        self._consecutive_successes[provider_name] = \
            self._consecutive_successes.get(provider_name, 0) + 1
        self._health_scores[provider_name] = \
            min(100.0, self._health_scores.get(provider_name, 50) + 5)
    
    def record_failure(self, provider_name: str, error: str = ""):
        """
        Manually record provider failure.
        
        Args:
            provider_name: Provider name
            error: Error message
        """
        self._consecutive_successes[provider_name] = 0
        self._consecutive_failures[provider_name] = \
            self._consecutive_failures.get(provider_name, 0) + 1
        self._health_scores[provider_name] = \
            max(0.0, self._health_scores.get(provider_name, 50) - 10)
        
        logger.warning(
            f"Manual failure record for {provider_name}: {error} "
            f"(score: {self._health_scores[provider_name]:.0f})"
        )
