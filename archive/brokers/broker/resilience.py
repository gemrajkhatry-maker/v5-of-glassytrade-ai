"""
Shared resilience primitives for the brokers package.

Re-exports the canonical `CircuitState` enum and `CircuitBreakerConfig`
dataclass from `broker.ports` so existing imports continue to work.
"""

from shared.resilience import CircuitState
from brokers.broker.ports import CircuitBreakerConfig  # noqa: F401

__all__ = ["CircuitState", "CircuitBreakerConfig"]
