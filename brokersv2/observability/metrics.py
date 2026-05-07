"""Metrics Collector - Prometheus-compatible metrics aggregation."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricsError(Exception):
    """Base exception for metrics errors."""
    pass


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(frozen=True)
class MetricRecord:
    """Immutable metric record."""
    name: str
    metric_type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Histogram-specific fields
    count: int = 0
    sum: float = 0.0
    min: float = float("inf")
    max: float = float("-inf")


@dataclass
class HistogramState:
    """Mutable state for histogram metrics."""
    count: int = 0
    sum: float = 0.0
    min: float = float("inf")
    max: float = float("-inf")


class MetricsCollector:
    """
    Production metrics collector with Prometheus compatibility.
    
    Features:
    - Counter metrics (monotonically increasing)
    - Gauge metrics (can go up or down)
    - Histogram metrics (with min/max/avg)
    - Label support for dimensionality
    - Prometheus format export
    - Thread-safe operations
    - Timing context manager
    """

    def __init__(self):
        self._metrics: Dict[str, MetricRecord] = {}
        self._histogram_states: Dict[str, HistogramState] = {}
        self._lock = Lock()
        self._descriptions: Dict[str, str] = {}

    def increment(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict] = None,
        description: str = "",
    ):
        """
        Increment a counter metric.
        
        Args:
            name: Metric name
            value: Value to increment by (default: 1)
            labels: Optional labels for dimensionality
            description: Metric description
        """
        key = self._build_key(name, labels)
        
        # Convert labels to strings
        str_labels = {k: str(v) for k, v in (labels or {}).items()}
        
        with self._lock:
            if key in self._metrics:
                current = self._metrics[key]
                new_value = current.value + value
                self._metrics[key] = MetricRecord(
                    name=name,
                    metric_type=MetricType.COUNTER,
                    value=new_value,
                    labels=str_labels,
                    description=description or current.description,
                )
            else:
                self._descriptions[name] = description
                self._metrics[key] = MetricRecord(
                    name=name,
                    metric_type=MetricType.COUNTER,
                    value=value,
                    labels=str_labels,
                    description=description,
                )

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict] = None,
        description: str = "",
    ):
        """
        Set a gauge metric.
        
        Args:
            name: Metric name
            value: Current value
            labels: Optional labels
            description: Metric description
        """
        key = self._build_key(name, labels)
        str_labels = {k: str(v) for k, v in (labels or {}).items()}
        
        with self._lock:
            self._descriptions[name] = description
            self._metrics[key] = MetricRecord(
                name=name,
                metric_type=MetricType.GAUGE,
                value=value,
                labels=str_labels,
                description=description,
            )

    def observe(
        self,
        name: str,
        value: float,
        labels: Optional[Dict] = None,
        description: str = "",
    ):
        """
        Observe a value for histogram metric.
        
        Args:
            name: Metric name
            value: Observed value
            labels: Optional labels
            description: Metric description
        """
        key = self._build_key(name, labels)
        str_labels = {k: str(v) for k, v in (labels or {}).items()}
        
        with self._lock:
            self._descriptions[name] = description
            
            # Initialize histogram state if needed
            if key not in self._histogram_states:
                self._histogram_states[key] = HistogramState()
            
            state = self._histogram_states[key]
            state.count += 1
            state.sum += value
            state.min = min(state.min, value)
            state.max = max(state.max, value)
            
            # Calculate average
            avg = state.sum / state.count if state.count > 0 else 0.0
            
            self._metrics[key] = MetricRecord(
                name=name,
                metric_type=MetricType.HISTOGRAM,
                value=avg,
                labels=str_labels,
                description=description,
                count=state.count,
                sum=state.sum,
                min=state.min,
                max=state.max,
            )

    @contextmanager
    def timing(self, name: str, labels: Optional[Dict] = None, description: str = ""):
        """
        Context manager for timing operations.
        
        Args:
            name: Metric name
            labels: Optional labels
            description: Metric description
            
        Usage:
            with collector.timing("api_request_ms"):
                do_something()
        """
        start = time.time()
        try:
            yield
        finally:
            elapsed_ms = (time.time() - start) * 1000
            self.observe(name, elapsed_ms, labels, description)

    def get_metric(self, name: str, labels: Optional[Dict] = None) -> Optional[MetricRecord]:
        """
        Get a specific metric.
        
        Args:
            name: Metric name
            labels: Optional labels
            
        Returns:
            MetricRecord or None
        """
        key = self._build_key(name, labels)
        return self._metrics.get(key)

    def get_metrics(self) -> Dict[str, MetricRecord]:
        """
        Get all metrics (keyed by name for simplicity).
        
        Note: If there are multiple metrics with same name but different labels,
        only the last one will be returned. Use get_metric() with specific labels
        for precise retrieval.
        
        Returns:
            Dictionary of metric_name -> MetricRecord
        """
        with self._lock:
            # Return metrics keyed by name (simplified view)
            return {record.name: record for record in self._metrics.values()}

    def format_prometheus(self) -> str:
        """
        Format metrics in Prometheus exposition format.
        
        Returns:
            Prometheus-formatted string
        """
        lines = []
        
        with self._lock:
            for key, metric in sorted(self._metrics.items()):
                # Add HELP line
                if metric.description:
                    lines.append(f"# HELP {metric.name} {metric.description}")
                
                # Add TYPE line
                lines.append(f"# TYPE {metric.name} {metric.metric_type.value}")
                
                # Format labels
                label_str = ""
                if metric.labels:
                    label_parts = [f'{k}="{v}"' for k, v in sorted(metric.labels.items())]
                    label_str = "{" + ",".join(label_parts) + "}"
                
                # Add metric value
                if metric.metric_type == MetricType.HISTOGRAM:
                    lines.append(f"{metric.name}_count{label_str} {metric.count}")
                    lines.append(f"{metric.name}_sum{label_str} {metric.sum}")
                else:
                    lines.append(f"{metric.name}{label_str} {metric.value}")
        
        return "\n".join(lines) + "\n"

    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._metrics.clear()
            self._histogram_states.clear()
            self._descriptions.clear()
        logger.info("Metrics collector reset")

    def _build_key(self, name: str, labels: Optional[Dict] = None) -> str:
        """Build unique key from name and labels."""
        if not labels:
            return name
        
        # Sort labels for consistent keying
        label_parts = [f"{k}={v}" for k, v in sorted(labels.items())]
        return f"{name}:{','.join(label_parts)}"
