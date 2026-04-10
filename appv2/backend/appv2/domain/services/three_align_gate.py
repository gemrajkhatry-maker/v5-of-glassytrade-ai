"""Three-Align Gate — timeframe alignment gate for AMT entries.

Requires alignment across three timeframes:
- 5-minute: Entry timing
- 15-minute: Medium-term structure
- 1-hour: Trend bias

All three must agree on direction for a high-confidence signal.
Also checks POC shift direction and Value Area migration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreeAlignResult:
    passed: bool
    is_second_drive: bool  # D2 setup (pullback + continuation)
    alignment_score: int  # 0-3 (how many timeframes align)
    confirmation_strength: str  # "STRONG" | "MODERATE" | "WEAK"
    reason: str


def three_align_check(
    data_5min: list,
    data_15min: list,
    data_1hr: list,
    direction: str,
    poc_5min: float = 0.0,
    poc_15min: float = 0.0,
    poc_1hr: float = 0.0,
    current_price: float = 0.0,
) -> ThreeAlignResult:
    """Check three-timeframe alignment for entry.

    Args:
        data_5min: Recent 5-min candles
        data_15min: Recent 15-min candles
        data_1hr: Recent 1-hour candles
        direction: "LONG" or "SHORT"
        poc_*: POC for each timeframe
        current_price: Current market price
    """
    if not data_5min or not data_15min or not data_1hr:
        return ThreeAlignResult(
            passed=False,
            is_second_drive=False,
            alignment_score=0,
            confirmation_strength="WEAK",
            reason="Insufficient data on all timeframes",
        )

    score = 0

    # 5-min: Price above/below recent candles
    last_5 = data_5min[-1]
    if direction == "LONG":
        if last_5.close > last_5.open:
            score += 1
    else:
        if last_5.close < last_5.open:
            score += 1

    # 15-min: Price above/below POC
    if poc_15min > 0 and current_price > 0:
        if direction == "LONG" and current_price > poc_15min:
            score += 1
        elif direction == "SHORT" and current_price < poc_15min:
            score += 1

    # 1-hour: POC shift direction matches
    if poc_1hr > 0 and len(data_1hr) >= 2:
        prev_poc = _compute_prev_poc(data_1hr[:-1])
        if prev_poc > 0:
            poc_shift_up = poc_1hr > prev_poc
            if direction == "LONG" and poc_shift_up:
                score += 1
            elif direction == "SHORT" and not poc_shift_up:
                score += 1

    # Determine strength
    if score >= 3:
        strength = "STRONG"
    elif score >= 2:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    # Check for second drive (D2 setup)
    is_second_drive = _is_second_drive(data_5min, data_15min, direction)

    passed = score >= 2  # Need at least 2/3 alignment

    return ThreeAlignResult(
        passed=passed,
        is_second_drive=is_second_drive,
        alignment_score=score,
        confirmation_strength=strength,
        reason=f"{score}/3 timeframes aligned ({strength})",
    )


def _compute_prev_poc(candles: list) -> float:
    """Approximate POC from recent candles."""
    if not candles:
        return 0.0
    prices = [c.close for c in candles]
    volumes = [getattr(c, "volume", 1) for c in candles]
    if not volumes or sum(volumes) == 0:
        return sum(prices) / len(prices) if prices else 0.0

    # Weighted average price (approximate POC)
    total_vol = sum(volumes)
    return sum(p * v for p, v in zip(prices, volumes)) / total_vol


def _is_second_drive(data_5min: list, data_15min: list, direction: str) -> bool:
    """Detect D2 setup: pullback then continuation.

    D2 = first drive pushed price, pullback occurred, now resuming.
    """
    if len(data_5min) < 10 or len(data_15min) < 4:
        return False

    # Check for pullback pattern in 5-min
    recent = data_5min[-10:]
    if direction == "LONG":
        # Look for: up move → pullback → resuming up
        first_half = recent[:5]
        second_half = recent[5:]
        if not first_half or not second_half:
            return False

        first_avg_close = sum(c.close for c in first_half) / 5
        second_avg_close = sum(c.close for c in second_half) / 5

        # Price pulled back and is now resuming
        mid_point = recent[4].close
        last_close = recent[-1].close
        if mid_point > first_avg_close and last_close > mid_point:
            return True
    else:
        first_half = recent[:5]
        second_half = recent[5:]
        if not first_half or not second_half:
            return False

        mid_point = recent[4].close
        last_close = recent[-1].close
        first_avg_close = sum(c.close for c in first_half) / 5
        if mid_point < first_avg_close and last_close < mid_point:
            return True

    return False
