"""break detector — AMT analysis service.

Based on amt_docs FR-07:
- Initiative break: Price closes beyond VAH/VAL with volume confirmation
- Responsive break: Wick tests level but closes back inside
- Absorption break: Flat candle with hidden delta at level
"""

from __future__ import annotations

from app.domain.amt.model.amt_models import BreakResult

Bar = dict


def detect_break(
    bars: list[Bar],
    vp_levels: dict,
    ib_result: dict | None = None,
    baseline_vol: float = 0,
) -> BreakResult:
    """
    Detect break patterns from bars.
    
    Args:
        bars: List of bar dictionaries
        vp_levels: Dict with 'vah', 'val', 'poc' keys
        ib_result: Initial balance result with 'high', 'low' keys
        baseline_vol: Baseline volume for comparison
    
    Returns:
        BreakResult with direction and type
    """
    if len(bars) < 3:
        return BreakResult()

    vah = vp_levels.get("vah", 0)
    val = vp_levels.get("val", 0)
    poc = vp_levels.get("poc", 0)
    ib_high = ib_result.get("high", 0) if ib_result else 0
    ib_low = ib_result.get("low", 0) if ib_result else 0

    if vah == 0 or val == 0:
        return BreakResult()

    last_bar = bars[-1]
    prev_bar = bars[-2]

    high = last_bar.get("high", 0)
    low = last_bar.get("low", 0)
    close = last_bar.get("close", 0)
    volume = last_bar.get("volume", 0)
    buy_vol = last_bar.get("buyVolume", volume / 2)
    sell_vol = last_bar.get("sellVolume", volume / 2)

    # Calculate average volume
    avg_vol = sum(b.get("volume", 0) for b in bars) / len(bars) if bars else 0

    # Initiative UP break: Close > VAH + volume confirmation
    if close > vah and volume > avg_vol * 1.5:
        return BreakResult(direction="UP", type="INITIATIVE", level=vah)

    # Initiative DOWN break: Close < VAL + volume confirmation
    if close < val and volume > avg_vol * 1.5:
        return BreakResult(direction="DOWN", type="INITIATIVE", level=val)

    # Responsive fade at VAH: Wick above, close below (rejection)
    if high > vah and low < vah and close < vah:
        return BreakResult(direction="DOWN", type="RESPONSIVE", level=vah)

    # Responsive fade at VAL: Wick below, close above (rejection)
    if low < val and high > val and close > val:
        return BreakResult(direction="UP", type="RESPONSIVE", level=val)

    # IB break up
    if ib_high > 0 and close > ib_high:
        return BreakResult(direction="UP", type="INITIATIVE", level=ib_high)

    return BreakResult()


def check_ib_break_tick(
    price: float,
    ib_high: float,
    ib_low: float,
) -> BreakResult | None:
    """
    Check for IB break based on tick price.
    
    Args:
        price: Current price
        ib_high: Initial balance high
        ib_low: Initial balance low
    
    Returns:
        BreakResult if break detected, None otherwise
    """
    if ib_high > 0 and price > ib_high:
        return BreakResult(direction="UP", type="INITIATIVE", level=ib_high)

    if ib_low > 0 and price < ib_low:
        return BreakResult(direction="DOWN", type="INITIATIVE", level=ib_low)

    return None

