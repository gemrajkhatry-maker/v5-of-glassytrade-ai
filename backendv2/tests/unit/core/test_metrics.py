"""Tests for MetricsRegistry — global metrics collection.

Behavior: MetricsRegistry collects counters, gauges, and histograms
and provides snapshots for observability endpoints.
"""
from __future__ import annotations

import threading
import pytest

from app.core.metrics import MetricsRegistry


class TestMetricsRegistry:
    """Tests for MetricsRegistry behavior through public interface."""

    def test_counter_increments(self):
        """Counter should accumulate values."""
        registry = MetricsRegistry()
        
        registry.counter("ticks_processed")
        registry.counter("ticks_processed")
        registry.counter("ticks_processed", value=5.0)
        
        snapshot = registry.snapshot()
        assert snapshot["counters"]["ticks_processed"] == 7.0

    def test_gauge_overwrites(self):
        """Gauge should hold latest value."""
        registry = MetricsRegistry()
        
        registry.gauge("circuit_breaker_state", 0)
        registry.gauge("circuit_breaker_state", 1)
        
        snapshot = registry.snapshot()
        assert snapshot["gauges"]["circuit_breaker_state"] == 1.0

    def test_histogram_collects_values(self):
        """Histogram should collect all values."""
        registry = MetricsRegistry()
        
        registry.histogram("pipeline_latency", 10.5)
        registry.histogram("pipeline_latency", 20.3)
        registry.histogram("pipeline_latency", 15.7)
        
        snapshot = registry.snapshot()
        assert snapshot["histograms"]["pipeline_latency"] == 3  # count
        # Verify we can access the actual values if needed
        assert "pipeline_latency" in snapshot["histograms"]

    def test_snapshot_returns_all_metric_types(self):
        """Snapshot should include counters, gauges, and histograms."""
        registry = MetricsRegistry()
        
        registry.counter("requests_total", 10.0)
        registry.gauge("active_connections", 5.0)
        registry.histogram("response_time", 100.0)
        
        snapshot = registry.snapshot()
        
        assert "counters" in snapshot
        assert "gauges" in snapshot
        assert "histograms" in snapshot
        assert snapshot["counters"]["requests_total"] == 10.0
        assert snapshot["gauges"]["active_connections"] == 5.0
        assert snapshot["histograms"]["response_time"] == 1

    def test_empty_snapshot_has_zero_counts(self):
        """Empty registry should return empty dicts in snapshot."""
        registry = MetricsRegistry()
        
        snapshot = registry.snapshot()
        
        assert snapshot["counters"] == {}
        assert snapshot["gauges"] == {}
        assert snapshot["histograms"] == {}

    def test_counter_default_value_is_one(self):
        """Counter should default to 1.0 when no value provided."""
        registry = MetricsRegistry()
        
        registry.counter("errors")
        
        snapshot = registry.snapshot()
        assert snapshot["counters"]["errors"] == 1.0

    def test_multiple_counters_independent(self):
        """Different counters should be independent."""
        registry = MetricsRegistry()
        
        registry.counter("ticks_processed", 5.0)
        registry.counter("signals_generated", 3.0)
        
        snapshot = registry.snapshot()
        assert snapshot["counters"]["ticks_processed"] == 5.0
        assert snapshot["counters"]["signals_generated"] == 3.0

    def test_thread_safety(self):
        """Concurrent counter increments should be thread-safe."""
        registry = MetricsRegistry()
        num_threads = 10
        increments_per_thread = 100
        
        def increment_counter():
            for _ in range(increments_per_thread):
                registry.counter("concurrent_test")
        
        threads = [threading.Thread(target=increment_counter) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        snapshot = registry.snapshot()
        expected = num_threads * increments_per_thread
        assert snapshot["counters"]["concurrent_test"] == expected

    def test_can_retrieve_individual_counter(self):
        """Should be able to get a specific counter value."""
        registry = MetricsRegistry()
        
        registry.counter("my_counter", 42.0)
        
        assert registry.get_counter("my_counter") == 42.0
        assert registry.get_counter("nonexistent") == 0.0
