# ===== Gate Rejection Tracker =====


from app.domain.ops.gate_rejection_tracker import GateRejectionTracker
from app.domain.ops.latency_tracker import LatencyTracker


class TestGateRejectionTracker:
    def test_record_pass(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", True)
        stats = tracker.get_symbol_stats("NIFTY")
        assert stats["gate_0"]["passed"] == 1

    def test_record_rejection(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", False)
        stats = tracker.get_symbol_stats("NIFTY")
        assert stats["gate_0"]["rejected"] == 1

    def test_rejection_rate(self):
        tracker = GateRejectionTracker()
        for _ in range(7):
            tracker.record("NIFTY", "gate_0", False)
        for _ in range(3):
            tracker.record("NIFTY", "gate_0", True)
        stats = tracker.get_symbol_stats("NIFTY")
        assert stats["gate_0"]["rejection_rate"] == 0.7

    def test_top_killers(self):
        tracker = GateRejectionTracker()
        for _ in range(10):
            tracker.record("NIFTY", "gate_7", False)
        for _ in range(5):
            tracker.record("NIFTY", "gate_3", False)
        for _ in range(2):
            tracker.record("NIFTY", "gate_0", False)
        killers = tracker.get_top_killers("NIFTY", 2)
        assert killers[0]["gate"] == "gate_7"
        assert killers[1]["gate"] == "gate_3"

    def test_multi_symbol(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", False)
        tracker.record("BANKNIFTY", "gate_0", True)
        all_stats = tracker.get_all_stats()
        assert "NIFTY" in all_stats
        assert "BANKNIFTY" in all_stats

    def test_reset(self):
        tracker = GateRejectionTracker()
        tracker.record("NIFTY", "gate_0", False)
        tracker.reset()
        assert tracker.get_symbol_stats("NIFTY") == {}


# ===== Latency Tracker =====


class TestLatencyTracker:
    def test_record_and_snapshot(self):
        tracker = LatencyTracker()
        tracker.record("NIFTY", 5.0)
        snap = tracker.get_snapshot("NIFTY")
        assert snap.sample_count == 1
        assert snap.p50 == 5.0

    def test_p50_p95_p99(self):
        tracker = LatencyTracker()
        for i in range(100):
            tracker.record("NIFTY", float(i))
        snap = tracker.get_snapshot("NIFTY")
        assert snap.p50 == 50.0
        assert snap.p95 == 95.0
        assert snap.p99 == 99.0

    def test_warning_flag(self):
        tracker = LatencyTracker()
        for _ in range(100):
            tracker.record("NIFTY", 60.0)  # >50ms
        snap = tracker.get_snapshot("NIFTY")
        assert snap.warning is True
        assert snap.critical is False

    def test_critical_flag(self):
        tracker = LatencyTracker()
        for _ in range(100):
            tracker.record("NIFTY", 250.0)  # >200ms
        snap = tracker.get_snapshot("NIFTY")
        assert snap.critical is True

    def test_rolling_window(self):
        tracker = LatencyTracker(window_size=10)
        for i in range(20):
            tracker.record("NIFTY", float(i))
        snap = tracker.get_snapshot("NIFTY")
        assert snap.sample_count == 10  # only last 10 kept

    def test_empty_snapshot(self):
        tracker = LatencyTracker()
        snap = tracker.get_snapshot("NIFTY")
        assert snap.sample_count == 0
        assert snap.warning is False
