"""Parity: evaluate_short_gates via legacy shim vs moved quant module."""

from __future__ import annotations

from app.domain.services.short_signal_gates import (
    evaluate_short_gates as legacy_evaluate,
    check_s1_direction_allowed as legacy_s1,
    check_s2_market_state as legacy_s2,
    check_s3_ml_probability as legacy_s3,
    check_s4_aggression_direction as legacy_s4,
    check_s5_contract_type as legacy_s5,
)
from quant.decision.gates.short import (
    evaluate_short_gates,
    check_s1_direction_allowed,
    check_s2_market_state,
    check_s3_ml_probability,
    check_s4_aggression_direction,
    check_s5_contract_type,
)
from tests.quant.parity import assert_parity


def test_individual_gates_parity():
    assert_parity(legacy_s1, check_s1_direction_allowed, True)
    assert_parity(legacy_s1, check_s1_direction_allowed, False)
    assert_parity(legacy_s2, check_s2_market_state, "IMBALANCED", "DOWN", False)
    assert_parity(legacy_s2, check_s2_market_state, "BALANCED", "", True)
    assert_parity(legacy_s2, check_s2_market_state, "PROBING", "DOWN", False)
    assert_parity(legacy_s3, check_s3_ml_probability, "imbalance_continuation", 0.60)
    assert_parity(legacy_s3, check_s3_ml_probability, "imbalance_continuation", 0.55)
    assert_parity(legacy_s4, check_s4_aggression_direction, 100, 200, -5.0, -0.3)
    assert_parity(legacy_s4, check_s4_aggression_direction, 200, 100, 5.0, 0.3)
    assert_parity(legacy_s5, check_s5_contract_type, "PE")
    assert_parity(legacy_s5, check_s5_contract_type, "CE")


def _pass_kwargs():
    return dict(
        short_enabled=True,
        market_state="IMBALANCED",
        displacement_direction="DOWN",
        failed_breakout=False,
        playbook="imbalance_continuation",
        ml_probability=0.60,
        bid_volume=100,
        ask_volume=200,
        cvd_slope=-5.0,
        delta_normalized=-0.3,
        contract_type="PE",
    )


def test_evaluate_short_gates_pass_parity():
    assert_parity(legacy_evaluate, evaluate_short_gates, **_pass_kwargs())


def test_evaluate_short_gates_s1_fail_parity():
    kwargs = _pass_kwargs()
    kwargs["short_enabled"] = False
    assert_parity(legacy_evaluate, evaluate_short_gates, **kwargs)


def test_evaluate_short_gates_s4_fail_parity():
    kwargs = _pass_kwargs()
    kwargs.update(bid_volume=200, ask_volume=100, cvd_slope=5.0, delta_normalized=0.3)
    assert_parity(legacy_evaluate, evaluate_short_gates, **kwargs)
