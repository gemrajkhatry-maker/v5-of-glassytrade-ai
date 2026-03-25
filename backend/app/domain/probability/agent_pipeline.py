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

from app.domain.trading.models.enums import MarketStateCodec

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

    direction: str  # "LONG", "SHORT", or "FLAT"
    probability: float  # P(target hit) for chosen direction
    regime: str  # "TRENDING", "BALANCED", "VOLATILE", "DEAD"
    playbook: str  # "imbalance_continuation" | "return_to_value" | ""
    timing: str  # "ENTER_NOW", "WAIT", "SKIP"
    size_fraction: float  # Kelly-optimal fraction of capital [0, 1]
    sl_adjust: float  # Multiplier for SL distance (1.0 = default)
    tp_adjust: float  # Multiplier for TP distance (1.0 = default)
    latency_us: int  # Pipeline latency in microseconds
    rationale: str  # Human-readable summary
    feature_drivers: tuple[str, ...] = ()  # Top auction/order-flow drivers


# ---------------------------------------------------------------------------
# Agent 1: Regime Classification (rule-based, ~0.05ms)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeState:
    regime: str  # TRENDING, BALANCED, VOLATILE, DEAD
    allowed_long: bool
    allowed_short: bool
    risk_scale: float  # 0.0 = no risk, 1.0 = full risk


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
    latest_vol = (
        data[-1].volume
        if data[-1].time != tick.time
        else (data[-2].volume if len(data) >= 2 else tick.volume)
    )
    vol_ratio = latest_vol / ema_vol if ema_vol > 0 else 0

    # Only flag DEAD if volume is truly negligible (<5% of EMA).
    if vol_ratio < 0.05:
        logger.info(
            "Regime: DEAD — vol_ratio=%.3f (latest_vol=%.0f, ema=%.0f)",
            vol_ratio,
            latest_vol,
            ema_vol,
        )
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
    if MarketStateCodec.is_imbalanced(amt_result.market_state):
        return RegimeState("TRENDING", True, True, 1.0 * atr_pct_scale)

    return RegimeState("BALANCED", True, True, 1.0 * atr_pct_scale)


# ---------------------------------------------------------------------------
# Agent 2: Direction (LightGBM probability — already trained)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectionSignal:
    direction: str  # LONG, SHORT, FLAT
    p_long: float
    p_short: float
    edge: float  # p_chosen - base_rate


