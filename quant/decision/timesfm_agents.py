"""Specialized TimesFM 3.0 Agents: Auction Scanner & Position Manager.

Implements two dedicated, role-swapping agents operating over Google TimesFM 3.0 forecasts:
1. TimesFMScanningAgent:
   - Evaluates auction state when NO position is open.
   - Detects Triple-A (VAL/VAH absorption), VA-Fade mean-reversion, and Breakout setups.
   - Enforces 4-gate verification and institutional directional conviction.
   
2. TimesFMPositionAgent:
   - Manages active trades when a position IS open.
   - Strictly enforces Fabio Valentini's institutional rules from amt_dataset/position_mgmt:
     - HOLD (TREND_INTACT): Price remains inside TimesFM 90% confidence envelope.
     - TIGHTEN_SL (RISK_ZERO): 0.8R reached or p10/p90 clears cost basis -> breakeven floor.
     - TAKE_PROFIT (TARGET_HIT): Structural POC reached or 32-step trajectory inflects near target.
     - EXIT (THESIS_FLIP): Inversion of TimesFM trajectory, opposing absorption, or spread spike.
     - EXIT (STOP_LOSS): Structural invalidation hit.
     - EXIT (TIME_STOP): Stagnant consolidation after 5+ bars without expansion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from quant.contracts.instrument_registry import is_option_contract
from quant.contracts.vocabulary import (
    absorption_direction,
    is_closing_phase,
    is_opening_phase,
)
from quant.decision.context import DecisionContext

logger = logging.getLogger(__name__)


@dataclass
class TimesFMForecast:
    """Pre-computed TimesFM 3.0 multi-step forecast and quantile paths."""
    horizon: int
    p50_path: np.ndarray        # shape: (32,) - median trajectory
    p10_path: np.ndarray        # shape: (32,) - lower 10th percentile envelope
    p90_path: np.ndarray        # shape: (32,) - upper 90th percentile envelope
    q_spread: float             # mean(p90 - p10) forecast uncertainty
    mean_forecast: float        # p50[-1] terminal forecast price
    pct_change: float           # (mean_forecast - curr_price) / curr_price
    forecast_steps: List[str]   # 32 step direction labels: LONG | SHORT | FLAT
    curr_price: float           # latest bar close price
    lat_ms: float               # inference latency in milliseconds
    asof_bar: int = -1          # bar index the forecast was computed at (-1 = unknown)
    observation: object | None = None  # ForecastObservationIdentity when available


def _format_scanning_rationale(
    session_phase: str,
    curr_price: float,
    val: float,
    vah: float,
    symbol: str,
) -> str:
    """Generate session-timing and price-location aware scanning rationale."""
    phase = str(session_phase or "").upper()
    if is_opening_phase(phase):
        phase_label = "Opening range"
    elif any(p in phase for p in ("MIDDAY", "CHOP")):
        phase_label = "Midday"
    elif any(p in phase for p in ("PRIMARY", "MORNING")):
        phase_label = "Morning session"
    elif any(p in phase for p in ("POWER_HOUR", "AFTERNOON")):
        phase_label = "Afternoon"
    elif "EVENING" in phase:
        phase_label = "Evening session"
    elif is_closing_phase(phase):
        phase_label = "Session close"
    else:
        phase_label = "Session"

    if any(p in phase for p in ("OPENING", "PRE_OPEN")):
        return f"Opening 15m session warmup on {symbol}; accumulating initial balance."
    if any(p in phase for p in ("CLOSE", "POST_MARKET")):
        return f"Market close protection active on {symbol}; standing down."

    if curr_price > vah:
        return f"{phase_label} probe above VAH ({vah:.1f}) on {symbol} without order-flow acceptance; waiting for structural edge."
    elif curr_price < val:
        return f"{phase_label} probe below VAL ({val:.1f}) on {symbol} without order-flow acceptance; waiting for structural edge."
    else:
        return f"{phase_label} compression inside value area [{val:.1f} - {vah:.1f}]; waiting for structural edge."


class TimesFMScanningAgent:
    """Agent 1: Scans market auction setups when no position is open."""

    def __init__(self, target_horizon: int = 32) -> None:
        self.target_horizon = target_horizon

    def evaluate(
        self,
        ctx: DecisionContext,
        forecast: TimesFMForecast,
        chain: Optional[Any] = None,
    ) -> Dict[str, Any]:
        symbol = str(ctx.symbol or "UNKNOWN")
        # Retail scalpers are option buyers (long calls / long puts) with defined risk.
        # Shorting naked options is disabled — option instruments can never emit
        # ENTER_SHORT in advisory (mirrors the long-only guard in context_builder.py).
        is_option = is_option_contract(symbol)
        curr_price = float(ctx.bar.close if ctx.bar else forecast.curr_price)
        session_phase = str(ctx.session_phase or "").upper()
        allow_trend = getattr(ctx, "allow_trend", True)
        allow_reversion = getattr(ctx, "allow_reversion", True)

        # Gate 1 (session phase) is evaluated before the profile guard so that a
        # missing profile still reports the true session-phase gate result.
        is_opening = is_opening_phase(session_phase)
        is_closing = is_closing_phase(session_phase)
        g1 = bool(ctx.session_open and ctx.warmup_complete and not is_opening and not is_closing)
        g1_msg = ""
        if not g1:
            if not ctx.session_open:
                g1_msg = "Session closed"
            elif not ctx.warmup_complete:
                g1_msg = "Warming up — insufficient bars"
            elif is_opening:
                g1_msg = f"Opening noise ({session_phase})"
            elif is_closing:
                g1_msg = f"Close protection ({session_phase})"
            else:
                g1_msg = session_phase or "Phase restricted"

        # A zero/absent volume profile is NOT a value area at curr_price — it
        # means the AMT profile has not populated yet (empty seed, cold start).
        # Collapsing vah/val to curr_price makes every location test trivially
        # true and fabricates a fade with no auction structure behind it.
        poc = float(ctx.poc or 0.0)
        vah = float(ctx.vah or 0.0)
        val = float(ctx.val or 0.0)
        has_profile = vah > 0.0 and val > 0.0 and vah > val
        g2 = bool(not ctx.risk_halted and ctx.cooldown_remaining_sec == 0)
        g2_msg = "" if g2 else ("Risk halted" if ctx.risk_halted else "Cooldown")
        if not has_profile:
            return {
                "role": "SCANNING",
                "action": "FLAT",
                "direction": "FLAT",
                "setup": "NO_EDGE",
                "reason": "NO_PROFILE",
                "confidence": "Low",
                "confidenceScore": 0.0,
                "rationale": (
                    f"No volume profile on {symbol} yet (poc={poc:.2f}, "
                    f"vah={vah:.2f}, val={val:.2f}) — standing down until the "
                    f"AMT profile populates."
                ),
                "forecastSteps": list(forecast.forecast_steps),
                "quantileSpread": round(float(forecast.q_spread), 4),
                "meanForecast": round(float(forecast.mean_forecast), 2),
                "gateResults": [
                    {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": g1, "message": g1_msg},
                    {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": g2, "message": g2_msg},
                    {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": False, "message": "No volume profile"},
                    {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": False, "message": "No setup"},
                ],
                "activePosition": None,
                "dynamicTrailStop": None,
                "recommendedOption": None,
                "source": "TIMESFM_3.0_NATIVE",
                "latencyMs": round(float(forecast.lat_ms), 1),
                "modelLabel": "TimesFM-NoProfile",
                "modelVersions": {"timesfm": "3.0", "agent_role": "SCANNING", "engine": "native_direct"},
                "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
                "timing": str(ctx.session_phase or "REGULAR"),
                "sizeFraction": 0.0,
                "latencyUs": int(float(forecast.lat_ms) * 1000),
            }
        cvd_slope = float(ctx.cvd_slope or 0.0)
        absorption = str(ctx.absorption_side or "").upper()
        stacked_imb = str(getattr(ctx, "stacked_imbalance_direction", "") or "").upper()

        action, direction, setup, confidence, confidence_score, rationale = self._detect_setup(
            ctx, forecast,
            curr_price=curr_price, vah=vah, val=val, poc=poc,
            session_phase=session_phase,
            cvd_slope=cvd_slope, absorption=absorption, stacked_imb=stacked_imb,
            allow_trend=allow_trend, allow_reversion=allow_reversion,
            is_option=is_option, symbol=symbol,
        )

        # 4-Gate Evaluations (gate 1 already computed above the profile guard)

        g3 = bool(direction != "FLAT")
        g4 = bool(abs(forecast.mean_forecast - curr_price) >= (curr_price * 0.001))

        gate_results = [
            {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": g1, "message": g1_msg},
            {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": g2, "message": "" if g2 else "Cooldown"},
            {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": g3, "message": "" if g3 else "No direction"},
            {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": g4, "message": "" if g4 else "RR fail"},
        ]

        rec_opt = None
        if chain is not None and direction != "FLAT":
            try:
                from quant.decision.timesfm_option_selector import TimesFMOptionSelector
                opt_selector = TimesFMOptionSelector()
                ranked = opt_selector.evaluate_chain(
                    chain=chain,
                    underlying=symbol,
                    forecast=forecast,
                    direction=direction,
                )
                if ranked:
                    top = ranked[0]
                    rec_opt = {
                        "symbol": top.symbol,
                        "strike": top.strike,
                        "optionType": top.option_type,
                        "delta": top.delta,
                        "expectedROC": top.expected_roc,
                        "timesfmEdge": top.timesfm_edge,
                        "thetaViable": top.is_theta_viable,
                        "compositeScore": top.composite_score,
                    }
            except Exception as e:
                logger.debug("Failed evaluating recommended option in TimesFMScanningAgent: %s", e)

        all_gates_passed = all(g.get("passed", False) for g in gate_results)
        is_entry = action in ("ENTER_LONG", "ENTER_SHORT") and direction in ("LONG", "SHORT")
        timing = "ENTER_NOW" if (is_entry and all_gates_passed) else str(ctx.session_phase or "REGULAR")

        return {
            "role": "SCANNING",
            "action": action,
            "direction": direction,
            "setup": setup,
            "reason": None,
            "confidence": confidence,
            "confidenceScore": round(confidence_score, 3),
            "rationale": rationale,
            "forecastSteps": forecast.forecast_steps,
            "quantileSpread": round(forecast.q_spread, 4),
            "meanForecast": round(forecast.mean_forecast, 2),
            "gateResults": gate_results,
            "activePosition": None,
            "dynamicTrailStop": None,
            "recommendedOption": rec_opt,
            "source": "TIMESFM_3.0_NATIVE",
            "latencyMs": round(forecast.lat_ms, 1),
            "modelLabel": f"TimesFM-{setup}",
            "modelVersions": {"timesfm": "3.0", "agent_role": "SCANNING", "engine": "native_direct"},
            "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
            "timing": timing,
            "sizeFraction": 1.0 if direction != "FLAT" else 0.0,
            "latencyUs": int(forecast.lat_ms * 1000),
        }


    def _detect_setup(
        self, ctx, forecast, *, curr_price, vah, val, poc, session_phase,
        cvd_slope, absorption, stacked_imb, allow_trend,
        allow_reversion, is_option, symbol,
    ):
        """Return (action, direction, setup, confidence, confidence_score, rationale)."""
        va_range = max(vah - val, curr_price * 0.001)
        tol = va_range * 0.15

        action = "FLAT"
        direction = "FLAT"
        setup = "NO_EDGE"
        confidence = "Low"
        confidence_score = 0.2
        rationale = _format_scanning_rationale(session_phase, curr_price, val, vah, symbol)

        # Setup A: Triple-A Long (Absorption at VAL + positive CVD + TimesFM upward slope)
        if (
            ctx.session_open
            and allow_trend
            and (curr_price <= val + tol or "SELL" in absorption or stacked_imb == "BUY")
            and cvd_slope > 1.0
            and forecast.pct_change > 0.0005
        ):
            action = "ENTER_LONG"
            direction = "LONG"
            setup = "TRIPLE_A"
            confidence = "High"
            confidence_score = 0.85
            rationale = (
                f"Triple-A Long setup on {symbol}: Volume absorption at VAL ({val:.1f}) with positive "
                f"CVD slope ({cvd_slope:.1f}) and TimesFM upward trajectory to {forecast.mean_forecast:.1f}."
            )

        # Setup B: Triple-A Short (Absorption at VAH + negative CVD + TimesFM downward slope)
        elif (
            ctx.session_open
            and allow_trend
            and not is_option
            and (curr_price >= vah - tol or "BUY" in absorption or stacked_imb == "SELL")
            and cvd_slope < -1.0
            and forecast.pct_change < -0.0005
        ):
            action = "ENTER_SHORT"
            direction = "SHORT"
            setup = "TRIPLE_A"
            confidence = "High"
            confidence_score = 0.85
            rationale = (
                f"Triple-A Short setup on {symbol}: Selling absorption at VAH ({vah:.1f}) with aggressive "
                f"negative CVD slope ({cvd_slope:.1f}) and TimesFM downward trajectory to {forecast.mean_forecast:.1f}."
            )

        # Setup C: Value Area Breakout
        elif (
            ctx.session_open
            and allow_trend
            and curr_price > vah
            and cvd_slope > 0.5
            and all(s == "LONG" for s in forecast.forecast_steps[-16:])
        ):
            action = "ENTER_LONG"
            direction = "LONG"
            setup = "BREAKOUT"
            confidence = "Medium"
            confidence_score = 0.70
            rationale = f"Initiative Breakout above VAH ({vah:.1f}) on {symbol} with sustained TimesFM 32-step acceptance."

        elif (
            ctx.session_open
            and allow_trend
            and not is_option
            and curr_price < val
            and cvd_slope < -0.5
            and all(s == "SHORT" for s in forecast.forecast_steps[-16:])
        ):
            action = "ENTER_SHORT"
            direction = "SHORT"
            setup = "BREAKOUT"
            confidence = "Medium"
            confidence_score = 0.70
            rationale = f"Initiative Breakdown below VAL ({val:.1f}) on {symbol} with sustained TimesFM 32-step acceptance."

        # Setup D: Value Area Fade Reversion
        elif (
            ctx.session_open
            and allow_reversion
            and not is_option
            and curr_price >= vah
            and cvd_slope <= 0.0
            and forecast.mean_forecast < curr_price
        ):
            action = "ENTER_SHORT"
            direction = "SHORT"
            setup = "VA_FADE"
            confidence = "Medium"
            confidence_score = 0.60
            rationale = f"VA-Fade short: Price probe above VAH rejected; TimesFM projecting mean-reversion toward POC ({poc:.1f})."

        elif (
            ctx.session_open
            and allow_reversion
            and curr_price <= val
            and cvd_slope >= 0.0
            and forecast.mean_forecast > curr_price
        ):
            action = "ENTER_LONG"
            direction = "LONG"
            setup = "VA_FADE"
            confidence = "Medium"
            confidence_score = 0.60
            rationale = f"VA-Fade long: Price probe below VAL rejected; TimesFM projecting mean-reversion toward POC ({poc:.1f})."

        # Setup E: Model-Directed Momentum (Pure TimesFM Directional Drift + CVD Concordance)
        elif (
            ctx.session_open
            and allow_trend
            and abs(forecast.pct_change) >= 0.0010
        ):
            long_steps = sum(1 for s in forecast.forecast_steps if s == "LONG")
            short_steps = sum(1 for s in forecast.forecast_steps if s == "SHORT")
            total_steps = len(forecast.forecast_steps) or 1
            if forecast.pct_change > 0 and (long_steps / total_steps) >= 0.60 and cvd_slope >= -0.5:
                action = "ENTER_LONG"
                direction = "LONG"
                setup = "MODEL_MOMENTUM"
                confidence = "High"
                confidence_score = 0.80
                rationale = (
                    f"Model-Directed Momentum Long on {symbol}: TimesFM projecting +{forecast.pct_change*100:.2f}% "
                    f"drift ({long_steps}/{total_steps} bullish steps, q_spread={forecast.q_spread:.1f}) with CVD concordance ({cvd_slope:.1f})."
                )
            elif forecast.pct_change < 0 and not is_option and (short_steps / total_steps) >= 0.60 and cvd_slope <= 0.5:
                action = "ENTER_SHORT"
                direction = "SHORT"
                setup = "MODEL_MOMENTUM"
                confidence = "High"
                confidence_score = 0.80
                rationale = (
                    f"Model-Directed Momentum Short on {symbol}: TimesFM projecting {forecast.pct_change*100:.2f}% "
                    f"drift ({short_steps}/{total_steps} bearish steps, q_spread={forecast.q_spread:.1f}) with CVD concordance ({cvd_slope:.1f})."
                )

        return action, direction, setup, confidence, confidence_score, rationale

class TimesFMPositionAgent:
    """Agent 2: Manages active positions according to Fabio AMT rules and TimesFM quantiles."""

    def __init__(self, target_horizon: int = 32) -> None:
        self.target_horizon = target_horizon

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self, ctx: DecisionContext, forecast: TimesFMForecast) -> Dict[str, Any]:
        state = self._extract_state(ctx, forecast)
        dyn_stop = self._compute_trailing_stop(state, forecast)
        action, reason, confidence, confidence_score, rationale = self._default_hold(state)

        # Evaluate exit/management conditions in priority order (first match wins)
        result = self._check_stop_loss(state)
        if result is None:
            result = self._check_take_profit(state)
        if result is None:
            result = self._check_trajectory_inflection(state, forecast)
        if result is None:
            result = self._check_thesis_flip(state, forecast)
        if result is None:
            result = self._check_risk_zero_ratchet(state, forecast)
        if result is None:
            result = self._check_time_stop(state, forecast)

        if result is not None:
            action, reason, confidence, confidence_score, rationale, dyn_stop_override = result
            if dyn_stop_override is not None:
                dyn_stop = dyn_stop_override

        is_risk_free = state["is_risk_free"] or (action == "TIGHTEN_SL")
        active_pos_payload = self._build_active_position_payload(state, action, is_risk_free)
        return self._build_result(ctx, forecast, state, action, reason, confidence,
                                  confidence_score, rationale, active_pos_payload, dyn_stop)

    # ------------------------------------------------------------------
    # State extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bar_vals(ctx: DecisionContext, forecast: TimesFMForecast):
        """Return (close, low, high) from ctx.bar or forecast fallback."""
        if ctx.bar:
            return float(ctx.bar.close), float(ctx.bar.low), float(ctx.bar.high)
        cp = float(forecast.curr_price)
        return cp, cp, cp

    @staticmethod
    def _extract_state(ctx: DecisionContext, forecast: TimesFMForecast) -> Dict[str, Any]:
        """Pull all position-related values out of *ctx* / *forecast* once."""
        bar_close, bar_low, bar_high = TimesFMPositionAgent._bar_vals(ctx, forecast)
        _f = lambda v, d=0.0: float(v or d)  # noqa: E731
        side = str(ctx.position_side or "LONG").upper()
        entry_price = _f(ctx.position_entry_price, forecast.curr_price)
        poc_raw = ctx.poc or (ctx.state.poc if ctx.state else bar_close)
        poc = float(poc_raw)
        sl_val = _f(ctx.position_sl)
        risk = abs(entry_price - sl_val) if sl_val > 0 else (bar_close * 0.005)
        profit = (bar_close - entry_price) if side == "LONG" else (entry_price - bar_close)
        rr_achieved = profit / max(risk, 1e-4)
        is_risk_free = (sl_val >= entry_price) if side == "LONG" else (sl_val > 0 and sl_val <= entry_price)
        return {
            "symbol": str(ctx.symbol or "UNKNOWN"), "side": side,
            "entry_price": entry_price, "curr_price": bar_close,
            "bar_low": bar_low, "bar_high": bar_high,
            "sl": sl_val, "tp": _f(ctx.position_tp),
            "pnl": _f(ctx.position_unrealized_pnl),
            "bars_held": int(ctx.position_bars_held or 0),
            "cvd_slope": _f(ctx.cvd_slope),
            "absorption": str(ctx.absorption_side or "").upper(),
            "stacked_imb": str(getattr(ctx, "stacked_imbalance_direction", "") or "").upper(),
            "poc": poc, "risk": risk, "profit": profit,
            "rr_achieved": rr_achieved, "is_risk_free": is_risk_free,
        }

    # ------------------------------------------------------------------
    # Trailing-stop computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_trailing_stop(state: Dict[str, Any], forecast: TimesFMForecast) -> float:
        """Dynamic trailing stop peg from TimesFM quantiles."""
        side, sl = state["side"], state["sl"]
        if side == "LONG":
            dyn_candidate = float(forecast.p10_path[0])
            return max(sl, dyn_candidate) if sl > 0 else dyn_candidate
        dyn_candidate = float(forecast.p90_path[0])
        return min(sl, dyn_candidate) if sl > 0 else dyn_candidate

    # ------------------------------------------------------------------
    # Default HOLD rationale
    # ------------------------------------------------------------------

    @staticmethod
    def _default_hold(state: Dict[str, Any]):
        """Return the default (action, reason, confidence, score, rationale) for HOLD."""
        cvd_slope, symbol, side = state["cvd_slope"], state["symbol"], state["side"]
        bars_held, pnl = state["bars_held"], state["pnl"]
        cvd_text = f"CVD confirms trend ({cvd_slope:+.1f})" if abs(cvd_slope) >= 0.5 else "Order flow steady"
        rationale = (
            f"{cvd_text} and TimesFM 32-step trajectory remains favorable — "
            f"holding {symbol} {side} ({bars_held} bars held, PnL: {pnl:+.1f})."
        )
        return "HOLD", "TREND_INTACT", "High", 0.85, rationale

    # ------------------------------------------------------------------
    # Condition checks — each returns None or a 6-tuple
    # (action, reason, confidence, confidence_score, rationale, dyn_stop_override)
    # ------------------------------------------------------------------

    def _check_stop_loss(self, s: Dict[str, Any]):
        """1. HARD STOP LOSS TRIGGERED."""
        side, sl = s["side"], s["sl"]
        bar_low, bar_high, symbol = s["bar_low"], s["bar_high"], s["symbol"]
        if sl > 0 and ((side == "LONG" and bar_low <= sl) or (side == "SHORT" and bar_high >= sl)):
            return (
                "EXIT", "STOP_LOSS", "High", 0.95,
                f"Stop loss triggered on {symbol} {side} at structural invalidation level ({sl:.2f}).",
                None,
            )
        return None

    def _check_take_profit(self, s: Dict[str, Any]):
        """2. STRUCTURAL TAKE PROFIT TARGET HIT."""
        side, tp = s["side"], s["tp"]
        bar_low, bar_high = s["bar_low"], s["bar_high"]
        symbol, rr = s["symbol"], s["rr_achieved"]
        if tp > 0 and ((side == "LONG" and bar_high >= tp) or (side == "SHORT" and bar_low <= tp)):
            return (
                "TAKE_PROFIT", "TARGET_HIT", "High", 0.95,
                f"Structural take-profit target reached on {symbol} {side} at {tp:.2f} (RR: {rr:.1f}R).",
                None,
            )
        return None

    def _check_trajectory_inflection(self, s: Dict[str, Any], forecast: TimesFMForecast):
        """3. PREDICTIVE TRAJECTORY INFLECTION / POC FRONT-RUNNING."""
        side, rr = s["side"], s["rr_achieved"]
        symbol, profit, poc = s["symbol"], s["profit"], s["poc"]
        if rr < 0.9:
            return None
        p50 = forecast.p50_path
        if side == "LONG" and np.argmax(p50) < 16 and p50[-1] < p50[np.argmax(p50)]:
            return (
                "TAKE_PROFIT", "TARGET_HIT", "High", 0.88,
                f"TimesFM 32-step trajectory inflects near session POC ({poc:.1f}); front-running liquidity cascade "
                f"with partial take-profit on {symbol} {side} (+{profit:.1f} pts).",
                None,
            )
        if side == "SHORT" and np.argmin(p50) < 16 and p50[-1] > p50[np.argmin(p50)]:
            return (
                "TAKE_PROFIT", "TARGET_HIT", "High", 0.88,
                f"TimesFM 32-step trajectory inflects near session POC ({poc:.1f}); front-running liquidity cascade "
                f"with partial take-profit on {symbol} {side} (+{profit:.1f} pts).",
                None,
            )
        return None

    def _check_thesis_flip(self, s: Dict[str, Any], forecast: TimesFMForecast):
        """4. THESIS FLIP / OPPOSING ABSORPTION / ADVERSE ORDER FLOW."""
        if not self._thesis_flip_triggered(s, forecast):
            return None
        rationale = self._build_thesis_flip_rationale(s, forecast)
        return "EXIT", "THESIS_FLIP", "High", 0.90, rationale, None

    def _check_risk_zero_ratchet(self, s: Dict[str, Any], forecast: TimesFMForecast):
        """5. RISK-ZERO RATCHET (Breakeven Trailing)."""
        side, is_risk_free, rr = s["side"], s["is_risk_free"], s["rr_achieved"]
        entry_price, symbol = s["entry_price"], s["symbol"]
        if is_risk_free:
            return None
        p10_clear = side == "LONG" and float(np.min(forecast.p10_path[:5])) > entry_price
        p90_clear = side == "SHORT" and float(np.max(forecast.p90_path[:5])) < entry_price
        if not (rr >= 0.8 or p10_clear or p90_clear):
            return None
        rationale = (
            f"CVD confirms and TimesFM 90% confidence envelope clears cost basis on {symbol} {side} — "
            f"moving stop to breakeven ({entry_price:.2f})."
        )
        return "TIGHTEN_SL", "RISK_ZERO", "High", 0.90, rationale, entry_price

    def _check_time_stop(self, s: Dict[str, Any], forecast: TimesFMForecast):
        """6. TIME-STOP / STAGNATION DECAY."""
        bars_held, rr = s["bars_held"], s["rr_achieved"]
        symbol, side = s["symbol"], s["side"]
        if bars_held >= 5 and abs(rr) < 0.25 and abs(forecast.pct_change) < 0.0003:
            return (
                "EXIT", "TIME_STOP", "Medium", 0.70,
                f"Time stop on {symbol} {side}: Auction stagnant without directional expansion after "
                f"{bars_held} bars — exiting flat.",
                None,
            )
        return None

    # ------------------------------------------------------------------
    # Thesis-flip helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_absorption_opposed(side: str, absorption: str) -> bool:
        """True when the absorption print opposes the position side."""
        opp = absorption_direction(absorption)
        return (side == "LONG" and opp == "SHORT") or (side == "SHORT" and opp == "LONG")

    @staticmethod
    def _thesis_flip_triggered(s: Dict[str, Any], forecast: TimesFMForecast) -> bool:
        """Return True when any thesis-flip condition is met."""
        side, absorption = s["side"], s["absorption"]
        stacked_imb, cvd_slope = s["stacked_imb"], s["cvd_slope"]
        entry_price, risk = s["entry_price"], s["risk"]
        if TimesFMPositionAgent._is_absorption_opposed(side, absorption):
            return True
        if (side == "LONG" and stacked_imb == "SELL" and cvd_slope < -1.0) or (side == "SHORT" and stacked_imb == "BUY" and cvd_slope > 1.0):
            return True
        if (side == "LONG" and cvd_slope <= -2.5) or (side == "SHORT" and cvd_slope >= 2.5):
            return True
        if side == "LONG" and forecast.mean_forecast < entry_price - (0.5 * risk):
            return True
        if side == "SHORT" and forecast.mean_forecast > entry_price + (0.5 * risk):
            return True
        return False

    @staticmethod
    def _build_thesis_flip_rationale(s: Dict[str, Any], forecast: TimesFMForecast) -> str:
        """Build the human-readable rationale for a thesis-flip exit."""
        side, absorption = s["side"], s["absorption"]
        stacked_imb, cvd_slope = s["stacked_imb"], s["cvd_slope"]
        entry_price, risk = s["entry_price"], s["risk"]
        symbol = s["symbol"]
        if TimesFMPositionAgent._is_absorption_opposed(side, absorption):
            if side == "LONG":
                return "Heavy buy absorption cluster — sellers in control."
            return "Heavy sell absorption cluster — buyers in control."
        if side == "LONG" and ((stacked_imb == "SELL" and cvd_slope < -1.0) or cvd_slope <= -2.5):
            return (
                f"Thesis flip on {symbol} LONG: Opposing order flow (CVD slope {cvd_slope:+.1f}) "
                f"and seller pressure — exiting before stop loss hit."
            )
        if side == "SHORT" and ((stacked_imb == "BUY" and cvd_slope > 1.0) or cvd_slope >= 2.5):
            return (
                f"Thesis flip on {symbol} SHORT: Opposing order flow (CVD slope {cvd_slope:+.1f}) "
                f"and buyer pressure — exiting before stop loss hit."
            )
        if side == "LONG" and forecast.mean_forecast < entry_price - (0.5 * risk):
            return (
                f"Thesis flip on {symbol} LONG: TimesFM 32-step trajectory breakdown "
                f"(projected {forecast.mean_forecast:.2f} breaches 0.5R envelope) — exiting before stop loss hit."
            )
        if side == "SHORT" and forecast.mean_forecast > entry_price + (0.5 * risk):
            return (
                f"Thesis flip on {symbol} SHORT: TimesFM 32-step trajectory breakdown "
                f"(projected {forecast.mean_forecast:.2f} breaches 0.5R envelope) — exiting before stop loss hit."
            )
        return (
            f"Thesis flip on {symbol} {side}: Invalidation of market structure — "
            f"exiting before stop loss hit."
        )

    # ------------------------------------------------------------------
    # Result builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_active_position_payload(
        s: Dict[str, Any], action: str, is_risk_free: bool,
    ) -> Dict[str, Any]:
        """Build the ``activePosition`` sub-dict."""
        return {
            "side": s["side"],
            "entryPrice": round(s["entry_price"], 2),
            "currentPrice": round(s["curr_price"], 2),
            "pnl": round(s["pnl"], 2),
            "stopLoss": round(s["sl"], 2) if s["sl"] > 0 else None,
            "takeProfit": round(s["tp"], 2) if s["tp"] > 0 else None,
            "barsHeld": s["bars_held"],
            "isRiskFree": is_risk_free,
            "rrAchieved": round(s["rr_achieved"], 2),
        }

    @staticmethod
    def _build_result(
        ctx: DecisionContext,
        forecast: TimesFMForecast,
        state: Dict[str, Any],
        action: str,
        reason: str,
        confidence: str,
        confidence_score: float,
        rationale: str,
        active_pos_payload: Dict[str, Any],
        dyn_stop: float,
    ) -> Dict[str, Any]:
        """Assemble the full return dictionary."""
        side = state["side"]
        entry_price = state["entry_price"]
        pnl = state["pnl"]
        return {
            "role": "POSITION_MANAGEMENT",
            "action": action,
            "direction": side,
            "setup": "POSITION_MGMT",
            "reason": reason,
            "confidence": confidence,
            "confidenceScore": round(confidence_score, 3),
            "rationale": rationale,
            "forecastSteps": forecast.forecast_steps,
            "quantileSpread": round(forecast.q_spread, 4),
            "meanForecast": round(forecast.mean_forecast, 2),
            "gateResults": [
                {"gate_no": 1, "gate_name": "POSITION_ACTIVE", "passed": True, "message": f"{side} @ {entry_price:.1f}"},
                {"gate_no": 2, "gate_name": "TREND_HEALTH", "passed": bool(action in ("HOLD", "TIGHTEN_SL")), "message": reason},
                {"gate_no": 3, "gate_name": "RISK_STATE", "passed": True, "message": f"PnL {pnl:+.1f}"},
                {"gate_no": 4, "gate_name": "ACTION_DISPATCH", "passed": True, "message": action},
            ],
            "activePosition": active_pos_payload,
            "dynamicTrailStop": round(dyn_stop, 2) if dyn_stop is not None else None,
            "source": "TIMESFM_3.0_NATIVE",
            "latencyMs": round(forecast.lat_ms, 1),
            "modelLabel": f"TimesFM-PM-{action}",
            "modelVersions": {"timesfm": "3.0", "agent_role": "POSITION_MANAGEMENT", "engine": "native_direct"},
            "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
            "timing": "EXIT_NOW" if action == "EXIT" else ("REDUCE_NOW" if action == "SCALE_OUT" else "HOLD"),
            "sizeFraction": 1.0 if action in ("HOLD", "TIGHTEN_SL") else 0.0,
            "latencyUs": int(forecast.lat_ms * 1000),
        }
