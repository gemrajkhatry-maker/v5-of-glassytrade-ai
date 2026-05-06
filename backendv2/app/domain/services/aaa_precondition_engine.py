"""AAA precondition engine."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.services.session_phase_gate import PhaseState


class Precondition(str, Enum):
    PRE1_STATE = "PRE1_STATE"
    PRE2_TIME = "PRE2_TIME"
    PRE3_SHAPE = "PRE3_SHAPE"
    PRE4_PRICE = "PRE4_PRICE"
    PRE5_ABSORPTION = "PRE5_ABSORPTION"


@dataclass(frozen=True)
class PreconditionResult:
    all_passed: bool
    failed: list[Precondition]
    passed: list[Precondition]
    reason: str


class AAAPreconditionEngine:
    """All five preconditions must pass before AAA signal."""

    def __init__(
        self,
        buffer_pct: float = 0.005,
        volume_spike_multiplier: float = 1.5,
        candle_body_threshold: float = 0.40,
    ) -> None:
        self._buffer_pct = float(buffer_pct)
        self._vol_spike_mult = float(volume_spike_multiplier)
        self._body_threshold = float(candle_body_threshold)

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
        current_candle,
        avg_volume: float,
        delta: float,
        ofi: float,
        direction: str,
        leg_poc: float = 0.0,
    ) -> PreconditionResult:
        effective_poc = leg_poc if (session_state in {"PROBING", "IMBALANCED"} and leg_poc > 0) else poc
        failed: list[Precondition] = []
        passed: list[Precondition] = []

        if session_state != "IMBALANCED" or leg_state != "IMBALANCED":
            failed.append(Precondition.PRE1_STATE)
            return PreconditionResult(False, failed, passed, "PRE-1 state not IMBALANCED")
        passed.append(Precondition.PRE1_STATE)

        from app.domain.services.session_phase_gate import AllowedAction

        if phase_state.allowed_action not in (AllowedAction.ALL_MODELS, AllowedAction.AAA_ONLY):
            failed.append(Precondition.PRE2_TIME)
            return PreconditionResult(
                False,
                failed,
                passed,
                f"PRE-2 phase={phase_state.phase} requires AAA window",
            )
        passed.append(Precondition.PRE2_TIME)

        if direction == "LONG" and profile_shape not in {"P", "p", "D", "d"}:
            failed.append(Precondition.PRE3_SHAPE)
            return PreconditionResult(False, failed, passed, "PRE-3 LONG needs P-shape")
        if direction == "SHORT" and profile_shape not in {"b", "B"}:
            failed.append(Precondition.PRE3_SHAPE)
            return PreconditionResult(False, failed, passed, "PRE-3 SHORT needs b-shape")
        passed.append(Precondition.PRE3_SHAPE)

        near_poc = effective_poc > 0 and abs(price - effective_poc) / effective_poc <= self._buffer_pct
        if direction == "LONG":
            near_val = val > 0 and abs(price - val) / val <= self._buffer_pct
            if not near_val and not near_poc:
                failed.append(Precondition.PRE4_PRICE)
                return PreconditionResult(
                    False,
                    failed,
                    passed,
                    f"PRE-4 price {price} not within {self._buffer_pct:.1%} of VAL={val}",
                )
        else:
            near_vah = vah > 0 and abs(price - vah) / vah <= self._buffer_pct
            if not near_vah and not near_poc:
                failed.append(Precondition.PRE4_PRICE)
                return PreconditionResult(
                    False,
                    failed,
                    passed,
                    f"PRE-4 price {price} not within {self._buffer_pct:.1%} of VAH={vah}",
                )
        passed.append(Precondition.PRE4_PRICE)

        vol_ok = avg_volume > 0 and float(current_candle.volume) > avg_volume * self._vol_spike_mult
        candle_range = float(current_candle.high) - float(current_candle.low)
        if candle_range > 0:
            body_pos = (float(current_candle.close) - float(current_candle.low)) / candle_range
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
            return PreconditionResult(False, failed, passed, "PRE-5 volume spike not confirmed")
        if not body_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(False, failed, passed, "PRE-5 candle structure not confirmed")
        if not delta_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(False, failed, passed, "PRE-5 delta not confirmed")
        if not ofi_ok:
            failed.append(Precondition.PRE5_ABSORPTION)
            return PreconditionResult(False, failed, passed, "PRE-5 OFI not confirmed")
        passed.append(Precondition.PRE5_ABSORPTION)

        return PreconditionResult(True, failed, passed, "All 5 AAA preconditions passed")