def pick_direction(
    features: dict[str, float],
    probability_engine: ProbabilityInferencePort,
    regime: RegimeState,
    playbook: str,
    p_threshold_long: float = 0.52,  # positive edge at 2:1 R/R
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

    # Direction selection — LLM decides when probabilities are close
    # If one direction has clear edge (>margin), use it
    # If probabilities are close (within margin), pass both to LLM for reading
    if p_long >= p_threshold_long and p_long > p_short + margin and regime.allowed_long:
        return DirectionSignal("LONG", p_long, p_short, p_long - 0.27)
    elif (
        p_short >= p_threshold_short
        and p_short > p_long + margin
        and regime.allowed_short
    ):
        return DirectionSignal("SHORT", p_long, p_short, p_short - 0.29)
    elif abs(p_long - p_short) < margin and max(p_long, p_short) >= 0.50:
        # Close probabilities — let LLM read the market
        # Pick the higher probability direction as suggestion
        direction = "LONG" if p_long >= p_short else "SHORT"
        prob = max(p_long, p_short)
        edge = abs(p_long - p_short)
        return DirectionSignal(direction, p_long, p_short, edge)
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
    playbook: str,
) -> str:
    """Decide whether to enter NOW or WAIT for a better price.

    Rules:
    - If price just spiked (bar range > 2x ATR5): WAIT (chasing)
    - If entering LONG and close is near bar high (>80% of range): WAIT
    - If entering SHORT and close is near bar low (<20% of range): WAIT
    - If aggressive print in our direction within last bar: ENTER_NOW (momentum)
    - If delta = 0 and no aggressive prints: WAIT (no directional commitment)
    - Default: ENTER_NOW
    """
    if len(data) < 5:
        return "ENTER_NOW"

    atr5 = sum(d.high - d.low for d in data[-5:]) / 5
    bar_range = tick.high - tick.low

    # Don't chase extreme spikes (3x ATR = genuine anomaly, not normal moves)
    if atr5 > 0 and bar_range > 3.0 * atr5:
        return "WAIT"

    # ── UNIVERSAL DELTA GATE (applies to ALL playbooks) ──
    # Fabio rule: no entry without directional commitment from order flow.
    # Delta < 1.5 means insufficient buy/sell imbalance for a trade signal.
    # This catches ENTER_NOW on low/zero delta for all playbooks.
    delta_abs = abs(float(getattr(tick, "delta", 0) or 0))
    has_aggression = bool(amt_result.aggressive_prints)
    if delta_abs < 1.5 and not has_aggression:
        return "WAIT"  # Low delta + no prints = no directional commitment

    # Also block if CVD contradicts direction significantly
    from app.domain.constants import CVD_SLOPE_HARD_BLOCK

    cvd_slope = float(getattr(amt_result, "cvd_slope", 0) or 0)
    if direction == "LONG" and cvd_slope < -CVD_SLOPE_HARD_BLOCK:
        return "WAIT"  # Strong bearish CVD contradicts LONG
    if direction == "SHORT" and cvd_slope > CVD_SLOPE_HARD_BLOCK:
        return "WAIT"  # Strong bullish CVD contradicts SHORT

    # Mean reversion must not enter back at fair value.
    if playbook == "return_to_value":
        va_width = abs(amt_result.value_area_high - amt_result.value_area_low)
        if va_width > 0 and abs(tick.close - amt_result.poc) < va_width * 0.25:
            return "SKIP"
        if direction == "LONG" and tick.close > amt_result.poc:
            return "WAIT"
        if direction == "SHORT" and tick.close < amt_result.poc:
            return "WAIT"

    # Trend continuation should not trigger back inside balance.
    if playbook == "imbalance_continuation":
        if direction == "LONG" and tick.close < amt_result.poc:
            return "WAIT"
        if direction == "SHORT" and tick.close > amt_result.poc:
            return "WAIT"

    # PROBING breakout requires aggression confirmation — cannot enter on delta=0
    # Fabio rule: unconfirmed breaks need institutional aggression to validate
    if playbook == "probing_breakout":
        if not amt_result.aggressive_prints:
            return "WAIT"  # No aggression = watch, don't enter
        aggression = float(getattr(amt_result, "aggression", 0) or 0)
        if aggression < 2.0:
            return "WAIT"  # Insufficient aggression for breakout entry

    # Aggressive print momentum — enter NOW
    if amt_result.aggressive_prints:
        last_print = amt_result.aggressive_prints[-1]
        if direction == "LONG" and last_print.side == "BUY":
            return "ENTER_NOW"
        if direction == "SHORT" and last_print.side == "SELL":
            return "ENTER_NOW"

    return "ENTER_NOW"


def select_playbook(regime: RegimeState, amt_result: AMTResult) -> str:
    """Map regime and auction state to one of the canonical playbooks."""
    ms = getattr(amt_result, "market_state", "")
    if regime.regime == "TRENDING" and MarketStateCodec.is_imbalanced(ms):
        return "imbalance_continuation"
    if regime.regime == "BALANCED" and MarketStateCodec.is_balanced(ms):
        return "return_to_value"
    # PROBING playbook: unconfirmed break with aggression confirmation
    # Supports acceptance (continuation) and rejection (fade) scenarios
    if MarketStateCodec.is_probing(ms):
        return "probing_breakout"
    return ""


def playbook_thresholds(playbook: str) -> tuple[float, float, float]:
    """Return (p_threshold_long, p_threshold_short, margin) for a playbook."""
    if playbook == "imbalance_continuation":
        return 0.55, 0.53, 0.04
    if playbook == "return_to_value":
        return 0.51, 0.51, 0.02
    if playbook == "probing_breakout":
        # PROBING requires higher conviction (unconfirmed break)
        return 0.58, 0.58, 0.06
    return 0.60, 0.60, 0.05


