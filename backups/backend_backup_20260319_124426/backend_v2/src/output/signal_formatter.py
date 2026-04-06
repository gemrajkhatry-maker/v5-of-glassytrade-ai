"""
Signal formatter — format signals for output.

Builds OutputSchema from state data.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from src.output.schema import OutputSchema


class SignalFormatter:
    """
    Format signals for output.

    Uses static methods for pure function behavior.
    """

    @staticmethod
    def format(
        symbol: str,
        direction: str,
        confidence: str,
        market_state: str,
        market_zone: str,
        poc: Optional[float],
        vah: Optional[float],
        val: Optional[float],
        cvd_current: float,
        cvd_slope: float,
        cvd_divergence: Optional[str],
        footprint_imbalance: bool,
        absorption_type: Optional[str],
        big_trade_detected: bool,
        bubble_detected: bool,
        ofi_value: float,
        aggression_score: float,
        aggression_confirmed: bool,
        aggression_breakdown: Dict[str, float],
        drive_number: int,
        drive_level: Optional[float],
        drive_rejected: bool,
        entry_price: Optional[float],
        stop_loss: Optional[float],
        target: Optional[float],
        risk_reward: Optional[float],
        cushion_ticks: Optional[int],
        cushion_quality: Optional[str],
        invalidation: Optional[float],
        position_size_lots: Optional[int],
        risk_amount: Optional[float],
        risk_pct: Optional[float],
        gate_passed: bool,
        gate_failed: Optional[int],
        gate_reason: str,
        active_profile: str,
        lvns: List[float],
        hvns: List[float],
        session_state: str,
        candle_count: int,
        vwap: Optional[float],
        vwap_sigma1_upper: Optional[float],
        vwap_sigma1_lower: Optional[float],
        vwap_sigma2_upper: Optional[float],
        vwap_sigma2_lower: Optional[float],
        ib_high: Optional[float],
        ib_low: Optional[float],
        ib_broken: bool,
        rationale: str,
        pyramid_eligible: bool,
        data_quality: str,
    ) -> OutputSchema:
        """
        Build complete OutputSchema from state data.

        Returns:
            OutputSchema with all fields populated.
        """
        return OutputSchema(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            market_state=market_state,
            market_zone=market_zone,
            poc=poc,
            vah=vah,
            val=val,
            cvd_current=cvd_current,
            cvd_slope=cvd_slope,
            cvd_divergence=cvd_divergence,
            footprint_imbalance=footprint_imbalance,
            absorption_type=absorption_type,
            big_trade_detected=big_trade_detected,
            bubble_detected=bubble_detected,
            ofi_value=ofi_value,
            aggression_score=aggression_score,
            aggression_confirmed=aggression_confirmed,
            aggression_breakdown=aggression_breakdown,
            drive_number=drive_number,
            drive_level=drive_level,
            drive_rejected=drive_rejected,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            risk_reward=risk_reward,
            cushion_ticks=cushion_ticks,
            cushion_quality=cushion_quality,
            invalidation=invalidation,
            position_size_lots=position_size_lots,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
            gate_passed=gate_passed,
            gate_failed=gate_failed,
            gate_reason=gate_reason,
            active_profile=active_profile,
            lvns=lvns,
            hvns=hvns,
            session_state=session_state,
            candle_count=candle_count,
            vwap=vwap,
            vwap_sigma1_upper=vwap_sigma1_upper,
            vwap_sigma1_lower=vwap_sigma1_lower,
            vwap_sigma2_upper=vwap_sigma2_upper,
            vwap_sigma2_lower=vwap_sigma2_lower,
            ib_high=ib_high,
            ib_low=ib_low,
            ib_broken=ib_broken,
            rationale=rationale,
            pyramid_eligible=pyramid_eligible,
            data_quality=data_quality,
        )

    @staticmethod
    def to_json(signal: OutputSchema) -> str:
        """Convert signal to JSON string."""
        return signal.model_dump_json()

    @staticmethod
    def to_dict(signal: OutputSchema) -> Dict:
        """Convert signal to dictionary."""
        return signal.model_dump()