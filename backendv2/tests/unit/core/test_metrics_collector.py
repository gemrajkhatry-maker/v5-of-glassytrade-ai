"""Unit tests for enhanced metrics collector."""

from __future__ import annotations

import threading
import time

import pytest

from app.core.metrics_collector import Counter, Gauge, Histogram, MetricsCollector


class TestCounter:
    def test_initial_value(self):
        c = Counter("test_counter")
        assert c.value == 0.0

    def test_increment(self):
        c = Counter("test_counter")
        c.inc()
        assert c.value == 1.0
        c.inc(5.0)
        assert c.value == 6.0

    def test_increment_zero(self):
        c = Counter("test_counter")
        c.inc(0.0)
        assert c.value == 0.0

    def test_with_labels(self):
        c = Counter("http_requests", labels={"method": "GET", "path": "/api"})
        c.inc()
        assert c.labels == {"method": "GET", "path": "/api"}
        assert c.value == 1.0

    def test_to_dict(self):
        c = Counter("test", labels={"env": "prod"})
        c.inc(3.0)
        d = c.to_dict()
        assert d["name"] == "test"
        assert d["value"] == 3.0
        assert d["labels"]["env"] == "prod"


class TestGauge:
    def test_initial_value(self):
        g = Gauge("test_gauge")
        assert g.value == 0.0

    def test_set(self):
        g = Gauge("test_gauge")
        g.set(42.0)
        assert g.value == 42.0

    def test_inc_dec(self):
        g = Gauge("test_gauge")
        g.set(10.0)
        g.inc(5.0)
        assert g.value == 15.0
        g.dec(3.0)
        assert g.value == 12.0

    def test_can_go_negative(self):
        g = Gauge("test_gauge")
        g.set(-10.0)
        assert g.value == -10.0

    def test_to_dict(self):
        g = Gauge("cpu", labels={"host": "server1"})
        g.set(75.0)
        d = g.to_dict()
        assert d["name"] == "cpu"
        assert d["value"] == 75.0


class TestHistogram:
    def test_initial_count(self):
        h = Histogram("test_histogram")
        assert h.count == 0

    def test_observe(self):
        h = Histogram("test_histogram")
        h.observe(1.0)
        h.observe(2.0)
        h.observe(3.0)
        assert h.count == 3

    def test_stats_empty(self):
        h = Histogram("test_histogram")
        d = h.to_dict()
        assert d["stats"]["count"] == 0

    def test_stats_single_value(self):
        h = Histogram("test_histogram")
        h.observe(42.0)
        s = h.to_dict()["stats"]
        assert s["count"] == 1
        assert s["min"] == 42.0
        assert s["max"] == 42.0
        assert s["avg"] == 42.0

    def test_stats_multiple_values(self):
        h = Histogram("test_histogram")
        for v in range(1, 101):
            h.observe(float(v))
        s = h.to_dict()["stats"]
        assert s["count"] == 100
        assert s["min"] == 1.0
        assert s["max"] == 100.0
        assert s["avg"] == 50.5
        # nearest-rank: index = int(n * ratio)
        assert s["p50"] == 51.0   # index 50
        assert s["p95"] == 96.0   # index 95
        assert s["p99"] == 100.0  # index 99

    def test_time_context_manager(self):
        h = Histogram("latency")
        with h.time():
            time.sleep(0.01)
        assert h.count == 1
        assert h.to_dict()["stats"]["min"] > 0

    def test_with_labels(self):
        h = Histogram("request_duration", labels={"method": "POST"})
        h.observe(0.5)
        assert h.labels == {"method": "POST"}


class TestMetricsCollector:
    def test_counter_registry(self):
        mc = MetricsCollector()
        c1 = mc.counter("requests")
        c2 = mc.counter("requests")
        assert c1 is c2  # same instance
        c1.inc()
        assert c1.value == 1.0

    def test_counter_with_labels(self):
        mc = MetricsCollector()
        c_get = mc.counter("requests", labels={"method": "GET"})
        c_post = mc.counter("requests", labels={"method": "POST"})
        assert c_get is not c_post
        c_get.inc()
        c_post.inc(3.0)
        assert c_get.value == 1.0
        assert c_post.value == 3.0

    def test_gauge_registry(self):
        mc = MetricsCollector()
        g1 = mc.gauge("cpu")
        g2 = mc.gauge("cpu")
        assert g1 is g2
        g1.set(50.0)
        assert g1.value == 50.0

    def test_histogram_registry(self):
        mc = MetricsCollector()
        h1 = mc.histogram("latency")
        h2 = mc.histogram("latency")
        assert h1 is h2
        h1.observe(1.0)
        assert h1.count == 1

    def test_timing_context_manager(self):
        mc = MetricsCollector()
        with mc.timing("operation"):
            time.sleep(0.01)
        h = mc.histogram("operation")
        assert h.count == 1

    def test_snapshot(self):
        mc = MetricsCollector()
        mc.counter("requests").inc(5.0)
        mc.gauge("cpu").set(75.0)
        mc.histogram("latency").observe(1.0)

        snap = mc.snapshot()
        assert "counters" in snap
        assert "gauges" in snap
        assert "histograms" in snap

    def test_format_prometheus_basic(self):
        mc = MetricsCollector()
        mc.counter("requests_total").inc(100.0)
        mc.gauge("cpu_usage").set(75.0)

        output = mc.format_prometheus()
        assert "requests_total 100.0" in output
        assert "cpu_usage 75.0" in output

    def test_format_prometheus_with_labels(self):
        mc = MetricsCollector()
        mc.counter("requests", labels={"method": "GET"}).inc(50.0)

        output = mc.format_prometheus()
        assert 'requests{method="GET"}' in output

    def test_format_prometheus_histogram(self):
        mc = MetricsCollector()
        h = mc.histogram("latency")
        h.observe(1.0)
        h.observe(2.0)

        output = mc.format_prometheus()
        assert "latency_count" in output
        assert "latency_sum" in output
        assert "latency_avg" in output

    def test_clear(self):
        mc = MetricsCollector()
        mc.counter("requests").inc()
        mc.clear()
        c = mc.counter("requests")
        assert c.value == 0.0  # new counter after clear


class TestMetricsCollectorThreadSafety:
    def test_concurrent_counter_increments(self):
        mc = MetricsCollector()
        c = mc.counter("concurrent")

        def increment():
            for _ in range(100):
                c.inc()

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.value == 1000.0

    def test_concurrent_histogram_observes(self):
        mc = MetricsCollector()
        h = mc.histogram("concurrent_latency")

        def observe():
            for i in range(50):
                h.observe(float(i))

        threads = [threading.Thread(target=observe) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert h.count == 200
