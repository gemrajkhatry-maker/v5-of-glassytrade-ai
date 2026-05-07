"""Tests for Metrics Collector - Prometheus-compatible metrics aggregation."""
import pytest
import time
from brokersv2.observability.metrics import (
    MetricsCollector,
    MetricType,
    MetricRecord,
    MetricsError,
)


class TestMetricRecord:
    """Test MetricRecord value object."""

    def test_create_counter(self):
        """Test creating counter metric."""
        record = MetricRecord(
            name="orders_submitted",
            metric_type=MetricType.COUNTER,
            value=1,
            labels={"exchange": "NSE"},
        )

        assert record.name == "orders_submitted"
        assert record.metric_type == MetricType.COUNTER
        assert record.value == 1
        assert record.labels == {"exchange": "NSE"}

    def test_create_gauge(self):
        """Test creating gauge metric."""
        record = MetricRecord(
            name="active_positions",
            metric_type=MetricType.GAUGE,
            value=5.5,
        )

        assert record.metric_type == MetricType.GAUGE
        assert record.value == 5.5

    def test_create_histogram(self):
        """Test creating histogram metric."""
        record = MetricRecord(
            name="order_latency_ms",
            metric_type=MetricType.HISTOGRAM,
            value=45.2,
            labels={"endpoint": "/orders"},
        )

        assert record.metric_type == MetricType.HISTOGRAM

    def test_record_timestamp(self):
        """Test record has timestamp."""
        record = MetricRecord(
            name="test_metric",
            metric_type=MetricType.COUNTER,
            value=1,
        )

        assert record.timestamp is not None

    def test_metric_type_values(self):
        """Test enum values."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"


class TestMetricsCollector:
    """Test metrics collection and aggregation."""

    def test_increment_counter(self):
        """Test incrementing counter metric."""
        collector = MetricsCollector()
        collector.increment("orders_submitted", labels={"exchange": "NSE"})

        metrics = collector.get_metrics()
        assert "orders_submitted" in metrics
        assert metrics["orders_submitted"].value == 1

    def test_increment_counter_multiple_times(self):
        """Test incrementing counter multiple times."""
        collector = MetricsCollector()
        collector.increment("orders_submitted", labels={"exchange": "NSE"})
        collector.increment("orders_submitted", labels={"exchange": "NSE"})
        collector.increment("orders_submitted", labels={"exchange": "NSE"})

        metrics = collector.get_metrics()
        assert metrics["orders_submitted"].value == 3

    def test_counter_with_different_labels(self):
        """Test counter with different label combinations."""
        collector = MetricsCollector()
        collector.increment("orders_submitted", labels={"exchange": "NSE"})
        collector.increment("orders_submitted", labels={"exchange": "MCX"})
        collector.increment("orders_submitted", labels={"exchange": "NSE"})

        # Get metrics with specific labels
        nse_metric = collector.get_metric("orders_submitted", labels={"exchange": "NSE"})
        mcx_metric = collector.get_metric("orders_submitted", labels={"exchange": "MCX"})

        # Both should exist and have correct values
        assert nse_metric is not None
        assert nse_metric.value == 2  # Incremented twice
        assert nse_metric.labels["exchange"] == "NSE"

        assert mcx_metric is not None
        assert mcx_metric.value == 1
        assert mcx_metric.labels["exchange"] == "MCX"

    def test_set_gauge(self):
        """Test setting gauge metric."""
        collector = MetricsCollector()
        collector.set_gauge("active_positions", 10)

        metrics = collector.get_metrics()
        assert "active_positions" in metrics
        assert metrics["active_positions"].value == 10

    def test_gauge_overwrite(self):
        """Test gauge can be overwritten."""
        collector = MetricsCollector()
        collector.set_gauge("active_positions", 10)
        collector.set_gauge("active_positions", 15)

        metrics = collector.get_metrics()
        assert metrics["active_positions"].value == 15

    def test_gauge_decrease(self):
        """Test gauge can decrease."""
        collector = MetricsCollector()
        collector.set_gauge("active_positions", 10)
        collector.set_gauge("active_positions", 5)

        metrics = collector.get_metrics()
        assert metrics["active_positions"].value == 5

    def test_observe_histogram(self):
        """Test observing histogram metric."""
        collector = MetricsCollector()
        collector.observe("order_latency_ms", 45.2)

        metrics = collector.get_metrics()
        assert "order_latency_ms" in metrics

    def test_histogram_multiple_observations(self):
        """Test histogram with multiple observations."""
        collector = MetricsCollector()
        collector.observe("order_latency_ms", 10.0)
        collector.observe("order_latency_ms", 20.0)
        collector.observe("order_latency_ms", 30.0)

        metrics = collector.get_metrics()
        record = metrics["order_latency_ms"]
        
        assert record.value == 20.0  # Average
        assert record.count == 3
        assert record.sum == 60.0

    def test_histogram_min_max(self):
        """Test histogram tracks min/max."""
        collector = MetricsCollector()
        collector.observe("order_latency_ms", 10.0)
        collector.observe("order_latency_ms", 50.0)
        collector.observe("order_latency_ms", 30.0)

        metrics = collector.get_metrics()
        record = metrics["order_latency_ms"]

        assert record.min == 10.0
        assert record.max == 50.0

    def test_timing_context_manager(self):
        """Test timing context manager."""
        collector = MetricsCollector()

        with collector.timing("api_request_ms"):
            time.sleep(0.01)  # 10ms

        metrics = collector.get_metrics()
        assert "api_request_ms" in metrics
        assert metrics["api_request_ms"].count == 1

    def test_get_metric_by_name(self):
        """Test retrieving specific metric."""
        collector = MetricsCollector()
        collector.increment("test_counter")
        collector.set_gauge("test_gauge", 42)

        counter = collector.get_metric("test_counter")
        assert counter is not None
        assert counter.value == 1

        gauge = collector.get_metric("test_gauge")
        assert gauge is not None
        assert gauge.value == 42

    def test_get_nonexistent_metric(self):
        """Test retrieving nonexistent metric returns None."""
        collector = MetricsCollector()
        metric = collector.get_metric("does_not_exist")
        assert metric is None

    def test_reset_metrics(self):
        """Test resetting all metrics."""
        collector = MetricsCollector()
        collector.increment("counter1")
        collector.set_gauge("gauge1", 100)

        collector.reset()
        metrics = collector.get_metrics()
        assert len(metrics) == 0

    def test_format_prometheus_output(self):
        """Test Prometheus format output."""
        collector = MetricsCollector()
        collector.increment("orders_total", labels={"exchange": "NSE"})
        collector.set_gauge("positions_active", 5)

        output = collector.format_prometheus()

        assert "orders_total" in output
        assert "positions_active" in output
        assert "exchange=\"NSE\"" in output

    def test_metric_with_description(self):
        """Test metric with description."""
        collector = MetricsCollector()
        collector.increment(
            "orders_submitted",
            description="Total orders submitted",
            labels={"exchange": "NSE"},
        )

        metric = collector.get_metric("orders_submitted", labels={"exchange": "NSE"})
        assert metric is not None
        assert metric.description == "Total orders submitted"

    def test_concurrent_counter_increments(self):
        """Test counter handles concurrent increments."""
        collector = MetricsCollector()

        # Simulate concurrent increments
        for _ in range(100):
            collector.increment("high_volume_counter")

        metric = collector.get_metric("high_volume_counter")
        assert metric.value == 100

    def test_gauge_negative_values(self):
        """Test gauge can have negative values."""
        collector = MetricsCollector()
        collector.set_gauge("pnl_daily", -500.50)

        metric = collector.get_metric("pnl_daily")
        assert metric.value == -500.50

    def test_histogram_zero_observations(self):
        """Test histogram with no observations."""
        collector = MetricsCollector()

        # Get metric that doesn't exist
        metric = collector.get_metric("empty_histogram")
        assert metric is None

    def test_metric_labels_are_strings(self):
        """Test that labels are stored as strings."""
        collector = MetricsCollector()
        collector.increment(
            "test_metric",
            labels={"numeric_key": 123, "bool_key": True},
        )

        metric = collector.get_metric("test_metric", labels={"numeric_key": 123, "bool_key": True})
        assert metric is not None
        # Labels should be converted to strings
        assert metric.labels["numeric_key"] == "123"
        assert metric.labels["bool_key"] == "True"

    def test_multiple_metric_types(self):
        """Test collector handles multiple metric types."""
        collector = MetricsCollector()
        collector.increment("counter_metric")
        collector.set_gauge("gauge_metric", 42)
        collector.observe("histogram_metric", 10.5)

        metrics = collector.get_metrics()
        assert len(metrics) == 3
        assert metrics["counter_metric"].metric_type == MetricType.COUNTER
        assert metrics["gauge_metric"].metric_type == MetricType.GAUGE
        assert metrics["histogram_metric"].metric_type == MetricType.HISTOGRAM

    def test_metric_record_frozen(self):
        """Test MetricRecord is immutable."""
        record = MetricRecord(
            name="test",
            metric_type=MetricType.COUNTER,
            value=1,
        )

        # Should not be able to modify
        with pytest.raises(Exception):  # frozen dataclass
            record.value = 2
