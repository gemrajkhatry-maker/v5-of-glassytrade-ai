"""AAA Setup Precondition Engine — 5 preconditions for Trend Model entry.

CHANGE 3: ALL 5 preconditions must pass before any AAA signal.

PRE-1: Market state = IMBALANCED (displacement leg confirmed)
PRE-2: Time in Phase 2 (09:30-11:30) OR Phase 4 (14:00-15:15)
PRE-3: Volume profile shape = P-shape (long) or b-shape (short)
PRE-4: Price at VAL (longs) or VAH (shorts) ± 0.5% buffer
PRE-5: Absorption confirmed (volume spike + candle structure + delta + OFI)

If any single precondition fails → MODEL = SKIP for this candle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC
    from app.domain.services.session_phase_gate import PhaseState


class Precondition(str, Enum):
    PRE1_STATE = "PRE1_STATE"
    PRE2_TIME = "PRE2_TIME"
    PRE3_SHAPE = "PRE3_SHAPE"
    PRE4_PRICE = "PRE4_PRICE"
    PRE5_ABSORPTION = "PRE5_ABSORPTION"


@dataclass(frozen=True)
class PreconditionResult:
    """Result of AAA precondition evaluation."""

    all_passed: bool
    failed: list[Precondition]
    passed: list[Precondition]
    reason: str


class AAAPreconditionEngine:
    """Evaluates 5 AAA preconditions.

    ALL must pass for AAA signal generation. First failure stops evaluation.
    """

    def __init__(
        self,
        buffer_pct: float = 0.005,  # 0.5% buffer for PRE-4
        volume_spike_multiplier: float = 1.5,  # 1.5x average volume
        candle_body_threshold: float = 0.40,  # close in upper 40% for long
    ) -> None:
        self._buffer_pct = buffer_pct
        self._vol_spike_mult = volume_spike_multiplier
        self._body_threshold = candle_body_threshold

    def evaluate(
        self,
        session_state: str,
        leg_state: str,
        phase_state: "PhaseState",
        profile_shape: str,
        price: float,
        val: float,
        vah: float,
        poc: float,
        current_candle: OHLC,
        avg_volume: float,
        delta: float,
        ofi: float,
        direction: str,
    ) -> PreconditionResult:
        """Evaluate all 5 preconditions. First failure stops evaluation."""
        failed: list[Precondition] = []
        passed: list[Precondition] = []

        # PRE-1: Market state = IMBALANCED
        if session_state != "IMBALANCED" or leg_state != "IMBALANCED":
            failed.append(Precondition.PRE1_STATE)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"PRE-1: state={session_state}/{leg_state} — need IMBALANCED/IMBALANCED",
            )
        passed.append(Precondition.PRE1_STATE)

        # PRE-2: Time in Phase 2 or Phase 4
        from app.domain.services.session_phase_gate import AllowedAction

        if phase_state.allowed_action not in (
            AllowedAction.ALL_MODELS,
            AllowedAction.AAA_ONLY,
        ):
            failed.append(Precondition.PRE2_TIME)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"PRE-2: phase={phase_state.phase.value} — need AAA_WINDOW or POWER_HOUR",
            )
        passed.append(Precondition.PRE2_TIME)

        # PRE-3: Volume profile shape
        if direction == "LONG" and profile_shape not in ("P", "D"):
            failed.append(Precondition.PRE3_SHAPE)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"PRE-3: shape={profile_shape} for LONG — need P-shape",
            )
        elif direction == "SHORT" and profile_shape not in ("b", "B"):
            failed.append(Precondition.PRE3_SHAPE)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason=f"PRE-3: shape={profile_shape} for SHORT — need b-shape",
            )
        passed.append(Precondition.PRE3_SHAPE)

        # PRE-4: Price at VAL (longs) or VAH (shorts) ± buffer
        if direction == "LONG":
            if val > 0 and abs(price - val) / val > self._buffer_pct:
                failed.append(Precondition.PRE4_PRICE)
                return PreconditionResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason=f"PRE-4: price={price:.2f} not within {self._buffer_pct:.1%} of VAL={val:.2f}",
                )
        else:  # SHORT
            if vah > 0 and abs(price - vah) / vah > self._buffer_pct:
                failed.append(Precondition.PRE4_PRICE)
                return PreconditionResult(
                    all_passed=False,
                    failed=failed,
                    passed=passed,
                    reason=f"PRE-4: price={price:.2f} not within {self._buffer_pct:.1%} of VAH={vah:.2f}",
                )
        passed.append(Precondition.PRE4_PRICE)

        # PRE-5: Absorption confirmed
        vol_ok = (
            avg_volume > 0
            and float(current_candle.volume) > avg_volume * self._vol_spike_mult
        )
        candle_range = float(current_candle.high) - float(current_candle.low)
        if candle_range > 0:
            body_pos = (
                float(current_candle.close) - float(current_candle.low)
            ) / candle_range
            if direction == "LONG":
                body_ok = body_pos >= self._body_threshold
            else:
                body_ok = body_pos <= (1 - self._body_threshold)
        else:
            body_ok = False
        delta_ok = (delta > 0) if direction == "LONG" else (delta < 0)
        ofi_ok = (ofi > 0) if direction == "LONG" else (ofi < 0)

        if not vol_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason="PRE-5: volume spike not confirmed",
            )
        if not body_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason="PRE-5: candle structure not confirmed",
            )
        if not delta_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason="PRE-5: delta not confirmed",
            )
        if not ofi_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(
                all_passed=False,
                failed=failed,
                passed=passed,
                reason="PRE-5: OFI not confirmed",
            )
        passed.append(Precondition.PRE5_ABSORPTION)

        return PreconditionResult(
            all_passed=True,
            failed=[],
            passed=passed,
            reason="All 5 AAA preconditions passed",
        )
