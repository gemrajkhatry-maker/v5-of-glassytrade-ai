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


def _format_scanning_rationale(
    session_phase: str,
    curr_price: float,
    val: float,
    vah: float,
    symbol: str,
) -> str:
    """Generate session-timing and price-location aware scanning rationale."""
    phase = str(session_phase or "").upper()
    if any(p in phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET")):
        phase_label = "Opening range"
    elif any(p in phase for p in ("MIDDAY", "CHOP")):
        phase_label = "Midday"
    elif any(p in phase for p in ("PRIMARY", "MORNING")):
        phase_label = "Morning session"
    elif any(p in phase for p in ("POWER_HOUR", "AFTERNOON")):
        phase_label = "Afternoon"
    elif "EVENING" in phase:
        phase_label = "Evening session"
    elif any(p in phase for p in ("CLOSE", "POST_MARKET", "EOD")):
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
        is_opening = any(p in session_phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET"))
        is_closing = any(p in session_phase for p in ("CLOSE", "POST_MARKET", "EOD"))
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
                "dynamicSizing": None,
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

        # 4-Gate Evaluations (gate 1 already computed above the profile guard)

        # Fabio AMT Structural Target Identification
        def _valid_target(t: float) -> bool:
            if not t or t <= 0:
                return False
            # Scale check: structural target must be within 20% of curr_price
            return abs(t - curr_price) / curr_price <= 0.20

        structural_target = None
        if direction == "LONG":
            if setup == "VA_FADE" and poc > curr_price and _valid_target(poc):
                structural_target = poc
            elif setup in ("BREAKOUT", "MODEL_MOMENTUM"):
                npoc_a = getattr(ctx, "npoc_above", 0.0)
                prior_p = getattr(ctx, "prior_poc", 0.0)
                if npoc_a > curr_price and _valid_target(npoc_a):
                    structural_target = npoc_a
                elif prior_p > curr_price and _valid_target(prior_p):
                    structural_target = prior_p
                elif vah > curr_price and _valid_target(vah):
                    structural_target = vah
            elif setup == "TRIPLE_A":
                prior_p = getattr(ctx, "prior_poc", 0.0)
                if vah > curr_price and _valid_target(vah):
                    structural_target = vah
                elif prior_p > curr_price and _valid_target(prior_p):
                    structural_target = prior_p
        elif direction == "SHORT":
            if setup == "VA_FADE" and 0 < poc < curr_price and _valid_target(poc):
                structural_target = poc
            elif setup in ("BREAKOUT", "MODEL_MOMENTUM"):
                npoc_b = getattr(ctx, "npoc_below", 0.0)
                prior_p = getattr(ctx, "prior_poc", 0.0)
                if 0 < npoc_b < curr_price and _valid_target(npoc_b):
                    structural_target = npoc_b
                elif 0 < prior_p < curr_price and _valid_target(prior_p):
                    structural_target = prior_p
                elif 0 < val < curr_price and _valid_target(val):
                    structural_target = val
            elif setup == "TRIPLE_A":
                prior_p = getattr(ctx, "prior_poc", 0.0)
                if 0 < val < curr_price and _valid_target(val):
                    structural_target = val
                elif 0 < prior_p < curr_price and _valid_target(prior_p):
                    structural_target = prior_p

        is_high_conviction = bool(confidence_score >= 0.80)

        dynamic_sizing = None
        if direction != "FLAT":
            try:
                from quant.decision.timesfm_sizing import TimesFMPositionSizer
                sizer = TimesFMPositionSizer()
                sizing_res = sizer.compute_size(
                    equity=float(getattr(ctx, "equity", None) or 100000.0),
                    entry=curr_price,
                    side=direction,
                    forecast=forecast,
                    override_tp=structural_target,
                    is_aggressive=is_high_conviction,
                )
                dynamic_sizing = {
                    "lots": sizing_res.lots,
                    "quantity": sizing_res.quantity,
                    "riskPct": sizing_res.risk_pct,
                    "riskAmount": sizing_res.risk_amount,
                    "varStop": sizing_res.var_stop,
                    "targetPrice": sizing_res.target_price,
                    "winProb": sizing_res.win_prob,
                    "payoffRatio": sizing_res.payoff_ratio,
                    "dispersionMultiplier": sizing_res.dispersion_multiplier,
                    "velocityMultiplier": sizing_res.velocity_multiplier,
                    "expectedPeakStep": sizing_res.expected_peak_step,
                    "rationale": sizing_res.rationale,
                }
            except Exception as e:
                logger.debug("Failed computing dynamic sizing in TimesFMScanningAgent: %s", e)

        g3 = bool(direction != "FLAT")
        g4 = bool(
            abs(forecast.mean_forecast - curr_price) >= (curr_price * 0.001)
            or (dynamic_sizing and float(dynamic_sizing.get("payoffRatio", 0.0)) >= 1.4)
        )

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
            "dynamicSizing": dynamic_sizing,
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


class TimesFMPositionAgent:
    """Agent 2: Manages active positions according to Fabio AMT rules and TimesFM quantiles."""

    def __init__(self, target_horizon: int = 32) -> None:
        self.target_horizon = target_horizon

    def evaluate(self, ctx: DecisionContext, forecast: TimesFMForecast) -> Dict[str, Any]:
        symbol = str(ctx.symbol or "UNKNOWN")
        side = str(ctx.position_side or "LONG").upper()
        entry_price = float(ctx.position_entry_price or forecast.curr_price)
        curr_price = float(ctx.bar.close if ctx.bar else forecast.curr_price)
        bar_low = float(ctx.bar.low if ctx.bar else curr_price)
        bar_high = float(ctx.bar.high if ctx.bar else curr_price)
        sl = float(ctx.position_sl or 0.0)
        tp = float(ctx.position_tp or 0.0)
        pnl = float(ctx.position_unrealized_pnl or 0.0)
        bars_held = int(ctx.position_bars_held or 0)
        cvd_slope = float(ctx.cvd_slope or 0.0)
        absorption = str(ctx.absorption_side or "").upper()
        stacked_imb = str(getattr(ctx, "stacked_imbalance_direction", "") or "").upper()
        poc = float(ctx.poc or (ctx.state.poc if ctx.state else curr_price))

        risk = abs(entry_price - sl) if sl > 0 else (curr_price * 0.005)
        profit = (curr_price - entry_price) if side == "LONG" else (entry_price - curr_price)
        rr_achieved = profit / max(risk, 1e-4)

        # Compute dynamic trailing stop peg from TimesFM quantiles
        # Long trails behind lower quantile p10; Short trails behind upper quantile p90
        if side == "LONG":
            dyn_candidate = float(forecast.p10_path[0])
            dyn_stop = max(sl, dyn_candidate) if sl > 0 else dyn_candidate
        else:
            dyn_candidate = float(forecast.p90_path[0])
            dyn_stop = min(sl, dyn_candidate) if sl > 0 else dyn_candidate

        # Check if already at risk-free breakeven
        is_risk_free = (sl >= entry_price) if side == "LONG" else (sl > 0 and sl <= entry_price)

        action = "HOLD"
        reason = "TREND_INTACT"
        confidence = "High"
        confidence_score = 0.85
        cvd_text = f"CVD confirms trend ({cvd_slope:+.1f})" if abs(cvd_slope) >= 0.5 else "Order flow steady"
        rationale = (
            f"{cvd_text} and TimesFM 32-step trajectory remains favorable — "
            f"holding {symbol} {side} ({bars_held} bars held, PnL: {pnl:+.1f})."
        )

        # 1. HARD STOP LOSS TRIGGERED
        if sl > 0 and ((side == "LONG" and bar_low <= sl) or (side == "SHORT" and bar_high >= sl)):
            action = "EXIT"
            reason = "STOP_LOSS"
            confidence = "High"
            confidence_score = 0.95
            rationale = f"Stop loss triggered on {symbol} {side} at structural invalidation level ({sl:.2f})."

        # 2. STRUCTURAL TAKE PROFIT TARGET HIT
        elif tp > 0 and ((side == "LONG" and bar_high >= tp) or (side == "SHORT" and bar_low <= tp)):
            action = "TAKE_PROFIT"
            reason = "TARGET_HIT"
            confidence = "High"
            confidence_score = 0.95
            rationale = f"Structural take-profit target reached on {symbol} {side} at {tp:.2f} (RR: {rr_achieved:.1f}R)."

        # 3. PREDICTIVE TRAJECTORY INFLECTION / POC FRONT-RUNNING (Fabio 1-2 ticks inside shield)
        elif rr_achieved >= 0.9 and (
            (side == "LONG" and np.argmax(forecast.p50_path) < 16 and forecast.p50_path[-1] < forecast.p50_path[np.argmax(forecast.p50_path)])
            or (side == "SHORT" and np.argmin(forecast.p50_path) < 16 and forecast.p50_path[-1] > forecast.p50_path[np.argmin(forecast.p50_path)])
        ):
            action = "TAKE_PROFIT"
            reason = "TARGET_HIT"
            confidence = "High"
            confidence_score = 0.88
            rationale = (
                f"TimesFM 32-step trajectory inflects near session POC ({poc:.1f}); front-running liquidity cascade "
                f"with partial take-profit on {symbol} {side} (+{profit:.1f} pts)."
            )

        # 4. THESIS FLIP / OPPOSING ABSORPTION / ADVERSE ORDER FLOW
        elif (
            # Opposing absorption cluster (Fabio: institutional inventory capping the move)
            (side == "LONG" and absorption in ("BUY", "BUY_ABSORBED"))
            or (side == "SHORT" and absorption in ("SELL", "SELL_ABSORBED"))
            # Or opposing stacked imbalance with opposing CVD
            or (side == "LONG" and stacked_imb == "SELL" and cvd_slope < -1.0)
            or (side == "SHORT" and stacked_imb == "BUY" and cvd_slope > 1.0)
            # Or strong opposing CVD divergence without stacked imbalance
            or (side == "LONG" and cvd_slope <= -2.5)
            or (side == "SHORT" and cvd_slope >= 2.5)
            # Or TimesFM trajectory breaks down significantly against trade
            or (side == "LONG" and forecast.mean_forecast < entry_price - (0.5 * risk))
            or (side == "SHORT" and forecast.mean_forecast > entry_price + (0.5 * risk))
        ):
            action = "EXIT"
            reason = "THESIS_FLIP"
            confidence = "High"
            confidence_score = 0.90
            if side == "LONG" and absorption in ("BUY", "BUY_ABSORBED"):
                rationale = "Heavy buy absorption cluster — sellers in control."
            elif side == "SHORT" and absorption in ("SELL", "SELL_ABSORBED"):
                rationale = "Heavy sell absorption cluster — buyers in control."
            elif (side == "LONG" and stacked_imb == "SELL" and cvd_slope < -1.0) or (side == "LONG" and cvd_slope <= -2.5):
                rationale = (
                    f"Thesis flip on {symbol} LONG: Opposing order flow (CVD slope {cvd_slope:+.1f}) "
                    f"and seller pressure — exiting before stop loss hit."
                )
            elif (side == "SHORT" and stacked_imb == "BUY" and cvd_slope > 1.0) or (side == "SHORT" and cvd_slope >= 2.5):
                rationale = (
                    f"Thesis flip on {symbol} SHORT: Opposing order flow (CVD slope {cvd_slope:+.1f}) "
                    f"and buyer pressure — exiting before stop loss hit."
                )
            elif side == "LONG" and forecast.mean_forecast < entry_price - (0.5 * risk):
                rationale = (
                    f"Thesis flip on {symbol} LONG: TimesFM 32-step trajectory breakdown "
                    f"(projected {forecast.mean_forecast:.2f} breaches 0.5R envelope) — exiting before stop loss hit."
                )
            elif side == "SHORT" and forecast.mean_forecast > entry_price + (0.5 * risk):
                rationale = (
                    f"Thesis flip on {symbol} SHORT: TimesFM 32-step trajectory breakdown "
                    f"(projected {forecast.mean_forecast:.2f} breaches 0.5R envelope) — exiting before stop loss hit."
                )
            else:
                rationale = (
                    f"Thesis flip on {symbol} {side}: Invalidation of market structure — "
                    f"exiting before stop loss hit."
                )

        # 5. RISK-ZERO RATCHET (Breakeven Trailing)
        elif not is_risk_free and (
            rr_achieved >= 0.8
            or (side == "LONG" and float(np.min(forecast.p10_path[:5])) > entry_price)
            or (side == "SHORT" and float(np.max(forecast.p90_path[:5])) < entry_price)
        ):
            action = "TIGHTEN_SL"
            reason = "RISK_ZERO"
            confidence = "High"
            confidence_score = 0.90
            dyn_stop = entry_price
            rationale = (
                f"CVD confirms and TimesFM 90% confidence envelope clears cost basis on {symbol} {side} — "
                f"moving stop to breakeven ({entry_price:.2f})."
            )

        # 6. TIME-STOP / STAGNATION DECAY
        elif bars_held >= 5 and abs(rr_achieved) < 0.25 and abs(forecast.pct_change) < 0.0003:
            action = "EXIT"
            reason = "TIME_STOP"
            confidence = "Medium"
            confidence_score = 0.70
            rationale = (
                f"Time stop on {symbol} {side}: Auction stagnant without directional expansion after "
                f"{bars_held} bars — exiting flat."
            )

        # Active position details payload
        active_pos_payload = {
            "side": side,
            "entryPrice": round(entry_price, 2),
            "currentPrice": round(curr_price, 2),
            "pnl": round(pnl, 2),
            "stopLoss": round(sl, 2) if sl > 0 else None,
            "takeProfit": round(tp, 2) if tp > 0 else None,
            "barsHeld": bars_held,
            "isRiskFree": is_risk_free or (action == "TIGHTEN_SL"),
            "rrAchieved": round(rr_achieved, 2),
        }

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
