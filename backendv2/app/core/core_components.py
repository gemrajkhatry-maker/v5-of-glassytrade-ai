"""Core infrastructure components for backendv2."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
import asyncio
import time


# ---------------------------------------------------------------------------
# Circuit Breaker - Risk Management
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    timeout_seconds: float = 300.0
    success_threshold: int = 3


class CircuitBreaker:
    """Adaptive circuit breaker for trading risk management."""
    
    def __init__(self, config: CircuitBreakerConfig | None = None):
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
    
    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self._last_failure_time > self._config.timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
        return self._state
    
    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN
    
    def record_success(self):
        """Record a successful call."""
        self._failure_count = 0
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._success_count = 0
    
    def record_failure(self):
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
    
    def __call__(self, func):
        """Decorator for circuit breaker."""
        async def wrapper(*args, **kwargs):
            if self.is_open:
                raise RuntimeError("Circuit breaker is OPEN")
            try:
                result = await func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise
        return wrapper


# ---------------------------------------------------------------------------
# Event Store
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    event_type: str
    timestamp: float
    data: Dict[str, Any]


class EventStore:
    """In-memory immutable event timeline for diagnostics and audits."""
    
    def __init__(self):
        self._events: List[Event] = []
    
    def append(self, event: Event) -> None:
        self._events.append(event)
    
    def get_events(self, event_type: str | None = None) -> List[Event]:
        if event_type:
            return [e for e in self._events if e.event_type == event_type]
        return self._events.copy()
    
    def read_all(self) -> List[Event]:
        """Read all recorded events."""
        return self._events.copy()

    def snapshot(self) -> List[Event]:
        """Alias for read-only timeline snapshots."""
        return self._events.copy()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """Simple metrics registry for counters, gauges, histograms."""
    
    def __init__(self):
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
    
    def counter(self, name: str, value: float = 1.0) -> None:
        self._counters[name] = self._counters.get(name, 0) + value
    
    def gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value
    
    def histogram(self, name: str, value: float) -> None:
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)
    
    def get_counter(self, name: str) -> float:
        return self._counters.get(name, 0)
    
    def snapshot(self) -> Dict[str, Any]:
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {k: len(v) for k, v in self._histograms.items()}
        }


# ---------------------------------------------------------------------------
# Feature Flags
# ---------------------------------------------------------------------------

class Feature(str, Enum):
    TRADING_ENABLED = "trading_enabled"
    PAPER_TRADING = "paper_trading"
    RISK_MANAGEMENT = "risk_management"
    AI_ANALYSIS = "ai_analysis"


@dataclass
class FeatureFlags:
    features: Dict[Feature, bool] = field(default_factory=dict)
    
    def is_enabled(self, feature: Feature) -> bool:
        return self.features.get(feature, False)
    
    def enable(self, feature: Feature) -> None:
        self.features[feature] = True
    
    def disable(self, feature: Feature) -> None:
        self.features[feature] = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RiskConfig:
    max_position_size: float = 1000.0
    daily_loss_limit: float = 500.0
    max_drawdown: float = 0.1
    halt_on_losses: int = 5


@dataclass
class SystemConfig:
    symbol: str = "BTCUSDT"
    timeframe: str = "1m"
    risk: RiskConfig = field(default_factory=RiskConfig)
    features: FeatureFlags = field(default_factory=FeatureFlags)


# Global instances
_metrics = MetricsRegistry()
_circuit_breaker = CircuitBreaker()
_event_store = EventStore()
_config = SystemConfig()