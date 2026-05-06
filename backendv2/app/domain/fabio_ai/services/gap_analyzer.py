"""Gap analysis utilities."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GapAnalysis:
    gap_size: float
    gap_pct: float
    gap_type: str
    gap_size_label: str
    fill_probability: float
    direction: str
    entry_filter: str
    thesis: str


def analyze_gap(
    open_price: float,
    prior_close: float,
    prior_vah: float,
    prior_val: float,
    prior_ib_high: float = 0.0,
    prior_ib_low: float = 0.0,
    prior_range: float = 0.0,
) -> GapAnalysis:
    if open_price <= 0 or prior_close <= 0:
        return GapAnalysis(0.0, 0.0, "", "NONE", 0.0, "", "NONE", "Invalid inputs.")
    gap = open_price - prior_close
    direction = "UP" if gap > 0 else "DOWN" if gap < 0 else ""
    abs_gap = abs(gap)
    if prior_range <= 0 and prior_vah > 0 and prior_val > 0:
        prior_range = prior_vah - prior_val
    if prior_range <= 0:
        prior_range = abs_gap * 2
    gap_pct = abs_gap / prior_range if prior_range else 0.0
    if gap_pct < 0.005:
        label = "NONE"
    elif gap_pct < 0.15:
        label = "SMALL"
    elif gap_pct < 0.50:
        label = "MEDIUM"
    elif gap_pct < 2.0:
        label = "LARGE"
    else:
        label = "EXTREME"
    gap_type = _classify_gap_type(open_price, prior_vah, prior_val, prior_ib_high, prior_ib_low, prior_range)
    fill_probability = _estimate_fill_probability(gap_type, gap_pct, direction, prior_vah, prior_val)
    entry_filter = _gap_entry_filter(gap_type, gap_pct, direction)
    thesis = _gap_thesis(gap_type, label, gap_pct, direction, fill_probability)
    return GapAnalysis(abs_gap, gap_pct, gap_type, label, fill_probability, direction, entry_filter, thesis)


def _classify_gap_type(open_price: float, prior_vah: float, prior_val: float, prior_ib_high: float, prior_ib_low: float, prior_range: float) -> str:
    if prior_vah <= 0 or prior_val <= 0:
        return ""
    if prior_range > 0 and abs(open_price - prior_vah) > prior_range * 2:
        return "EXTREME"
    if prior_range > 0 and abs(open_price - prior_val) > prior_range * 2:
        return "EXTREME"
    if prior_ib_high > 0 and prior_ib_low > 0 and prior_ib_low <= open_price <= prior_ib_high:
        return "INSIDE_IB"
    if prior_val <= open_price <= prior_vah:
        return "INSIDE_VA"
    if open_price > prior_vah:
        return "OUTSIDE_VA_ABOVE"
    if open_price < prior_val:
        return "OUTSIDE_VA_BELOW"
    return ""


def _estimate_fill_probability(gap_type: str, gap_pct: float, direction: str, prior_vah: float, prior_val: float) -> float:
    base = {
        "INSIDE_VA": 0.78,
        "INSIDE_IB": 0.68,
        "OUTSIDE_VA_ABOVE": 0.40,
        "OUTSIDE_VA_BELOW": 0.40,
        "EXTREME": 0.18,
    }.get(gap_type, 0.50)
    if gap_pct < 0.10:
        base += 0.10
    elif gap_pct > 1.0:
        base -= 0.15
    va_range = prior_vah - prior_val if prior_vah > 0 and prior_val > 0 else 0
    if va_range > 0 and gap_type.startswith("OUTSIDE_VA"):
        base += min(0.10, va_range * 0.0001)
    return max(0.05, min(0.95, base))


def _gap_entry_filter(gap_type: str, gap_pct: float, direction: str) -> str:
    if gap_type == "":
        return "NONE"
    if gap_type == "INSIDE_VA":
        return "FADE"
    if gap_type == "INSIDE_IB":
        return "FADE"
    if gap_type in {"OUTSIDE_VA_ABOVE", "OUTSIDE_VA_BELOW"}:
        return "CONTINUE" if gap_pct < 0.30 else "WAIT"
    if gap_type == "EXTREME":
        return "WAIT"
    return "NONE"


def _gap_thesis(gap_type: str, gap_size_label: str, gap_pct: float, direction: str, fill_probability: float) -> str:
    direction_str = "bullish" if direction == "UP" else "bearish" if direction == "DOWN" else "neutral"
    base = {
        "INSIDE_VA": f"Opening inside prior value area — rotation expected. {fill_probability:.0%} fill.",
        "INSIDE_IB": f"Opening inside prior initial balance — tight rotation likely. {fill_probability:.0%} fill.",
        "OUTSIDE_VA_ABOVE": f"{direction_str.title()} gap above prior VA — continuation bias. {fill_probability:.0%} fill.",
        "OUTSIDE_VA_BELOW": f"{direction_str.title()} gap below prior VA — continuation bias. {fill_probability:.0%} fill.",
        "EXTREME": f"Extreme {direction_str} gap ({gap_pct:.1%} prior range) — new value discovery.",
    }.get(gap_type, "No clear gap thesis.")
    return f"{gap_size_label} {base}"


def classify_gap_enhanced(open_price: float, prior_close: float, prior_range: float, prior_vah: float = 0.0, prior_val: float = 0.0, prior_ib_high: float = 0.0, prior_ib_low: float = 0.0) -> GapAnalysis:
    return analyze_gap(
        open_price=open_price,
        prior_close=prior_close,
        prior_vah=prior_vah or (prior_close + prior_range / 2),
        prior_val=prior_val or (prior_close - prior_range / 2),
        prior_ib_high=prior_ib_high,
        prior_ib_low=prior_ib_low,
        prior_range=prior_range,
    )
