"""Port for pipeline telemetry — domain-to-host boundary.

The brain counts what it evaluates (bars decided, signals emitted) and knows
nothing about where those counts land. The host owns the sink: the backend
installs a Prometheus adapter at composition time, a test installs a recorder,
and a bare embedding (replay, script, another process) gets
:data:`NULL_TELEMETRY` and runs unchanged.

This port exists so quant never reaches into the host to find a counter. The
dependency points one way: an adapter imports this module, never the reverse.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ITelemetry(ABC):
    """Sink for pipeline activity counters.

    Implementations must be safe to call from the engine thread on every
    evaluated bar, must never raise, and must not block the decision path.
    """

    # Dict-free instances: a sink that is handed around (the shared no-op) has
    # nowhere to accumulate state. Implementations that need state declare
    # fields on their own class.
    __slots__ = ()

    @abstractmethod
    def record_tick(self) -> None:
        """Record one market tick handled by the engine's tick loop."""

    @abstractmethod
    def record_signal(self, direction: str) -> None:
        """Record one approved signal.

        ``direction``/``type`` is advisory — a sink that only keeps totals may
        ignore it; one that buckets per direction (LONG/SHORT) may not.
        """

    def record_decision(self, approved: bool) -> None:
        """Record one entry decision evaluation.

        Default is a no-op so existing sinks stay valid; the host adapter
        overrides this to move ``decisions_evaluated_total`` and the
        approved/blocked split. Not abstract — the port's abstract surface
        stays pinned to ``record_tick``/``record_signal``.
        """
        return None


class NullTelemetry(ITelemetry):
    """No-op sink used when the host installed nothing.

    Stateless and immutable, so one shared instance is enough and quant stays
    free of both a host import and a global mutable counter.
    """

    __slots__ = ()

    def record_tick(self) -> None:
        return None

    def record_signal(self, direction: str) -> None:
        return None


NULL_TELEMETRY = NullTelemetry()
