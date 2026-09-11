"""Broker-neutral provenance contracts for order-flow safety checks."""

from enum import Enum


class FlowProvenance(str, Enum):
    """Evidence level behind an order-flow observation."""

    EXACT_L2 = "exact_l2"
    INFERRED_AMT_TICK = "inferred_amt_tick"


class InferredFlowRejected(ValueError):
    """Raised when paper safety requires exact L2 evidence."""


def require_exact_l2_for_paper(provenance: FlowProvenance) -> None:
    """Reject inferred or unknown flow before it can drive paper orders."""
    if provenance is not FlowProvenance.EXACT_L2:
        raise InferredFlowRejected(
            "paper order-flow requires exact L2 provenance; "
            f"received {getattr(provenance, 'value', provenance)!r} provenance"
        )
