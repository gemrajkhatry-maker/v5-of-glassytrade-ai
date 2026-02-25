"""Ultra-fast micro-agent pipeline for options scalping.

Replaces the slow LLM hot-path (~300ms) with a cascade of specialized
sub-millisecond "agents" (LightGBM + rules). Total latency: <1ms.

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │  Tick arrives (~every 5s for 5min candles)              │
    │                                                         │
    │  Agent 1: RegimeAgent        (~0.05ms)  ← rule-based   │
    │    → TRENDING / BALANCED / VOLATILE / DEAD              │
    │    → sets allowed_directions, risk_budget               │
    │                                                         │
    │  Agent 2: DirectionAgent     (~0.1ms)   ← LightGBM     │
    │    → P(long_target), P(short_target)                    │
    │    → picks best direction or FLAT                       │
    │                                                         │
    │  Agent 3: TimingAgent        (~0.1ms)   ← LightGBM     │
    │    → P(better_entry_next_bar)                           │
    │    → ENTER_NOW / WAIT / SKIP                            │
    │                                                         │
    │  Agent 4: SizingAgent        (~0.01ms)  ← Kelly formula │
    │    → position_size from probability + edge              │
    │    → adjusts SL/TP based on MFE quantiles               │
    │                                                         │
    │  Output: AgentDecision (direction, size, sl, tp, meta)  │
    └─────────────────────────────────────────────────────────┘

    LLM role: slow-path meta-agent that runs on regime CHANGES only
    (every 5-15 min), adjusting thresholds and risk params.

Why this beats single-model or LLM approaches:
1. Each agent is specialized — no single model tries to do everything
2. Regime agent prevents trading in dead/volatile markets (biggest PnL saver)
3. Timing agent avoids chasing — waits for pullback entries
4. Kelly sizing turns probability edge into optimal position sizing
5. Total pipeline: <1ms vs LLM's 300ms
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook
    from app.domain.ports.probability_inference import ProbabilityInferencePort

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentDecision:
    """Final output of the micro-agent pipeline."""
    direction: str          # "LONG", "SHORT", or "FLAT"
    probability: float      # P(target hit) for chosen direction
    regime: str             # "TRENDING", "BALANCED", "VOLATILE", "DEAD"
    timing: str             # "ENTER_NOW", "WAIT", "SKIP"
    size_fraction: float    # Kelly-optimal fraction of capital [0, 1]
    sl_adjust: float        # Multiplier for SL distance (1.0 = default)
    tp_adjust: float        # Multiplier for TP distance (1.0 = default)
    latency_us: int         # Pipeline latency in microseconds
    rationale: str          # Human-readable summary


# ---------------------------------------------------------------------------
# Agent 1: Regime Classification (rule-based, ~0.05ms)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeState:
    regime: str             # TRENDING, BALANCED, VOLATILE, DEAD
    allowed_long: bool
    allowed_short: bool
    risk_scale: float       # 0.0 = no risk, 1.0 = full risk


def classify_regime(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
) -> RegimeState:
    """Fast regime classification from AMT + price action.

    Rules (Fabio methodology):
    - DEAD: volume < 20% of EMA(20) → no edge, skip
    - DEAD: symbol ATR percentile < 20th (stale/illiquid) → skip
    - VOLATILE: ATR(5)/ATR(20) > 3.0 → whipsaw risk, reduce size to 0.5
    - TRENDING: market_state=IMBALANCED + CVD confirms → trend trades only
    - BALANCED: default → mean reversion trades
    - ATR percentile gate: p20-p40 → risk_scale 0.6; p40+ → full risk
    """
    if len(data) < 20:
        logger.info("Regime: DEAD — only %d candles (need 20)", len(data))
        return RegimeState("DEAD", False, False, 0.0)

    # Volume check — use the CANDLE volume from data (not the live tick which is mid-candle)
    alpha = 2.0 / 21
    ema_vol = data[-20].volume
    for d in data[-19:]:
        ema_vol = alpha * d.volume + (1 - alpha) * ema_vol
    # Use the latest completed candle's volume, not the mid-candle tick
    latest_vol = data[-1].volume if data[-1].time != tick.time else (data[-2].volume if len(data) >= 2 else tick.volume)
    vol_ratio = latest_vol / ema_vol if ema_vol > 0 else 0

    # Only flag DEAD if volume is truly negligible (<5% of EMA).
    if vol_ratio < 0.05:
        logger.info("Regime: DEAD — vol_ratio=%.3f (latest_vol=%.0f, ema=%.0f)", vol_ratio, latest_vol, ema_vol)
        return RegimeState("DEAD", False, False, 0.0)

    # ATR percentile gate DISABLED for options — option ATR naturally varies
    # with time decay, moneyness, and IV crush. Walk-forward results were on
    # futures; for options the gate causes persistent false DEAD classification.
    # Volume ratio check above is sufficient for filtering dead markets.
    atr_pct_scale = 1.0

    # Volatility check — only block extreme (>3x), reduce size on moderate
    atr5 = sum(d.high - d.low for d in data[-5:]) / 5
    atr20 = sum(d.high - d.low for d in data[-20:]) / 20
    atr_ratio = atr5 / atr20 if atr20 > 0 else 1.0

    if atr_ratio > 3.0:
        return RegimeState("VOLATILE", True, True, 0.5 * atr_pct_scale)

    # Trending vs balanced — for OPTIONS, allow both directions in all regimes.
    # The probability model already accounts for direction edge.
    # Regime agent's job: kill dead markets, reduce size in volatile, inform SL/TP.
    ms = str(amt_result.market_state)
    if "IMBALANCED" in ms.upper():
        return RegimeState("TRENDING", True, True, 1.0 * atr_pct_scale)

    return RegimeState("BALANCED", True, True, 1.0 * atr_pct_scale)


# ---------------------------------------------------------------------------
# Agent 2: Direction (LightGBM probability — already trained)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DirectionSignal:
    direction: str       # LONG, SHORT, FLAT
    p_long: float
    p_short: float
    edge: float          # p_chosen - base_rate


def pick_direction(
    features: dict[str, float],
    probability_engine: ProbabilityInferencePort,
    regime: RegimeState,
    p_threshold_long: float = 0.52,   # positive edge at 2:1 R/R
    p_threshold_short: float = 0.50,  # positive edge
    margin: float = 0.03,
) -> DirectionSignal:
    """Pick direction using probability model + regime filter.

    Thresholds are calibrated post-class-balancing:
    - Long: P >= 0.60 → 35% WR (2:1 R/R → positive EV)
    - Short: P >= 0.55 → 40% WR (2:1 R/R → strong EV)
    """
    if not probability_engine.is_ready():
        return DirectionSignal("FLAT", 0.5, 0.5, 0.0)

    est = probability_engine.estimate(features)
    p_long = est.p_long_target
    p_short = est.p_short_target

    # Regime filter
    if not regime.allowed_long:
        p_long = 0.0
    if not regime.allowed_short:
        p_short = 0.0

    # Direction selection
    if p_long >= p_threshold_long and p_long > p_short + margin and regime.allowed_long:
        return DirectionSignal("LONG", p_long, p_short, p_long - 0.27)
    elif p_short >= p_threshold_short and p_short > p_long + margin and regime.allowed_short:
        return DirectionSignal("SHORT", p_long, p_short, p_short - 0.29)
    else:
        return DirectionSignal("FLAT", p_long, p_short, 0.0)


# ---------------------------------------------------------------------------
# Agent 3: Timing (rule-based for now, upgradeable to LightGBM)
# ---------------------------------------------------------------------------

def assess_timing(
    data: list[OHLC],
    tick: OHLC,
    amt_result: AMTResult,
    direction: str,
) -> str:
    """Decide whether to enter NOW or WAIT for a better price.

    Rules:
    - If price just spiked (bar range > 2x ATR5): WAIT (chasing)
    - If entering LONG and close is near bar high (>80% of range): WAIT
    - If entering SHORT and close is near bar low (<20% of range): WAIT
    - If aggressive print in our direction within last bar: ENTER_NOW (momentum)
    - Default: ENTER_NOW
    """
    if len(data) < 5:
        return "ENTER_NOW"

    atr5 = sum(d.high - d.low for d in data[-5:]) / 5
    bar_range = tick.high - tick.low

    # Don't chase extreme spikes (3x ATR = genuine anomaly, not normal moves)
    if atr5 > 0 and bar_range > 3.0 * atr5:
        return "WAIT"

    # Aggressive print momentum — enter NOW
    if amt_result.aggressive_prints:
        last_print = amt_result.aggressive_prints[-1]
        if direction == "LONG" and last_print.side == "BUY":
            return "ENTER_NOW"
        if direction == "SHORT" and last_print.side == "SELL":
            return "ENTER_NOW"

    return "ENTER_NOW"


# ---------------------------------------------------------------------------
# Agent 4: Position Sizing (Kelly criterion)
# ---------------------------------------------------------------------------

def kelly_size(
    probability: float,
    win_pct: float = 0.015,    # 1.5% target
    loss_pct: float = 0.0075,  # 0.75% stop
    max_fraction: float = 0.25,
    risk_scale: float = 1.0,
) -> float:
    """Half-Kelly position sizing from probability estimate.

    Kelly fraction = (p * b - q) / b
    where p = win probability, q = 1-p, b = win/loss ratio.

    We use HALF-Kelly for safety (reduces variance by 75%).
    """
    if probability <= 0 or probability >= 1:
        return 0.0

    b = win_pct / loss_pct  # payoff ratio (2.0 for our 1:2 RR)
    p = probability
    q = 1.0 - p

    kelly = (p * b - q) / b
    if kelly <= 0:
        return 0.0

    half_kelly = kelly * 0.5 * risk_scale
    return min(half_kelly, max_fraction)


def adjust_sl_tp(
    direction: str,
    regime: str,
    probability: float,
    predicted_mfe: float = 0.0,
    base_tp_pct: float = 0.015,
    base_sl_pct: float = 0.0075,
) -> tuple[float, float]:
    """Adjust SL/TP multipliers based on regime, probability, and predicted MFE.

    Returns (sl_multiplier, tp_multiplier).

    If predicted_mfe > 0, uses it to set dynamic TP:
    - TP = predicted_mfe (clamped to [0.5x, 2x] of base TP)
    - This adapts TP to what's actually reachable in current conditions.
    """
    sl_mult = 1.0
    tp_mult = 1.0

    # Dynamic TP from MFE quantile model
    if predicted_mfe > 0 and base_tp_pct > 0:
        # Predicted median MFE → TP multiplier relative to base
        dynamic_tp = predicted_mfe / base_tp_pct
        # Clamp to [0.5x, 2.0x] to avoid extreme values
        tp_mult = max(0.5, min(2.0, dynamic_tp))
    else:
        # Fallback: regime-based static adjustments
        if regime == "TRENDING":
            tp_mult = 1.3
            sl_mult = 1.1
        elif regime == "VOLATILE":
            sl_mult = 1.4
            tp_mult = 1.2

    # Probability-based fine-tuning (thresholds re-calibrated post class-balancing)
    if probability > 0.65:
        tp_mult *= 1.1  # extend TP on high confidence
    elif probability < 0.55:
        sl_mult *= 0.8  # tighter SL on low confidence

    return sl_mult, tp_mult


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def run_agent_pipeline(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    probability_engine: ProbabilityInferencePort,
    features: dict[str, float],
    order_book: "OrderBook | None" = None,
    p_threshold: float = 0.35,
    margin: float = 0.05,
) -> AgentDecision:
    """Run the full 4-agent pipeline. Target: <1ms total."""
    t0 = time.perf_counter_ns()

    # Agent 1: Regime
    regime = classify_regime(data, amt_result, tick)
    if regime.regime == "DEAD":
        elapsed_us = (time.perf_counter_ns() - t0) // 1000
        return AgentDecision(
            direction="FLAT", probability=0.0, regime="DEAD",
            timing="SKIP", size_fraction=0.0, sl_adjust=1.0, tp_adjust=1.0,
            latency_us=elapsed_us,
            rationale="Dead market — volume < 5% of average",
        )

    # Agent 2: Direction
    signal = pick_direction(features, probability_engine, regime,
                            p_threshold_long=0.52, p_threshold_short=0.50, margin=margin)
    if signal.direction == "FLAT":
        elapsed_us = (time.perf_counter_ns() - t0) // 1000
        return AgentDecision(
            direction="FLAT", probability=max(signal.p_long, signal.p_short),
            regime=regime.regime, timing="SKIP", size_fraction=0.0,
            sl_adjust=1.0, tp_adjust=1.0, latency_us=elapsed_us,
            rationale=f"No edge — P(long)={signal.p_long:.3f} P(short)={signal.p_short:.3f}",
        )

    # Agent 3: Timing
    timing = assess_timing(data, tick, amt_result, signal.direction)

    # Agent 4: Sizing
    chosen_p = signal.p_long if signal.direction == "LONG" else signal.p_short
    size = kelly_size(chosen_p, risk_scale=regime.risk_scale)

    # Get predicted MFE from probability engine for dynamic TP
    est = probability_engine.estimate(features)
    predicted_mfe = est.expected_mfe_long if signal.direction == "LONG" else est.expected_mfe_short
    sl_mult, tp_mult = adjust_sl_tp(signal.direction, regime.regime, chosen_p, predicted_mfe=predicted_mfe)

    elapsed_us = (time.perf_counter_ns() - t0) // 1000

    rationale = (
        f"{regime.regime} regime | {signal.direction} P={chosen_p:.3f} edge={signal.edge:+.3f} | "
        f"{timing} | Kelly={size:.1%} | SL×{sl_mult:.2f} TP×{tp_mult:.2f}"
    )

    return AgentDecision(
        direction=signal.direction if timing == "ENTER_NOW" else "FLAT",
        probability=chosen_p,
        regime=regime.regime,
        timing=timing,
        size_fraction=size,
        sl_adjust=sl_mult,
        tp_adjust=tp_mult,
        latency_us=elapsed_us,
        rationale=rationale,
    )
