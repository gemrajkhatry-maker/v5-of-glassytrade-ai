"""Gate 3 — the Triple-A edge (Fabio: absorption -> accumulation -> aggression)."""

from quant.contracts.enums import MarketState

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

# Fresh absorption window (bars): the absorption must be recent enough to back
# the breakout — older footprints are re-tested, not traded through.
_ABSORPTION_MAX_AGE_BARS = 5

# Depth-derived order-flow aggression (Fabio's A3): |OBI| above this threshold
# with the price beyond the matching VWAP band is an aggression confirmation.
# OBI is the live order-book imbalance ([-1, 1]) computed by the AMT analyzer
# from the Dhan 5-level depth snapshot.
_OBI_AGGRESSION_THRESHOLD = 0.20


def _check_guards(ctx: DecisionContext) -> GateResult | None:
    """Pre-check guards that veto entry before setup evaluation."""
    if ctx.bar is None:
        return GateResult(3, False, "No bar")
    si_dir = getattr(ctx, "stacked_imbalance_direction", "")
    if si_dir and ctx.agent_direction:
        if (ctx.agent_direction == "LONG" and si_dir == "SELL") or (ctx.agent_direction == "SHORT" and si_dir == "BUY"):
            mag = getattr(ctx, "stacked_imbalance_magnitude", 0)
            lo = getattr(ctx, "stacked_imbalance_price_low", 0.0)
            hi = getattr(ctx, "stacked_imbalance_price_high", 0.0)
            return GateResult(3, False, f"Opposing stacked {si_dir} imbalance x{mag} at {lo:.2f}-{hi:.2f}")
    if getattr(ctx, "contested_bubble_zone", False):
        return GateResult(3, False, "Contested bubble zone — both sides stacked, stay flat")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(3, False, "No direction")
    ms_val = getattr(ctx.market_state, "value", ctx.market_state)
    if ms_val in (MarketState.DEAD.value, "DEAD", "DEAD_MARKET"):
        return GateResult(3, False, "Dead market — no edge")
    close_px = float(ctx.bar.close) if ctx.bar else 0.0
    if ctx.agent_direction == "LONG" and ctx.vwap_upper_2 > 0 and close_px > ctx.vwap_upper_2:
        return GateResult(3, False, f"Anti-Climax: LONG rejected at +{ctx.vwap_std:.1f}σ extension")
    if ctx.agent_direction == "SHORT" and ctx.vwap_lower_2 > 0 and close_px < ctx.vwap_lower_2:
        return GateResult(3, False, f"Anti-Climax: SHORT rejected at -{ctx.vwap_std:.1f}σ extension")
    if getattr(ctx, "drive_number", 0) >= 3 and not getattr(ctx, "drive_entry_valid", False):
        return GateResult(3, False, f"Drive count exhausted ({ctx.drive_number})")
    cvd_slope = ctx.cvd_slope
    if ctx.agent_direction == "LONG" and cvd_slope < -0.5:
        return GateResult(3, False, f"CVD slope aggressively negative ({cvd_slope:.2f}) conflicts with LONG")
    if ctx.agent_direction == "SHORT" and cvd_slope > 0.5:
        return GateResult(3, False, f"CVD slope aggressively positive ({cvd_slope:.2f}) conflicts with SHORT")
    return None


def _check_setup_paths(ctx: DecisionContext, cvd_slope: float) -> GateResult | None:
    """Check each setup path (evidence, Triple-A, drive, LVN, initiative)."""
    if getattr(ctx, "setup_evidence", None) is not None:
        ev = ctx.setup_evidence
        if ev.is_complete():
            if ev.direction and ev.direction != ctx.agent_direction:
                return GateResult(3, False, f"Evidence direction {ev.direction} conflicts with trade direction {ctx.agent_direction}")
            return GateResult(3, True, f"{ev.setup_type} confirmed")
    phase = getattr(ctx, "triple_a_phase", "") or ""
    tsignal = getattr(ctx, "triple_a_signal", "") or ""
    if phase == "AGGRESSION" and tsignal == ctx.agent_direction:
        return GateResult(3, True, f"Triple-A AGGRESSION {tsignal}")
    if ctx.drive_entry_valid:
        return GateResult(3, True, "Second Drive reclaim confirmed")
    leg_lvn = getattr(ctx, "leg_lvn", 0.0) or 0.0
    if leg_lvn > 0 and ctx.bar:
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        price = float(ctx.bar.close)
        if abs(price - leg_lvn) <= 2.0 * tick:
            if ctx.absorption_side == "SELL_ABSORBED" and ctx.agent_direction == "LONG" and cvd_slope >= -0.2:
                return GateResult(3, True, f"LVN Sniper LONG @ {leg_lvn:.2f}")
            if ctx.absorption_side == "BUY_ABSORBED" and ctx.agent_direction == "SHORT" and cvd_slope <= 0.2:
                return GateResult(3, True, f"LVN Sniper SHORT @ {leg_lvn:.2f}")
    break_dir = getattr(ctx, "break_direction", "") or ""
    break_type = getattr(ctx, "break_type", "") or ""
    if break_type == "INITIATIVE":
        if break_dir == "UP" and ctx.agent_direction == "LONG" and cvd_slope > -0.2:
            return GateResult(3, True, "Initiative upside breakout confirmed")
        if break_dir == "DOWN" and ctx.agent_direction == "SHORT" and cvd_slope < 0.2:
            return GateResult(3, True, "Initiative downside breakdown confirmed")
    return None


def gate_triple_a_edge(ctx: DecisionContext) -> GateResult:
    """Gate 3: Triple-A edge — the institutional entry trigger (Fabio Valentini).

    Three valid canonical paths: Triple-A AGGRESSION, IB Second Drive, LVN Sniper.
    Guards: volume bubble, contested zone, anti-climax, drive exhaustion, CVD direction.
    """
    r = _check_guards(ctx)
    if r: return r
    r = _check_setup_paths(ctx, ctx.cvd_slope)
    if r: return r
    return GateResult(3, False, "No Triple-A edge: no valid setup")
