"""Gate Rejection Tracker — tracks and analyzes gate rejections.

Provides:
- Total evaluated vs rejected counts
- Per-gate rejection breakdown
- Overall rejection rate
- Per-symbol breakdown
- Trend analysis (increasing/decreasing rejections)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class GateRejectionStats:
    session_duration_seconds: float
    total_evaluated: int
    total_rejected: int
    overall_rejection_rate: float
    by_gate: dict[str, int]
    by_symbol: dict[str, dict]
    recent_trend: str  # "INCREASING" | "DECREASING" | "STABLE"


class GateRejectionTracker:
    """Tracks gate rejection patterns."""

    def __init__(self, recent_window: int = 20):
        self._total_evaluated = 0
        self._total_rejected = 0
        self._by_gate: dict[str, int] = defaultdict(int)
        self._by_symbol: dict[str, dict] = defaultdict(lambda: {
            "evaluated": 0, "rejected": 0, "gates": defaultdict(int),
        })
        self._recent_results: list[bool] = []  # True = rejected
        self._recent_window = recent_window
        self._session_start: float = 0.0

    def record_evaluation(self, symbol: str) -> None:
        """Record that a signal was evaluated."""
        self._total_evaluated += 1
        self._by_symbol[symbol]["evaluated"] += 1
        if self._session_start == 0:
            import time
            self._session_start = time.time()

    def record_rejection(
        self, symbol: str, gate_name: str, reason: str = ""
    ) -> None:
        """Record a gate rejection."""
        self._total_rejected += 1
        self._by_gate[gate_name] += 1
        self._by_symbol[symbol]["rejected"] += 1
        self._by_symbol[symbol]["gates"][gate_name] += 1
        self._recent_results.append(True)
        if len(self._recent_results) > self._recent_window:
            self._recent_results.pop(0)

    def record_pass(self, symbol: str) -> None:
        """Record a signal that passed all gates."""
        self._recent_results.append(False)
        if len(self._recent_results) > self._recent_window:
            self._recent_results.pop(0)

    def get_stats(self) -> GateRejectionStats:
        """Get full rejection statistics."""
        import time
        duration = time.time() - self._session_start if self._session_start > 0 else 0

        rate = self._total_rejected / self._total_evaluated if self._total_evaluated > 0 else 0

        # Recent trend
        if len(self._recent_results) < 5:
            trend = "STABLE"
        else:
            first_half = sum(self._recent_results[:len(self._recent_results)//2])
            second_half = sum(self._recent_results[len(self._recent_results)//2:])
            if second_half > first_half * 1.3:
                trend = "INCREASING"
            elif second_half < first_half * 0.7:
                trend = "DECREASING"
            else:
                trend = "STABLE"

        # Per-symbol summary
        by_symbol = {
            sym: {
                "evaluated": data["evaluated"],
                "rejected": data["rejected"],
                "rate": round(data["rejected"] / data["evaluated"], 3) if data["evaluated"] > 0 else 0,
                "top_gates": dict(dict(data["gates"]).most_common(3) if hasattr(data["gates"], 'most_common') else dict(list(data["gates"].items())[:3])),
            }
            for sym, data in self._by_symbol.items()
        }

        return GateRejectionStats(
            session_duration_seconds=round(duration, 1),
            total_evaluated=self._total_evaluated,
            total_rejected=self._total_rejected,
            overall_rejection_rate=round(rate, 3),
            by_gate=dict(self._by_gate),
            by_symbol=by_symbol,
            recent_trend=trend,
        )

    def reset(self) -> None:
        import time
        self._total_evaluated = 0
        self._total_rejected = 0
        self._by_gate.clear()
        self._by_symbol.clear()
        self._recent_results.clear()
        self._session_start = time.time()
