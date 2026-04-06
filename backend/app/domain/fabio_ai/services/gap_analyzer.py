"""Gap Analyzer — comprehensive gap classification and fill probability.

Extends the basic classify_gap() in session_context.py with:
- Gap type classification relative to prior session structure (VA, IB)
- Gap fill probability based on historical statistics
- Gap magnitude as % of prior session range
- Entry filter implications for each gap type

Fabio Valentini methodology:
- Gaps within prior value → fill likely (fade trade)
- Gaps above/below prior VA → directional continuation
- Gaps within prior IB → rotation likely
- Extreme gaps (>2x prior range) → new value discovery
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GapAnalysis:
    """Comprehensive gap analysis result."""

    gap_size: float  # Absolute gap in price units
    gap_pct: float  # Gap as % of prior session range
    gap_type: str  # "INSIDE_VA", "INSIDE_IB", "OUTSIDE_VA_ABOVE", "OUTSIDE_VA_BELOW", "EXTREME", ""
    gap_size_label: str  # "NONE", "SMALL", "MEDIUM", "LARGE", "EXTREME"
    fill_probability: float  # 0.0-1.0 estimated fill probability
    direction: str  # "UP", "DOWN", "" (no gap)
    entry_filter: str  # "FADE", "CONTINUE", "WAIT", "NONE"
    thesis: str  # Human-readable gap interpretation


def analyze_gap(
    open_price: float,
    prior_close: float,
    prior_vah: float,
    prior_val: float,
    prior_ib_high: float = 0.0,
    prior_ib_low: float = 0.0,
    prior_range: float = 0.0,
) -> GapAnalysis:
    """Analyze opening gap with full structural context.

    Args:
        open_price: Today's opening price (first candle open).
        prior_close: Prior session close (or POC as proxy).
        prior_vah: Prior session value area high.
        prior_val: Prior session value area low.
        prior_ib_high: Prior session initial balance high.
        prior_ib_low: Prior session initial balance low.
        prior_range: Prior session range (high - low).

    Returns:
        GapAnalysis with type, fill probability, and entry filter.
    """
    if open_price <= 0 or prior_close <= 0:
        return GapAnalysis(
            gap_size=0.0,
            gap_pct=0.0,
            gap_type="",
            gap_size_label="NONE",
            fill_probability=0.0,
            direction="",
            entry_filter="NONE",
            thesis="Invalid inputs — no gap analysis possible.",
        )

    gap_size = open_price - prior_close
    direction = "UP" if gap_size > 0 else "DOWN" if gap_size < 0 else ""
    abs_gap = abs(gap_size)

    # Compute prior range if not provided
    if prior_range <= 0 and prior_vah > 0 and prior_val > 0:
        prior_range = prior_vah - prior_val
    if prior_range <= 0:
        prior_range = abs_gap * 2  # Fallback: assume gap is 50% of range

    gap_pct = abs_gap / prior_range if prior_range > 0 else 0.0

    # Gap size label
    if gap_pct < 0.005:
        gap_size_label = "NONE"
    elif gap_pct < 0.15:
        gap_size_label = "SMALL"
    elif gap_pct < 0.50:
        gap_size_label = "MEDIUM"
    elif gap_pct < 2.0:
        gap_size_label = "LARGE"
    else:
        gap_size_label = "EXTREME"

    # Gap type classification (structural)
    gap_type = _classify_gap_type(
        open_price, prior_vah, prior_val, prior_ib_high, prior_ib_low, prior_range
    )

    # Fill probability based on gap type and size
    fill_probability = _estimate_fill_probability(
        gap_type, gap_pct, direction, prior_vah, prior_val
    )

    # Entry filter recommendation
    entry_filter = _gap_entry_filter(gap_type, gap_pct, direction)

    # Thesis
    thesis = _gap_thesis(gap_type, gap_size_label, gap_pct, direction, fill_probability)

    return GapAnalysis(
        gap_size=round(gap_size, 2),
        gap_pct=round(gap_pct, 4),
        gap_type=gap_type,
        gap_size_label=gap_size_label,
        fill_probability=round(fill_probability, 2),
        direction=direction,
        entry_filter=entry_filter,
        thesis=thesis,
    )


def _classify_gap_type(
    open_price: float,
    prior_vah: float,
    prior_val: float,
    prior_ib_high: float,
    prior_ib_low: float,
    prior_range: float,
) -> str:
    """Classify gap type based on structural location.

    Priority order:
    1. EXTREME: gap > 2x prior range (new value discovery)
    2. INSIDE_IB: within prior initial balance (rotation)
    3. INSIDE_VA: within prior value area (fill likely)
    4. OUTSIDE_VA_ABOVE/BELOW: outside prior value (continuation)
    """
    if prior_vah <= 0 or prior_val <= 0:
        return ""

    # Extreme gap: > 2x prior range
    if prior_range > 0 and abs(open_price - prior_vah) > prior_range * 2:
        return "EXTREME"
    if prior_range > 0 and abs(open_price - prior_val) > prior_range * 2:
        return "EXTREME"

    # Inside prior IB (if IB data available)
    if prior_ib_high > 0 and prior_ib_low > 0:
        if prior_ib_low <= open_price <= prior_ib_high:
            return "INSIDE_IB"

    # Inside prior VA
    if prior_val <= open_price <= prior_vah:
        return "INSIDE_VA"

    # Outside VA
    if open_price > prior_vah:
        return "OUTSIDE_VA_ABOVE"

    if open_price < prior_val:
        return "OUTSIDE_VA_BELOW"

    return ""


def _estimate_fill_probability(
    gap_type: str,
    gap_pct: float,
    direction: str,
    prior_vah: float,
    prior_val: float,
) -> float:
    """Estimate probability that gap will be filled.

    Based on empirical studies and Fabio's methodology:
    - INSIDE_VA gaps: 70-85% fill rate (rotation back to POC)
    - INSIDE_IB gaps: 60-75% fill rate (IB rotation)
    - OUTSIDE_VA gaps: 30-50% fill rate (continuation more likely)
    - EXTREME gaps: 10-25% fill rate (new value discovery)
    - Small gaps (<15% of range): higher fill probability
    - Large gaps (>50% of range): lower fill probability
    """
    if gap_type == "":
        return 0.0

    # Base probability by gap type
    base_probs = {
        "INSIDE_VA": 0.78,
        "INSIDE_IB": 0.68,
        "OUTSIDE_VA_ABOVE": 0.40,
        "OUTSIDE_VA_BELOW": 0.40,
        "EXTREME": 0.18,
    }
    base = base_probs.get(gap_type, 0.50)

    # Adjust for gap size
    if gap_pct < 0.10:
        base += 0.10  # Very small gaps fill more often
    elif gap_pct > 1.0:
        base -= 0.15  # Very large gaps less likely to fill

    # Adjust for VA width (wider VA = stronger magnet)
    va_range = prior_vah - prior_val if prior_vah > 0 and prior_val > 0 else 0
    if va_range > 0 and gap_type.startswith("OUTSIDE_VA"):
        # Wider VA = stronger pull back = higher fill probability
        base += min(0.10, va_range * 0.0001)

    return max(0.05, min(0.95, base))


def _gap_entry_filter(
    gap_type: str,
    gap_pct: float,
    direction: str,
) -> str:
    """Determine entry filter based on gap analysis.

    Returns:
        "FADE": Trade against gap direction (expect fill)
        "CONTINUE": Trade with gap direction (expect continuation)
        "WAIT": Wait for acceptance/rejection confirmation
        "NONE": No gap-based filter
    """
    if gap_type == "":
        return "NONE"

    if gap_type == "INSIDE_VA":
        return "FADE"  # Gap inside VA → fade back to POC

    if gap_type == "INSIDE_IB":
        return "FADE"  # IB rotation → fade extremes

    if gap_type == "OUTSIDE_VA_ABOVE":
        if gap_pct < 0.30:
            return "CONTINUE"  # Small gap above VA → continuation
        return "WAIT"  # Larger gap → wait for acceptance/rejection

    if gap_type == "OUTSIDE_VA_BELOW":
        if gap_pct < 0.30:
            return "CONTINUE"  # Small gap below VA → continuation
        return "WAIT"  # Larger gap → wait for acceptance/rejection

    if gap_type == "EXTREME":
        return "WAIT"  # Extreme gap → wait for new value to form

    return "NONE"


def _gap_thesis(
    gap_type: str,
    gap_size_label: str,
    gap_pct: float,
    direction: str,
    fill_probability: float,
) -> str:
    """Generate human-readable gap thesis."""
    if gap_type == "":
        return "No significant gap at open."

    direction_str = (
        "bullish"
        if direction == "UP"
        else "bearish"
        if direction == "DOWN"
        else "neutral"
    )

    type_descriptions = {
        "INSIDE_VA": f"Opening inside prior value area — rotation expected. {fill_probability:.0%} fill probability.",
        "INSIDE_IB": f"Opening inside prior initial balance — tight rotation likely. {fill_probability:.0%} fill probability.",
        "OUTSIDE_VA_ABOVE": f"{direction_str.capitalize()} gap above prior VA — continuation bias. {fill_probability:.0%} fill probability.",
        "OUTSIDE_VA_BELOW": f"{direction_str.capitalize()} gap below prior VA — continuation bias. {fill_probability:.0%} fill probability.",
        "EXTREME": f"Extreme {direction_str} gap ({gap_pct:.1%} of prior range) — new value discovery. Low fill probability ({fill_probability:.0%}).",
    }

    base = type_descriptions.get(
        gap_type, f"{gap_size_label} {direction_str} gap detected."
    )
    return f"{gap_size_label} {base}"


# Backward-compatible wrapper for existing classify_gap() calls
def classify_gap_enhanced(
    open_price: float,
    prior_close: float,
    prior_range: float,
    prior_vah: float = 0.0,
    prior_val: float = 0.0,
    prior_ib_high: float = 0.0,
    prior_ib_low: float = 0.0,
) -> GapAnalysis:
    """Enhanced gap classification with full structural context.

    Backward-compatible with existing classify_gap() signature but
    returns full GapAnalysis instead of just a string label.
    """
    return analyze_gap(
        open_price=open_price,
        prior_close=prior_close,
        prior_vah=prior_vah or (prior_close + prior_range / 2),
        prior_val=prior_val or (prior_close - prior_range / 2),
        prior_ib_high=prior_ib_high,
        prior_ib_low=prior_ib_low,
        prior_range=prior_range,
    )
