"""Rule-based deterministic rationale helper."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RationaleContext:
    market_state: str
    zone: str
    poc: float
    vah: float
    val: float
    price: float
    aggression_score: float
    aggression_confidence: str
    footprint_confirmed: bool
    cvd_confirmed: bool
    big_trade_confirmed: bool
    absorption_detected: bool
    ofi_aligned: bool
    confluence_bonus: bool
    volume_bubble_near: bool
    cvd_slope: float
    cvd_divergence: str
    drive_number: int
    drive_level: float
    direction: str
    setup_type: str
    entry_price: float
    stop_loss: float
    take_profit: float
    r_r_ratio: float
    gate_number: int
    profile_shape: str
    lvn_play: dict | None = None
    vwap: float = 0.0
    vwap_bias: str = ""


class RuleBasedRationale:
    def generate(self, ctx: RationaleContext) -> str:
        if ctx.direction == "FLAT":
            return self._generate_flat(ctx)
        return " ".join([
            self._market_state_sentence(ctx),
            self._key_level_sentence(ctx),
            self._aggression_sentence(ctx),
            self._setup_sentence(ctx),
            self._drive_sentence(ctx) if ctx.drive_number >= 2 else "",
            self._lvn_sentence(ctx) if ctx.lvn_play else "",
        ]).strip()

    def _generate_flat(self, ctx: RationaleContext) -> str:
        if ctx.r_r_ratio < 1.5:
            return f"R:R too low ({ctx.r_r_ratio:.2f}); wait for better structure."
        if ctx.aggression_score < 2.0:
            return f"Insufficient aggression ({ctx.aggression_score:.1f}/4.5); no entry."
        return "No high-confidence directional edge."

    def _market_state_sentence(self, ctx: RationaleContext) -> str:
        if ctx.market_state == "IMBALANCED":
            return f"Market IMBALANCED. Price {ctx.price:.2f} outside VA ({ctx.val:.2f}-{ctx.vah:.2f})."
        if ctx.market_state == "BALANCED":
            return f"Market BALANCED{f' ({ctx.zone})' if ctx.zone else ''}. Price {ctx.price:.2f} near VA ({ctx.val:.2f}-{ctx.vah:.2f})."
        return f"Market state {ctx.market_state}."

    def _key_level_sentence(self, ctx: RationaleContext) -> str:
        levels = {"POC": ctx.poc, "VAH": ctx.vah, "VAL": ctx.val}
        if ctx.drive_level > 0:
            levels[f"D{ctx.drive_number}"] = ctx.drive_level
        nearest = min(levels, key=lambda n: abs(ctx.price - levels[n]))
        nearest_price = levels[nearest]
        dist = abs(ctx.price - nearest_price)
        if dist < ctx.price * 0.001:
            return f"Price at {nearest} ({nearest_price:.2f})."
        return f"Nearest level: {nearest} at {nearest_price:.2f} ({dist:.2f} away)."

    def _aggression_sentence(self, ctx: RationaleContext) -> str:
        components = []
        if ctx.footprint_confirmed:
            components.append("footprint imbalance")
        if ctx.cvd_confirmed:
            components.append(f"CVD {ctx.cvd_divergence.lower()}" if ctx.cvd_divergence else "CVD aligned")
        if ctx.big_trade_confirmed:
            components.append("institutional prints")
        if ctx.absorption_detected:
            components.append("absorption")
        if ctx.ofi_aligned:
            components.append("OFI aligned")
        if ctx.confluence_bonus:
            components.append("confluence")
        if ctx.volume_bubble_near:
            components.append("volume bubble")
        if not components:
            return f"Aggression {ctx.aggression_score:.1f}/4.5 ({ctx.aggression_confidence})."
        return f"Aggression {ctx.aggression_score:.1f}/4.5 ({ctx.aggression_confidence}): {', '.join(components)}."

    def _setup_sentence(self, ctx: RationaleContext) -> str:
        setup = "Trend" if ctx.setup_type == "TREND_MODEL" else "Mean Reversion"
        reward = abs(ctx.take_profit - ctx.entry_price)
        risk = abs(ctx.entry_price - ctx.stop_loss)
        return f"{setup} {ctx.direction}: entry {ctx.entry_price:.2f}, SL {ctx.stop_loss:.2f} ({risk:.2f}), TP {ctx.take_profit:.2f} ({reward:.2f}), R:R {ctx.r_r_ratio:.2f}."

    def _drive_sentence(self, ctx: RationaleContext) -> str:
        return f"Drive {ctx.drive_number} at {ctx.drive_level:.2f}."

    def _lvn_sentence(self, ctx: RationaleContext) -> str:
        if not ctx.lvn_play:
            return ""
        return f"LVN play: {ctx.lvn_play.get('direction', '')} at {ctx.lvn_play.get('price', 0):.2f}."

    def generate_market_narrative(self, prev_state: str, curr_state: str, poc: float, vah: float, val: float, price: float) -> str:
        return f"Market state transition: {prev_state} -> {curr_state} at {price:.2f} (POC {poc:.2f}, VA {val:.2f}-{vah:.2f})."

    def generate_risk_commentary(self, event_type: str, consecutive_losses: int, daily_pnl: float, max_drawdown: float) -> str:
        if event_type == "CONSECUTIVE_LOSSES":
            return f"{consecutive_losses} consecutive losses. Daily P&L: {daily_pnl:.2f}. Max drawdown: {max_drawdown:.2%}."
        if event_type == "DAILY_LOSS_LIMIT":
            return f"Daily loss limit hit. P&L: {daily_pnl:.2f}. Trading paused."
        if event_type == "DRAWDOWN_LIMIT":
            return f"Max drawdown limit hit ({max_drawdown:.2%}). Trading paused."
        return f"Risk event: {event_type}."
