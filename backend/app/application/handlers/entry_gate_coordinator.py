"""Entry Gate Coordinator — Orchestrates gate checking for trade entries.

Responsibilities:
- Three-Align gate coordination
- Confirmation bundle validation
- Gate pipeline execution
- Entry eligibility determination
- Momentum fade detection
- VWAP bias checking
- CVD hard gates
- Profile shape validation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.entry_gates.three_align import three_align_check
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import (
    check_momentum_fade,
    check_confirmation_bundle,
)
from app.domain.fabio_ai.services.entry_gates.gate_runner import run_gate_pipeline
from app.domain.constants import CVD_SLOPE_EXTREME, CVD_SLOPE_HARD_BLOCK

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook

logger = logging.getLogger(__name__)


class EntryGateCoordinator:
    """Coordinates entry gate checking for trade entries.

    This module encapsulates all gate-checking logic, providing a single
    point of entry for determining trade eligibility.
    """

    def check_entry_eligibility(
        self,
        data: list[OHLC],
        amt_result: AMTResult,
        tick: OHLC,
        order_book: OrderBook | None = None,
        direction: str = "LONG",
        ib_high: float = 0.0,
        ib_low: float = 0.0,
        aggressive_levels: list[float] | None = None,
        footprint_domain: dict | None = None,
        session_info=None,
        tick_size: float = 0.05,  # NEW: tick-size awareness
    ) -> tuple[bool, str, bool]:
        """Check if entry is eligible through all gates.

        Args:
            data: Historical OHLC data
            amt_result: AMT analysis result
            tick: Current tick data
            order_book: Current order book
            direction: Trade direction (LONG/SHORT)
            ib_high: Initial Balance high
            ib_low: Initial Balance low
            aggressive_levels: Aggressive print cluster levels
            footprint_domain: Footprint domain data
            session_info: Session context information
            tick_size: Tick size of the instrument

        Returns:
            Tuple of (eligible: bool, reason: str, is_second_drive: bool)
        """
        # Three-Align gate
        gate_passed, confirmation_strong, is_second_drive = three_align_check(
            data=data,
            amt_result=amt_result,
            tick=tick,
            order_book=order_book,
            ib_high=ib_high,
            ib_low=ib_low,
            aggressive_levels=aggressive_levels,
            footprint_domain=footprint_domain,
            return_is_second_drive=True,
            session_info=session_info,
            tick_size=tick_size,  # Pass tick size
        )

        if not gate_passed:
            return False, "Three-Align gate failed", is_second_drive

        # Momentum fade gate
        if check_momentum_fade(data, tick, direction):
            return False, "Momentum fade detected", is_second_drive

        # Gate pipeline
        gate_passed, gate_reason, gate_detail, _soft_gates_passed, _soft_gates_total = run_gate_pipeline(
            data=data,
            amt_result=amt_result,
            tick=tick,
            market_state=amt_result.market_state,
            drive_number=getattr(amt_result, "drive_number", 0),
            drive_entry_valid=getattr(amt_result, "drive_entry_valid", False),
            aggression_score=amt_result.aggression,
            is_risk_halted=False,
            halt_reason="",
            tick_age_seconds=1.0,
            symbol=getattr(tick, "symbol", ""),
            tick_size=tick_size,  # Pass tick size
            is_extreme_deviation=getattr(amt_result, "is_extreme_deviation", False),
        )

        if not gate_passed:
            return (
                False,
                f"Gate pipeline: {gate_reason} - {gate_detail}",
                is_second_drive,
            )

        # CVD hard gate
        cvd_result = self._check_cvd_hard_gate(amt_result, direction)
        if not cvd_result[0]:
            return False, cvd_result[1], is_second_drive

        # Profile shape gate
        profile_result = self._check_profile_shape_gate(amt_result, direction)
        if not profile_result[0]:
            return False, profile_result[1], is_second_drive

        return True, "All gates passed", is_second_drive

    def _check_cvd_hard_gate(
        self,
        amt_result: AMTResult,
        direction: str,
    ) -> tuple[bool, str]:
        """Check CVD hard gate for extreme flow.

        Args:
            amt_result: AMT analysis result
            direction: Trade direction (LONG/SHORT)

        Returns:
            Tuple of (passed: bool, reason: str)
        """
        cvd_slope = getattr(amt_result, "cvd_slope", 0.0)

        # Extreme CVD in balance = don't fade (institutional pressure building)
        if cvd_slope < -CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
            return False, f"CVD extreme selling ({cvd_slope:.0f}) in balance"
        if cvd_slope > CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
            return False, f"CVD extreme buying (+{cvd_slope:.0f}) in balance"

        # CVD opposing direction
        if direction == "LONG" and cvd_slope < -CVD_SLOPE_HARD_BLOCK:
            return False, f"CVD opposing LONG ({cvd_slope:.0f})"
        if direction == "SHORT" and cvd_slope > CVD_SLOPE_HARD_BLOCK:
            return False, f"CVD opposing SHORT ({cvd_slope:.0f})"

        return True, "CVD gate passed"

    def _check_profile_shape_gate(
        self,
        amt_result: AMTResult,
        direction: str,
    ) -> tuple[bool, str]:
        """Check profile shape gate for distribution patterns.

        Args:
            amt_result: AMT analysis result
            direction: Trade direction (LONG/SHORT)

        Returns:
            Tuple of (passed: bool, reason: str)
        """
        profile_shape = getattr(amt_result, "profile_shape", "")
        if not profile_shape:
            return True, "No profile shape data"

        shape_code = profile_shape[0] if profile_shape else ""

        # P-shape (top-heavy) blocks LONG entries
        if shape_code == "P" and direction == "LONG":
            return False, "P-shape (top-heavy distribution) blocks LONG"

        # b-shape (bottom-heavy) blocks SHORT entries
        if shape_code == "b" and direction == "SHORT":
            return False, "b-shape (bottom accumulation) blocks SHORT"

        return True, "Profile shape gate passed"

    def check_vwap_bias(
        self,
        direction: str,
        price: float,
        vwap: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
    ) -> dict:
        """Check VWAP bias for entry quality.

        Returns:
            Dictionary with "warning" and "overextended" flags
        """
        if vwap <= 0:
            return {"warning": False, "overextended": False}

        warning = False
        overextended = False

        if direction == "LONG":
            if price < vwap:
                warning = True
            if vwap_upper_2 > 0 and price >= vwap_upper_2:
                overextended = True
        elif direction == "SHORT":
            if price > vwap:
                warning = True
            if vwap_lower_2 > 0 and price <= vwap_lower_2:
                overextended = True

        return {"warning": warning, "overextended": overextended}

    def check_confirmation_bundle(
        self,
        data: list[OHLC],
        tick: OHLC,
        order_book: OrderBook | None = None,
    ) -> bool:
        """Check confirmation bundle (2/3): Volume Impulse + Delta Pressure + Spread Tightness.

        Volume impulse is MANDATORY — no aggression = no trade.
        Need 2/3 overall, but volume impulse must be present.
        """
        return check_confirmation_bundle(data, tick, order_book)
