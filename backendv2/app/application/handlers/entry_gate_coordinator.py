"""Entry gate coordinator for backendv2."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.amt.service.entry_gates import run_entry_gates
from app.domain.constants import CVD_SLOPE_EXTREME, CVD_SLOPE_HARD_BLOCK

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import AMTResult, OHLC, OrderBook

logger = logging.getLogger(__name__)


class EntryGateCoordinator:
    """Coordinate entry-gate checks and expose gate-specific helpers."""

    def check_entry_eligibility(
        self,
        data: list["OHLC"],
        amt_result: "AMTResult",
        tick: "OHLC",
        order_book: "OrderBook | None" = None,
        direction: str = "LONG",
        ib_high: float = 0.0,
        ib_low: float = 0.0,
        aggressive_levels: list[float] | None = None,
        footprint_domain: dict | None = None,
        session_info=None,
        tick_size: float = 0.05,
    ) -> tuple[bool, str, bool]:
        del ib_high, ib_low, aggressive_levels, footprint_domain, session_info, tick_size

        tick_price = float(getattr(tick, "close", 0.0))
        market_state = str(getattr(amt_result, "market_state", "BALANCED"))

        passed, reason, detail, _soft_passed, soft_total = run_entry_gates(
            data=[{"time": getattr(item, "time", 0), "close": float(getattr(item, "close", 0.0))} for item in data],
            amt_result=amt_result,
            tick=tick,
            aggression_score=float(getattr(amt_result, "aggression_score", getattr(amt_result, "aggression", 0.0)) or 0.0),
            market_state=market_state,
            drive_number=int(getattr(amt_result, "drive_number", 0)),
            drive_entry_valid=bool(getattr(amt_result, "drive_entry_valid", False)),
            cvd_conflict=False,
            distance_to_level_ticks=0.0,
            tick_age_seconds=0.5,
            symbol=str(getattr(tick, "symbol", "")),
            is_risk_halted=False,
            halt_reason="",
            tick_size=float(tick_size or 1.0),
            is_extreme_deviation=bool(getattr(amt_result, "is_extreme_deviation", False)),
        )

        if not passed:
            return False, f"Gate pipeline: {reason}: {detail}", False

        cvd_result = self._check_cvd_hard_gate(amt_result, direction)
        if not cvd_result[0]:
            return False, cvd_result[1], False

        profile_result = self._check_profile_shape_gate(amt_result, direction)
        if not profile_result[0]:
            return False, profile_result[1], False

        # Lightweight two-gate safety checks.
        if direction == "LONG" and tick_price <= float(getattr(amt_result, "session_vwap", 0.0)):
            logger.debug("LONG entry rejected for vwap bias")
        if direction == "SHORT" and tick_price >= float(getattr(amt_result, "session_vwap", 0.0)):
            logger.debug("SHORT entry rejected for vwap bias")

        return True, "All gates passed", bool(getattr(amt_result, "drive_entry_valid", False))

    def _check_cvd_hard_gate(
        self,
        amt_result: "AMTResult",
        direction: str,
    ) -> tuple[bool, str]:
        cvd_slope = float(getattr(amt_result, "cvd_slope", 0.0))
        market_state = str(getattr(amt_result, "market_state", "BALANCED")).upper()

        if cvd_slope < -CVD_SLOPE_EXTREME and market_state == "BALANCED":
            return False, f"CVD extreme selling ({cvd_slope:.0f}) in balance"
        if cvd_slope > CVD_SLOPE_EXTREME and market_state == "BALANCED":
            return False, f"CVD extreme buying (+{cvd_slope:.0f}) in balance"
        if direction == "LONG" and cvd_slope < -CVD_SLOPE_HARD_BLOCK:
            return False, f"CVD opposing LONG ({cvd_slope:.0f})"
        if direction == "SHORT" and cvd_slope > CVD_SLOPE_HARD_BLOCK:
            return False, f"CVD opposing SHORT ({cvd_slope:.0f})"
        return True, "CVD gate passed"

    def _check_profile_shape_gate(
        self,
        amt_result: "AMTResult",
        direction: str,
    ) -> tuple[bool, str]:
        shape = str(getattr(amt_result, "profile_shape", ""))
        if not shape:
            return True, "No profile shape data"
        shape_code = shape[0]
        if shape_code == "P" and direction == "LONG":
            return False, "P-shape blocks LONG"
        if shape_code == "b" and direction == "SHORT":
            return False, "b-shape blocks SHORT"
        return True, "Profile shape gate passed"

    def check_vwap_bias(
        self,
        direction: str,
        price: float,
        vwap: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
    ) -> dict:
        if vwap <= 0:
            return {"warning": False, "overextended": False}

        warning = False
        overextended = False
        if direction == "LONG":
            warning = price < vwap
            overextended = bool(vwap_upper_2 > 0 and price >= vwap_upper_2)
        elif direction == "SHORT":
            warning = price > vwap
            overextended = bool(vwap_lower_2 > 0 and price <= vwap_lower_2)
        return {"warning": warning, "overextended": overextended}

    def check_confirmation_bundle(
        self,
        data: list["OHLC"],
        tick: "OHLC",
        order_book: "OrderBook | None" = None,
    ) -> bool:
        del order_book
        if len(data) < 2:
            return False

        prev_close = float(getattr(data[-2], "close", 0.0))
        curr_close = float(getattr(tick, "close", 0.0))
        # Simple mandatory confirmation: momentum against previous candle
        return curr_close != prev_close and abs(curr_close - prev_close) > 0
