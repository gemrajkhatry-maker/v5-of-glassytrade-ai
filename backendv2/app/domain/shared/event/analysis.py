"""Analysis events — AMT and AI analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key


@dataclass(frozen=True)
class AMTAnalyzed(DomainEvent):
    """AMT analysis completed for a symbol.

    Published by AMTService after the full 6-stage pipeline completes.
    Consumed by entry evaluators and state snapshot builder.
    """

    symbol: str = ""
    # Core AMT results
    market_state: str = "BALANCED"
    poc: float = 0.0
    value_area_high: float = 0.0
    value_area_low: float = 0.0
    lvns: tuple = field(default_factory=tuple)
    hvns: tuple = field(default_factory=tuple)
    aggression: float = 0.0
    aggression_score: float = 0.0
    aggression_confidence: str = "LOW"
    setup: str = ""
    profile_shape: str = ""
    cvd_slope: float = 0.0
    cvd_divergence: str = ""
    session_vwap: float = 0.0
    vwap_upper_1: float = 0.0
    vwap_lower_1: float = 0.0
    vwap_upper_2: float = 0.0
    vwap_lower_2: float = 0.0
    balance_ratio: float = 0.0
    has_displacement: bool = False
    has_acceptance: bool = False
    # Phase results
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_complete: bool = False
    prior_poc: float = 0.0
    prior_vah: float = 0.0
    prior_val: float = 0.0
    gap_type: str = ""
    opening_bias: str = ""
    acceptance_above: bool = False
    acceptance_below: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    liquidity_sweep: str = ""
    break_direction: str = ""
    break_type: str = ""
    poc_signal: str = ""
    poc_vs_price: str = ""
    lvn_play: Any = None
    # Leg profile
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0
    leg_regime: str = ""
    # MTF
    mtf_alignment: str = ""
    daily_vah: float = 0.0
    daily_val: float = 0.0
    daily_poc: float = 0.0
    hourly_vah: float = 0.0
    hourly_val: float = 0.0
    hourly_poc: float = 0.0
    # Drive state
    drive_number: int = 0
    drive_entry_valid: bool = False
    # Absorption
    absorption_side: str = ""
    absorption_range_ratio: float = 0.0
    absorption_vol_ratio: float = 0.0
    # Market structure
    market_structure: str = "BALANCE"
    structure_confidence: int = 0
    day_type: str = "UNKNOWN"
    opening_type: str = ""
    # Counters
    absorptions_count: int = 0
    aggressive_prints_count: int = 0


@dataclass(frozen=True)
class AIAnalysisCompleted(DomainEvent):
    """Generative AI analysis finished for a symbol.

    Published by LLMEntryHandler after LLM inference completes.
    Consumed by entry coordinator and state snapshot builder.
    """

    symbol: str = ""
    direction: str = "FLAT"  # "LONG", "SHORT", "FLAT"
    rationale: str = ""
    confidence: str = "Medium"
    analysis_id: str = ""
    sentiment: str = "NEUTRAL"
    quant_score: float = 0.0
    projected_price: float = 0.0

    @staticmethod
    def create(
        symbol: str,
        direction: str,
        rationale: str,
        confidence: str,
        analysis_id: str = "",
        sentiment: str = "NEUTRAL",
        quant_score: float = 0.0,
        projected_price: float = 0.0,
    ) -> "AIAnalysisCompleted":
        idempotency_key = _generate_idempotency_key(
            symbol, analysis_id or "ai_analysis", direction
        )
        return AIAnalysisCompleted(
            idempotency_key=idempotency_key,
            symbol=symbol,
            direction=direction,
            rationale=rationale,
            confidence=confidence,
            analysis_id=analysis_id,
            sentiment=sentiment,
            quant_score=quant_score,
            projected_price=projected_price,
        )
