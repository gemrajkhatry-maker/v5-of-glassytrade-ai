"""Coordinator-backed metrics — per-engine activity from the runtime.

Phase 0.4 of the architecture refactor. The previous MetricsCollector was a
disconnected singleton that never received events from the coordinator —
/api/v1/metrics reported 0 ticks while WebSocket showed live market flow.

This module reads activity directly from the coordinator's engines:
- last_tick_received_at: wall clock of the most recent tick
- last_bar_closed_at: wall clock of the most recent bar close
- last_amt_update_at: wall clock of the most recent AMT update
- last_decision_at: wall clock of the most recent entry decision
- decision_count, approved_count, blocked_count: decision tallies
- open_position: whether the engine currently holds a position
- seed_status: history seed state (NOT_STARTED/SEEDING/READY/DEGRADED_*)
- data_age_seconds: seconds since last tick (staleness signal)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class EngineActivity:
    """Per-engine runtime activity snapshot."""
    symbol: str
    last_tick_received_at: float | None
    last_bar_closed_at: float | None
    last_amt_update_at: float | None
    last_decision_at: float | None
    decision_count: int
    approved_count: int
    blocked_count: int
    open_position: bool
    seed_status: str
    data_age_seconds: float | None


class CoordinatorMetricsProvider:
    """Reads runtime activity from the coordinator's engines.

    Replaces the disconnected MetricsCollector singleton. Each snapshot
    reflects the actual state of the running engines, not a separate
    counter that may have never been incremented.
    """

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of per-engine activity and aggregate totals."""
        engines: dict[str, dict[str, Any]] = {}
        now = time.time()
        total_decisions = 0
        total_approved = 0
        total_blocked = 0

        engine_map = getattr(self._coordinator, "engines", {}) or {}
        for symbol, engine in engine_map.items():
            ea = self._read_engine_activity(engine, symbol, now)
            engines[symbol] = asdict(ea)
            total_decisions += ea.decision_count
            total_approved += ea.approved_count
            total_blocked += ea.blocked_count

        return {
            "engines": engines,
            "totals": {
                "decision_count": total_decisions,
                "approved_count": total_approved,
                "blocked_count": total_blocked,
                "engine_count": len(engines),
            },
        }

    def _read_engine_activity(self, engine: Any, symbol: str, now: float) -> EngineActivity:
        """Read activity from a single engine, with defensive defaults."""
        last_tick = getattr(engine, "_last_tick", None)
        last_bar = getattr(engine, "_last_bar", None)
        last_amt = getattr(engine, "_last_amt", None)
        last_decision = getattr(engine, "_last_decision", None)

        decision_count = getattr(engine, "_decision_count", 0) or 0
        approved_count = getattr(engine, "_approved_count", 0) or 0
        blocked_count = getattr(engine, "_blocked_count", 0) or 0

        # Open position detection — check explicit attribute first,
        # then fall back to state.position (calling state() if needed).
        open_pos = getattr(engine, "_open_position", None)
        if open_pos is None:
            state = getattr(engine, "state", None)
            if callable(state):
                try:
                    state = state()
                except Exception:
                    state = None
            if state is not None:
                open_pos = getattr(state, "position", None)
        open_position = open_pos is not None

        seed_status = getattr(engine, "_seed_status", "UNKNOWN") or "UNKNOWN"
        data_age = (now - last_tick) if last_tick is not None else None

        return EngineActivity(
            symbol=symbol,
            last_tick_received_at=last_tick,
            last_bar_closed_at=last_bar,
            last_amt_update_at=last_amt,
            last_decision_at=last_decision,
            decision_count=decision_count,
            approved_count=approved_count,
            blocked_count=blocked_count,
            open_position=open_position,
            seed_status=seed_status,
            data_age_seconds=data_age,
        )


def coordinator_metrics_provider(coordinator: Any) -> CoordinatorMetricsProvider:
    """Convenience wrapper — build a provider for the given coordinator."""
    return CoordinatorMetricsProvider(coordinator)
