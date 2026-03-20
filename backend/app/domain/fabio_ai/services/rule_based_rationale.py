"""Rule-Based Rationale Generator — Deterministic trade explanation per Fabio AMT spec (FR-11).

Replaces LLM rationale with deterministic rule-based explanation.
No LLM dependency. Pure logic. Reproducible.

Every rationale includes:
1. Market state context
2. Key level identification
3. Aggression score breakdown
4. Gate validation summary
5. Setup type and R:R
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import AMTResult

logger = logging.getLogger(__name__)


@dataclass
class RationaleContext:
    """Context for rationale generation."""

    # Market state
    market_state: str  # NO_TRADE, BALANCED, IMBALANCED, PROBING
    zone: str  # NEAR_VAH, NEAR_VAL, NEAR_POC, ""

    # Volume profile
    poc: float
    vah: float
    val: float
    price: float

    # Aggression breakdown
    aggression_score: float
    aggression_confidence: str  # HIGH, MEDIUM, LOW
    footprint_confirmed: bool
    cvd_confirmed: bool
    big_trade_confirmed: bool
    absorption_detected: bool
    ofi_aligned: bool
    confluence_bonus: bool
    volume_bubble_near: bool

    # CVD
    cvd_slope: float
    cvd_divergence: str  # BULLISH_DIV, BEARISH_DIV, ""

    # Drive
    drive_number: int
    drive_level: float

    # Setup
    direction: str  # LONG, SHORT, FLAT
    setup_type: str  # TREND_MODEL, MEAN_REVERSION
    entry_price: float
    stop_loss: float
    take_profit: float
    r_r_ratio: float

    # Gate
    gate_number: int  # Last gate passed (0-12)

    # Profile shape
    profile_shape: str  # D, P, b, B, ""

    # LVN play
    lvn_play: dict | None = None

    # VWAP
    vwap: float = 0.0
    vwap_bias: str = ""  # ALIGNED, OPPOSING, NEUTRAL


class RuleBasedRationale:
    """Deterministic rationale generator per Fabio AMT spec.

    Generates human-readable trade explanations using pure logic.
    No LLM dependency. Reproducible. Fast (<1ms).
    """

    def generate(self, ctx: RationaleContext) -> str:
        """Generate trade rationale from context."""
        if ctx.direction == "FLAT":
            return self._generate_flat_rationale(ctx)

        parts = []

        # 1. Market state context
        parts.append(self._market_state_sentence(ctx))

        # 2. Key level identification
        parts.append(self._key_level_sentence(ctx))

        # 3. Aggression breakdown
        parts.append(self._aggression_sentence(ctx))

        # 4. Setup type and R:R
        parts.append(self._setup_sentence(ctx))

        # 5. Drive context
        if ctx.drive_number >= 2:
            parts.append(self._drive_sentence(ctx))

        # 6. LVN play
        if ctx.lvn_play:
            parts.append(self._lvn_sentence(ctx))

        return " ".join(parts)

    def _generate_flat_rationale(self, ctx: RationaleContext) -> str:
        """Generate rationale for FLAT decision."""
        if ctx.market_state == "NO_TRADE":
            return f"NO_TRADE: Price at POC dead zone ({ctx.poc:.2f}). Waiting for price to move away from POC."
        if ctx.market_state == "PROBING":
            return f"PROBING: Price outside VA without displacement confirmation. Waiting for acceptance."
        if ctx.aggression_score < 2.0:
            return f"Insufficient aggression ({ctx.aggression_score:.1f}/4.5). Need ≥2.0 for trade signal."
        if ctx.r_r_ratio < 1.5:
            return f"R:R too low ({ctx.r_r_ratio:.2f}). Need ≥1.5 for valid setup."
        return "No clear setup. Waiting for alignment of market state, location, and aggression."

    def _market_state_sentence(self, ctx: RationaleContext) -> str:
        """Market state context sentence."""
        if ctx.market_state == "IMBALANCED":
            return f"Market IMBALANCED (trending). Price {ctx.price:.2f} outside VA ({ctx.val:.2f}-{ctx.vah:.2f})."
        if ctx.market_state == "BALANCED":
            zone_str = f" ({ctx.zone})" if ctx.zone else ""
            return f"Market BALANCED{zone_str}. Price {ctx.price:.2f} inside VA ({ctx.val:.2f}-{ctx.vah:.2f})."
        return f"Market state: {ctx.market_state}."

    def _key_level_sentence(self, ctx: RationaleContext) -> str:
        """Key level identification sentence."""
        # Find nearest level
        levels = {
            "POC": ctx.poc,
            "VAH": ctx.vah,
            "VAL": ctx.val,
        }
        if ctx.drive_level > 0:
            levels[f"D{ctx.drive_number}"] = ctx.drive_level

        nearest_name = min(levels, key=lambda k: abs(ctx.price - levels[k]))
        nearest_price = levels[nearest_name]
        dist = abs(ctx.price - nearest_price)

        if dist < ctx.price * 0.001:
            return f"Price at {nearest_name} ({nearest_price:.2f})."
        return f"Nearest level: {nearest_name} at {nearest_price:.2f} ({dist:.2f} away)."

    def _aggression_sentence(self, ctx: RationaleContext) -> str:
        """Aggression score breakdown sentence."""
        components = []
        if ctx.footprint_confirmed:
            components.append("footprint imbalance")
        if ctx.cvd_confirmed:
            if ctx.cvd_divergence:
                components.append(f"CVD {ctx.cvd_divergence.replace('_', ' ').lower()}")
            else:
                components.append("CVD aligned")
        if ctx.big_trade_confirmed:
            components.append("institutional prints")
        if ctx.absorption_detected:
            components.append("absorption")
        if ctx.ofi_aligned:
            components.append("OFI aligned")
        if ctx.confluence_bonus:
            components.append("profile confluence")
        if ctx.volume_bubble_near:
            components.append("volume bubble")

        if not components:
            return f"Aggression {ctx.aggression_score:.1f}/4.5 ({ctx.aggression_confidence})."

        comp_str = ", ".join(components)
        return f"Aggression {ctx.aggression_score:.1f}/4.5 ({ctx.aggression_confidence}): {comp_str}."

    def _setup_sentence(self, ctx: RationaleContext) -> str:
        """Setup type and R:R sentence."""
        setup = "Trend" if ctx.setup_type == "TREND_MODEL" else "Mean Reversion"
        risk = abs(ctx.entry_price - ctx.stop_loss)
        reward = abs(ctx.take_profit - ctx.entry_price)
        return (
            f"{setup} {ctx.direction}: entry {ctx.entry_price:.2f}, "
            f"SL {ctx.stop_loss:.2f} ({risk:.2f}), TP {ctx.take_profit:.2f} ({reward:.2f}), "
            f"R:R {ctx.r_r_ratio:.2f}."
        )

    def _drive_sentence(self, ctx: RationaleContext) -> str:
        """Drive context sentence."""
        if ctx.drive_number == 2:
            return f"Second drive at {ctx.drive_level:.2f} — D1 rejected, entry valid."
        return f"Drive {ctx.drive_number} at {ctx.drive_level:.2f}."

    def _lvn_sentence(self, ctx: RationaleContext) -> str:
        """LVN play context sentence."""
        if not ctx.lvn_play:
            return ""
        lvn_dir = ctx.lvn_play.get("direction", "")
        lvn_price = ctx.lvn_play.get("price", 0)
        return f"LVN play: {lvn_dir} at thin node {lvn_price:.2f}."

    def generate_market_narrative(
        self,
        prev_state: str,
        curr_state: str,
        poc: float,
        vah: float,
        val: float,
        price: float,
    ) -> str:
        """Generate market narrative on state change."""
        if prev_state == "BALANCED" and curr_state == "IMBALANCED":
            return (
                f"Market transitioning from BALANCE to IMBALANCE. "
                f"Price {price:.2f} broke outside VA ({val:.2f}-{vah:.2f}) with displacement. "
                f"Trend mode active."
            )
        if prev_state == "IMBALANCED" and curr_state == "BALANCED":
            return (
                f"Market returning to BALANCE. "
                f"Price {price:.2f} re-entered VA ({val:.2f}-{vah:.2f}). "
                f"Trend momentum fading."
            )
        if prev_state == "BALANCED" and curr_state == "PROBING":
            return (
                f"Market PROBING outside VA. "
                f"Price {price:.2f} outside VA ({val:.2f}-{vah:.2f}) without displacement. "
                f"Waiting for confirmation."
            )
        if curr_state == "NO_TRADE":
            return f"Price at POC dead zone ({poc:.2f}). NO_TRADE — waiting for movement."
        return f"Market state: {prev_state} → {curr_state}."

    def generate_risk_commentary(
        self,
        event_type: str,
        consecutive_losses: int,
        daily_pnl: float,
        max_drawdown: float,
    ) -> str:
        """Generate risk commentary on risk events."""
        if event_type == "CONSECUTIVE_LOSSES":
            return (
                f"{consecutive_losses} consecutive losses. "
                f"Daily P&L: {daily_pnl:.2f}. "
                f"Max drawdown: {max_drawdown:.2%}. "
                f"Reviewing market structure."
            )
        if event_type == "DAILY_LOSS_LIMIT":
            return (
                f"Daily loss limit hit. P&L: {daily_pnl:.2f}. "
                f"Trading paused for session."
            )
        if event_type == "DRAWDOWN_LIMIT":
            return (
                f"Max drawdown limit hit ({max_drawdown:.2%}). "
                f"Trading paused."
            )
        return f"Risk event: {event_type}."