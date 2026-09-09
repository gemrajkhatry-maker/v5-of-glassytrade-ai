"""TimesFM 3.0 Model-Driven Dynamic Position Sizing.

Replaces hardcoded static rules (rigid 0.5% risk, arbitrary Mon/Fri 50% cuts,
static expiry cuts, and fixed tier thresholds) with continuous mathematical
formulations derived directly from Google TimesFM 3.0 probabilistic quantile paths:

1. Continuous Fractional Kelly Criterion (f*):
   - Win probability (p) estimated from TimesFM quantile distribution crossing target vs stop.
   - Payoff ratio (b) = (p50_peak - entry) / (entry - VaR_stop).
   - Dampened by safety half/quarter Kelly multiplier (kappa).

2. Quantile Dispersion Uncertainty Scaling (M_uncertainty):
   - Replaces arbitrary Monday/Friday/Expiry calendar discounts.
   - Measures normalized forecast cone width Delta Q = mean(p90 - p10) / curr_price.
   - Scales inversely with forecast dispersion: tight cone -> size up, wide cone -> size down.

3. Velocity & Theta-Decay Awareness (M_velocity):
   - Evaluates expected horizon to peak (tau* = argmax p50).
   - Fast impulsive moves (tau* <= 6 bars) preserve full size.
   - Slow grinding moves (tau* >= 20 bars) are downsized to prevent option theta decay.

4. Dynamic Value-at-Risk (VaR) Stop:
   - Sets structural stop loss to min(p10) over early forecast horizon.
   - Statistical invalidation: if price breaches the 10th percentile, model thesis is broken.

5. Immutable Safety Bounding Box:
   - Clamps final risk to strict min/max floor and ceiling (e.g. 0.15% min, 1.0% max in standard mode).
   - Snaps to exact exchange lot sizes and verifies rupee risk affordance.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np

from quant.decision.timesfm_agents import TimesFMForecast

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DynamicSizingResult:
    """Telemetry and execution values from TimesFM dynamic sizing."""
    quantity: float
    lots: int
    risk_pct: float
    risk_amount: float
    var_stop: float
    target_price: float
    payoff_ratio: float
    win_prob: float
    kelly_fraction: float
    dispersion_multiplier: float
    velocity_multiplier: float
    expected_peak_step: int
    rationale: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class TimesFMPositionSizer:
    """Calculates position size using TimesFM probabilistic forecasts."""

    def __init__(
        self,
        base_kelly_fraction: float = 0.35,     # Quarter-to-half Kelly safety dampener
        min_risk_pct: float = 0.0015,          # 0.15% minimum risk floor
        max_risk_pct: float = 0.0100,          # 1.00% maximum standard risk ceiling
        aggressive_max_risk_pct: float = 0.05, # 5.00% aggressive mode ceiling
        baseline_dispersion: float = 0.0035,   # Typical normalized quantile spread (0.35%)
    ) -> None:
        self.base_kelly_fraction = base_kelly_fraction
        self.min_risk_pct = min_risk_pct
        self.max_risk_pct = max_risk_pct
        self.aggressive_max_risk_pct = aggressive_max_risk_pct
        self.baseline_dispersion = baseline_dispersion

    def calculate_var_stop(
        self,
        entry: float,
        side: str,
        forecast: TimesFMForecast,
        tick_size: float = 0.05,
        lookahead_bars: int = 5,
    ) -> float:
        """Compute dynamic 90% VaR structural stop from TimesFM quantile envelope."""
        bars = min(lookahead_bars, len(forecast.p10_path))
        if side.upper() == "LONG":
            min_p10 = float(np.min(forecast.p10_path[:bars]))
            stop = min(entry - tick_size, min_p10 - tick_size)
            # Guarantee minimum 1-tick stop distance
            return round(min(stop, entry - tick_size), 2)
        else:
            max_p90 = float(np.max(forecast.p90_path[:bars]))
            stop = max(entry + tick_size, max_p90 + tick_size)
            return round(max(stop, entry + tick_size), 2)

    def calculate_expected_target(
        self,
        entry: float,
        side: str,
        forecast: TimesFMForecast,
        structural_target: Optional[float] = None,
        var_stop: Optional[float] = None,
        min_rr: float = 1.5,
    ) -> tuple[float, int]:
        """Find target price considering Fabio AMT structural levels and minimum R:R."""
        p50 = forecast.p50_path
        loss_dist = abs(entry - var_stop) if (var_stop is not None and var_stop > 0) else max(float(forecast.q_spread * 0.5), entry * 0.005)
        min_target_dist = max(loss_dist * min_rr, float(forecast.q_spread * 0.5), entry * 0.002)

        if side.upper() == "LONG":
            idx = int(np.argmax(p50))
            fc_target = float(p50[idx])
            # If a structural target (POC / Prior POC / NPOC / VAH) is provided and valid:
            if structural_target is not None and structural_target > entry:
                if abs(structural_target - entry) / entry <= 0.20:
                    if (structural_target - entry) >= min_target_dist * 0.8:
                        return round(structural_target, 2), idx + 1
            # Fallback: ensure target expands to at least min_rr or forecast expansion
            target = max(fc_target, entry + min_target_dist)
        else:
            idx = int(np.argmin(p50))
            fc_target = float(p50[idx])
            # If a structural target (POC / Prior POC / NPOC / VAL) is provided and valid:
            if structural_target is not None and 0 < structural_target < entry:
                if abs(entry - structural_target) / entry <= 0.20:
                    if (entry - structural_target) >= min_target_dist * 0.8:
                        return round(structural_target, 2), idx + 1
            # Fallback: ensure target expands to at least min_rr or forecast expansion
            target = min(fc_target, entry - min_target_dist)

        return round(target, 2), idx + 1

    def compute_size(
        self,
        equity: float,
        entry: float,
        side: str,
        forecast: TimesFMForecast,
        lot_size: float = 1.0,
        override_sl: Optional[float] = None,
        override_tp: Optional[float] = None,
        is_aggressive: bool = False,
        max_lots: Optional[int] = None,
        max_rupee_risk_cap: Optional[float] = None,
    ) -> DynamicSizingResult:
        """Compute dynamic position size using continuous TimesFM distribution.
        
        Guarantees:
        - Never returns negative quantity or NaN.
        - Strictly respects safety bounds [min_risk_pct, max_risk_pct].
        - Snaps to exact lot_size.
        """
        if equity <= 0 or entry <= 0:
            return self._zero_result("Invalid equity or entry price")

        # 1. Dynamic VaR Stop and Expected Target
        var_stop = override_sl if (override_sl is not None and override_sl > 0) else self.calculate_var_stop(entry, side, forecast)
        loss_distance = abs(entry - var_stop)
        if loss_distance <= 1e-4:
            return self._zero_result(f"Zero loss distance: entry={entry}, stop={var_stop}")

        target_price, tau_star = self.calculate_expected_target(
            entry, side, forecast, structural_target=override_tp, var_stop=var_stop
        )
        gain_distance = abs(target_price - entry)

        # 2. Payoff Ratio (b)
        b = max(gain_distance / loss_distance, 0.1)

        # 3. Model-Implied Probability of Profit (p)
        # In scalping, probability of profit reflects expected favorable trajectory expansion toward target
        sigma = max(float(forecast.q_spread) / 2.563, entry * 0.001)
        target_drift = float(target_price - entry) if side.upper() == "LONG" else float(entry - target_price)
        terminal_drift = float(forecast.p50_path[-1] - entry) if side.upper() == "LONG" else float(entry - forecast.p50_path[-1])
        favorable_drift = max(target_drift, terminal_drift, 0.0)
        z_score = favorable_drift / sigma
        # Standard normal CDF approximation (Abramowitz and Stegun)
        win_prob = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
        # Clamp win_prob to realistic quantitative limits [0.25, 0.85]
        win_prob = min(max(win_prob, 0.25), 0.85)

        # 4. Continuous Kelly Criterion (f*)
        # f* = (p * b - (1 - p)) / b
        raw_kelly = (win_prob * b - (1.0 - win_prob)) / b
        kelly_fraction = max(0.0, raw_kelly) * self.base_kelly_fraction

        # 5. Quantile Dispersion Uncertainty Multiplier (M_uncertainty)
        # Normalized spread: Delta Q = q_spread / entry
        norm_spread = max(float(forecast.q_spread) / entry, 1e-5)
        # Ratio of baseline uncertainty to current uncertainty
        dispersion_ratio = self.baseline_dispersion / norm_spread
        dispersion_multiplier = float(np.clip(math.sqrt(dispersion_ratio), 0.35, 1.40))

        # 6. Velocity / Horizon Efficiency Multiplier (M_velocity)
        # Horizon H = len(p50)
        h = max(len(forecast.p50_path), 1)
        horizon_fraction = min(tau_star / h, 1.0)
        # Faster expansion gets bonus, slow grinding move gets penalty
        velocity_multiplier = float(np.clip(1.15 - (0.65 * horizon_fraction), 0.40, 1.20))

        # 7. Synthesize Risk Percentage
        ceiling = self.aggressive_max_risk_pct if is_aggressive else self.max_risk_pct
        effective_risk_pct = kelly_fraction * dispersion_multiplier * velocity_multiplier
        if is_aggressive:
            # Fabio high-conviction cushion / momentum day mode: deploy aggressive risk
            effective_risk_pct = max(effective_risk_pct, ceiling * 0.6)
        elif kelly_fraction <= 0.01:
            # Fallback to minimum base risk if Kelly is flat
            effective_risk_pct = self.min_risk_pct

        # Apply Safety Bounding Box
        final_risk_pct = float(np.clip(effective_risk_pct, self.min_risk_pct, ceiling))
        risk_budget = equity * final_risk_pct

        if max_rupee_risk_cap is not None and max_rupee_risk_cap > 0:
            risk_budget = min(risk_budget, max_rupee_risk_cap)

        # 8. Lot Snapping & Sizing
        if lot_size and lot_size > 1.0:
            loss_per_lot = loss_distance * lot_size
            lots = int(risk_budget // loss_per_lot) if loss_per_lot > 0 else 0
            # If budget affords 0 lots but is close (>= 75% of 1 lot risk), afford 1 lot if under ceiling
            if lots == 0 and loss_per_lot > 0 and risk_budget >= (loss_per_lot * 0.75):
                if loss_per_lot <= (equity * ceiling):
                    lots = 1
            # Capital deployment cap: notional value must not exceed 2.5x equity leverage
            if entry > 0:
                notional_per_lot = entry * lot_size
                max_dep_lots = max(1, int((equity * 2.5) // notional_per_lot)) if notional_per_lot <= (equity * 3.0) else 0
                lots = min(lots, max_dep_lots)
            if max_lots is not None and max_lots > 0:
                lots = min(lots, max_lots)
            quantity = float(lots * lot_size)
            actual_risk = loss_per_lot * lots
        else:
            quantity = risk_budget / loss_distance
            lots = int(math.floor(quantity))
            if max_lots is not None and max_lots > 0:
                quantity = min(quantity, float(max_lots))
            actual_risk = loss_distance * quantity

        rationale = (
            f"TimesFM Sizing: p={win_prob:.1%}, b={b:.2f}, Kelly={kelly_fraction:.2%}, "
            f"Dispersion={dispersion_multiplier:.2f}x, Velocity={velocity_multiplier:.2f}x (tau*={tau_star}) "
            f"-> Risk {final_risk_pct:.2%} (Rs {actual_risk:.1f}) => {lots} lots ({quantity:.0f} qty)"
        )

        return DynamicSizingResult(
            quantity=quantity,
            lots=lots,
            risk_pct=round(final_risk_pct, 4),
            risk_amount=round(actual_risk, 2),
            var_stop=var_stop,
            target_price=target_price,
            payoff_ratio=round(b, 2),
            win_prob=round(win_prob, 3),
            kelly_fraction=round(kelly_fraction, 4),
            dispersion_multiplier=round(dispersion_multiplier, 3),
            velocity_multiplier=round(velocity_multiplier, 3),
            expected_peak_step=tau_star,
            rationale=rationale,
            metadata={
                "sigma": round(sigma, 2),
                "norm_spread": round(norm_spread, 5),
                "tau_star": tau_star,
                "loss_distance": round(loss_distance, 2),
                "gain_distance": round(gain_distance, 2),
            },
        )

    def _zero_result(self, reason: str) -> DynamicSizingResult:
        return DynamicSizingResult(
            quantity=0.0,
            lots=0,
            risk_pct=0.0,
            risk_amount=0.0,
            var_stop=0.0,
            target_price=0.0,
            payoff_ratio=0.0,
            win_prob=0.0,
            kelly_fraction=0.0,
            dispersion_multiplier=1.0,
            velocity_multiplier=1.0,
            expected_peak_step=0,
            rationale=f"Zero sizing: {reason}",
            metadata={"error": reason},
        )
