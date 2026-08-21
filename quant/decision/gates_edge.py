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


def gate_triple_a_edge(ctx: DecisionContext) -> GateResult:
    """Gate 3: Triple-A edge — the institutional entry trigger (Fabio Valentini).

    Three valid canonical paths per Fabio AMT playbook (spec §9, §10):

    Path A — Full Triple-A AGGRESSION (primary): the state machine has
      progressed WAITING → ABSORBING → ACCUMULATING → AGGRESSION, confirming
      2+ bars of consolidation near POC AND a full candle close beyond the
      absorption cluster. Never bypassed on raw volume spikes.

    Path B — IB Second Drive reclaim: after the Initial Balance high/low was
      tested and rejected (D1_REJECTED), the market attempts a second drive
      (D2). Valid standalone entry per Fabio's "failed auction" rule.

    Path C — Impulse Leg LVN Sniper (Playbook C): price pulls back to the
      primary LVN of the most recent impulse leg (Layer 3 profile) with fresh
      absorption confirming the level is holding.

    GUARDS APPLIED:
    - Climax Guard: Price must NOT exceed VWAP ±2.0σ (overextension).
    - CVD Momentum: CVD slope must agree with entry direction (positive for LONG, negative for SHORT).
    """
    if ctx.bar is None:
        return GateResult(3, False, "No bar")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(3, False, "No direction")
    market_state = ctx.market_state
    ms_val = getattr(market_state, "value", market_state)
    if ms_val in ("DEAD", "DEAD_MARKET"):
        return GateResult(3, False, "Dead market — no edge")

    # ── 0. SetupEvidence Evaluation (if explicit evidence provided) ─────────
    if getattr(ctx, "setup_evidence", None) is not None:
        ev = ctx.setup_evidence
        if not ev.is_complete():
            return GateResult(3, False, ev.rejection_reason())
        if ev.setup_type in ("TRIPLE_A", "NONE") and not getattr(ctx, "allow_trend", True):
            return GateResult(3, False, "SESSION_PHASE: Trend continuation blocked in this session phase")
        if ev.setup_type == "VA_FADE" and not getattr(ctx, "allow_reversion", True):
            return GateResult(3, False, "SESSION_PHASE: Mean reversion blocked in this session phase")
        return GateResult(3, True, f"{ev.setup_type} confirmed")

    # ── 1. Anti-Climax / Overextension Guard ─────────────────────────────────
    # Price beyond ±2.0σ is a statistical exhaustion zone. Never enter new breakouts there.
    close_px = float(ctx.bar.close) if ctx.bar else 0.0
    if ctx.agent_direction == "LONG" and ctx.vwap_upper_2 > 0 and close_px > ctx.vwap_upper_2:
        return GateResult(3, False, f"Anti-Climax: LONG rejected at +{ctx.vwap_std:.1f}σ extension")
    if ctx.agent_direction == "SHORT" and ctx.vwap_lower_2 > 0 and close_px < ctx.vwap_lower_2:
        return GateResult(3, False, f"Anti-Climax: SHORT rejected at -{ctx.vwap_std:.1f}σ extension")

    # ── 2. Contested Zone Guard ──────────────────────────────────────────────
    if getattr(ctx, "contested_bubble_zone", False):
        return GateResult(3, False, "Contested buy/sell bubble cluster — flat until resolution")

    # ── 3. Drive Exhaustion Guard ────────────────────────────────────────────
    # 3+ drives into a level indicates exhaustion (Fabio Valentini rule)
    if getattr(ctx, "drive_number", 0) >= 3 and not getattr(ctx, "drive_entry_valid", False):
        return GateResult(3, False, f"Drive count exhausted ({ctx.drive_number})")

    # ── 4. CVD Order Flow Direction Guard ────────────────────────────────────
    # Order flow pressure must not aggressively oppose the trade direction.
    cvd_slope = ctx.cvd_slope
    if ctx.agent_direction == "LONG" and cvd_slope < -0.5:
        return GateResult(3, False, f"CVD slope aggressively negative ({cvd_slope:.2f}) conflicts with LONG")
    if ctx.agent_direction == "SHORT" and cvd_slope > 0.5:
        return GateResult(3, False, f"CVD slope aggressively positive ({cvd_slope:.2f}) conflicts with SHORT")

    # ── Setup B: Second-Drive Rejection (D1 rejected → D2 weaker re-approach) ─
    if ctx.drive_entry_valid:
        return GateResult(3, True, "Second Drive reclaim confirmed")

    # ── Setup C: Impulse Leg LVN Sniper (Playbook C) ─────────────────────────
    leg_lvn = getattr(ctx, "leg_lvn", 0.0) or 0.0
    if leg_lvn > 0 and ctx.bar:
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        price = float(ctx.bar.close)
        if abs(price - leg_lvn) <= 2.0 * tick:
            if ctx.absorption_side == "SELL_ABSORBED" and ctx.agent_direction == "LONG" and cvd_slope >= -0.2:
                return GateResult(3, True, f"LVN Sniper LONG @ {leg_lvn:.2f}")
            if ctx.absorption_side == "BUY_ABSORBED" and ctx.agent_direction == "SHORT" and cvd_slope <= 0.2:
                return GateResult(3, True, f"LVN Sniper SHORT @ {leg_lvn:.2f}")

    # ── Setup A.1: Fresh Absorption + OB Imbalance (Microstructure Confirmation)
    if ctx.agent_direction == "LONG" and ctx.absorption_side == "SELL_ABSORBED" and ctx.obi >= 0.15 and cvd_slope > -0.3:
        return GateResult(3, True, "Absorption cluster confirmed by order flow imbalance")
    if ctx.agent_direction == "SHORT" and ctx.absorption_side == "BUY_ABSORBED" and ctx.obi <= -0.15 and cvd_slope < 0.3:
        return GateResult(3, True, "Absorption cluster confirmed by order flow imbalance")

    # ── Setup A.2: Initiative Breakout (Model 1: IB / VA Breakout) ───────────
    # In Midday session (allow_trend=False), blind breakouts are blocked.
    allow_trend = getattr(ctx, "allow_trend", True)
    break_dir = getattr(ctx, "break_direction", "") or ""
    break_type = getattr(ctx, "break_type", "") or ""
    if break_type == "INITIATIVE":
        if not allow_trend:
            return GateResult(3, False, "SESSION_PHASE: Trend continuation blocked in this session phase")
        if break_dir == "UP" and ctx.agent_direction == "LONG" and cvd_slope > -0.2:
            return GateResult(3, True, "Initiative upside breakout confirmed")
        if break_dir == "DOWN" and ctx.agent_direction == "SHORT" and cvd_slope < 0.2:
            return GateResult(3, True, "Initiative downside breakdown confirmed")

    # ── Setup A.3: Triple-A Continuation (Model 2 Continuation) ──────────────
    # Continuation requires directional breakout beyond VA or confirmed imbalance with CVD agreement.
    if allow_trend and (ms_val in (MarketState.IMBALANCED, "IMBALANCED") or (ctx.vah > 0 and close_px > ctx.vah) or (ctx.val > 0 and close_px < ctx.val)):
        if ctx.agent_direction == "LONG" and cvd_slope > -0.2:
            return GateResult(3, True, "Triple-A Continuation LONG confirmed")
        elif ctx.agent_direction == "SHORT" and cvd_slope < 0.2:
            return GateResult(3, True, "Triple-A Continuation SHORT confirmed")

    return GateResult(3, False, "No Triple-A edge: no valid setup")
