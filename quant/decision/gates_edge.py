"""Gate 3 — the Triple-A edge (Fabio: absorption -> accumulation -> aggression)."""

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult

# Fresh absorption window (bars): the absorption must be recent enough to back
# the breakout — older footprints are re-tested, not traded through.
_ABSORPTION_MAX_AGE_BARS = 3


def gate_triple_a_edge(ctx: DecisionContext) -> GateResult:
    """Gate 3: AGGRESSION signal or fresh absorption backing a VWAP breakout.

    The machine's edge (Triple-A signal or absorption side) must agree with the
    intended direction, so an edge and a direction that disagree can never
    produce an inverted signal.

    Fabio's playbook (Valentini Triple-A, see amt_docs/):
      - Absorption:  high volume, little movement at a level (BUY/SELL side).
      - Accumulation: consolidation near POC (implicit between absorption and
        the breakout — the machine's phase machine tracks it).
      - Aggression:   breakout beyond VWAP with volume — the entry trigger.
    LONG requires BUY absorption + close above the VWAP band; SHORT requires
    SELL absorption + close below the VWAP band. A DEAD market (volume
    collapse) rejects — there is nothing to trade. Entries are allowed in both
    BALANCED and IMBALANCED auctions: in balance the same absorption/breakout
    rule applies, and the VA-fade tier covers balance-returning reversion.
    """
    state = ctx.state
    if state is None:
        return GateResult(3, False, "No state")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(3, False, "No direction")
    market_state = str(ctx.market_state or "").upper()
    if market_state in ("DEAD", "DEAD_MARKET"):
        return GateResult(3, False, "Dead market — no edge")
    if state.triple_a_phase == "AGGRESSION" and state.triple_a_signal is not None:
        if state.triple_a_signal != ctx.agent_direction:
            return GateResult(3, False, "Triple-A direction conflicts with agent direction")
        return GateResult(3, True)
    if state.absorption is not None and state.absorption.bar_age <= _ABSORPTION_MAX_AGE_BARS:
        if state.absorption.side == "BUY" and state.close > state.vwap.upper_1:
            if ctx.agent_direction != "LONG":
                return GateResult(3, False, "Absorption direction conflicts with agent direction")
            return GateResult(3, True)
        if state.absorption.side == "SELL" and state.close < state.vwap.lower_1:
            if ctx.agent_direction != "SHORT":
                return GateResult(3, False, "Absorption direction conflicts with agent direction")
            return GateResult(3, True)
    return GateResult(3, False, "No Triple-A edge")
