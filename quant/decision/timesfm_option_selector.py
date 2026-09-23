"""TimesFM Quantitative Option Contract Selector.

Bridges Google TimesFM 3.0 multi-step forecasts with live broker option chains.
Uses analytical Greeks expansion (Delta-Gamma-Theta-Vega) to simulate contract payoffs
and select the optimal option contract (strike, option type, expiry) that maximizes
risk-adjusted expected return on capital while avoiding the theta decay trap.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import numpy as np

from quant.decision.timesfm_agents import TimesFMForecast

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredOptionContract:
    """Fully evaluated option contract with TimesFM quantitative metrics."""

    symbol: str
    underlying: str
    strike: int
    option_type: str  # "CE" or "PE"
    expiry: str
    ltp: float
    bid: float
    ask: float
    spread: float
    oi: int
    volume: int
    delta: float
    gamma: float
    theta: float
    iv: float

    # TimesFM-derived quantitative metrics
    expected_delta_v: float       # Predicted option price change E[ΔV]
    expected_roc: float           # Expected Return on Capital (E[ΔV] - 0.5*spread) / LTP
    downside_risk: float          # Adverse loss under p10/p90 + theta + 0.5*spread
    timesfm_edge: float           # E[ΔV] / downside_risk
    theta_drain_ratio: float      # (Theta * hold_time) / E[ΔV]
    tau_star_steps: int           # Predicted peak velocity step horizon
    tau_star_minutes: float       # Horizon in minutes
    is_theta_viable: bool         # theta_drain_ratio <= max_theta_ratio
    composite_score: float        # Final ranking score [0, 100]


def find_velocity_horizon(
    forecast: TimesFMForecast,
    direction: str,
    min_steps: int = 2,
) -> Tuple[int, float]:
    """Identify the optimal step horizon tau* where price velocity / momentum peaks.

    Args:
        forecast: TimesFM multi-step forecast containing p50, p10, p90.
        direction: "LONG" | "SHORT" | "BULLISH" | "BEARISH".
        min_steps: Minimum holding horizon (default 2 bars).

    Returns:
        (tau_star_steps, expected_drift_points)
    """
    p50 = forecast.p50_path
    curr = forecast.curr_price
    horizon = len(p50)
    is_long = direction.upper() in ("LONG", "BULLISH", "BUY")

    if is_long:
        # Find step with maximum upward drift
        diffs = p50 - curr
        best_step = int(np.argmax(diffs))
        best_drift = float(diffs[best_step])
        # Enforce minimum steps
        best_step = max(min_steps, best_step)
        best_drift = float(p50[min(best_step, horizon - 1)] - curr)
    else:
        # Find step with maximum downward drift
        diffs = curr - p50
        best_step = int(np.argmax(diffs))
        best_drift = float(diffs[best_step])
        best_step = max(min_steps, best_step)
        best_drift = float(curr - p50[min(best_step, horizon - 1)])

    return best_step + 1, max(0.0, best_drift)


def simulate_contract_payoff(
    opt: Any,
    strike: int,
    option_type: str,
    underlying: str,
    expiry_str: str,
    forecast: TimesFMForecast,
    direction: str,
    bar_duration_minutes: float = 5.0,
    max_theta_ratio: float = 0.25,
) -> Optional[ScoredOptionContract]:
    """Evaluate a single option contract against TimesFM underlying forecast using Greeks.

    Second-order Taylor expansion:
        E[ΔV] ≈ |Δ| · ΔS + ½ · Γ · (ΔS)² - |Θ| · Δt + ν · Δσ

    Downside risk:
        Risk = |Δ| · ΔS_adverse + |Θ| · Δt + ½ · spread
    """
    ltp = float(opt.ltp or 0.0)
    if ltp <= 0.0:
        return None

    bid = float(opt.bid or 0.0)
    ask = float(opt.ask or 0.0)
    spread = ask - bid if (bid > 0 and ask > 0 and ask >= bid) else max(0.05, ltp * 0.005)
    oi = int(opt.oi or 0)
    volume = int(opt.volume or 0)

    # Greeks resolution
    delta = abs(float(getattr(opt, "delta", 0.5) or 0.5))
    gamma = float(getattr(opt, "gamma", 0.0) or 0.0)
    theta = abs(float(getattr(opt, "theta", 0.0) or 0.0))
    iv = float(getattr(opt, "iv", 0.0) or 0.0)

    # 1. Identify velocity horizon tau* and expected drift
    tau_star, drift_pts = find_velocity_horizon(forecast, direction)
    tau_minutes = tau_star * bar_duration_minutes
    # Holding fraction of a day (1440 minutes in a 24h day, standard in selector)
    hold_days = max(1e-4, tau_minutes / 1440.0)

    # 2. Expected Option Premium Change E[ΔV]
    # Delta term
    delta_gain = delta * drift_pts
    # Gamma acceleration term
    gamma_gain = 0.5 * gamma * (drift_pts ** 2) if gamma > 0 else 0.0
    # Theta decay cost
    theta_cost = theta * hold_days

    # Vega term: compare TimesFM quantile spread vs IV
    # Estimate forecast annualized volatility
    curr_price = max(1e-4, forecast.curr_price)
    annualized_factor = math.sqrt(252.0 * 1440.0 / max(1.0, tau_minutes))
    forecast_vol_pct = (forecast.q_spread / curr_price) * annualized_factor * 100.0 if forecast.q_spread > 0 else 0.0
    vega = float(getattr(opt, "vega", 0.0) or 0.0)
    vega_gain = 0.0
    if vega > 0 and iv > 0 and forecast_vol_pct > 0:
        vol_diff = min(20.0, max(-20.0, forecast_vol_pct - iv))
        vega_gain = vega * (vol_diff / 100.0)

    expected_delta_v = max(0.0, delta_gain + gamma_gain - theta_cost + vega_gain)

    # 3. Downside risk under 10th/90th percentile adverse excursion
    is_long = direction.upper() in ("LONG", "BULLISH", "BUY")
    idx = min(tau_star - 1, len(forecast.p10_path) - 1)
    if is_long:
        adverse_pts = max(0.0, forecast.curr_price - float(forecast.p10_path[idx]))
    else:
        adverse_pts = max(0.0, float(forecast.p90_path[idx]) - forecast.curr_price)

    downside_risk = (delta * adverse_pts) + theta_cost + (0.5 * spread)
    downside_risk = max(0.5 * spread, downside_risk)

    # 4. Expected Return on Capital (ROC) and TimesFM Edge
    expected_roc = (expected_delta_v - (0.5 * spread)) / max(0.1, ltp)
    timesfm_edge = expected_delta_v / max(0.05, downside_risk)

    # 5. Theta Drain Ratio & Viability
    theta_drain_ratio = theta_cost / max(0.01, expected_delta_v)
    is_theta_viable = bool(theta_drain_ratio <= max_theta_ratio)

    # 6. Composite Scoring [0, 100]
    score = 0.0

    # A. Liquidity & Spread Quality (max 30 pts)
    spread_pct = (spread / ltp) * 100.0
    if spread_pct <= 0.5:
        score += 15.0
    elif spread_pct <= 2.0:
        score += max(0.0, 15.0 - (spread_pct - 0.5) * 6.0)

    if volume > 5000:
        score += 15.0
    elif volume > 500:
        score += 10.0
    elif volume > 0:
        score += 5.0

    # B. Expected ROC (max 35 pts)
    # 10% expected gain -> 15 pts, 30% -> 30 pts, 40%+ -> 35 pts
    roc_pts = min(35.0, max(0.0, expected_roc * 100.0))
    score += roc_pts

    # C. TimesFM Edge (Risk/Reward) (max 25 pts)
    # Edge of 2.0 -> 20 pts, 2.5+ -> 25 pts
    edge_pts = min(25.0, max(0.0, timesfm_edge * 10.0))
    score += edge_pts

    # D. Velocity-Aware Gamma Bonus vs Theta Penalty (max 10 pts)
    if tau_star <= 6 and gamma > 0:
        # Fast impulse setup: reward high gamma
        score += 10.0
    elif tau_star >= 15:
        # Slow drift setup: reward higher delta / lower theta
        if delta >= 0.60:
            score += 8.0
        elif delta <= 0.40:
            score -= 5.0

    # Hard theta penalty if theta eats > 25% of expected move
    if not is_theta_viable:
        score = max(0.0, score - 25.0)

    # Delta sweet spot [0.40, 0.70]
    if not (0.30 <= delta <= 0.75):
        score = max(0.0, score - 15.0)

    return ScoredOptionContract(
        symbol=getattr(opt, "symbol", f"{underlying} {strike} {option_type}"),
        underlying=underlying,
        strike=strike,
        option_type=option_type,
        expiry=expiry_str,
        ltp=round(ltp, 2),
        bid=round(bid, 2),
        ask=round(ask, 2),
        spread=round(spread, 2),
        oi=oi,
        volume=volume,
        delta=round(delta, 3),
        gamma=round(gamma, 5),
        theta=round(theta, 3),
        iv=round(iv, 2),
        expected_delta_v=round(expected_delta_v, 2),
        expected_roc=round(expected_roc, 4),
        downside_risk=round(downside_risk, 2),
        timesfm_edge=round(timesfm_edge, 3),
        theta_drain_ratio=round(theta_drain_ratio, 4),
        tau_star_steps=tau_star,
        tau_star_minutes=tau_minutes,
        is_theta_viable=is_theta_viable,
        composite_score=round(max(0.0, min(100.0, score)), 1),
    )


class TimesFMOptionSelector:
    """Quantitative selector that ranks option chain contracts using TimesFM."""

    def __init__(
        self,
        bar_duration_minutes: float = 5.0,
        max_theta_ratio: float = 0.25,
        min_oi: int = 50,
        min_volume: int = 10,
    ) -> None:
        self.bar_duration_minutes = bar_duration_minutes
        self.max_theta_ratio = max_theta_ratio
        self.min_oi = min_oi
        self.min_volume = min_volume

    def evaluate_chain(
        self,
        chain: Any,
        underlying: str,
        forecast: TimesFMForecast,
        direction: str,
        preferred_option_type: Optional[str] = None,
        strikes_around_atm: int = 3,
    ) -> List[ScoredOptionContract]:
        """Evaluate candidate strikes in an option chain and rank by TimesFM score.

        Args:
            chain: Option chain object with calls, puts, atm_strike, expiry.
            underlying: Asset symbol root (e.g. NIFTY, CRUDEOIL).
            forecast: Pre-computed TimesFMForecast on the underlying.
            direction: Directional thesis ("LONG" or "SHORT").
            preferred_option_type: Optional filter ("CE" or "PE").
            strikes_around_atm: Number of strikes above and below ATM to evaluate.

        Returns:
            Sorted list of ScoredOptionContract, highest composite score first.
        """
        if chain is None or forecast is None:
            return []

        # Directional mapping: LONG underlying -> CE, SHORT underlying -> PE
        is_long = direction.upper() in ("LONG", "BULLISH", "BUY")
        opt_type = "CE" if is_long else "PE"
        if preferred_option_type:
            opt_type = preferred_option_type.upper()

        opt_map = chain.calls if opt_type == "CE" else chain.puts
        if not opt_map:
            return []

        atm = float(chain.atm_strike or forecast.curr_price)
        listed_strikes = sorted([float(s) for s in opt_map.keys()])
        if not listed_strikes:
            return []

        # Snap to nearest listed strike
        closest_atm = min(listed_strikes, key=lambda s: abs(s - atm))
        atm_idx = listed_strikes.index(closest_atm)

        # Slice candidate strikes around ATM
        start_idx = max(0, atm_idx - strikes_around_atm)
        end_idx = min(len(listed_strikes), atm_idx + strikes_around_atm + 1)
        candidate_strikes = listed_strikes[start_idx:end_idx]

        expiry_str = (
            chain.expiry.date().isoformat()
            if hasattr(chain.expiry, "date")
            else (chain.expiry.isoformat() if hasattr(chain.expiry, "isoformat") else str(chain.expiry))
        )

        scored: List[ScoredOptionContract] = []
        for s in candidate_strikes:
            opt = opt_map.get(s)
            if opt is None:
                continue

            # Basic liquidity gate
            if int(opt.volume or 0) < self.min_volume and int(opt.oi or 0) < self.min_oi:
                continue

            contract = simulate_contract_payoff(
                opt=opt,
                strike=int(s),
                option_type=opt_type,
                underlying=underlying,
                expiry_str=expiry_str,
                forecast=forecast,
                direction=direction,
                bar_duration_minutes=self.bar_duration_minutes,
                max_theta_ratio=self.max_theta_ratio,
            )
            if contract is not None and contract.composite_score > 0.0:
                scored.append(contract)

        # Rank by composite score descending
        scored.sort(key=lambda c: -c.composite_score)
        return scored
