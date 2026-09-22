from __future__ import annotations

from dataclasses import dataclass

from quant.contracts.value_objects import AMTResult, FootprintCandle


def derive_stacked_imbalance(footprints: dict[str, FootprintCandle]) -> tuple[str, int, float, float]:
    if not footprints:
        return "", 0, 0.0, 0.0
    sorted_keys = sorted(footprints.keys(), reverse=True)
    # Forming candle first; fall back to most recently completed (matches context_builder).
    for key in sorted_keys[:2]:
        levels = footprints[key].levels
        best_dir, best_n, best_prices = "", 0, []
        run_dir, run_n, run_prices = "", 0, []
        for lvl in levels:
            if not lvl.stacked:
                run_dir, run_n, run_prices = "", 0, []
                continue
            d = "BUY" if lvl.ask > lvl.bid else "SELL"
            px = float(lvl.price)
            if d != run_dir:
                run_dir, run_n, run_prices = d, 1, [px]
            else:
                run_n += 1
                run_prices.append(px)
            if run_n > best_n:
                best_dir, best_n, best_prices = run_dir, run_n, list(run_prices)
        if best_n >= 3 and best_prices:
            return best_dir, best_n, min(best_prices), max(best_prices)
    return "", 0, 0.0, 0.0


@dataclass(frozen=True)
class AnalysisSnapshot:
    result: AMTResult
    asof_time: str
    stacked_imbalance_direction: str = ""
    stacked_imbalance_magnitude: int = 0
    stacked_imbalance_low: float = 0.0
    stacked_imbalance_high: float = 0.0


def analysis_snapshot_from_result(result: AMTResult, asof_time: str) -> AnalysisSnapshot:
    d, n, lo, hi = derive_stacked_imbalance(result.footprints or {})
    return AnalysisSnapshot(
        result=result,
        asof_time=asof_time,
        stacked_imbalance_direction=d,
        stacked_imbalance_magnitude=n,
        stacked_imbalance_low=lo,
        stacked_imbalance_high=hi,
    )