def summarize_feature_drivers(
    features: dict[str, float],
    direction: str,
    playbook: str,
    amt_result: AMTResult,
) -> tuple[str, ...]:
    """Return concise, auction-aware reasons behind the current signal."""
    is_long = direction == "LONG"
    ms = getattr(amt_result, "market_state", "")
    drivers: list[tuple[float, str]] = []

    if playbook == "imbalance_continuation" and MarketStateCodec.is_imbalanced(ms):
        drivers.append((1.2, "auction: imbalance accepted"))
    elif playbook == "return_to_value" and MarketStateCodec.is_balanced(ms):
        drivers.append((1.2, "auction: balanced rotation"))
    elif playbook == "probing_breakout" and MarketStateCodec.is_probing(ms):
        drivers.append((1.2, "auction: probing outside value"))

    if abs(features.get("nearest_lvn_distance_pct", 1.0)) <= 0.003:
        drivers.append((1.0, "location: near LVN"))

    if playbook == "imbalance_continuation":
        vah_gap = abs(features.get("close_vs_vah_pct", 1.0))
        if vah_gap <= 0.004:
            drivers.append((0.9, "location: pressing VAH"))
    elif playbook == "return_to_value":
        val_gap = abs(features.get("close_vs_val_pct", 1.0))
        if val_gap <= 0.004:
            drivers.append((0.9, "location: probing VAL"))
    elif playbook == "probing_breakout":
        vah_gap = abs(features.get("close_vs_vah_pct", 1.0))
        val_gap = abs(features.get("close_vs_val_pct", 1.0))
        if vah_gap <= 0.004:
            drivers.append((0.9, "location: testing VAH"))
        elif val_gap <= 0.004:
            drivers.append((0.9, "location: testing VAL"))

    directional_checks = [
        ("delta_normalized", "orderflow: positive delta", "orderflow: negative delta"),
        ("cvd_slope", "orderflow: rising CVD", "orderflow: falling CVD"),
        (
            "aggressive_print_imbalance",
            "aggression: buy prints dominate",
            "aggression: sell prints dominate",
        ),
        (
            "book_imbalance_l1",
            "liquidity: bid stack stronger",
            "liquidity: ask stack stronger",
        ),
        (
            "book_imbalance_l5",
            "liquidity: depth supports bid",
            "liquidity: depth supports ask",
        ),
    ]
    for feature_name, long_label, short_label in directional_checks:
        value = float(features.get(feature_name, 0.0))
        aligned = value if is_long else -value
        if aligned > 0.05:
            drivers.append((min(aligned, 1.0), long_label if is_long else short_label))

    volume_expansion = float(features.get("volume_vs_ema20", 1.0))
    if volume_expansion > 1.1:
        drivers.append(
            (min(volume_expansion - 1.0, 1.0), "participation: volume expansion")
        )

    atr_ratio = float(features.get("atr_ratio", 1.0))
    if playbook == "imbalance_continuation" and atr_ratio > 1.15:
        drivers.append((min(atr_ratio - 1.0, 1.0), "range: volatility expanding"))

    if playbook == "return_to_value":
        balance_ratio = float(features.get("balance_ratio", 0.0))
        if balance_ratio >= 0.55:
            drivers.append((min(balance_ratio, 1.0), "auction: value holding"))

    ordered = sorted(drivers, key=lambda item: item[0], reverse=True)
    top_labels: list[str] = []
    for _, label in ordered:
        if label not in top_labels:
            top_labels.append(label)
        if len(top_labels) == 3:
            break
    if top_labels and not any(
        label.startswith(("orderflow:", "aggression:", "liquidity:"))
        for label in top_labels
    ):
        for _, label in ordered:
            if (
                label.startswith(("orderflow:", "aggression:", "liquidity:"))
                and label not in top_labels
            ):
                top_labels[-1] = label
                break
    return tuple(top_labels)


# ---------------------------------------------------------------------------
# Agent 4: Position Sizing (Kelly criterion)
# ---------------------------------------------------------------------------


