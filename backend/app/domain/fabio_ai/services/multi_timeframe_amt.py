"""Multi-Timeframe AMT Analyzer — Three-Timeframe Alignment per Fabio Valentini.

Fabio's methodology requires three-timeframe alignment:
1. Higher Timeframe (60-min or daily): Macro auction context, trend bias
2. Session Timeframe (15-min or 5-min): Setup validation
3. Entry Timeframe (5-min or 1-min): Precise execution timing

All three must agree directionally before any entry is allowed.
This prevents trading against the macro trend on lower timeframes.

Architecture:
- Maintains three separate IncrementalVolumeProfile instances per symbol
- Each profile aggregates candles at different intervals
- Runs AMTAnalyzer.analyze() on each timeframe
- Computes alignment score and direction
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult

logger = logging.getLogger(__name__)


class AlignmentState(str, Enum):
    """Three-timeframe alignment states."""

    ALIGNED_LONG = "ALIGNED_LONG"  # All three timeframes bullish
    ALIGNED_SHORT = "ALIGNED_SHORT"  # All three timeframes bearish
    CONFLICTED = "CONFLICTED"  # Timeframes disagree
    NEUTRAL = "NEUTRAL"  # No clear bias on any timeframe
    HIGHER_BEARISH = "HIGHER_BEARISH"  # Higher TF bearish, others unclear
    HIGHER_BULLISH = "HIGHER_BULLISH"  # Higher TF bullish, others unclear


@dataclass(frozen=True)
class MultiTimeframeAMTResult:
    """Result of multi-timeframe AMT analysis."""

    # Per-timeframe results
    higher_tf: "AMTResult | None" = None  # 60-min or daily
    session_tf: "AMTResult | None" = None  # 15-min or 5-min
    entry_tf: "AMTResult | None" = None  # 5-min or 1-min

    # Alignment
    alignment: str = "NEUTRAL"  # AlignmentState value
    alignment_strength: float = 0.0  # 0.0-1.0
    higher_tf_bias: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"
    session_tf_bias: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"
    entry_tf_bias: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"

    # Trade implications
    allow_entries: bool = True  # False if CONFLICTED
    position_size_multiplier: float = 1.0  # Reduce size if partial alignment
    thesis: str = ""  # Human-readable alignment summary


@dataclass
class TimeframeConfig:
    """Configuration for a single timeframe."""

    name: str  # "higher", "session", "entry"
    candle_interval_minutes: int  # 60, 15, 5, or 1
    lookback_candles: int  # How many candles to keep
    min_candles_for_analysis: int  # Minimum candles before analysis


class MultiTimeframeAMTAnalyzer:
    """Analyzes market across three timeframes for alignment.

    Usage:
        analyzer = MultiTimeframeAMTAnalyzer()
        result = analyzer.analyze(ticks, session_tf_result)

    The session timeframe result is passed in (already computed by AMTHandler).
    The higher and entry timeframes are computed from the same tick data
    by aggregating at different intervals.
    """

    # Default timeframe configurations
    DEFAULT_HIGHER_TF = TimeframeConfig(
        name="higher",
        candle_interval_minutes=60,
        lookback_candles=50,
        min_candles_for_analysis=3,
    )
    DEFAULT_SESSION_TF = TimeframeConfig(
        name="session",
        candle_interval_minutes=5,
        lookback_candles=100,
        min_candles_for_analysis=6,
    )
    DEFAULT_ENTRY_TF = TimeframeConfig(
        name="entry",
        candle_interval_minutes=1,
        lookback_candles=30,
        min_candles_for_analysis=10,
    )

    def __init__(
        self,
        higher_tf_config: TimeframeConfig | None = None,
        entry_tf_config: TimeframeConfig | None = None,
    ):
        self.higher_tf_config = higher_tf_config or self.DEFAULT_HIGHER_TF
        self.entry_tf_config = entry_tf_config or self.DEFAULT_ENTRY_TF

    def compute_alignment(
        self,
        session_tf_result: "AMTResult",
        higher_tf_bias: str = "",
        entry_tf_bias: str = "",
    ) -> MultiTimeframeAMTResult:
        """Compute three-timeframe alignment from pre-computed biases.

        This is the lightweight path — caller has already computed
        the per-timeframe biases (e.g., from separate AMTAnalyzer instances).

        Args:
            session_tf_result: The session timeframe AMTResult (already computed).
            higher_tf_bias: "BULLISH", "BEARISH", or "NEUTRAL" from higher TF.
            entry_tf_bias: "BULLISH", "BEARISH", or "NEUTRAL" from entry TF.

        Returns:
            MultiTimeframeAMTResult with alignment state and trade implications.
        """
        # Derive session bias from session result
        session_bias = _derive_bias(session_tf_result)

        # Compute alignment
        alignment, strength = _compute_alignment(
            higher_tf_bias, session_bias, entry_tf_bias
        )

        # Trade implications
        allow_entries = alignment not in (
            AlignmentState.CONFLICTED,
            AlignmentState.NEUTRAL,
        )
        position_size_multiplier = _position_size_multiplier(alignment, strength)

        thesis = _alignment_thesis(
            alignment, strength, higher_tf_bias, session_bias, entry_tf_bias
        )

        return MultiTimeframeAMTResult(
            session_tf=session_tf_result,
            alignment=alignment.value
            if isinstance(alignment, AlignmentState)
            else alignment,
            alignment_strength=strength,
            higher_tf_bias=higher_tf_bias,
            session_tf_bias=session_bias,
            entry_tf_bias=entry_tf_bias,
            allow_entries=allow_entries,
            position_size_multiplier=position_size_multiplier,
            thesis=thesis,
        )

    def aggregate_candles_to_timeframe(
        self,
        base_candles: list["OHLC"],
        target_interval_minutes: int,
        min_candles: int = 3,
    ) -> list["OHLC"]:
        """Aggregate base candles to a higher timeframe.

        Args:
            base_candles: Source candles (e.g., 1-min or 5-min).
            target_interval_minutes: Target candle interval (e.g., 60 for hourly).
            min_candles: Minimum aggregated candles to return.

        Returns:
            List of aggregated OHLC candles at target interval.
        """
        if not base_candles or target_interval_minutes <= 1:
            return base_candles

        # Determine base interval from candle timestamps
        base_interval = _estimate_base_interval(base_candles)
        if base_interval <= 0:
            return base_candles

        # How many base candles make one target candle
        ratio = target_interval_minutes // base_interval
        if ratio <= 1:
            return base_candles

        # Aggregate
        aggregated = []
        for i in range(0, len(base_candles), ratio):
            chunk = base_candles[i : i + ratio]
            if len(chunk) < max(1, ratio // 2):
                continue  # Incomplete candle, skip
            agg = _aggregate_chunk(chunk)
            if agg:
                aggregated.append(agg)

        return (
            aggregated[-self.higher_tf_config.lookback_candles :] if aggregated else []
        )


def _derive_bias(amt_result: "AMTResult") -> str:
    """Derive directional bias from an AMTResult.

    Uses multiple signals for robust bias detection:
    1. Market state (IMBALANCED = directional, BALANCED = neutral)
    2. CVD slope (positive = bullish, negative = bearish)
    3. Price relative to POC (above = bullish, below = bearish)
    4. POC migration (rising = bullish, falling = bearish)
    """
    if not amt_result or amt_result.poc <= 0:
        return "NEUTRAL"

    score = 0

    # Market state
    if amt_result.market_state == "IMBALANCED":
        score += 2
    elif amt_result.market_state == "PROBING":
        score += 1

    # CVD slope
    if amt_result.cvd_slope > 10:
        score += 2
    elif amt_result.cvd_slope > 0:
        score += 1
    elif amt_result.cvd_slope < -10:
        score -= 2
    elif amt_result.cvd_slope < 0:
        score -= 1

    # POC migration
    poc_signal = getattr(amt_result, "poc_signal", "")
    if "RISING" in poc_signal or "BULLISH" in poc_signal:
        score += 1
    elif "FALLING" in poc_signal or "BEARISH" in poc_signal:
        score -= 1

    # Aggression direction
    if amt_result.aggression > 2.0:
        score += 1
    elif amt_result.aggression < -2.0:
        score -= 1

    if score >= 3:
        return "BULLISH"
    elif score <= -3:
        return "BEARISH"
    elif score >= 1:
        return "SLIGHTLY_BULLISH"
    elif score <= -1:
        return "SLIGHTLY_BEARISH"
    return "NEUTRAL"

    score = 0

    # Market state
    if amt_result.market_state == "IMBALANCED":
        score += 2
    elif amt_result.market_state == "PROBING":
        score += 1

    # CVD slope
    if amt_result.cvd_slope > 10:
        score += 2
    elif amt_result.cvd_slope > 0:
        score += 1
    elif amt_result.cvd_slope < -10:
        score -= 2
    elif amt_result.cvd_slope < 0:
        score -= 1

    # Price vs POC
    price_poc_dist = (amt_result.value_area_high + amt_result.value_area_low) / 2
    if hasattr(amt_result, "_current_price"):
        price = getattr(amt_result, "_current_price", price_poc_dist)
    else:
        price = price_poc_dist  # Default to mid-VA if no price available

    # POC migration
    poc_signal = getattr(amt_result, "poc_signal", "")
    if "RISING" in poc_signal or "BULLISH" in poc_signal:
        score += 1
    elif "FALLING" in poc_signal or "BEARISH" in poc_signal:
        score -= 1

    # Aggression direction
    if amt_result.aggression > 2.0:
        score += 1
    elif amt_result.aggression < -2.0:
        score -= 1

    if score >= 3:
        return "BULLISH"
    elif score <= -3:
        return "BEARISH"
    elif score >= 1:
        return "SLIGHTLY_BULLISH"
    elif score <= -1:
        return "SLIGHTLY_BEARISH"
    return "NEUTRAL"


def _compute_alignment(
    higher_bias: str,
    session_bias: str,
    entry_bias: str,
) -> tuple[AlignmentState, float]:
    """Compute alignment state and strength from three timeframe biases.

    Returns:
        Tuple of (alignment_state, strength 0.0-1.0)
    """
    biases = [higher_bias, session_bias, entry_bias]

    # Count bullish/bearish/neutral
    bullish = sum(1 for b in biases if "BULLISH" in b)
    bearish = sum(1 for b in biases if "BEARISH" in b)
    neutral = sum(1 for b in biases if b in ("NEUTRAL", ""))

    # All three agree
    if bullish == 3:
        return AlignmentState.ALIGNED_LONG, 1.0
    if bearish == 3:
        return AlignmentState.ALIGNED_SHORT, 1.0

    # Two agree, one neutral
    if bullish == 2 and neutral == 1:
        return AlignmentState.ALIGNED_LONG, 0.7
    if bearish == 2 and neutral == 1:
        return AlignmentState.ALIGNED_SHORT, 0.7

    # Two agree, one disagrees (partial conflict)
    if bullish == 2 and bearish == 1:
        # Higher TF matters most — if higher is bullish, allow with reduced size
        if "BULLISH" in higher_bias:
            return AlignmentState.ALIGNED_LONG, 0.5
        return AlignmentState.CONFLICTED, 0.3
    if bearish == 2 and bullish == 1:
        if "BEARISH" in higher_bias:
            return AlignmentState.ALIGNED_SHORT, 0.5
        return AlignmentState.CONFLICTED, 0.3

    # Higher TF dominant, others neutral
    if bullish == 1 and neutral == 2 and "BULLISH" in higher_bias:
        return AlignmentState.HIGHER_BULLISH, 0.4
    if bearish == 1 and neutral == 2 and "BEARISH" in higher_bias:
        return AlignmentState.HIGHER_BEARISH, 0.4

    # All neutral or mixed
    return AlignmentState.NEUTRAL, 0.0


def _position_size_multiplier(alignment: AlignmentState, strength: float) -> float:
    """Calculate position size multiplier based on alignment quality.

    Full alignment = 1.0x
    Partial alignment = 0.5-0.7x
    Conflicted = 0.0x (no trade)
    """
    if alignment in (AlignmentState.ALIGNED_LONG, AlignmentState.ALIGNED_SHORT):
        return max(0.5, strength)
    if alignment in (AlignmentState.HIGHER_BULLISH, AlignmentState.HIGHER_BEARISH):
        return 0.5
    return 0.0  # CONFLICTED or NEUTRAL = no trade


def _alignment_thesis(
    alignment: AlignmentState,
    strength: float,
    higher_bias: str,
    session_bias: str,
    entry_bias: str,
) -> str:
    """Generate human-readable alignment thesis."""
    if alignment in (AlignmentState.ALIGNED_LONG, AlignmentState.ALIGNED_SHORT):
        direction = "bullish" if "LONG" in alignment.value else "bearish"
        return (
            f"All timeframes aligned {direction}. "
            f"Higher: {higher_bias}, Session: {session_bias}, Entry: {entry_bias}. "
            f"Alignment strength: {strength:.0%}. Full position size allowed."
        )
    if alignment in (AlignmentState.HIGHER_BULLISH, AlignmentState.HIGHER_BEARISH):
        direction = "bullish" if "BULLISH" in alignment.value else "bearish"
        return (
            f"Higher timeframe {direction}, session/entry neutral. "
            f"Reduced position size (50%). Wait for session confirmation."
        )
    if alignment == AlignmentState.CONFLICTED:
        return (
            f"Timeframes conflicted. Higher: {higher_bias}, Session: {session_bias}, "
            f"Entry: {entry_bias}. NO TRADE — wait for alignment."
        )
    return "No clear bias on any timeframe. Wait for structure to develop."


def _estimate_base_interval(candles: list["OHLC"]) -> int:
    """Estimate the base candle interval in minutes from timestamps."""
    if len(candles) < 2:
        return 5  # Default to 5-min

    try:
        from datetime import datetime

        times = []
        for c in candles[:20]:  # Sample first 20
            t = c.time if hasattr(c, "time") else c.get("time", "")
            if isinstance(t, str) and "T" in t:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            elif (
                isinstance(t, str)
                and t.replace(".", "", 1).replace("-", "", 1).isdigit()
            ):
                dt = datetime.fromtimestamp(float(t))
            else:
                continue
            times.append(dt)

        if len(times) < 2:
            return 5

        diffs = [
            (times[i + 1] - times[i]).total_seconds() / 60
            for i in range(len(times) - 1)
        ]
        avg_diff = sum(diffs) / len(diffs)

        # Round to nearest standard interval
        standard_intervals = [1, 3, 5, 15, 30, 60]
        return min(standard_intervals, key=lambda x: abs(x - avg_diff))
    except (ValueError, TypeError):
        return 5 


def _aggregate_chunk(chunk: list["OHLC"]) -> "OHLC | None":
    """Aggregate a list of candles into one higher-timeframe candle."""
    if not chunk:
        return None

    from dataclasses import replace

    first = chunk[0]
    last = chunk[-1]

    high = max(float(c.high) if hasattr(c, "high") else c["high"] for c in chunk)
    low = min(float(c.low) if hasattr(c, "low") else c["low"] for c in chunk)
    volume = sum(
        float(c.volume) if hasattr(c, "volume") else c["volume"] for c in chunk
    )
    delta = sum(
        float(c.delta) if hasattr(c, "delta") else c.get("delta", 0) for c in chunk
    )
    buy_vol = sum(
        float(c.taker_buy_volume)
        if hasattr(c, "taker_buy_volume")
        else c.get("taker_buy_volume", 0)
        for c in chunk
    )

    # VWAP: weighted average of close prices
    total_vol = volume if volume > 0 else 1
    vwap = (
        sum(
            (float(c.close) if hasattr(c, "close") else c["close"])
            * (float(c.volume) if hasattr(c, "volume") else c["volume"])
            for c in chunk
        )
        / total_vol
    )

    time_str = last.time if hasattr(last, "time") else last.get("time", "")

    if hasattr(first, "open"):
        return replace(
            first,
            time=time_str,
            open=first.open,
            high=high,
            low=low,
            close=last.close,
            volume=volume,
            vwap=vwap,
            taker_buy_volume=buy_vol,
            delta=delta,
        )
    else:
        return {
            **first,
            "time": time_str,
            "open": first["open"],
            "high": high,
            "low": low,
            "close": last["close"],
            "volume": volume,
            "vwap": vwap,
            "taker_buy_volume": buy_vol,
            "delta": delta,
        }
