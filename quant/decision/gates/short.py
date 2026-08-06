"""SHORT Signal Gate Logic — gates S1-S5 for PE/SHORT entries.

Feature-flagged via short_signals_enabled. When disabled, all SHORT signals blocked.

GATE S1: SHORT DIRECTION ALLOWED check (flag kill switch)
GATE S2: SHORT MARKET STATE check (IMBALANCED DOWN or BALANCED failed-breakout UP)
GATE S3: SHORT ML PROBABILITY check (higher thresholds than LONG)
GATE S4: SHORT AGGRESSION DIRECTION check (sellers in control)
GATE S5: SHORT CONTRACT TYPE check (must select PE, not CE)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShortGateResult:
    """Result of SHORT gate evaluation."""

    passed: bool
    gate_name: str
    reason: str


# ML thresholds for SHORT (higher than LONG due to India upward bias)
SHORT_ML_THRESHOLDS = {
    "imbalance_continuation": 0.58,  # vs 0.55 for long
    "return_to_value": 0.51,  # same as long
    "probing_breakout": 0.58,  # same as long
}


def check_s1_direction_allowed(short_enabled: bool) -> ShortGateResult:
    """GATE S1: Kill switch for SHORT signals."""
    if not short_enabled:
        return ShortGateResult(
            passed=False,
            gate_name="S1_DIRECTION",
            reason="short_signals_enabled=false — all SHORT blocked",
        )
    return ShortGateResult(passed=True, gate_name="S1_DIRECTION", reason="")


def check_s2_market_state(
    market_state: str,
    displacement_direction: str,
    failed_breakout: bool,
) -> ShortGateResult:
    """GATE S2: Valid SHORT market states only.

    Valid SHORT states:
      IMBALANCED + displacement_direction = DOWN → Trend SHORT
      BALANCED + failed_breakout = UP → MR SHORT
    """
    if market_state == "IMBALANCED" and displacement_direction == "DOWN":
        return ShortGateResult(passed=True, gate_name="S2_MARKET_STATE", reason="")

    if market_state == "BALANCED" and failed_breakout:
        return ShortGateResult(passed=True, gate_name="S2_MARKET_STATE", reason="")

    return ShortGateResult(
        passed=False,
        gate_name="S2_MARKET_STATE",
        reason=f"SHORT invalid: state={market_state} disp={displacement_direction} failed_brk={failed_breakout}",
    )


def check_s3_ml_probability(
    playbook: str,
    ml_probability: float,
) -> ShortGateResult:
    """GATE S3: ML probability must exceed SHORT threshold (higher than LONG)."""
    threshold = SHORT_ML_THRESHOLDS.get(playbook, 0.58)
    if ml_probability >= threshold:
        return ShortGateResult(passed=True, gate_name="S3_ML_PROB", reason="")

    return ShortGateResult(
        passed=False,
        gate_name="S3_ML_PROB",
        reason=f"SHORT P={ml_probability:.3f} < threshold {threshold} for {playbook}",
    )


def check_s4_aggression_direction(
    bid_volume: float,
    ask_volume: float,
    cvd_slope: float,
    delta_normalized: float,
) -> ShortGateResult:
    """GATE S4: Aggression must come from SELLERS.

    Requirements:
      ask_volume > bid_volume (selling pressure)
      cvd_slope < 0 (sellers in control)
      delta_normalized < 0
    """
    if ask_volume > bid_volume and cvd_slope < 0 and delta_normalized < 0:
        return ShortGateResult(passed=True, gate_name="S4_AGGRESSION", reason="")

    return ShortGateResult(
        passed=False,
        gate_name="S4_AGGRESSION",
        reason=f"SHORT aggression missing: bid={bid_volume} ask={ask_volume} cvd_slope={cvd_slope:.1f} delta={delta_normalized:.2f}",
    )


def check_s5_contract_type(
    contract_type: str,
) -> ShortGateResult:
    """GATE S5: SHORT signal must select PE option."""
    if contract_type == "PE":
        return ShortGateResult(passed=True, gate_name="S5_CONTRACT", reason="")

    return ShortGateResult(
        passed=False,
        gate_name="S5_CONTRACT",
        reason=f"SHORT requires PE contract, got {contract_type}",
    )


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
    """Evaluate all 5 SHORT gates in sequence.

    Returns (all_passed, list_of_results).
    First failure stops evaluation.
    """
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

    r = check_s4_aggression_direction(
        bid_volume, ask_volume, cvd_slope, delta_normalized
    )
    results.append(r)
    if not r.passed:
        return False, results

    r = check_s5_contract_type(contract_type)
    results.append(r)
    if not r.passed:
        return False, results

    return True, results
