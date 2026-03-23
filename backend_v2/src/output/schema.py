"""
Output schema — Pydantic model for signal output.

40+ fields for complete signal output per FR-11.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class OutputSchema(BaseModel):
    """
    Complete signal output schema.

    Contains all fields required for frontend display and audit.
    """

    # =========================================================================
    # SIGNAL IDENTITY
    # =========================================================================
    signal_id: str = Field(description="Unique signal identifier")
    timestamp: datetime = Field(description="Signal generation time")
    symbol: str = Field(description="Trading symbol")

    # =========================================================================
    # DIRECTION
    # =========================================================================
    direction: str = Field(description="LONG, SHORT, or FLAT")
    confidence: str = Field(description="HIGH, MEDIUM, LOW")

    # =========================================================================
    # MARKET CONTEXT
    # =========================================================================
    market_state: str = Field(description="NO_TRADE, BALANCED, IMBALANCED, PROBING")
    market_zone: str = Field(description="NEAR_VAH, NEAR_VAL, NEAR_POC, EMPTY")
    poc: Optional[float] = Field(None, description="Point of Control")
    vah: Optional[float] = Field(None, description="Value Area High")
    val: Optional[float] = Field(None, description="Value Area Low")

    # =========================================================================
    # ORDER FLOW
    # =========================================================================
    cvd_current: float = Field(description="Current CVD value")
    cvd_slope: float = Field(description="CVD slope (20-candle)")
    cvd_divergence: Optional[str] = Field(None, description="BULLISH, BEARISH, or None")
    footprint_imbalance: bool = Field(description="Footprint imbalance confirmed")
    absorption_type: Optional[str] = Field(None, description="SELL_ABSORBED, BUY_ABSORBED, or None")
    big_trade_detected: bool = Field(description="Big trade cluster detected")
    bubble_detected: bool = Field(description="Volume bubble detected")
    ofi_value: float = Field(description="Order Flow Imbalance value")

    # =========================================================================
    # AGGRESSION
    # =========================================================================
    aggression_score: float = Field(description="Aggression score (0-4.5)")
    aggression_confirmed: bool = Field(description="Aggression ≥ 2.0")
    aggression_breakdown: Dict[str, float] = Field(description="Component breakdown")

    # =========================================================================
    # DRIVE
    # =========================================================================
    drive_number: int = Field(description="Drive number (1/2/3+)")
    drive_level: Optional[float] = Field(None, description="Level being driven")
    drive_rejected: bool = Field(description="First drive rejected")

    # =========================================================================
    # TRADE SETUP
    # =========================================================================
    entry_price: Optional[float] = Field(None, description="Entry price")
    stop_loss: Optional[float] = Field(None, description="Stop loss price")
    target: Optional[float] = Field(None, description="Target price")
    risk_reward: Optional[float] = Field(None, description="Risk-reward ratio")
    cushion_ticks: Optional[int] = Field(None, description="Cushion in ticks")
    cushion_quality: Optional[str] = Field(None, description="EXCELLENT, ACCEPTABLE, INVALID")
    invalidation: Optional[float] = Field(None, description="Invalidation level")

    # =========================================================================
    # RISK
    # =========================================================================
    position_size_lots: Optional[int] = Field(None, description="Position size in lots")
    risk_amount: Optional[float] = Field(None, description="Risk amount (INR)")
    risk_pct: Optional[float] = Field(None, description="Risk percentage")

    # =========================================================================
    # GATE PIPELINE
    # =========================================================================
    gate_passed: bool = Field(description="All gates passed")
    gate_failed: Optional[int] = Field(None, description="Failed gate number")
    gate_reason: str = Field(description="Gate result reason")

    # =========================================================================
    # PROFILE
    # =========================================================================
    active_profile: str = Field(description="SESSION, LEG, or COMBINED")
    lvns: List[float] = Field(description="Low Volume Nodes")
    hvns: List[float] = Field(description="High Volume Nodes")

    # =========================================================================
    # SESSION
    # =========================================================================
    session_state: str = Field(description="OUTSIDE, WARMUP, ACTIVE, DEAD_ZONE, CLOSING")
    candle_count: int = Field(description="Candles since session open")

    # =========================================================================
    # VWAP
    # =========================================================================
    vwap: Optional[float] = Field(None, description="VWAP value")
    vwap_sigma1_upper: Optional[float] = Field(None, description="VWAP +1σ")
    vwap_sigma1_lower: Optional[float] = Field(None, description="VWAP -1σ")
    vwap_sigma2_upper: Optional[float] = Field(None, description="VWAP +2σ")
    vwap_sigma2_lower: Optional[float] = Field(None, description="VWAP -2σ")

    # =========================================================================
    # INITIAL BALANCE
    # =========================================================================
    ib_high: Optional[float] = Field(None, description="Initial Balance High")
    ib_low: Optional[float] = Field(None, description="Initial Balance Low")
    ib_broken: bool = Field(description="IB broken")

    # =========================================================================
    # RATIONALE
    # =========================================================================
    rationale: str = Field(description="Human-readable rationale")

    # =========================================================================
    # PYRAMID
    # =========================================================================
    pyramid_eligible: bool = Field(description="Pyramid add eligible")

    # =========================================================================
    # DATA QUALITY
    # =========================================================================
    data_quality: str = Field(description="LIVE, STALE, RECONNECTING")