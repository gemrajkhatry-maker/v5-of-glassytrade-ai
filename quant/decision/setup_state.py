# quant/decision/setup_state.py
"""Fabio AMT Setup State and Evidence Modeling.

Defines the explicit evidence and validation state machines for the 4 canonical
Fabio Valentini AMT setups:
1. TRIPLE_A: 3-step sequence (Absorption -> Accumulation -> Aggression + Acceptance beyond cluster)
2. SECOND_DRIVE: Drive 1 rejected -> Drive 2 weaker re-approach + rejection
3. LVN_SNIPER: Impulse leg LVN return within 2 ticks + fresh absorption + CVD confirmation
4. VA_FADE: Value Area edge probe + failed acceptance / rejection wick + CVD reversal
5. NONE: No structural setup (e.g. imbalanced trend without absorption, or balanced rotation)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SetupType = Literal["TRIPLE_A", "SECOND_DRIVE", "LVN_SNIPER", "VA_FADE", "NONE"]


@dataclass(frozen=True)
class SetupEvidence:
    """Immutable evidence snapshot for a detected setup candidate."""

    setup_type: SetupType = "NONE"
    direction: str = ""  # "LONG" | "SHORT"
    level: float = 0.0
    absorption: bool = False
    accumulation: bool = False
    aggression: bool = False
    acceptance: bool = False
    rejection: bool = False
    drive_number: int = 0
    d1_rejected: bool = False
    fresh_bars: int = 0
    cvd_agrees: bool = False
    obi_agrees: bool = False
    price_location: str = ""  # "ABOVE_VAH", "BELOW_VAL", "AT_LVN", "IN_VA", etc.
    target: float = 0.0
    invalidation: float = 0.0
    evidence_age_bars: int = 0

    def is_complete(self) -> bool:
        """Return True if the evidence satisfies all mandatory criteria for its setup type."""
        if self.setup_type == "NONE" or not self.direction:
            return False

        if self.evidence_age_bars > 10:
            return False

        if not self.cvd_agrees:
            return False

        if self.setup_type == "TRIPLE_A":
            # Mandatory 3-step sequence + acceptance beyond cluster
            return bool(
                self.absorption
                and self.accumulation
                and self.aggression
                and self.acceptance
            )

        if self.setup_type == "SECOND_DRIVE":
            # D1 must be rejected, and we must be on Drive 2 with rejection confirmation
            return bool(
                self.drive_number == 2
                and self.d1_rejected
                and self.rejection
            )

        if self.setup_type == "LVN_SNIPER":
            # Must be at LVN, with fresh absorption and CVD agreement
            return bool(
                self.level > 0
                and self.absorption
                and self.cvd_agrees
            )

        if self.setup_type == "VA_FADE":
            # Must show rejection outside VA (failed acceptance)
            return bool(
                self.rejection
                and not self.acceptance
                and self.cvd_agrees
            )

        return False

    def rejection_reason(self) -> str:
        """Return a human-readable explanation if evidence is incomplete."""
        if self.setup_type == "NONE":
            return "No named setup"
        if not self.direction:
            return "Missing trade direction"
        if self.evidence_age_bars > 10:
            return f"Evidence too old ({self.evidence_age_bars} bars > 10)"
        if not self.cvd_agrees:
            return "CVD opposes trade direction"

        if self.setup_type == "TRIPLE_A":
            missing = []
            if not self.absorption:
                missing.append("Absorption")
            if not self.accumulation:
                missing.append("Accumulation")
            if not self.aggression:
                missing.append("Aggression")
            if not self.acceptance:
                missing.append("Acceptance")
            return f"Incomplete Triple-A: missing {', '.join(missing)}"

        if self.setup_type == "SECOND_DRIVE":
            if self.drive_number != 2:
                return f"Drive number {self.drive_number} != 2"
            if not self.d1_rejected:
                return "Drive 1 was not rejected"
            if not self.rejection:
                return "Missing Drive 2 rejection confirmation"

        if self.setup_type == "LVN_SNIPER":
            if self.level <= 0:
                return "Missing LVN price level"
            if not self.absorption:
                missing = "absorption"
                return f"Missing {missing} at LVN"

        if self.setup_type == "VA_FADE":
            if not self.rejection:
                return "No rejection wick/failure outside Value Area"
            if self.acceptance:
                return "Price accepted outside Value Area (breakout, not fade)"

        return "Incomplete setup evidence"