def kelly_size(
    probability: float,
    win_pct: float = 0.015,  # 1.5% target
    loss_pct: float = 0.0075,  # 0.75% stop
    max_fraction: float = 0.25,
    risk_scale: float = 1.0,
    win_rate_sample_size: int = 0,  # NEW: for conservative capping
) -> float:
    """Half-Kelly position sizing from probability estimate.

    Kelly fraction = (p * b - q) / b
    where p = win probability, q = 1-p, b = win/loss ratio.

    We use HALF-Kelly for safety (reduces variance by 75%).

    FIX 0.2: Hard cap Kelly at 0.5% risk until backtested.
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

    # FIX 0.2: Conservative cap for unproven models
    # FIX: When no real trade data, use Fabio's conservative default (0.25%)
    MAX_KELLY_UNPROVEN = 0.0025  # 0.25% Fabio conservative default
    MAX_KELLY_PROVEN = 0.005  # 0.5% max when proven (30+ trades)

    if win_rate_sample_size < 30:
        # No proven track record — use conservative Kelly
        half_kelly = min(half_kelly, MAX_KELLY_UNPROVEN)
    else:
        # Proven track record — allow up to 0.5%
        half_kelly = min(half_kelly, MAX_KELLY_PROVEN)

    # Final cap against max_fraction
    half_kelly = min(half_kelly, max_fraction)

    return half_kelly


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
) -> AgentDecision:
    """Run the full 4-agent pipeline. Target: <1ms total."""
    t0 = time.perf_counter_ns()

    # Agent 1: Regime
    regime = classify_regime(data, amt_result, tick)
    if regime.regime == "DEAD":
        elapsed_us = (time.perf_counter_ns() - t0) // 1000
        return AgentDecision(
            direction="FLAT",
            probability=0.0,
            regime="DEAD",
            playbook="",
            timing="SKIP",
            size_fraction=0.0,
            sl_adjust=1.0,
            tp_adjust=1.0,
            latency_us=elapsed_us,
            rationale="Dead market — volume < 5% of average",
        )

    playbook = select_playbook(regime, amt_result)
    if not playbook:
        elapsed_us = (time.perf_counter_ns() - t0) // 1000
        return AgentDecision(
            direction="FLAT",
            probability=0.0,
            regime=regime.regime,
            playbook="",
            timing="SKIP",
            size_fraction=0.0,
            sl_adjust=1.0,
            tp_adjust=1.0,
            latency_us=elapsed_us,
            rationale=f"No canonical playbook for regime={regime.regime} market_state={amt_result.market_state}",
        )

    # Agent 2: Direction
    p_threshold_long, p_threshold_short, margin = playbook_thresholds(playbook)
    signal = pick_direction(
        features,
        probability_engine,
        regime,
        playbook,
        p_threshold_long=p_threshold_long,
        p_threshold_short=p_threshold_short,
        margin=margin,
    )
    if signal.direction == "FLAT":
        elapsed_us = (time.perf_counter_ns() - t0) // 1000
        return AgentDecision(
            direction="FLAT",
            probability=max(signal.p_long, signal.p_short),
            regime=regime.regime,
            playbook=playbook,
            timing="SKIP",
            size_fraction=0.0,
            sl_adjust=1.0,
            tp_adjust=1.0,
            latency_us=elapsed_us,
            rationale=(
                f"{playbook} | No edge — P(long)={signal.p_long:.3f} "
                f"P(short)={signal.p_short:.3f}"
            ),
        )

    # Agent 3: Timing
    timing = assess_timing(data, tick, amt_result, signal.direction, playbook)

    # Agent 4: Sizing
    chosen_p = signal.p_long if signal.direction == "LONG" else signal.p_short
    size = kelly_size(chosen_p, risk_scale=regime.risk_scale)

    # Get predicted MFE from probability engine for dynamic TP
    est = probability_engine.estimate(features)
    predicted_mfe = (
        est.expected_mfe_long if signal.direction == "LONG" else est.expected_mfe_short
    )
    sl_mult, tp_mult = adjust_sl_tp(
        signal.direction, regime.regime, chosen_p, predicted_mfe=predicted_mfe
    )
    feature_drivers = summarize_feature_drivers(
        features, signal.direction, playbook, amt_result
    )

    elapsed_us = (time.perf_counter_ns() - t0) // 1000

    rationale = (
        f"{playbook} | {regime.regime} regime | {signal.direction} P={chosen_p:.3f} edge={signal.edge:+.3f} | "
        f"{timing} | Kelly={size:.1%} | SL×{sl_mult:.2f} TP×{tp_mult:.2f}"
    )

    return AgentDecision(
        direction=signal.direction,  # Always pass direction to LLM (let LLM decide)
        probability=chosen_p,
        regime=regime.regime,
        playbook=playbook,
        timing=timing,  # Timing is informational, not a gate
        size_fraction=size if timing == "ENTER_NOW" else 0.0,
        sl_adjust=sl_mult,
        tp_adjust=tp_mult,
        latency_us=elapsed_us,
        rationale=rationale,
        feature_drivers=feature_drivers,
    )
