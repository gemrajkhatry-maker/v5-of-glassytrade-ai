"""
Market Data Metrics - Comprehensive observability for market data pipeline.

Tracks:
- Tick latency (p50, p95, p99)
- Provider success/failure rates
- Cache hit/miss rates
- WebSocket connection uptime
- Replay progress
- Alerting on threshold breaches
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional


class MarketDataMetrics:
    """
    Comprehensive metrics for market data pipeline.
    
    Provides visibility into:
    - Tick processing latency with percentile calculations
    - Provider API call success/failure rates
    - Cache performance (hit/miss rates)
    - WebSocket connection uptime
    - Alert generation for threshold breaches
    """
    
    def __init__(self):
        self._tick_latencies: List[float] = []
        self._provider_calls: Dict[str, Dict] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._ws_uptime_start: Optional[datetime] = None
        self._ws_connected = False
        self._alerts: List[Dict] = []
        
        # Alert thresholds
        self._tick_latency_threshold_ms = 100.0  # Alert if >100ms
        self._provider_failure_threshold = 0.1  # Alert if >10% failure rate
    
    # -------------------------------------------------------------------------
    # Tick Latency Tracking
    # -------------------------------------------------------------------------
    
    def record_tick_latency(self, latency_ms: float):
        """
        Record tick processing latency.
        
        Args:
            latency_ms: Latency in milliseconds
        """
        self._tick_latencies.append(latency_ms)
        
        # Keep last 1000 samples
        if len(self._tick_latencies) > 1000:
            self._tick_latencies = self._tick_latencies[-1000:]
        
        # Check alert threshold
        if latency_ms > self._tick_latency_threshold_ms:
            self._record_alert(
                "HIGH_TICK_LATENCY",
                f"Tick latency {latency_ms:.1f}ms exceeds threshold {self._tick_latency_threshold_ms}ms"
            )
    
    def get_latency_percentiles(self) -> Dict[str, float]:
        """
        Get latency percentiles (p50, p95, p99).
        
        Returns:
            Dict with p50, p95, p99, avg, count
        """
        if not self._tick_latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "count": 0}
        
        sorted_latencies = sorted(self._tick_latencies)
        n = len(sorted_latencies)
        
        return {
            "p50": sorted_latencies[int(n * 0.50)],
            "p95": sorted_latencies[min(int(n * 0.95), n - 1)],
            "p99": sorted_latencies[min(int(n * 0.99), n - 1)],
            "avg": sum(sorted_latencies) / n,
            "count": n,
        }
    
    # -------------------------------------------------------------------------
    # Provider Call Tracking
    # -------------------------------------------------------------------------
    
    def record_provider_call(self, provider: str, success: bool, latency_ms: float):
        """
        Record provider API call.
        
        Args:
            provider: Provider name (e.g., "dhan", "opencart")
            success: Whether call succeeded
            latency_ms: Call latency in milliseconds
        """
        if provider not in self._provider_calls:
            self._provider_calls[provider] = {
                "success": 0,
                "failure": 0,
                "latencies": [],
            }
        
        if success:
            self._provider_calls[provider]["success"] += 1
        else:
            self._provider_calls[provider]["failure"] += 1
        
        self._provider_calls[provider]["latencies"].append(latency_ms)
        
        # Keep last 100 latencies
        if len(self._provider_calls[provider]["latencies"]) > 100:
            self._provider_calls[provider]["latencies"] = \
                self._provider_calls[provider]["latencies"][-100:]
        
        # Check failure rate threshold
        stats = self._provider_calls[provider]
        total = stats["success"] + stats["failure"]
        if total > 10:  # Only check after enough samples
            failure_rate = stats["failure"] / total
            if failure_rate > self._provider_failure_threshold:
                self._record_alert(
                    "HIGH_PROVIDER_FAILURE_RATE",
                    f"Provider {provider} failure rate {failure_rate:.1%} exceeds threshold {self._provider_failure_threshold:.1%}"
                )
    
    def get_provider_stats(self, provider: str) -> Dict:
        """
        Get provider statistics.
        
        Args:
            provider: Provider name
            
        Returns:
            Dict with total_calls, success_rate, avg_latency_ms
        """
        stats = self._provider_calls.get(
            provider,
            {"success": 0, "failure": 0, "latencies": []}
        )
        
        total = stats["success"] + stats["failure"]
        success_rate = stats["success"] / total if total > 0 else 0.0
        
        avg_latency = (
            sum(stats["latencies"]) / len(stats["latencies"])
            if stats["latencies"]
            else 0.0
        )
        
        return {
            "total_calls": total,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
        }
    
    # -------------------------------------------------------------------------
    # Cache Performance Tracking
    # -------------------------------------------------------------------------
    
    def record_cache_hit(self):
        """Record cache hit."""
        self._cache_hits += 1
    
    def record_cache_miss(self):
        """Record cache miss."""
        self._cache_misses += 1
    
    def get_cache_stats(self) -> Dict:
        """
        Get cache hit/miss statistics.
        
        Returns:
            Dict with hits, misses, hit_rate
        """
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": self._cache_hits / total if total > 0 else 0.0,
        }
    
    # -------------------------------------------------------------------------
    # WebSocket Connection Tracking
    # -------------------------------------------------------------------------
    
    def record_ws_connected(self):
        """Record WebSocket connection established."""
        self._ws_connected = True
        self._ws_uptime_start = datetime.now()
    
    def record_ws_disconnected(self):
        """Record WebSocket connection lost."""
        self._ws_connected = False
        self._ws_uptime_start = None
    
    def get_ws_uptime_seconds(self) -> float:
        """Get WebSocket uptime in seconds."""
        if not self._ws_uptime_start:
            return 0.0
        
        return (datetime.now() - self._ws_uptime_start).total_seconds()
    
    # -------------------------------------------------------------------------
    # Alert Management
    # -------------------------------------------------------------------------
    
    def _record_alert(self, alert_type: str, message: str):
        """
        Record alert.
        
        Args:
            alert_type: Alert type identifier
            message: Alert message
        """
        self._alerts.append({
            "timestamp": datetime.now().isoformat(),
            "type": alert_type,
            "message": message,
        })
        
        # Keep last 100 alerts
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]
    
    def get_alerts(self, limit: int = 10) -> List[Dict]:
        """
        Get recent alerts.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of recent alerts
        """
        return self._alerts[-limit:]
    
    def clear_alerts(self):
        """Clear all alerts."""
        self._alerts.clear()
    
    # -------------------------------------------------------------------------
    # Dashboard
    # -------------------------------------------------------------------------
    
    def get_dashboard(self) -> Dict:
        """
        Get comprehensive dashboard data.
        
        Returns:
            Dict with all metrics organized for dashboard display
        """
        return {
            "latency": self.get_latency_percentiles(),
            "providers": {
                name: self.get_provider_stats(name)
                for name in self._provider_calls.keys()
            },
            "cache": self.get_cache_stats(),
            "websocket": {
                "connected": self._ws_connected,
                "uptime_seconds": self.get_ws_uptime_seconds(),
            },
            "alerts": self.get_alerts(limit=10),
            "timestamp": datetime.now().isoformat(),
        }
    
    def reset(self):
        """Reset all metrics."""
        self._tick_latencies.clear()
        self._provider_calls.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._ws_uptime_start = None
        self._ws_connected = False
        self._alerts.clear()
