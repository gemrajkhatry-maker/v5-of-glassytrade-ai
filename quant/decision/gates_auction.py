from quant.decision.context import DecisionContext
from quant.decision.result import GateResult


def gate_failed_auction_sequence(ctx: DecisionContext) -> GateResult:
    """Fabio: in BALANCE, entries must be failed-auction reversion —
    outside probe, reclaim, return visit. A first-touch at a level is NOT
    evidence. Continuation trades in IMBALANCE do not need a failed auction."""
    if ctx.market_state not in ("BALANCE", "BALANCED"):
        return GateResult(gate=3, passed=True)
    if getattr(ctx, "drive_entry_valid", False):
        return GateResult(gate=3, passed=True)
    drive = getattr(ctx, "drive_number", 0) or 0
    return GateResult(
        gate=3,
        passed=False,
        reason=f"Failed-auction sequence incomplete (drive={drive}, entry_valid=False)",
    )
