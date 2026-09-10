"""TimesFM 3.0 Model-Driven Risk Authority & Dynamic Exit Engine.

Replaces hardcoded static risk rules:
1. Replaces rigid 0.8R breakeven threshold and 20% giveback with rolling monotonic
   quantile trailing stops (p10 for LONG, p90 for SHORT).
2. Replaces rigid 30-bar time-stops with trajectory peak (tau*) velocity decay exits.
3. Replaces static 3-loss / 6-trade daily halts with continuous forecast error tracking
   (Brier / RMSE calibration) to throttle risk when market regime becomes unmodelable.
"""

from __future__ import annotations

import collections
import logging
import math
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

import numpy as np

from quant.decision.timesfm_agents import TimesFMForecast

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelExitEvaluation:
    """Outcome of model-driven exit evaluation."""
    should_exit: bool
    reason: str              # "" | "VAR_STOP" | "TARGET_PEAK" | "TRAJECTORY_INFLECTION" | "VELOCITY_DECAY"
    action: str              # "HOLD" | "EXIT" | "TAKE_PROFIT" | "TIGHTEN_SL"
    new_stop: Optional[float]
    rationale: str
    is_risk_free: bool


class TimesFMRiskAuthority:
    """Dynamic risk, trailing stop, and exit authority driven by TimesFM forecasts."""

    def __init__(
        self,
        lookback_calibration_window: int = 20,
        rmse_degradation_threshold: float = 0.015,  # 1.5% normalized price error
    ) -> None:
        # Rolling trailing stops keyed by position ID (UUID)
        self._trail_stops: Dict[str, float] = {}
        # Monotonic breakeven tracker keyed by position ID
        self._is_risk_free: Dict[str, bool] = {}
        # Forecast accuracy tracking: (predicted, actual)
        self._forecast_errors: Deque[float] = collections.deque(maxlen=lookback_calibration_window)
        self._directional_hits: Deque[int] = collections.deque(maxlen=lookback_calibration_window)
        self.rmse_degradation_threshold = rmse_degradation_threshold

    def clear_position(self, position_id: str) -> None:
        """Clean up tracking state when a position is closed."""
        self._trail_stops.pop(position_id, None)
        self._is_risk_free.pop(position_id, None)

    def update_trailing_stop(
        self,
        position_id: str,
        side: str,
        entry: float,
        current_sl: float,
        forecast: TimesFMForecast,
        tick_size: float = 0.05,
    ) -> Tuple[float, bool]:
        """Compute monotonic quantile trailing stop.
        
        Returns:
            (updated_stop, is_risk_free)
        """
        is_long = side.upper() == "LONG"
        prior_stop = self._trail_stops.get(position_id, current_sl)

        if is_long:
            # For LONG: ratchet along lower p10 quantile path
            candidate = float(forecast.p10_path[0]) - tick_size
            new_stop = max(prior_stop, candidate)
            # Monotonic ratchet: cannot loosen stop
            new_stop = max(new_stop, current_sl)
            risk_free = new_stop >= entry
        else:
            # For SHORT: ratchet along upper p90 quantile path
            candidate = float(forecast.p90_path[0]) + tick_size
            new_stop = min(prior_stop, candidate) if prior_stop > 0 else candidate
            # Monotonic ratchet: cannot loosen stop
            if current_sl > 0:
                new_stop = min(new_stop, current_sl)
            risk_free = new_stop <= entry and new_stop > 0

        self._trail_stops[position_id] = round(new_stop, 2)
        if risk_free:
            self._is_risk_free[position_id] = True

        return self._trail_stops[position_id], bool(self._is_risk_free.get(position_id, False))

    def evaluate_exit(
        self,
        position_id: str,
        side: str,
        entry: float,
        current_price: float,
        bars_held: int,
        forecast: TimesFMForecast,
        active_sl: float,
        tick_size: float = 0.05,
    ) -> ModelExitEvaluation:
        """Evaluate position state using continuous TimesFM trajectory."""
        is_long = side.upper() == "LONG"
        dyn_stop, is_risk_free = self.update_trailing_stop(
            position_id, side, entry, active_sl, forecast, tick_size=tick_size
        )

        # 1. Hard Dynamic VaR Stop breached
        if is_long and current_price <= dyn_stop:
            self.record_forecast_outcome(
                float(forecast.p50_path[-1]), float(current_price), float(entry))
            return ModelExitEvaluation(
                should_exit=True,
                reason="VAR_STOP",
                action="EXIT",
                new_stop=dyn_stop,
                rationale=f"Long breached dynamic VaR stop at {dyn_stop:.2f}",
                is_risk_free=is_risk_free,
            )
        elif (not is_long) and current_price >= dyn_stop and dyn_stop > 0:
            self.record_forecast_outcome(
                float(forecast.p50_path[-1]), float(current_price), float(entry))
            return ModelExitEvaluation(
                should_exit=True,
                reason="VAR_STOP",
                action="EXIT",
                new_stop=dyn_stop,
                rationale=f"Short breached dynamic VaR stop at {dyn_stop:.2f}",
                is_risk_free=is_risk_free,
            )

        # 2. Trajectory Apex & Inflection Detection
        p50 = forecast.p50_path
        h = len(p50)
        profit = (current_price - entry) if is_long else (entry - current_price)
        loss_dist = abs(entry - active_sl) if active_sl > 0 else (entry * 0.005)
        rr_achieved = profit / max(loss_dist, 1e-4)

        if is_long:
            tau_star = int(np.argmax(p50))
            # If trajectory already crested and terminal forecast slopes down sharply
            inflection = (tau_star < 8) and (p50[-1] < p50[tau_star] - (forecast.q_spread * 0.25))
        else:
            tau_star = int(np.argmin(p50))
            inflection = (tau_star < 8) and (p50[-1] > p50[tau_star] + (forecast.q_spread * 0.25))

        if rr_achieved >= 1.5 and inflection:
            self.record_forecast_outcome(
                float(forecast.p50_path[-1]), float(current_price), float(entry))
            return ModelExitEvaluation(
                should_exit=True,
                reason="TRAJECTORY_INFLECTION",
                action="TAKE_PROFIT",
                new_stop=dyn_stop,
                rationale=(
                    f"TimesFM 32-step trajectory crested at step {tau_star} and inflects; "
                    f"taking profit at {current_price:.2f} (+{profit:.1f} pts, {rr_achieved:.1f}R)"
                ),
                is_risk_free=is_risk_free,
            )
        elif rr_achieved >= 0.8 and inflection:
            # Fabio BE & Trailing: ratchet stop to lock in breakeven instead of premature full exit
            return ModelExitEvaluation(
                should_exit=False,
                reason="",
                action="TIGHTEN_SL",
                new_stop=entry,
                rationale=(
                    f"TimesFM inflection detected at step {tau_star}; tightening stop to breakeven "
                    f"at {entry:.2f} to protect runner toward structural target"
                ),
                is_risk_free=True,
            )

        # 3. Model Velocity Decay / Stagnation Stop
        # In Fabio AMT scalping, positions need time to work to the structural POC (15-45 mins).
        # Only exit for stagnation after at least 20 bars if completely dead.
        if bars_held >= max(tau_star + 5, 20) and rr_achieved < 0.2 and abs(forecast.pct_change) < 0.0002:
            self.record_forecast_outcome(
                float(forecast.p50_path[-1]), float(current_price), float(entry))
            return ModelExitEvaluation(
                should_exit=True,
                reason="VELOCITY_DECAY",
                action="EXIT",
                new_stop=dyn_stop,
                rationale=(
                    f"TimesFM velocity decay: Auction stagnant after {bars_held} bars (past tau*={tau_star}); "
                    f"exiting flat to prevent capital lockup."
                ),
                is_risk_free=is_risk_free,
            )

        # 4. Stop tightened to breakeven or beyond
        if dyn_stop != active_sl and (
            (is_long and dyn_stop > active_sl) or ((not is_long) and dyn_stop < active_sl)
        ):
            return ModelExitEvaluation(
                should_exit=False,
                reason="",
                action="TIGHTEN_SL",
                new_stop=dyn_stop,
                rationale=f"Monotonic quantile trailing stop ratcheted to {dyn_stop:.2f}",
                is_risk_free=is_risk_free,
            )

        return ModelExitEvaluation(
            should_exit=False,
            reason="",
            action="HOLD",
            new_stop=dyn_stop,
            rationale=f"Trend intact along TimesFM quantile path; holding ({bars_held} bars held)",
            is_risk_free=is_risk_free,
        )

    def record_forecast_outcome(self, predicted_p50_terminal: float, actual_price: float, initial_price: float) -> None:
        """Record model accuracy for continuous risk budget calibration."""
        if initial_price <= 0:
            return
        rel_error = abs(predicted_p50_terminal - actual_price) / initial_price
        self._forecast_errors.append(rel_error)

        pred_dir = 1 if predicted_p50_terminal >= initial_price else -1
        actual_dir = 1 if actual_price >= initial_price else -1
        self._directional_hits.append(1 if pred_dir == actual_dir else 0)

    def get_session_budget_multiplier(self) -> float:
        """Dynamic session capital throttling based on forecast calibration.
        
        When TimesFM predictions are highly calibrated, allow 1.0x - 1.2x normal budget.
        When forecast error surges (regime breakdown or news chop), throttle down to 0.4x.
        """
        if len(self._forecast_errors) < 5:
            return 1.0

        mean_error = float(np.mean(self._forecast_errors))
        dir_accuracy = float(np.mean(self._directional_hits))

        # Error penalty: if error exceeds threshold, scale down
        if mean_error > self.rmse_degradation_threshold:
            penalty = (mean_error - self.rmse_degradation_threshold) / self.rmse_degradation_threshold
            mult = max(0.40, 1.0 - penalty)
        else:
            mult = min(1.20, 1.0 + (dir_accuracy - 0.5) * 0.4)

        return round(float(mult), 2)
