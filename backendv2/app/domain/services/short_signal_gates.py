"""SHORT gate sequence used by SHORT entry evaluation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortGateResult:
    passed: bool
    gate_name: str
    reason: str


SHORT_ML_THRESHOLDS = {
    "imbalance_continuation": 0.58,
    "return_to_value": 0.51,
    "probing_breakout": 0.58,
}


def check_s1_direction_allowed(short_enabled: bool) -> ShortGateResult:
    if not short_enabled:
        return ShortGateResult(False, "S1_DIRECTION", "short_signals_enabled=false")
    return ShortGateResult(True, "S1_DIRECTION", "")


def check_s2_market_state(
    market_state: str,
    displacement_direction: str,
    failed_breakout: bool,
) -> ShortGateResult:
    if market_state == "IMBALANCED" and displacement_direction == "DOWN":
        return ShortGateResult(True, "S2_MARKET_STATE", "")
    if market_state == "BALANCED" and failed_breakout:
        return ShortGateResult(True, "S2_MARKET_STATE", "")
    return ShortGateResult(
        False,
        "S2_MARKET_STATE",
        f"SHORT invalid: state={market_state} disp={displacement_direction} failed_brk={failed_breakout}",
    )


def check_s3_ml_probability(playbook: str, ml_probability: float) -> ShortGateResult:
    threshold = SHORT_ML_THRESHOLDS.get(playbook, 0.58)
    if ml_probability >= threshold:
        return ShortGateResult(True, "S3_ML_PROB", "")
    return ShortGateResult(
        False,
        "S3_ML_PROB",
        f"SHORT P={ml_probability:.3f} < threshold {threshold} for {playbook}",
    )


def check_s4_aggression_direction(
    bid_volume: float,
    ask_volume: float,
    cvd_slope: float,
    delta_normalized: float,
) -> ShortGateResult:
    if ask_volume > bid_volume and cvd_slope < 0 and delta_normalized < 0:
        return ShortGateResult(True, "S4_AGGRESSION", "")
    return ShortGateResult(
        False,
        "S4_AGGRESSION",
        f"SHORT aggression missing: bid={bid_volume} ask={ask_volume} cvd_slope={cvd_slope:.1f} delta={delta_normalized:.2f}",
    )


def check_s5_contract_type(contract_type: str) -> ShortGateResult:
    if contract_type == "PE":
        return ShortGateResult(True, "S5_CONTRACT", "")
    return ShortGateResult(False, "S5_CONTRACT", f"SHORT requires PE contract, got {contract_type}")


def evaluate_short_gates(
    short_enabled: bool,
    market_state: str,
    displacement_direction: str,
    failed_breakout: bool,
    playbook: str,
    ml_probability: float,
    bid_volume: float,
    ask_volume: float,
    cvd_slope: float,
    delta_normalized: float,
    contract_type: str,
) -> tuple[bool, list[ShortGateResult]]:
    results = []

    r = check_s1_direction_allowed(short_enabled)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_s2_market_state(market_state, displacement_direction, failed_breakout)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_s3_ml_probability(playbook, ml_probability)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_s4_aggression_direction(bid_volume, ask_volume, cvd_slope, delta_normalized)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_s5_contract_type(contract_type)
    results.append(r)
    if not r.passed:
        return False, results

    return True, results

