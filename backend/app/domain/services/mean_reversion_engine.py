"""Mean Reversion Engine — deterministic rules for BALANCED session entries.

CHANGE 4: 5 conditions for Mean Reversion entry (ALL must pass).

MR-1: Session = BALANCED
MR-2: Price within 2% of VAL (long) or VAH (short) OR within 2% of POC
MR-3: b-shape confirmed for LONG, P-shape for SHORT
MR-4: CVD Slope > 0 for LONG, < 0 for SHORT
MR-5: Phase = 2 or 4 (Phase 3 allows only POC mean reversion)

Entry: limit order at VAL/VAH level
Target: POC (ALWAYS — do not stretch to other side of range)
Stop: below VAL - buffer (long) or above VAH + buffer (short)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MRCondition(str, Enum):
    MR1_STATE = "MR1_STATE"
    MR2_PRICE = "MR2_PRICE"
    MR3_SHAPE = "MR3_SHAPE"
    MR4_CVD = "MR4_CVD"
    MR5_PHASE = "MR5_PHASE"


@dataclass(frozen=True)
class MRResult:
    """Result of Mean Reversion evaluation."""

    all_passed: bool
    failed: list[MRCondition]
    passed: list[MRCondition]
    reason: str
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0


class MeanReversionEngine:
    """Evaluates Mean Reversion entry conditions.

    Implements CHANGE 4: 5 conditions for BALANCED session entries.
    All must pass for signal generation.
    """

    def __init__(
        self,
        price_buffer_pct: float = 0.02,  # 2% buffer for MR-2
        poc_buffer_pct: float = 0.02,  # 2% buffer for POC reversion
        stop_buffer_pct: float = 0.005,  # 0.5% buffer for stop
        min_rr: float = 2.0,  # minimum risk:reward
    ) -> None:
        self._price_buffer = price_buffer_pct
        self._poc_buffer = poc_buffer_pct
        self._stop_buffer = stop_buffer_pct
        self._min_rr = min_rr

    def evaluate(
        self,
        session_state: str,
        price: float,
        val: float,
        vah: float,
        poc: float,
        profile_shape: str,
        cvd_slope: float,
        direction: str,
        phase_name: str,
        tick_size: float,
    ) -> MRResult:
        """Evaluate 5 MR conditions. First failure stops evaluation."""
        failed: list[MRCondition] = []
        passed: list[MRCondition] = []

        # MR-1: Session = BALANCED
        if session_state != "BALANCED":
            failed.append(MRCondition.MR1_STATE)
            return MRResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"MR-1: state={session_state} — need BALANCED",
            )
        passed.append(MRCondition.MR1_STATE)

        # MR-2: Price near VAL (long) or VAH (short) or POC
        near_poc = poc > 0 and abs(price - poc) / poc <= self._poc_buffer
        near_val = val > 0 and abs(price - val) / val <= self._price_buffer
        near_vah = vah > 0 and abs(price - vah) / vah <= self._price_buffer

        if direction == "LONG":
            if not (near_val or near_poc):
                failed.append(MRCondition.MR2_PRICE)
                return MRResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason=f"MR-2: price={price:.2f} not near VAL={val:.2f} or POC={poc:.2f}",
                )
        else:  # SHORT
            if not (near_vah or near_poc):
                failed.append(MRCondition.MR2_PRICE)
                return MRResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason=f"MR-2: price={price:.2f} not near VAH={vah:.2f} or POC={poc:.2f}",
                )
        passed.append(MRCondition.MR2_PRICE)

        # MR-3: Profile shape
        if direction == "LONG":
            if profile_shape not in ("b", "B", "D"):
                failed.append(MRCondition.MR3_SHAPE)
                return MRResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason=f"MR-3: shape={profile_shape} for LONG — need b-shape",
                )
        else:  # SHORT
            if profile_shape not in ("P", "D"):
                failed.append(MRCondition.MR3_SHAPE)
                return MRResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason=f"MR-3: shape={profile_shape} for SHORT — need P-shape",
                )
        passed.append(MRCondition.MR3_SHAPE)

        # MR-4: CVD Slope
        if direction == "LONG" and cvd_slope <= 0:
            failed.append(MRCondition.MR4_CVD)
            return MRResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"MR-4: cvd_slope={cvd_slope:.1f} not positive for LONG",
            )
        elif direction == "SHORT" and cvd_slope >= 0:
            failed.append(MRCondition.MR4_CVD)
            return MRResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"MR-4: cvd_slope={cvd_slope:.1f} not negative for SHORT",
            )
        passed.append(MRCondition.MR4_CVD)

        # MR-5: Phase check
        if phase_name == "MIDDAY":
            # Phase 3 allows only POC mean reversion
            if not near_poc:
                failed.append(MRCondition.MR5_PHASE)
                return MRResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason="MR-5: Phase 3 (MIDDAY) allows only POC mean reversion",
                )
        # Phase 2/4: full access
        passed.append(MRCondition.MR5_PHASE)

        # Compute SL/TP
        if direction == "LONG":
            entry = price
            sl = val - tick_size * 2 if val > 0 else price * (1 - self._stop_buffer)
            tp = poc
            risk = entry - sl
            reward = tp - entry
        else:
            entry = price
            sl = vah + tick_size * 2 if vah > 0 else price * (1 + self._stop_buffer)
            tp = poc
            risk = sl - entry
            reward = entry - tp

        rr = reward / risk if risk > 0 else 0
        if rr < self._min_rr:
            return MRResult(
                all_passed=False,
                failed=[MRCondition.MR5_PHASE],
                passed=passed,
                reason=f"R:R={rr:.1f} < {self._min_rr} — SKIP",
            )

        return MRResult(
            all_passed=True,
            failed=[],
            passed=passed,
            reason="All 5 MR conditions passed",
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
        )
