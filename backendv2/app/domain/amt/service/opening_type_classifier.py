"""Opening Type Classifier — classifies the first 15-30 minutes of session.

Fabio Valentini's Opening Types framework:
The first 15-30 minutes dictate the entire day's strategy. Each opening type
maps to different allowed setups and gate overrides.

Six Opening Types:
1. OPEN_DRIVE: Strong directional open away from prior VA, no look-back
2. OPEN_TEST_DRIVE: Probe prior VA extreme, reject, then strong reversal
3. OPEN_REJECTION_REVERSE: Gap outside VA, immediate rejection, fade the gap
4. OPEN_AUCTION: Rotational open inside prior VA, balance expected
5. OPEN_AUCTION_OOR: Gap outside VA, developing new value area
6. GAP_FILL: Gap open that fills prior session close

Each type maps to:
- Allowed setups (e.g., ORR -> FAILED_AUCTION + MEAN_REVERSION only)
- Gate overrides (e.g., OPEN_DRIVE blocks MEAN_REVERSION for first hour)
- Strategy bias (trend vs mean reversion)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpeningTypeResult:
    """Result of opening type classification."""

    opening_type: str  # "OPEN_DRIVE" | "OPEN_TEST_DRIVE" | "OPEN_REJECTION_REVERSE" | "OPEN_AUCTION" | "OPEN_AUCTION_OOR" | "GAP_FILL" | "UNKNOWN"
    confidence: float  # 0.0-1.0
    direction: str  # "LONG" | "SHORT" | "" (neutral)
    allowed_setups: tuple[str, ...]  # Which setup types are allowed
    blocked_setups: tuple[str, ...]  # Which setup types are blocked
    thesis: str  # Human-readable explanation
    gate_overrides: dict  # Gate modifications for this opening type


def classify_opening_type(
    candles: list,
    open_price: float,
    prior_vah: float,
    prior_val: float,
    prior_poc: float = 0.0,
    prior_close: float = 0.0,
    max_candles: int = 6,
) -> OpeningTypeResult:
    """Classify the opening type from the first N candles.

    Args:
        candles: List of OHLC candles from session start.
        open_price: Session opening price (first candle open).
        prior_vah: Prior session value area high.
        prior_val: Prior session value area low.
        prior_poc: Prior session POC.
        prior_close: Prior session close.
        max_candles: Max candles to analyze (default 6 = 30 min at 5m).

    Returns:
        OpeningTypeResult with type, allowed setups, and gate overrides.
    """
    if not candles or prior_vah <= 0 or prior_val <= 0:
        return OpeningTypeResult(
            opening_type="UNKNOWN",
            confidence=0.0,
            direction="",
            allowed_setups=("AAA", "MOMENTUM", "MEAN_REVERSION", "FAILED_AUCTION"),
            blocked_setups=(),
            thesis="Insufficient data for opening type classification.",
            gate_overrides={},
        )

    # Analyze opening candles
    opening_candles = candles[:max_candles] if len(candles) >= max_candles else candles
    if len(opening_candles) < 2:
        return OpeningTypeResult(
            opening_type="UNKNOWN",
            confidence=0.0,
            direction="",
            allowed_setups=("AAA", "MOMENTUM", "MEAN_REVERSION", "FAILED_AUCTION"),
            blocked_setups=(),
            thesis="Need at least 2 candles for opening classification.",
            gate_overrides={},
        )

    # Compute opening characteristics
    gap_size = open_price - prior_close if prior_close > 0 else 0.0
    gap_pct = abs(gap_size) / (prior_vah - prior_val) if prior_vah > prior_val else 0.0
    is_gap_up = gap_size > 0
    is_gap_down = gap_size < 0
    is_inside_va = prior_val <= open_price <= prior_vah
    is_above_va = open_price > prior_vah
    is_below_va = open_price < prior_val

    # Track price action
    first_candle = opening_candles[0]
    last_candle = opening_candles[-1]
    first_close = (
        float(first_candle.close)
        if hasattr(first_candle, "close")
        else first_candle["close"]
    )
    last_close = (
        float(last_candle.close)
        if hasattr(last_candle, "close")
        else last_candle["close"]
    )
    high_of_opens = max(
        float(c.high) if hasattr(c, "high") else c["high"] for c in opening_candles
    )
    low_of_opens = min(
        float(c.low) if hasattr(c, "low") else c["low"] for c in opening_candles
    )

    # Directional movement
    net_move = last_close - open_price
    move_pct = abs(net_move) / open_price if open_price > 0 else 0.0

    # Rejection detection (wicks)
    first_range = (
        float(first_candle.high)
        if hasattr(first_candle, "high")
        else first_candle["high"]
    ) - (
        float(first_candle.low) if hasattr(first_candle, "low") else first_candle["low"]
    )
    first_body = abs(first_close - open_price)
    first_wick_ratio = 1.0 - (first_body / first_range) if first_range > 0 else 0.0

    # Volume analysis
    volumes = [
        float(c.volume) if hasattr(c, "volume") else c["volume"]
        for c in opening_candles
    ]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    first_vol = volumes[0] if volumes else 0
    vol_expansion = first_vol / avg_vol if avg_vol > 0 else 1.0

    # Check for probe and rejection of prior VA
    probed_above = high_of_opens > prior_vah
    probed_below = low_of_opens < prior_val
    rejected_above = probed_above and last_close < prior_vah
    rejected_below = probed_below and last_close > prior_val

    # Check for gap fill
    gap_filled = False
    if prior_close > 0:
        if is_gap_up:
            gap_filled = low_of_opens <= prior_close
        elif is_gap_down:
            gap_filled = high_of_opens >= prior_close

    # Classification logic (priority order)
    result = _classify(
        is_inside_va=is_inside_va,
        is_above_va=is_above_va,
        is_below_va=is_below_va,
        is_gap_up=is_gap_up,
        is_gap_down=is_gap_down,
        gap_pct=gap_pct,
        net_move=net_move,
        move_pct=move_pct,
        vol_expansion=vol_expansion,
        first_wick_ratio=first_wick_ratio,
        probed_above=probed_above,
        probed_below=probed_below,
        rejected_above=rejected_above,
        rejected_below=rejected_below,
        gap_filled=gap_filled,
        opening_candles=opening_candles,
        prior_vah=prior_vah,
        prior_val=prior_val,
        prior_poc=prior_poc,
    )

    return result


def _classify(
    is_inside_va: bool,
    is_above_va: bool,
    is_below_va: bool,
    is_gap_up: bool,
    is_gap_down: bool,
    gap_pct: float,
    net_move: float,
    move_pct: float,
    vol_expansion: float,
    first_wick_ratio: float,
    probed_above: bool,
    probed_below: bool,
    rejected_above: bool,
    rejected_below: bool,
    gap_filled: bool,
    opening_candles: list,
    prior_vah: float,
    prior_val: float,
    prior_poc: float,
) -> OpeningTypeResult:
    """Classify opening type based on characteristics."""

    # 1. OPEN_REJECTION_REVERSE: Gap outside VA, immediate rejection
    if (is_above_va and rejected_above) or (is_below_va and rejected_below):
        direction = "SHORT" if rejected_above else "LONG"
        confidence = min(0.95, 0.70 + first_wick_ratio * 0.25)
        return OpeningTypeResult(
            opening_type="OPEN_REJECTION_REVERSE",
            confidence=confidence,
            direction=direction,
            allowed_setups=("FAILED_AUCTION", "MEAN_REVERSION"),
            blocked_setups=("MOMENTUM",),
            thesis=(
                f"Gap {'above' if is_above_va else 'below'} prior VA rejected. "
                f"Price returned inside value. Fade the gap. "
                f"Wick ratio: {first_wick_ratio:.0%}."
            ),
            gate_overrides={
                "block_mean_reversion_minutes": 0,  # Allow immediately
                "block_momentum_minutes": 60,  # Block momentum for 1 hour
                "allow_failed_auction": True,
            },
        )

    # 2. OPEN_TEST_DRIVE: Probe VA extreme, reject, then strong reversal
    if (probed_above and rejected_above) or (probed_below and rejected_below):
        direction = "SHORT" if rejected_above else "LONG"
        reversal_strength = (
            abs(net_move) / (prior_vah - prior_val) if prior_vah > prior_val else 0
        )
        confidence = min(0.90, 0.60 + reversal_strength * 0.3)
        return OpeningTypeResult(
            opening_type="OPEN_TEST_DRIVE",
            confidence=confidence,
            direction=direction,
            allowed_setups=("FAILED_AUCTION", "MEAN_REVERSION", "AAA"),
            blocked_setups=("MOMENTUM",),
            thesis=(
                f"Tested {'VAH' if probed_above else 'VAL'} and rejected. "
                f"Strong {'bearish' if direction == 'SHORT' else 'bullish'} reversal. "
                f"Reversal: {reversal_strength:.1%} of VA range."
            ),
            gate_overrides={
                "block_momentum_minutes": 30,
                "allow_failed_auction": True,
            },
        )

    # 3. GAP_FILL: Gap open that fills prior session close
    if (is_gap_up or is_gap_down) and gap_filled:
        direction = "SHORT" if is_gap_up else "LONG"
        confidence = 0.65
        return OpeningTypeResult(
            opening_type="GAP_FILL",
            confidence=confidence,
            direction=direction,
            allowed_setups=("MEAN_REVERSION", "AAA"),
            blocked_setups=("MOMENTUM",),
            thesis=(
                f"{'Bullish' if is_gap_up else 'Bearish'} gap filled. "
                f"Expect rotation back toward POC. "
                f"Gap was {gap_pct:.1%} of prior VA range."
            ),
            gate_overrides={
                "block_momentum_minutes": 45,
                "allow_mean_reversion": True,
            },
        )

    # 4. OPEN_DRIVE: Strong directional open away from prior VA, no look-back
    if (is_above_va and net_move > 0 and move_pct > 0.003 and vol_expansion > 1.3) or (
        is_below_va and net_move < 0 and move_pct > 0.003 and vol_expansion > 1.3
    ):
        direction = "LONG" if net_move > 0 else "SHORT"
        confidence = min(0.90, 0.60 + vol_expansion * 0.1 + move_pct * 100)
        return OpeningTypeResult(
            opening_type="OPEN_DRIVE",
            confidence=confidence,
            direction=direction,
            allowed_setups=("MOMENTUM",),
            blocked_setups=("MEAN_REVERSION", "AAA"),
            thesis=(
                f"Strong {'bullish' if direction == 'LONG' else 'bearish'} drive. "
                f"Volume expansion: {vol_expansion:.1f}x. "
                f"Move: {move_pct:.2%}. No look-back — trend continuation only."
            ),
            gate_overrides={
                "block_mean_reversion_minutes": 60,  # Block MR for first hour
                "block_aaa_minutes": 30,
                "allow_momentum": True,
            },
        )

    # 5. OPEN_AUCTION_OOR: Gap outside VA, developing new value
    if (is_above_va or is_below_va) and gap_pct > 0.10 and not gap_filled:
        direction = "LONG" if is_above_va else "SHORT"
        confidence = 0.55
        return OpeningTypeResult(
            opening_type="OPEN_AUCTION_OOR",
            confidence=confidence,
            direction=direction,
            allowed_setups=("MOMENTUM", "FAILED_AUCTION"),
            blocked_setups=("AAA",),
            thesis=(
                f"Gap {'above' if is_above_va else 'below'} prior VA, "
                f"developing new value area. Wait for acceptance/rejection. "
                f"Gap: {gap_pct:.1%} of prior range."
            ),
            gate_overrides={
                "block_mean_reversion_minutes": 30,
                "require_acceptance": True,
            },
        )

    # 6. OPEN_AUCTION: Rotational open inside prior VA
    if is_inside_va:
        confidence = 0.70
        return OpeningTypeResult(
            opening_type="OPEN_AUCTION",
            confidence=confidence,
            direction="",
            allowed_setups=("AAA", "MEAN_REVERSION", "MOMENTUM", "FAILED_AUCTION"),
            blocked_setups=(),
            thesis=(
                f"Opening inside prior value area ({prior_val:.0f}-{prior_vah:.0f}). "
                f"Rotational market — all setups allowed. "
                f"Fade extremes, buy/sell at VA boundaries."
            ),
            gate_overrides={
                "allow_all_setups": True,
            },
        )

    # Fallback
    return OpeningTypeResult(
        opening_type="UNKNOWN",
        confidence=0.0,
        direction="",
        allowed_setups=("AAA", "MOMENTUM", "MEAN_REVERSION", "FAILED_AUCTION"),
        blocked_setups=(),
        thesis="Opening type unclear — use default setup permissions.",
        gate_overrides={},
    )


def get_setup_permissions(opening_type: str) -> dict:
    """Get setup permissions for a given opening type.

    Returns dict with:
    - allowed: tuple of allowed setup types
    - blocked: tuple of blocked setup types
    - mr_block_minutes: minutes to block mean reversion (if applicable)
    """
    permissions = {
        "OPEN_DRIVE": {
            "allowed": ("MOMENTUM",),
            "blocked": ("MEAN_REVERSION", "AAA"),
            "mr_block_minutes": 60,
        },
        "OPEN_TEST_DRIVE": {
            "allowed": ("FAILED_AUCTION", "MEAN_REVERSION", "AAA"),
            "blocked": ("MOMENTUM",),
            "mr_block_minutes": 0,
        },
        "OPEN_REJECTION_REVERSE": {
            "allowed": ("FAILED_AUCTION", "MEAN_REVERSION"),
            "blocked": ("MOMENTUM",),
            "mr_block_minutes": 0,
        },
        "OPEN_AUCTION": {
            "allowed": ("AAA", "MEAN_REVERSION", "MOMENTUM", "FAILED_AUCTION"),
            "blocked": (),
            "mr_block_minutes": 0,
        },
        "OPEN_AUCTION_OOR": {
            "allowed": ("MOMENTUM", "FAILED_AUCTION"),
            "blocked": ("AAA",),
            "mr_block_minutes": 30,
        },
        "GAP_FILL": {
            "allowed": ("MEAN_REVERSION", "AAA"),
            "blocked": ("MOMENTUM",),
            "mr_block_minutes": 45,
        },
        "UNKNOWN": {
            "allowed": ("AAA", "MEAN_REVERSION", "MOMENTUM", "FAILED_AUCTION"),
            "blocked": (),
            "mr_block_minutes": 0,
        },
    }
    return permissions.get(opening_type, permissions["UNKNOWN"])
