"""Gate Rejection Tracker — observability for gate pipeline.

Tracks per-gate, per-symbol rejection counts so you can see exactly
which gate is killing signals. Without this, you tune blindly.

Key insight: If Gate 7 rejects 80% of BANKNIFTY but 30% of NIFTY,
BANKNIFTY has more first-drive noise and the threshold may need tuning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class GateStats:
    """Per-gate statistics."""

    total_evaluated: int = 0
    total_passed: int = 0
    total_rejected: int = 0

    @property
    def rejection_rate(self) -> float:
        if self.total_evaluated == 0:
            return 0.0
        return self.total_rejected / self.total_evaluated

    def to_dict(self) -> dict:
        return {
            "evaluated": self.total_evaluated,
            "passed": self.total_passed,
            "rejected": self.total_rejected,
            "rejection_rate": round(self.rejection_rate, 4),
        }


class GateRejectionTracker:
    """Tracks gate rejections per symbol, per gate.

    Zero cost when disabled (callers check enabled flag before recording).
    """

    def __init__(self) -> None:
        # symbol -> gate_name -> GateStats
        self._stats: dict[str, dict[str, GateStats]] = {}
        self._session_start: float = time.time()

    def record(
        self,
        symbol: str,
        gate_name: str,
        passed: bool,
    ) -> None:
        """Record a gate evaluation result."""
        if symbol not in self._stats:
            self._stats[symbol] = {}
        if gate_name not in self._stats[symbol]:
            self._stats[symbol][gate_name] = GateStats()

        gs = self._stats[symbol][gate_name]
        gs.total_evaluated += 1
        if passed:
            gs.total_passed += 1
        else:
            gs.total_rejected += 1

    def get_symbol_stats(self, symbol: str) -> dict[str, dict]:
        """Get all gate stats for a symbol."""
        gates = self._stats.get(symbol, {})
        return {name: gs.to_dict() for name, gs in gates.items()}

    def get_top_killers(self, symbol: str, n: int = 5) -> list[dict]:
        """Get top N gate killers by rejection count for a symbol."""
        gates = self._stats.get(symbol, {})
        sorted_gates = sorted(
            gates.items(),
            key=lambda x: x[1].total_rejected,
            reverse=True,
        )
        return [{"gate": name, **gs.to_dict()} for name, gs in sorted_gates[:n]]

    def get_all_stats(self) -> dict[str, dict[str, dict]]:
        """Get all stats for all symbols."""
        return {symbol: self.get_symbol_stats(symbol) for symbol in self._stats}

    def get_summary(self) -> dict:
        """Get summary stats across all symbols."""
        total_evaluated = 0
        total_rejected = 0
        symbol_summaries = {}

        for symbol, gates in self._stats.items():
            sym_eval = sum(gs.total_evaluated for gs in gates.values())
            sym_rej = sum(gs.total_rejected for gs in gates.values())
            total_evaluated += sym_eval
            total_rejected += sym_rej
            symbol_summaries[symbol] = {
                "evaluated": sym_eval,
                "rejected": sym_rej,
                "rejection_rate": round(sym_rej / sym_eval, 4) if sym_eval > 0 else 0,
                "top_killers": self.get_top_killers(symbol, 3),
            }

        return {
            "session_duration_seconds": round(time.time() - self._session_start),
            "total_evaluated": total_evaluated,
            "total_rejected": total_rejected,
            "overall_rejection_rate": round(total_rejected / total_evaluated, 4)
            if total_evaluated > 0
            else 0,
            "symbols": symbol_summaries,
        }

    def reset(self) -> None:
        """Reset all stats."""
        self._stats.clear()
        self._session_start = time.time()
