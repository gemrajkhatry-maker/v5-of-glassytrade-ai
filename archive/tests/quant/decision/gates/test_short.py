"""Tests for SHORT Signal Gates — ported from backend/tests/unit/domain/test_ib_and_short.py."""

from quant.decision.gates.short import (
    ShortGateResult,
    check_s1_direction_allowed,
    check_s2_market_state,
    check_s3_ml_probability,
    check_s4_aggression_direction,
    check_s5_contract_type,
    evaluate_short_gates,
)


class TestShortGates:
    def test_s1_blocked_when_disabled(self):
        r = check_s1_direction_allowed(False)
        assert not r.passed
        assert "S1_DIRECTION" in r.gate_name

    def test_s1_passes_when_enabled(self):
        r = check_s1_direction_allowed(True)
        assert r.passed

    def test_s2_imbalanced_down(self):
        r = check_s2_market_state("IMBALANCED", "DOWN", False)
        assert r.passed

    def test_s2_balanced_failed_breakout(self):
        r = check_s2_market_state("BALANCED", "", True)
        assert r.passed

    def test_s2_rejects_invalid_state(self):
        r = check_s2_market_state("PROBING", "DOWN", False)
        assert not r.passed

    def test_s3_ml_probability_pass(self):
        r = check_s3_ml_probability("imbalance_continuation", 0.60)
        assert r.passed

    def test_s3_ml_probability_fail(self):
        r = check_s3_ml_probability("imbalance_continuation", 0.55)
        assert not r.passed

    def test_s4_seller_aggression(self):
        r = check_s4_aggression_direction(
            bid_volume=100, ask_volume=200, cvd_slope=-5.0, delta_normalized=-0.3
        )
        assert r.passed

    def test_s4_buyer_aggression_fails(self):
        r = check_s4_aggression_direction(
            bid_volume=200, ask_volume=100, cvd_slope=5.0, delta_normalized=0.3
        )
        assert not r.passed

    def test_s5_pe_contract(self):
        r = check_s5_contract_type("PE")
        assert r.passed

    def test_s5_ce_contract_fails(self):
        r = check_s5_contract_type("CE")
        assert not r.passed

    def test_full_short_evaluation_pass(self):
        passed, results = evaluate_short_gates(
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
        assert passed is True
        assert len(results) == 5

    def test_full_short_evaluation_fail_at_s1(self):
        passed, results = evaluate_short_gates(
            short_enabled=False,
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
        assert passed is False
        assert len(results) == 1
