"""Gate rejection tracking for signal gating observability."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GateStats:
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
    """Tracks gate pass/fail counts per symbol and gate name."""

    def __init__(self) -> None:
        self._stats: dict[str, dict[str, GateStats]] = {}
        self._total_rejections = 0

    def record(self, symbol: str, gate_name: str, passed: bool) -> None:
        symbol_stats = self._stats.setdefault(symbol, {})
        gate_stats = symbol_stats.setdefault(gate_name, GateStats())

        gate_stats.total_evaluated += 1
        if passed:
            gate_stats.total_passed += 1
        else:
            gate_stats.total_rejected += 1
            self._total_rejections += 1

    def get_symbol_stats(self, symbol: str) -> dict[str, dict]:
        return {
            name: stats.to_dict()
            for name, stats in self._stats.get(symbol, {}).items()
        }

    def get_top_killers(self, symbol: str, n: int = 5) -> list[dict]:
        gates = self._stats.get(symbol, {})
        return [
            {"gate": name, **stats.to_dict()}
            for name, stats in sorted(
                gates.items(), key=lambda item: item[1].total_rejected, reverse=True
            )[:n]
        ]

    def get_all_stats(self) -> dict[str, dict[str, dict]]:
        return {symbol: self.get_symbol_stats(symbol) for symbol in self._stats}

    def get_summary(self) -> dict:
        total_evaluated = sum(
            gs.total_evaluated for gates in self._stats.values() for gs in gates.values()
        )
        symbols = {}
        for symbol, gates in self._stats.items():
            sym_evaluated = sum(gs.total_evaluated for gs in gates.values())
            sym_rejected = sum(gs.total_rejected for gs in gates.values())
            symbols[symbol] = {
                "evaluated": sym_evaluated,
                "rejected": sym_rejected,
                "rejection_rate": round(sym_rejected / sym_evaluated, 4)
                if sym_evaluated
                else 0.0,
                "top_killers": self.get_top_killers(symbol, n=3),
            }

        return {
            "total_evaluated": total_evaluated,
            "total_rejected": self._total_rejections,
            "overall_rejection_rate": round(self._total_rejections / total_evaluated, 4)
            if total_evaluated
            else 0.0,
            "symbols": symbols,
        }

    def reset(self) -> None:
        self._stats.clear()
        self._total_rejections = 0

