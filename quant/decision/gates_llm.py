"""Gate 7 — LLM consensus.

When LLM execution is enabled (``ctx.llm_execution_enabled``), an entry must
have the LLM advisory AGREE with the deterministic Triple-A direction at High
confidence, and the advisory must be fresh (analyzed the current or
immediately-previous bar). The LLM can only BLOCK — it can never invent a
direction the kernel didn't already find. When execution is disabled (the
default), the gate passes trivially and the LLM stays advisory-only.
"""

from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


def gate_llm_consensus(ctx: DecisionContext) -> GateResult:
    """Gate 7: LLM advisory must confirm the deterministic direction."""
    if not ctx.llm_execution_enabled:
        return GateResult(7, True, "LLM consensus disabled (advisory-only)")
    # No deterministic direction: gate 4 already blocks; nothing to confirm.
    if ctx.agent_direction not in ("LONG", "SHORT"):
        return GateResult(7, True, "No deterministic direction — not applicable")
    if not ctx.llm_fresh:
        return GateResult(7, False, "LLM advisory stale (older than one bar)")
    if ctx.llm_direction not in ("LONG", "SHORT"):
        return GateResult(7, False, f"LLM advisory has no direction ({ctx.llm_direction})")
    if ctx.llm_direction != ctx.agent_direction:
        return GateResult(
            6,
            False,
            f"LLM {ctx.llm_direction} disagrees with deterministic {ctx.agent_direction}",
        )
    if str(ctx.llm_confidence or "").lower() != "high":
        return GateResult(
            6, False, f"LLM confidence {ctx.llm_confidence or 'n/a'} < High"
        )
    return GateResult(7, True, "LLM confirms deterministic direction (High)")
