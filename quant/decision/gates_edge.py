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
    """Gate 3: Triple-A edge — the entry trigger.

    Four valid paths per Fabio AMT playbook (spec §9, §10):

    Path A — Full Triple-A AGGRESSION (primary): the state machine has
      progressed WAITING → ABSORBING → ACCUMULATING → AGGRESSION, confirming
      2+ bars of consolidation near POC AND a full candle close beyond the
      absorption cluster. This is the canonical Fabio entry. Never bypassed.

    Path B — IB Second Drive reclaim: after the Initial Balance high/low was
      tested and rejected (D1_REJECTED), the market attempts a second drive
      (D2). Valid standalone entry per Fabio's "failed auction" rule.

    Path C — Impulse Leg LVN Sniper (Playbook C): price pulls back to the
      primary LVN of the most recent impulse leg (Layer 3 profile) with fresh
      absorption confirming the level is holding. R:R >= 3.0 required.
      Requires ctx.leg_lvn to be populated by runtime._decide().

    Path D — OBI depth aggression (fallback): the live 5-level order book
      shows a one-sided imbalance (|OBI| >= 0.20) while price is beyond the
      matching VWAP sigma band. Triggers only when Paths A/B/C do not fire
      and provides a depth-confirmed breakout entry.

    REMOVED: Priority 2 (fresh absorption + VWAP band alone WITHOUT the
      AGGRESSION phase) — this was the anti-whipsaw violation. Entering on
      the first raw intra-bar spike is exactly what Fabio warns never to do
      (spec §9.1 Anti-Whipsaw Rule). The Triple-A machine's 2-bar accumulation
      guard must not be bypassed.
    """
    state = ctx.state
    if state is None:
        return GateResult(3, False, "No state")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(3, False, "No direction")
    market_state = ctx.market_state
    ms_val = getattr(market_state, "value", market_state)
    if ms_val in ("DEAD", "DEAD_MARKET"):
        return GateResult(3, False, "Dead market — no edge")

    # ── Path A: Full Triple-A AGGRESSION (canonical — all 3 phases confirmed) ─
    if state.triple_a_phase == "AGGRESSION" and state.triple_a_signal is not None:
        if state.triple_a_signal != ctx.agent_direction:
            return GateResult(3, False, "Triple-A direction conflicts with agent direction")
        return GateResult(3, True, "Triple-A AGGRESSION confirmed")

    # ── Path A2: Fresh absorption backing a VWAP breakout ───────────────────
    if state.absorption is not None and state.absorption.bar_age <= _ABSORPTION_MAX_AGE_BARS:
        if state.absorption.side == "BUY" and state.close > state.vwap.upper_1:
            if ctx.agent_direction != "LONG":
                return GateResult(3, False, "Absorption direction conflicts with agent direction")
            return GateResult(3, True, "Absorption + upper-band breakout")
        if state.absorption.side == "SELL" and state.close < state.vwap.lower_1:
            if ctx.agent_direction != "SHORT":
                return GateResult(3, False, "Absorption direction conflicts with agent direction")
            return GateResult(3, True, "Absorption + lower-band breakout")

    # ── Path B: IB Second Drive (D1 rejected → D2 re-approach) ───────────────
    if ctx.drive_entry_valid:
        return GateResult(3, True, "IB Second Drive reclaim")

    # ── Path C: Impulse Leg LVN Sniper (Playbook C) ───────────────────────────
    # Price retests the primary LVN of the most recent impulse leg with a fresh
    # absorption cluster confirming the level holds.
    leg_lvn = getattr(ctx, "leg_lvn", 0.0) or 0.0
    if leg_lvn > 0:
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        price = float(state.close)
        if abs(price - leg_lvn) <= 2.0 * tick:
            absorption = state.absorption
            if absorption is not None and absorption.bar_age == 0:
                if absorption.side == "BUY" and ctx.agent_direction == "LONG":
                    return GateResult(3, True, f"LVN Sniper LONG @ {leg_lvn:.2f}")
                if absorption.side == "SELL" and ctx.agent_direction == "SHORT":
                    return GateResult(3, True, f"LVN Sniper SHORT @ {leg_lvn:.2f}")

    # ── Path D: OBI depth aggression (live book confirms breakout) ─────────────
    obi = float(ctx.obi or 0.0)
    if obi >= _OBI_AGGRESSION_THRESHOLD and state.close > state.vwap.upper_1:
        if ctx.agent_direction != "LONG":
            return GateResult(3, False, "OBI aggression conflicts with agent direction")
        return GateResult(3, True, "OBI aggression + upper-band breakout")
    if obi <= -_OBI_AGGRESSION_THRESHOLD and state.close < state.vwap.lower_1:
        if ctx.agent_direction != "SHORT":
            return GateResult(3, False, "OBI aggression conflicts with agent direction")
        return GateResult(3, True, "OBI aggression + lower-band breakout")

    return GateResult(3, False, "No Triple-A edge")
