# quant/decision/setup_state.py
"""Fabio AMT Setup State and Evidence Modeling.

Defines the explicit evidence and validation state machines for the 4 canonical
Fabio Valentini AMT setups:
1. TRIPLE_A: 3-step sequence (Absorption -> Accumulation -> Aggression + Acceptance beyond cluster)
2. SECOND_DRIVE: Drive 1 rejected -> Drive 2 weaker re-approach + rejection
3. LVN_SNIPER: Impulse leg LVN return within 2 ticks + fresh absorption + CVD confirmation
4. VA_FADE: Value Area edge probe + failed acceptance / rejection wick + CVD reversal
5. NONE: No structural setup (e.g. imbalanced trend without absorption, or balanced rotation)

is_complete() is the sole Gate-3 certificate. Location / LVN / breakout rules live
here — gates_edge must not re-implement them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

SetupType = Literal["TRIPLE_A", "SECOND_DRIVE", "LVN_SNIPER", "VA_FADE", "NONE"]

_TRIPLE_A_BLOCKED_LOCS = frozenset({"IN_COMPRESSION", "INSIDE_BOX", "IN_CHOP"})


def triple_a_cluster_valid(cluster_high, cluster_low) -> bool:
    try:
        high = float(cluster_high)
        low = float(cluster_low)
    except (TypeError, ValueError):
        return False
    return math.isfinite(high) and math.isfinite(low) and 0.0 < low < high


def triple_a_cvd_confirmed(direction, cvd_slope) -> bool:
    try:
        slope = float(cvd_slope)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(slope):
        return False
    if str(direction).upper() == "LONG":
        return slope > 0.0
    if str(direction).upper() == "SHORT":
        return slope < 0.0
    return False


def triple_a_breakout_confirmed(direction, close, cluster_high, cluster_low) -> bool:
    if not triple_a_cluster_valid(cluster_high, cluster_low):
        return False
    try:
        price = float(close)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(price):
        return False
    if str(direction).upper() == "LONG":
        return price > float(cluster_high)
    if str(direction).upper() == "SHORT":
        return price < float(cluster_low)
    return False


def triple_a_vwap_confirmed(direction, close, vwap) -> bool:
    try:
        price = float(close)
        reference = float(vwap)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(price) or not math.isfinite(reference) or reference <= 0.0:
        return False
    if str(direction).upper() == "LONG":
        return price > reference
    if str(direction).upper() == "SHORT":
        return price < reference
    return False


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
    # Location / progression fields owned by the certificate (not by gates_edge).
    price: float = 0.0
    tick_size: float = 0.05
    session_vwap: float = 0.0
    breakout_beyond_cluster: bool = False
    cluster_high: float | None = None
    cluster_low: float | None = None
    cvd_slope: float | None = None
    lvn_proximity_ok: bool = False
    # Tracker-derived: DriveTracker recorded a leave-and-return (DTO `departed`
    # = drive_count >= 2). context_builder passes it through — never re-derived
    # from the entry-valid flags.
    departed_and_reapproached: bool = False

    def _lvn_near(self, max_ticks: float = 3.0) -> bool:
        if self.lvn_proximity_ok:
            return True
        if self.level <= 0 or self.price <= 0:
            return False
        tick = self.tick_size if self.tick_size > 0 else 0.05
        return abs(self.price - self.level) <= (max_ticks * tick + 1e-9)

    def _vwap_side_ok(self) -> bool:
        if (
            self.setup_type == "TRIPLE_A"
            and (
                self.cvd_slope is not None
                or self.cluster_high is not None
                or self.cluster_low is not None
            )
        ):
            return triple_a_vwap_confirmed(
                self.direction,
                self.price,
                self.session_vwap,
            )
        if self.session_vwap <= 0 or self.price <= 0:
            return True
        tick = self.tick_size if self.tick_size > 0 else 0.05
        if self.direction == "LONG":
            return self.price >= self.session_vwap - tick
        if self.direction == "SHORT":
            return self.price <= self.session_vwap + tick
        return False

    def _triple_a_cvd_ok(self) -> bool:
        if self.cvd_slope is None:
            return True
        return triple_a_cvd_confirmed(self.direction, self.cvd_slope)

    def _triple_a_cluster_ok(self) -> bool:
        if self.cluster_high is None and self.cluster_low is None:
            return True
        return triple_a_cluster_valid(self.cluster_high, self.cluster_low)

    def _triple_a_breakout_ok(self) -> bool:
        if not self.breakout_beyond_cluster:
            return False
        if self.cluster_high is None and self.cluster_low is None:
            return True
        return triple_a_breakout_confirmed(
            self.direction,
            self.price,
            self.cluster_high,
            self.cluster_low,
        )

    def is_complete(self) -> bool:
        """Return True if the evidence satisfies all mandatory criteria for its setup type."""
        if self.setup_type == "NONE" or not self.direction:
            return False

        if self.evidence_age_bars > 10:
            return False

        if not self.cvd_agrees:
            return False

        if self.setup_type == "TRIPLE_A":
            if self.price_location in _TRIPLE_A_BLOCKED_LOCS:
                return False
            if not (
                self.absorption
                and self.accumulation
                and self.aggression
                and self.acceptance
            ):
                return False
            if not self._triple_a_cvd_ok():
                return False
            if not self._triple_a_cluster_ok():
                return False
            if not self._triple_a_breakout_ok():
                return False
            if not self._vwap_side_ok():
                return False
            return True

        if self.setup_type == "SECOND_DRIVE":
            return bool(
                self.drive_number == 2
                and self.d1_rejected
                and self.rejection
                and self.departed_and_reapproached
            )

        if self.setup_type == "LVN_SNIPER":
            return bool(
                self.level > 0
                and self.absorption
                and self.cvd_agrees
                and self._lvn_near(max_ticks=3.0)
            )

        if self.setup_type == "VA_FADE":
            if self.direction == "LONG" and self.price_location == "BELOW_VAL":
                return False
            if self.direction == "SHORT" and self.price_location == "ABOVE_VAH":
                return False
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
            if self.price_location in _TRIPLE_A_BLOCKED_LOCS:
                return f"Triple-A blocked in {self.price_location}"
            missing = []
            if not self.absorption:
                missing.append("Absorption")
            if not self.accumulation:
                missing.append("Accumulation")
            if not self.aggression:
                missing.append("Aggression")
            if not self.acceptance:
                missing.append("Acceptance")
            if missing:
                return f"Incomplete Triple-A: missing {', '.join(missing)}"
            if not self._triple_a_cvd_ok():
                return "Triple-A CVD does not confirm trade direction"
            if not self._triple_a_cluster_ok():
                return "Missing or invalid absorption cluster bounds"
            if not self.breakout_beyond_cluster:
                return "Close did not break beyond absorption cluster"
            if not self._triple_a_breakout_ok():
                return "Close did not break beyond absorption cluster"
            if not self._vwap_side_ok():
                return "Triple-A on wrong side of session VWAP"
            return "Incomplete Triple-A"

        if self.setup_type == "SECOND_DRIVE":
            if self.drive_number != 2:
                return f"Drive number {self.drive_number} != 2"
            if not self.d1_rejected:
                return "Drive 1 was not rejected"
            if not self.rejection:
                return "Missing Drive 2 rejection confirmation"
            if not self.departed_and_reapproached:
                return "No departure and re-approach (range rotation, not Drive 2)"

        if self.setup_type == "LVN_SNIPER":
            if self.level <= 0:
                return "Missing LVN price level"
            if not self.absorption:
                return "Missing absorption at LVN"
            if not self._lvn_near(max_ticks=3.0):
                return "Price too far from LVN"

        if self.setup_type == "VA_FADE":
            if self.direction == "LONG" and self.price_location == "BELOW_VAL":
                return "VA Fade LONG still below VAL"
            if self.direction == "SHORT" and self.price_location == "ABOVE_VAH":
                return "VA Fade SHORT still above VAH"
            if not self.rejection:
                return "No rejection wick/failure outside Value Area"
            if self.acceptance:
                return "Price accepted outside Value Area (breakout, not fade)"

        return "Incomplete setup evidence"
