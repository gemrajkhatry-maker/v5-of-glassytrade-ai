"""Tests for per-stage latency tracking in TradingSessionService."""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from app.domain.ops.latency_tracker import LatencyTracker


class TestPerStageLatencyTracking:
    """Verify that trading session tracks latency per stage."""

    def test_latency_tracker_records_stage_latencies(self):
        """LatencyTracker should record per-stage latencies with symbol:stage keys."""
        tracker = LatencyTracker()
        
        # Simulate stage recordings
        tracker.record("CRUDEOIL:amt_analysis", 15.5)
        tracker.record("CRUDEOIL:micro_agents", 2.3)
        tracker.record("CRUDEOIL:entry_execution", 5.1)
        tracker.record("CRUDEOIL:total_tick", 45.2)
        
        # Check stage-specific snapshots
        amt_snapshot = tracker.get_snapshot("CRUDEOIL:amt_analysis")
        assert amt_snapshot.sample_count == 1
        assert amt_snapshot.p50 == 15.5
        
        micro_snapshot = tracker.get_snapshot("CRUDEOIL:micro_agents")
        assert micro_snapshot.sample_count == 1
        assert micro_snapshot.p50 == 2.3
        
        # Check total
        total_snapshot = tracker.get_snapshot("CRUDEOIL:total_tick")
        assert total_snapshot.p50 == 45.2

    def test_latency_tracker_aggregates_multiple_samples(self):
        """Should track rolling window of samples per stage."""
        tracker = LatencyTracker(window_size=10)
        
        # Record multiple samples for same stage
        for i in range(5):
            tracker.record("NIFTY:amt_analysis", 10.0 + i)
        
        snapshot = tracker.get_snapshot("NIFTY:amt_analysis")
        assert snapshot.sample_count == 5
        # p50 of [10, 11, 12, 13, 14] = 12
        assert snapshot.p50 == 12.0

    def test_latency_tracker_detects_slow_stages(self):
        """Should flag stages exceeding thresholds."""
        tracker = LatencyTracker()
        
        # Record slow stage (p99 > 50ms = warning)
        for _ in range(100):
            tracker.record("GOLDM:amt_analysis", 60.0)
        
        snapshot = tracker.get_snapshot("GOLDM:amt_analysis")
        assert snapshot.warning is True
        assert snapshot.critical is False  # < 200ms
        
        # Record very slow stage (p99 > 200ms = critical)
        for _ in range(100):
            tracker.record("GOLDM:llm_trigger", 250.0)
        
        llm_snapshot = tracker.get_snapshot("GOLDM:llm_trigger")
        assert llm_snapshot.critical is True

    def test_latency_tracker_summary_across_stages(self):
        """Should provide summary across all stages."""
        tracker = LatencyTracker()
        
        tracker.record("CRUDEOIL:amt_analysis", 15.0)
        tracker.record("CRUDEOIL:micro_agents", 2.0)
        tracker.record("CRUDEOIL:entry_execution", 5.0)
        
        summary = tracker.get_summary()
        assert "CRUDEOIL:amt_analysis" in summary
        assert "CRUDEOIL:micro_agents" in summary
        assert "CRUDEOIL:entry_execution" in summary
        
        # Each stage should have metrics
        assert summary["CRUDEOIL:amt_analysis"]["p50"] == 15.0
        assert summary["CRUDEOIL:micro_agents"]["p50"] == 2.0

    def test_latency_tracker_resets(self):
        """Should clear all recorded latencies."""
        tracker = LatencyTracker()
        tracker.record("NIFTY:amt_analysis", 10.0)
        tracker.record("NIFTY:micro_agents", 2.0)
        
        tracker.reset()
        
        summary = tracker.get_summary()
        assert len(summary) == 0


class TestLatencyTrackerEdgeCases:
    """Edge cases for latency tracking."""

    def test_empty_tracker_returns_zero_snapshot(self):
        """Tracker with no samples should return zero metrics."""
        tracker = LatencyTracker()
        snapshot = tracker.get_snapshot("NONEXISTENT:stage")
        
        assert snapshot.p50 == 0
        assert snapshot.p95 == 0
        assert snapshot.p99 == 0
        assert snapshot.sample_count == 0
        assert snapshot.warning is False
        assert snapshot.critical is False

    def test_rolling_window_limits_memory(self):
        """Should not grow beyond window_size."""
        tracker = LatencyTracker(window_size=5)
        
        # Record 100 samples
        for i in range(100):
            tracker.record("TEST:stage", float(i))
        
        snapshot = tracker.get_snapshot("TEST:stage")
        assert snapshot.sample_count == 5  # Only last 5 kept
        # Last 5 samples: [95, 96, 97, 98, 99]
        assert snapshot.max_ms == 99.0

    def test_all_snapshots_retrieval(self):
        """Should retrieve snapshots for all tracked stages."""
        tracker = LatencyTracker()
        tracker.record("A:stage1", 10.0)
        tracker.record("A:stage2", 20.0)
        tracker.record("B:stage1", 30.0)
        
        all_snapshots = tracker.get_all_snapshots()
        assert len(all_snapshots) == 3
        assert "A:stage1" in all_snapshots
        assert "A:stage2" in all_snapshots
        assert "B:stage1" in all_snapshots
