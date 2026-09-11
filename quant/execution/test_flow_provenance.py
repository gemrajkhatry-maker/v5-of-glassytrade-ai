"""Tests for broker-neutral order-flow provenance safety."""

import pytest

from quant.execution.flow_provenance import (
    FlowProvenance,
    InferredFlowRejected,
    require_exact_l2_for_paper,
)


def test_exact_l2_flow_is_allowed_for_paper():
    assert require_exact_l2_for_paper(FlowProvenance.EXACT_L2) is None


def test_inferred_amt_tick_flow_is_rejected_for_paper():
    with pytest.raises(InferredFlowRejected, match="exact L2"):
        require_exact_l2_for_paper(FlowProvenance.INFERRED_AMT_TICK)


def test_unknown_provenance_fails_closed():
    with pytest.raises(InferredFlowRejected, match="provenance"):
        require_exact_l2_for_paper("unknown")
