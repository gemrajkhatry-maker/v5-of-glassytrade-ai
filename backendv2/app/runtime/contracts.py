"""Runtime contracts shared by live and paper runtime modes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from app.runtime.pipeline.events import OrderRequest, OrderStatusEvent


class RuntimeMode(str, Enum):
    """Supported runtime composition modes."""

    LIVE = "live"
    PAPER = "paper"


class RuntimeHealth(str, Enum):
    """Operator-visible runtime health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"
    UNSAFE_TO_TRADE = "unsafe_to_trade"


class RuntimeSessionState(str, Enum):
    """Explicit lifecycle states for runtime sessions."""

    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class OrderLifecycleStatus(str, Enum):
    """Canonical order states accepted by the runtime."""

    SUBMITTED = "SUBMITTED"
    ACKED = "ACKED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderLifecycleStatus.FILLED.value,
        OrderLifecycleStatus.CANCELLED.value,
        OrderLifecycleStatus.REJECTED.value,
        OrderLifecycleStatus.EXPIRED.value,
    }
)


@runtime_checkable
class ExecutionPort(Protocol):
    """Order-submission boundary used by the deterministic runtime."""

    def submit_order(self, request: OrderRequest) -> OrderStatusEvent | list[OrderStatusEvent]:
        """Submit one order request and return explicit broker status events."""


@dataclass(frozen=True)
class ReadinessCheck:
    """A typed readiness result for preflight and health endpoints."""

    name: str
    status: RuntimeHealth
    reason: str = ""


@dataclass(frozen=True)
class RuntimeReadiness:
    """Aggregated readiness for runtime start decisions."""

    status: RuntimeHealth
    checks: tuple[ReadinessCheck, ...] = ()
    feed_present: bool = False
    feed_running: bool = False
    broker_bound: bool = False
    ticks_seen: int = 0
    first_tick_age_sec: float | None = None
    last_tick_age_sec: float | None = None
    last_feed_error: str = ""
    startup_ready: bool = False

    @property
    def safe_to_trade(self) -> bool:
        return self.status == RuntimeHealth.HEALTHY and self.startup_ready

