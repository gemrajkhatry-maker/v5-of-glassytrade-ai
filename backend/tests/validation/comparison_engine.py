"""Dual-Run Comparison Engine.

Run old vs new codepaths in parallel for N ticks and assert that
state snapshots are identical (or within tolerance).

Usage:
    comparer = DualRunComparer(tolerance=1e-9)
    
    for tick in simulate_10000_ticks():
        old_result = old_pipeline.process(tick)
        new_result = new_pipeline.process(tick)
        comparer.compare(old_result, new_result)
    
    # After all ticks:
    report = comparer.report()
    assert report["mismatches"] == 0, report["details"]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Mismatch:
    """A single state mismatch between old and new codepaths."""
    tick: int
    key: str
    old_value: Any
    new_value: Any
    symbol: str = ""
    tolerance: float = 0.0


@dataclass
class ComparisonReport:
    """Summary of a dual-run comparison."""
    total_ticks: int
    mismatches: int
    max_numeric_error: float = 0.0
    detail_keys: list[str] = field(default_factory=list)
    mismatches_list: list[Mismatch] = field(default_factory=list)


class DualRunComparer:
    """Compare old vs new codepaths tick by tick.

    Tracks both exact string/dict equality and numeric equality within
    tolerance (for floating-point differences in different execution orders).
    """

    def __init__(self, tolerance: float = 1e-9) -> None:
        self._tolerance = tolerance
        self._tick_count: int = 0
        self._mismatches: list[Mismatch] = []
        self._max_numeric_error: float = 0.0
        self._matched_keys: set[str] = set()

    def compare(
        self,
        old_state: dict,
        new_state: dict,
        tick: int | None = None,
        symbol: str = "",
    ) -> list[Mismatch]:
        """Compare two state dicts for a single tick.

        Returns list of mismatches found (empty if identical).
        """
        self._tick_count = tick if tick is not None else self._tick_count + 1
        current_mismatches: list[Mismatch] = []

        all_keys = set(old_state.keys()) | set(new_state.keys())
        for key in all_keys:
            self._matched_keys.add(key)
            old_val = old_state.get(key)
            new_val = new_state.get(key)

            if old_val == new_val:
                continue

            # Numeric comparison with tolerance
            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                error = abs(old_val - new_val)
                if error > self._tolerance:
                    self._max_numeric_error = max(self._max_numeric_error, error)
                    mm = Mismatch(
                        tick=self._tick_count,
                        key=key,
                        old_value=old_val,
                        new_value=new_val,
                        symbol=symbol,
                        tolerance=self._tolerance,
                    )
                    current_mismatches.append(mm)
                    self._mismatches.append(mm)
                continue

            # Dict/list comparison
            if isinstance(old_val, dict) and isinstance(new_val, dict):
                sub = self._compare_nested(old_val, new_val, key, self._tick_count, symbol)
                current_mismatches.extend(sub)
                self._mismatches.extend(sub)
                continue

            # Deep mismatch
            mm = Mismatch(
                tick=self._tick_count,
                key=key,
                old_value=old_val,
                new_value=new_val,
                symbol=symbol,
            )
            current_mismatches.append(mm)
            self._mismatches.append(mm)

        return current_mismatches

    def _compare_nested(
        self,
        old_val: dict,
        new_val: dict,
        parent_key: str,
        tick: int,
        symbol: str,
    ) -> list[Mismatch]:
        """Recursively compare nested dicts."""
        mismatches: list[Mismatch] = []
        all_keys = set(old_val.keys()) | set(new_val.keys())
        for key in all_keys:
            full_key = f"{parent_key}.{key}"
            ov = old_val.get(key)
            nv = new_val.get(key)

            if ov == nv:
                continue

            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):
                error = abs(ov - nv)
                if error > self._tolerance:
                    self._max_numeric_error = max(self._max_numeric_error, error)
                    mismatches.append(Mismatch(
                        tick=tick, key=full_key, old_value=ov,
                        new_value=nv, symbol=symbol, tolerance=self._tolerance,
                    ))
                continue

            if isinstance(ov, dict) and isinstance(nv, dict):
                sub = self._compare_nested(ov, nv, full_key, tick, symbol)
                mismatches.extend(sub)
                continue

            mismatches.append(Mismatch(
                tick=tick, key=full_key, old_value=ov, new_value=nv, symbol=symbol,
            ))

        return mismatches

    def report(self) -> ComparisonReport:
        """Generate a comparison report."""
        detail_keys = list(set(m.key for m in self._mismatches))
        return ComparisonReport(
            total_ticks=self._tick_count,
            mismatches=len(self._mismatches),
            max_numeric_error=self._max_numeric_error,
            detail_keys=detail_keys,
            mismatches_list=self._mismatches[-50:],  # Last 50 mismatches
        )

    def is_clean(self) -> bool:
        """Return True if no mismatches found."""
        return len(self._mismatches) == 0

    def summary(self) -> str:
        """Human-readable summary."""
        r = self.report()
        lines = [
            "Dual-Run Comparison Report",
            "==========================",
            f"Ticks compared:  {r.total_ticks}",
            f"Mismatches:      {r.mismatches}",
            f"Max numeric err: {r.max_numeric_error:.6e}",
            f"Keys compared:   {sorted(self._matched_keys)}",
        ]
        if r.mismatches > 0:
            lines.append("")
            lines.append("Last 10 mismatches:")
            for m in r.mismatches_list[-10:]:
                lines.append(f"  tick={m.tick} key={m.key} "
                           f"old={m.old_value} new={m.new_value}")
        return "\n".join(lines)
