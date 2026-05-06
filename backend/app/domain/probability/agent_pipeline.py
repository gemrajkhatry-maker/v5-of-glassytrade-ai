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
from app.domain.constants import (
    CVD_SLOPE_HARD_BLOCK,
    AGENT_DECISION_THRESHOLD,
    BALANCE_RATIO_THRESHOLD,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_LOW_THRESHOLD,
)

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook
    from app.domain.ports.probability_inference import IProbabilityInference
    from app.domain.probability.regime_hysteresis_store import RegimeHysteresisStore

from app.domain.fabio_ai.services.entry_gates.three_align import three_align_check
from app.domain.fabio_ai.services.entry_gates.gate_runner import run_gate_pipeline

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


class RegimeHysteresis:
    """Adds hysteresis to regime classification to prevent rapid flipping.

    Requires the new regime to persist for `min_persistence` consecutive
    evaluations before switching. This prevents the model from oscillating
    between BALANCED and TRENDING every minute on edge cases.
    """

    def __init__(self, min_persistence: int = 3) -> None:
        self._min_persistence = min_persistence
        self._current_regime: str = ""
        self._candidate_regime: str = ""
        self._candidate_count: int = 0

    def apply(self, raw_regime: RegimeState) -> RegimeState:
        """Apply hysteresis filter to the raw regime result.

        If the raw regime matches the current stable regime, confirm immediately.
        If different, count consecutive occurrences before switching.
        DEAD regime always passes through immediately (safety).
        """
        # DEAD and VOLATILE always pass through immediately (safety)
        if raw_regime.regime in ("DEAD", "VOLATILE"):
            self._current_regime = raw_regime.regime
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # First evaluation — accept immediately
        if not self._current_regime:
            self._current_regime = raw_regime.regime
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # Same as current stable regime — confirm immediately
        if raw_regime.regime == self._current_regime:
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # Different from current — track persistence
        if raw_regime.regime == self._candidate_regime:
            self._candidate_count += 1
        else:
            self._candidate_regime = raw_regime.regime
            self._candidate_count = 1

        if self._candidate_count >= self._min_persistence:
            # Candidate has persisted long enough — switch
            logger.info(
                "Regime hysteresis: %s → %s (persisted %d evaluations)",
                self._current_regime, self._candidate_regime, self._candidate_count,
            )
            self._current_regime = self._candidate_regime
            self._candidate_regime = ""
            self._candidate_count = 0
            return raw_regime

        # Not yet stable — return current stable regime
        return RegimeState(
            regime=self._current_regime,
            allowed_long=raw_regime.allowed_long if self._current_regime == raw_regime.regime else True,
            allowed_short=raw_regime.allowed_short if self._current_regime == raw_regime.regime else True,
            risk_scale=raw_regime.risk_scale,
        )


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

    # Hard DEAD check: No price or no volume activity
    # Relaxed from 0.05 to 0.01 for MCX markets where volume can be sparse.
    if tick.close <= 0 or vol_ratio < 0.01:
        logger.info(
            "Regime: DEAD — ltp=%.2f, vol_ratio=%.3f (latest_vol=%.0f, ema=%.0f)",
            tick.close,
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
    probability_engine: IProbabilityInference,
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
    elif (
        abs(p_long - p_short) < margin
        and max(p_long, p_short) >= CONFIDENCE_LOW_THRESHOLD
    ):
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
    tick_size: float = 0.05,
    symbol: str = "",  # NEW: symbol for gate checks
    tick_age_seconds: float = 1.0,  # NEW: tick age for gate checks
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
    # FIX BUG 6C: Lowered delta threshold from 1.5 to 0.5 for options
    # Options have naturally smaller delta values (especially OTM)
    # Aggressive prints can substitute for delta confirmation
    delta_abs = abs(float(getattr(tick, "delta", 0) or 0))
    has_aggression = bool(amt_result.aggressive_prints)
    if delta_abs < 0.5 and not has_aggression:
        return "WAIT"  # Low delta + no prints = no directional commitment

    # Also block if CVD contradicts direction significantly

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

    # ── FABIO THREE-ALIGN GATE (SYNCHRONIZATION) ──
    # Mirror the actual execution gate to prevent scanner false positives.
    gate_passed, confirmation_strong = three_align_check(
        data=data,
        amt_result=amt_result,
        tick=tick,
        tick_size=tick_size,
    )
    if not gate_passed:
        return "WAIT"

    # ── FULL 12-GATE PIPELINE (EXECUTION SYNC) ──

    # Use generic thresholds for scanner; actual execution gate is still the final decider
    # symbol and tick_age_seconds are now passed from the session service
    gate_passed, gate_reason, gate_detail = run_gate_pipeline(
        data=data,
        amt_result=amt_result,
        tick=tick,
        market_state=amt_result.market_state,
        drive_number=getattr(amt_result, "drive_number", 0),
        drive_entry_valid=getattr(amt_result, "drive_entry_valid", False),
        aggression_score=amt_result.aggression,
        is_risk_halted=False,
        halt_reason="",
        tick_age_seconds=tick_age_seconds,
        symbol=symbol,
        tick_size=tick_size,
    )
    if not gate_passed:
        return "WAIT"

    # ── DISPLACEMENT LEG GATE ──
    # Fabio Rule: Don't chase displacement legs. Wait for the pullback (Phase 2).
    # If the leg status is DISPLACEMENT, we must wait.
    leg_status = getattr(amt_result, "leg_status", "")
    if leg_status == "DISPLACEMENT":
        return "WAIT"

    # Aggressive print momentum — enter NOW
    if amt_result.aggressive_prints:
        last_print = amt_result.aggressive_prints[-1]
        if direction == "LONG" and last_print.side == "BUY":
            return "ENTER_NOW"
        if direction == "SHORT" and last_print.side == "SELL":
            return "ENTER_NOW"

    return "ENTER_NOW"


def calculate_timing_probability(
    data: list[OHLC],
    tick: OHLC,
    amt_result: AMTResult,
    direction: str,
    playbook: str,
    timing_decision: str,
) -> float:
    """Calculate timing probability based on entry conditions.
    
    Returns probability [0.0, 1.0] that this is an optimal entry timing.
    This fixes the issue where UI showed 0.0% timing probability.
    
    Factors:
    - ATR vs bar range ratio (lower ratio = higher probability)
    - Delta confirmation strength
    - CVD slope alignment with direction
    - Playbook-specific conditions (e.g., return_to_value near VAL/VAH)
    """
    if timing_decision == "SKIP":
        return 0.0
    if timing_decision == "WAIT":
        return 0.3  # Base probability for WAIT states
    
    # ENTER_NOW: calculate based on quality factors
    if len(data) < 5 or tick is None:
        return 0.5  # Insufficient data
    
    atr5 = sum(d.high - d.low for d in data[-5:]) / 5
    bar_range = tick.high - tick.low
    delta_abs = abs(float(getattr(tick, "delta", 0) or 0))
    
    # Factor 1: Bar range vs ATR (lower = better timing)
    range_ratio = bar_range / atr5 if atr5 > 0 else 1.0
    range_score = max(0.0, 1.0 - (range_ratio / 3.0))  # 1.0 if ratio=0, 0.0 if ratio>=3
    
    # Factor 2: Delta confirmation strength
    delta_score = min(1.0, delta_abs / 500.0)  # Normalize (adjust based on instrument)
    
    # Factor 3: CVD slope alignment
    cvd_slope = float(getattr(amt_result, "cvd_slope", 0) or 0)
    cvd_aligned = (direction == "LONG" and cvd_slope > 0) or (direction == "SHORT" and cvd_slope < 0)
    cvd_score = 0.8 if cvd_aligned else 0.2
    
    # Factor 4: Playbook-specific timing quality
    playbook_score = 0.5
    if playbook == "return_to_value":
        va_width = abs(amt_result.value_area_high - amt_result.value_area_low)
        if va_width > 0:
            distance_from_edge = min(
                abs(tick.close - amt_result.value_area_high),
                abs(tick.close - amt_result.value_area_low)
            )
            edge_proximity = 1.0 - (distance_from_edge / va_width)
            playbook_score = 0.5 + 0.5 * edge_proximity
    
    # Weighted average
    timing_prob = (
        0.30 * range_score +
        0.25 * delta_score +
        0.25 * cvd_score +
        0.20 * playbook_score
    )
    
    # Log input→output for debugging
    logger.info(
        "TIMING PROB: %.3f | range_ratio=%.2f (score=%.2f) | delta=%.0f (score=%.2f) | "
        "cvd_slope=%.2f (aligned=%s, score=%.2f) | playbook=%s (score=%.2f)",
        timing_prob, range_ratio, range_score, delta_abs, delta_score,
        cvd_slope, cvd_aligned, cvd_score, playbook, playbook_score
    )
    
    return min(1.0, max(0.0, timing_prob))


def select_playbook(regime: RegimeState, amt_result: AMTResult) -> str:
    """Map regime and auction state to one of the canonical playbooks.
    
    FIX: NO_TRADE market state (price at POC) is a sub-state of BALANCED.
    When session regime is NO_TRADE but leg regime is BALANCED/TRENDING,
    use leg regime as fallback to avoid empty playbook.
    
    This allows the system to:
    1. Monitor setups even when price is at POC
    2. Return non-zero probabilities for direction
    3. Let timing agent decide when to enter (WAIT/SKIP/ENTER_NOW)
    """
    ms = getattr(amt_result, "market_state", "")
    
    # Primary: session regime
    if regime.regime == "TRENDING" and MarketStateCodec.is_imbalanced(ms):
        return "imbalance_continuation"
    if regime.regime == "BALANCED" and (MarketStateCodec.is_balanced(ms) or MarketStateCodec.is_no_trade(ms)):
        return "return_to_value"
    # PROBING playbook: unconfirmed break with aggression confirmation
    # Supports acceptance (continuation) and rejection (fade) scenarios
    if MarketStateCodec.is_probing(ms):
        return "probing_breakout"
    
    # FALLBACK: If session is NO_TRADE, use leg regime
    leg_regime = getattr(amt_result, "leg_regime", "")
    if regime.regime == "NO_TRADE" or MarketStateCodec.is_no_trade(ms):
        if leg_regime == "BALANCED":
            return "return_to_value"
        if leg_regime == "TRENDING":
            return "imbalance_continuation"
    
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
        if balance_ratio >= BALANCE_RATIO_THRESHOLD:
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
    if probability > CONFIDENCE_HIGH_THRESHOLD:
        tp_mult *= 1.1  # extend TP on high confidence
    elif probability < AGENT_DECISION_THRESHOLD:
        sl_mult *= 0.8  # tighter SL on low confidence

    return sl_mult, tp_mult


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------


def run_agent_pipeline(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    probability_engine: IProbabilityInference,
    features: dict[str, float],
    order_book: "OrderBook | None" = None,
    tick_size: float = 0.05,
    symbol: str = "",
    tick_age_seconds: float = 1.0,
    hysteresis_store: "RegimeHysteresisStore | None" = None,
) -> AgentDecision:
    """Run the full 4-agent pipeline. Target: <1ms total."""
    t0 = time.perf_counter_ns()

    # Agent 1: Regime (with hysteresis to prevent rapid flipping)
    raw_regime = classify_regime(data, amt_result, tick)
    if symbol and hysteresis_store is not None:
        regime = hysteresis_store.get(symbol).apply(raw_regime)
    else:
        regime = raw_regime
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

    # ── DELTA SCORE WIRING ──
    # Delta Score (+/-1.5) represents the net institutional aggression.
    # FIX BUG #3: Use per-symbol delta_normalized_option for isolation.
    # Previously, 'aggression' was computed from shared underlying data,
    # causing identical delta_score values across options on same underlying.
    # Now we use delta_normalized_option which is computed from option tick.
    delta_normalized_option = float(
        getattr(amt_result, "delta_normalized_option", 0.0) or 0.0
    )
    # norm_delta: -1 to +1 (from tick, also per-symbol)
    norm_delta = tick.delta / tick.volume if tick.volume > 0 else 0

    # Location penalty: price in tail (outside VA) reduces confidence
    if amt_result.value_area_high > 0 and amt_result.value_area_low > 0:
        _price = float(tick.close)
        if _price < amt_result.value_area_low:
            # Below VAL — penalize LONG, mild boost SHORT
            _tail_dist = (amt_result.value_area_low - _price) / max(amt_result.value_area_low, 1)
            _penalty = min(0.20, _tail_dist * 2)  # up to 20% penalty
            p_long = max(0.01, signal.p_long - _penalty)
            p_short = min(0.85, signal.p_short + _penalty * 0.3)
            signal = DirectionSignal(signal.direction, p_long, p_short, signal.edge)
        elif _price > amt_result.value_area_high:
            # Above VAH — penalize SHORT, mild boost LONG
            _tail_dist = (_price - amt_result.value_area_high) / max(amt_result.value_area_high, 1)
            _penalty = min(0.20, _tail_dist * 2)
            p_short = max(0.01, signal.p_short - _penalty)
            p_long = min(0.85, signal.p_long + _penalty * 0.3)
            signal = DirectionSignal(signal.direction, p_long, p_short, signal.edge)

    # IB break context: reduce counter-trend probability
    # A fresh IB break UP should reduce SHORT probability (don't short into upside breakout)
    # A fresh IB break DOWN should reduce LONG probability (don't go long into downside break)
    # Uses amt_result.break_direction ("UP" / "DOWN" / "")
    _ib_break = getattr(amt_result, "ib_break", None) or getattr(amt_result, "break_direction", "") or ""
    if _ib_break:
        _ib_break_upper = _ib_break.upper()
        if "UP" in _ib_break_upper or "HIGH" in _ib_break_upper or "ABOVE" in _ib_break_upper:
            # Fresh upside IB break — reduce short probability by up to 25%
            _ib_penalty = 0.25
            p_short = max(0.05, signal.p_short - _ib_penalty)
            p_long = min(0.85, signal.p_long + _ib_penalty * 0.3)
            signal = DirectionSignal(signal.direction, p_long, p_short, signal.edge)
        elif "DOWN" in _ib_break_upper or "LOW" in _ib_break_upper or "BELOW" in _ib_break_upper:
            # Fresh downside IB break — reduce long probability by up to 25%
            _ib_penalty = 0.25
            p_long = max(0.05, signal.p_long - _ib_penalty)
            p_short = min(0.85, signal.p_short + _ib_penalty * 0.3)
            signal = DirectionSignal(signal.direction, p_long, p_short, signal.edge)

    # delta_score: positive if bull delta, negative if bear
    # Use delta_normalized_option (per-symbol) as primary signal
    # Scale: delta_normalized_option is -1 to +1, so multiply for impact
    delta_score = delta_normalized_option * 1.5
    # Add a floor/boost from the tick delta ratio (also per-symbol)
    delta_score += norm_delta * 0.5

    p_long = signal.p_long
    p_short = signal.p_short

    # Influence: shift probability by up to 35% based on delta confluence
    # FIX BUG 4A: Increased multiplier from 0.15 to 0.25 for stronger delta influence
    if delta_score > 0.15:
        # Bullish aggression: boost long, penalize short
        shift = min(0.35, delta_score * 0.25)
        p_long = min(0.99, p_long + shift)
        p_short = max(0.01, p_short - shift * 0.6)
    elif delta_score < -0.15:
        # Bearish aggression: boost short, penalize long
        shift = min(0.35, abs(delta_score) * 0.25)
        p_short = min(0.99, p_short + shift)
        p_long = max(0.01, p_long - shift * 0.6)

    # Re-evaluate chosen direction based on shifted probabilities
    new_dir = signal.direction
    new_edge = signal.edge
    if p_long >= p_threshold_long and p_long > p_short + margin and regime.allowed_long:
        new_dir = "LONG"
        new_edge = p_long - 0.27
    elif (
        p_short >= p_threshold_short
        and p_short > p_long + margin
        and regime.allowed_short
    ):
        new_dir = "SHORT"
        new_edge = p_short - 0.29
    elif (
        abs(p_long - p_short) < margin
        and max(p_long, p_short) >= CONFIDENCE_LOW_THRESHOLD
    ):
        new_dir = "LONG" if p_long >= p_short else "SHORT"
        new_edge = abs(p_long - p_short)
    else:
        new_dir = "FLAT"
        new_edge = 0.0

    signal = DirectionSignal(new_dir, p_long, p_short, new_edge)

    # Global probability cap — no single reading should exceed 85%
    # Probabilities above this require multi-signal confluence that we can't guarantee
    _MAX_PROBABILITY = 0.85
    signal = DirectionSignal(
        signal.direction,
        min(_MAX_PROBABILITY, signal.p_long),
        min(_MAX_PROBABILITY, signal.p_short),
        signal.edge,
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
    timing = assess_timing(
        data,
        tick,
        amt_result,
        signal.direction,
        playbook,
        tick_size=tick_size,
        symbol=symbol,
        tick_age_seconds=tick_age_seconds,
    )

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
