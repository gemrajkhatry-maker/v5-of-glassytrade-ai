"""Tests for the prometheus_client-backed metrics registry."""

import pytest

from app.core.metrics import (
    Counter,
    Gauge,
    Histogram,
    Metric,
    MetricsRegistry,
    metrics,
)


@pytest.fixture
def fresh_registry():
    """Return a standalone registry (not the module singleton) to avoid
    cross-test pollution from module-level metrics."""
    reg = object.__new__(MetricsRegistry)
    MetricsRegistry.__init__(reg)
    return reg


class TestMetricsRegistry:
    def test_singleton(self):
        assert metrics is MetricsRegistry()

    def test_counter_inc_and_value(self, fresh_registry):
        c = fresh_registry.counter("test_ops_total", "Test operations")
        c.inc()
        c.inc(2)
        assert c.value == 3.0
        assert isinstance(c, Counter)

    def test_gauge_set_and_value(self, fresh_registry):
        g = fresh_registry.gauge("test_watermark", "Test watermark")
        g.set(42.0)
        assert g.value == 42.0
        assert isinstance(g, Gauge)

    def test_histogram_observe_count_sum(self, fresh_registry):
        h = fresh_registry.histogram("test_latency_seconds", "Test latency")
        h.observe(0.1)
        h.observe(0.9)
        assert h.count == 2
        assert h.sum_val == pytest.approx(1.0)
        assert isinstance(h, Histogram)

    def test_metric_key_without_labels(self, fresh_registry):
        assert fresh_registry._metric_key("foo_total", {}) == "foo_total"

    def test_metric_key_with_labels(self, fresh_registry):
        key = fresh_registry._metric_key("foo_total", {"b": "2", "a": "1"})
        assert key == "foo_total{a=1,b=2}"

    def test_metrics_dict_keyed_by_name(self, fresh_registry):
        c = fresh_registry.counter("test_ops_total", "Test operations")
        assert fresh_registry._metrics["test_ops_total"] is c
        assert fresh_registry._metrics.get("test_ops_total") is c

    def test_get_or_create_returns_same_object(self, fresh_registry):
        c1 = fresh_registry.counter("test_ops_total", "Test operations")
        c2 = fresh_registry.counter("test_ops_total", "Different help ignored")
        assert c1 is c2

    def test_labeled_metric_separate_from_unlabeled(self, fresh_registry):
        plain = fresh_registry.counter("test_ops_total", "Test operations")
        labeled = fresh_registry.counter(
            "test_ops_total", "Test operations", labels={"kind": "a"}
        )
        assert plain is not labeled
        assert plain.value == 0.0
        labeled.inc(5)
        assert labeled.value == 5.0
        assert plain.value == 0.0


class TestExposition:
    def test_counter_renders_into_text_format(self, fresh_registry):
        c = fresh_registry.counter("test_ops_total", "Test operations")
        c.inc(2)
        out = fresh_registry.to_prometheus()
        assert "# HELP test_ops_total Test operations" in out
        assert "# TYPE test_ops_total counter" in out
        assert "test_ops_total 2.0" in out

    def test_gauge_renders_into_text_format(self, fresh_registry):
        g = fresh_registry.gauge("test_watermark", "Test watermark")
        g.set(-1.0)
        out = fresh_registry.to_prometheus()
        assert "# TYPE test_watermark gauge" in out
        assert "test_watermark -1.0" in out

    def test_histogram_renders_buckets_count_sum(self, fresh_registry):
        h = fresh_registry.histogram("test_latency_seconds", "Test latency")
        h.observe(0.1)
        h.observe(2.0)
        out = fresh_registry.to_prometheus()
        assert "# TYPE test_latency_seconds histogram" in out
        assert 'test_latency_seconds_bucket{le="0.1"} 1.0' in out
        assert 'test_latency_seconds_bucket{le="2.5"} 2.0' in out
        assert 'test_latency_seconds_bucket{le="+Inf"} 2.0' in out
        assert "test_latency_seconds_sum 2.1" in out
        assert "test_latency_seconds_count 2.0" in out

    def test_histogram_uses_original_bucket_boundaries(self, fresh_registry):
        h = fresh_registry.histogram("test_buckets_seconds", "Test buckets")
        h.observe(0.07)
        out = fresh_registry.to_prometheus()
        assert 'test_buckets_seconds_bucket{le="0.05"} 0.0' in out
        assert 'test_buckets_seconds_bucket{le="0.1"} 1.0' in out
        assert 'test_buckets_seconds_bucket{le="0.25"} 1.0' in out

    def test_labeled_metric_renders_label_values(self, fresh_registry):
        c = fresh_registry.counter(
            "test_labeled_total", "Labeled counter", labels={"kind": "alpha"}
        )
        c.inc(1)
        out = fresh_registry.to_prometheus()
        assert 'test_labeled_total{kind="alpha"} 1.0' in out

    def test_no_created_series_emitted(self, fresh_registry):
        fresh_registry.counter("test_ops_total", "Test operations").inc(1)
        out = fresh_registry.to_prometheus()
        assert "test_ops_created" not in out


class TestModuleSurface:
    def test_module_convenience_metrics_exist(self):
        assert isinstance(metrics.counter("ticks_processed_total", ""), Counter)
        assert isinstance(metrics.counter("signals_generated_total", ""), Counter)
        assert isinstance(metrics.counter("errors_total", ""), Counter)
        assert isinstance(metrics.histogram("amt_pipeline_duration_seconds", ""), Histogram)
        assert isinstance(metrics.gauge("positions_active", ""), Gauge)
        assert isinstance(Metric, type)
        assert isinstance(Counter, type)
        assert isinstance(Gauge, type)
        assert isinstance(Histogram, type)
        assert isinstance(MetricsRegistry, type)
