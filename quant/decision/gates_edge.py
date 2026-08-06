from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


def gate_direction_probability(ctx: DecisionContext, min_probability: float = 0.55) -> GateResult:
    """Gate 3: direction + probability threshold, CVD-conflict aware."""
    state = ctx.state
    if state is None:
        return GateResult(3, False, "No state")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(3, False, "No direction")
    if ctx.agent_probability < min_probability:
        return GateResult(3, False, "Probability below threshold")
    cvd_slope = state.order_flow.cvd_slope
    if ctx.agent_direction == "LONG" and cvd_slope < 0:
        return GateResult(3, False, "CVD conflict")
    if ctx.agent_direction == "SHORT" and cvd_slope > 0:
        return GateResult(3, False, "CVD conflict")
    return GateResult(3, True)


def gate_triple_a_edge(ctx: DecisionContext) -> GateResult:
    """Gate 4: AGGRESSION signal or fresh absorption backing a VWAP breakout.

    Requires the machine's edge (Triple-A signal or absorption side) to agree
    with the agent's intended direction, so an edge and an agent that disagree
    can never produce an inverted signal.
    """
    state = ctx.state
    if state is None:
        return GateResult(4, False, "No state")
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "No direction")
    if state.triple_a_phase == "AGGRESSION" and state.triple_a_signal is not None:
        if state.triple_a_signal != ctx.agent_direction:
            return GateResult(4, False, "Triple-A direction conflicts with agent direction")
        return GateResult(4, True)
    if state.absorption is not None and state.absorption.bar_age <= 3:
        if state.absorption.side == "BUY" and state.close > state.vwap.upper_1:
            if ctx.agent_direction != "LONG":
                return GateResult(4, False, "Absorption direction conflicts with agent direction")
            return GateResult(4, True)
        if state.absorption.side == "SELL" and state.close < state.vwap.lower_1:
            if ctx.agent_direction != "SHORT":
                return GateResult(4, False, "Absorption direction conflicts with agent direction")
            return GateResult(4, True)
    return GateResult(4, False, "No Triple-A edge")
