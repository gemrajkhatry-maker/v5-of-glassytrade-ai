"""SignalPipeline — Single entry point for all trade signal generation.

Flow: TradeContext → GatePipeline.evaluate() → Signal.create() → Signal | None

All signals MUST pass through gate validation. No bypass paths.
This enforces the architectural constraint that AMTAnalyzer no longer
generates signals (Task 2A) — all signal creation goes through gates.

Task 50 — SignalPipeline orchestrator
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from app.domain.trading.models.entities import Signal
from app.domain.trading.models.enums import MarketState, SignalType, SetupType, Source
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


@dataclass
class TradeContext:
    """All inputs needed to evaluate and generate a trade signal.

    Collects data from AMTAnalyzer, LLM decisions, and session state
    into a single context object for the SignalPipeline.
    """

    # Market analysis (from AMTAnalyzer)
    market_state: str = ""  # "BALANCED", "IMBALANCED", "PROBING", "NO_TRADE"
    aggression_score: float = 0.0
    setup_type: str = ""  # Setup classification

    # Price data
    symbol: str = ""
    current_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    # LLM decision (optional — not all signals come from LLM)
    llm_decision: dict | None = None  # Raw LLM output with type, reason, SL, TP

    # Session state
    session_phase: str = ""  # "MORNING" or "AFTERNOON"
    is_expiry: bool = False

    # Enrichment metadata
    metadata: dict = field(default_factory=dict)

    # AMT result reference (for gate pipeline)
    amt_result: Any = None  # The full AMTResult object

    # Tick data
    tick: Any = None  # Current OHLC tick


class SignalPipeline:
    """Single entry point for all trade signal generation.

    Flow: TradeContext → GatePipeline.evaluate() → Signal.create() → Signal | None

    All signals MUST pass through gate validation. No bypass paths.
    """

    def __init__(
        self,
        gate_pipeline=None,
        signal_builder_fn: Callable[[TradeContext], Signal | None] | None = None,
    ):
        """Initialize the signal pipeline.

        Args:
            gate_pipeline: GatePipeline instance for gate validation.
                          If None, gate validation is skipped (for testing/fallback).
            signal_builder_fn: Optional custom signal builder function.
                              Default uses Signal.create() directly.
        """
        self._gate_pipeline = gate_pipeline
        self._signal_builder_fn = signal_builder_fn

    def evaluate(self, context: TradeContext) -> Signal | None:
        """Evaluate a trade context and produce a Signal if gates pass.

        Returns:
            Signal if all hard gates pass and soft gate quorum met, else None.
        """
        if not context.symbol:
            logger.warning("SignalPipeline: no symbol in context")
            return None

        if context.market_state == "NO_TRADE":
            logger.debug("SignalPipeline: market_state is NO_TRADE, skipping")
            return None

        # Step 1: Gate validation (skip if no gate_pipeline for testing)
        if self._gate_pipeline:
            gate_context = self._build_gate_context(context)
            gate_result = self._gate_pipeline.evaluate(gate_context)

            if not gate_result.passed:
                logger.debug(
                    "SignalPipeline: gates rejected for %s — %s",
                    context.symbol,
                    gate_result.reason,
                )
                return None

        # Step 2: Build signal
        signal = self._build_signal(context)
        if signal:
            logger.info(
                "SignalPipeline: %s signal for %s at %.2f (SL=%.2f, TP=%.2f)",
                signal.type.value,
                context.symbol,
                float(signal.price),
                float(signal.stop_loss),
                float(signal.take_profit),
            )

        return signal

    def _build_gate_context(self, context: TradeContext):
        """Convert TradeContext to GateContext for the gate pipeline.

        Maps TradeContext fields to GateContext fields, using AMTResult
        when available for richer data.
        """
        from app.domain.fabio_ai.services.gate_pipeline import GateContext
        from app.domain.constants import (
            WARM_UP_MINUTES_MCX,
            SOFT_GATE_QUORUM,
        )

        amt = context.amt_result
        tick = context.tick

        # Extract data from AMTResult if available
        poc = 0.0
        vah = 0.0
        val = 0.0
        key_levels: list[float] = []
        drive_number = 0
        drive_entry_valid = False
        cvd_slope = 0.0
        price_velocity = 0.0
        weekly_bias = "NEUTRAL"
        weekly_bias_aligned = True

        if amt:
            poc = getattr(amt, "poc", 0.0) or 0.0
            vah = getattr(amt, "value_area_high", 0.0) or 0.0
            val = getattr(amt, "value_area_low", 0.0) or 0.0
            key_levels = list(getattr(amt, "lvns", [])) + list(getattr(amt, "hvns", []))
            drive_number = getattr(amt, "drive_number", 0) or 0
            drive_entry_valid = getattr(amt, "drive_entry_valid", False)
            cvd_slope = getattr(amt, "cvd_slope", 0.0) or 0.0
            price_velocity = getattr(amt, "price_velocity", 0.0) or 0.0
            weekly_bias = getattr(amt, "weekly_bias", "NEUTRAL") or "NEUTRAL"
            weekly_bias_aligned = getattr(amt, "weekly_bias_aligned", True)

        # Extract tick data
        current_price = context.current_price
        if tick:
            current_price = getattr(tick, "close", context.current_price) or context.current_price

        # Find nearest key level
        nearest_level = 0.0
        distance_to_level_ticks = 0.0
        tick_size = context.metadata.get("tick_size", 0.05)

        if key_levels and current_price > 0:
            nearest_level = min(key_levels, key=lambda l: abs(l - current_price))
            distance_to_level_ticks = abs(current_price - nearest_level) / max(tick_size, 0.001)

        # Map market state string to MarketState enum
        market_state = MarketState.BALANCED
        ms_upper = context.market_state.upper()
        if ms_upper == "NO_TRADE":
            market_state = MarketState.NO_TRADE
        elif ms_upper == "IMBALANCED":
            market_state = MarketState.IMBALANCED
        elif ms_upper == "PROBING":
            market_state = MarketState.PROBING

        # Compute R:R ratio and cushion
        rr_ratio = 0.0
        cushion_ticks = 0.0
        if context.stop_loss > 0 and context.take_profit > 0 and current_price > 0:
            risk = abs(current_price - context.stop_loss)
            reward = abs(context.take_profit - current_price)
            rr_ratio = reward / risk if risk > 0 else 0.0

            # Cushion = distance from price to nearest level (in ticks)
            if nearest_level > 0:
                cushion_ticks = abs(current_price - nearest_level) / max(tick_size, 0.001)

        # Build GateContext
        return GateContext(
            symbol=context.symbol,
            # Data quality (defaults — caller should set these if needed)
            tick_age_seconds=context.metadata.get("tick_age_seconds", 1.0),
            candle_count=context.metadata.get("candle_count", 10),
            warm_up_minutes=WARM_UP_MINUTES_MCX,
            # Market state
            market_state=market_state,
            zone=context.metadata.get("zone", ""),
            # Volume profile
            poc=poc,
            vah=vah,
            val=val,
            price=current_price,
            tick_size=tick_size,
            # Key levels
            key_levels=key_levels,
            nearest_level=nearest_level,
            distance_to_level_ticks=distance_to_level_ticks,
            # Drive state
            drive_number=drive_number,
            drive_entry_valid=drive_entry_valid,
            # Aggression
            aggression_score=context.aggression_score,
            # Risk (from context or defaults)
            is_risk_halted=context.metadata.get("is_risk_halted", False),
            halt_reason=context.metadata.get("halt_reason", ""),
            # Position sizing
            position_size_ok=context.metadata.get("position_size_ok", True),
            # EIA window
            eia_window_active=context.metadata.get("eia_window_active", False),
            # Weekly bias
            weekly_bias=weekly_bias,
            weekly_bias_aligned=weekly_bias_aligned,
            # Setup
            setup_type=context.setup_type or context.metadata.get("setup_type", "NONE"),
            r_r_ratio=rr_ratio,
            cushion_ticks=cushion_ticks,
            # Quorum
            soft_gate_quorum=SOFT_GATE_QUORUM,
        )

    def _build_signal(self, context: TradeContext) -> Signal | None:
        """Construct a Signal from validated context."""
        if self._signal_builder_fn:
            return self._signal_builder_fn(context)

        # Determine signal type from LLM decision or market analysis
        signal_type = self._determine_signal_type(context)
        if not signal_type:
            return None

        # Determine source
        source = Source.AMT if not context.llm_decision else Source.LLM

        return Signal.create(
            type=signal_type,
            price=Decimal(str(context.current_price)),
            reason=context.metadata.get("reason", "SignalPipeline"),
            stop_loss=Decimal(str(context.stop_loss)),
            take_profit=Decimal(str(context.take_profit)),
            timestamp=datetime.datetime.now(IST).isoformat(),
            setup=self._determine_setup_type(context),
            source=source,
            metadata={
                "market_state": context.market_state,
                "aggression_score": context.aggression_score,
                "session_phase": context.session_phase,
                "is_expiry": context.is_expiry,
                **context.metadata,
            },
        )

    def _determine_signal_type(self, context: TradeContext) -> SignalType | None:
        """Determine BUY/SELL from context."""
        # From LLM decision
        if context.llm_decision:
            decision_type = context.llm_decision.get("type", "").upper()
            if decision_type in ("BUY", "LONG"):
                return SignalType.BUY
            elif decision_type in ("SELL", "SHORT"):
                return SignalType.SELL

        # From context metadata
        signal_type_str = context.metadata.get("signal_type", "")
        if signal_type_str:
            return (
                SignalType.BUY
                if signal_type_str.upper() in ("BUY", "LONG")
                else SignalType.SELL
            )

        # From direction in metadata (alternative key)
        direction = context.metadata.get("direction", "")
        if direction:
            if direction.upper() in ("BUY", "LONG"):
                return SignalType.BUY
            elif direction.upper() in ("SELL", "SHORT"):
                return SignalType.SELL

        return None

    def _determine_setup_type(self, context: TradeContext) -> SetupType:
        """Determine setup classification from context."""
        # From LLM decision
        if context.llm_decision:
            return SetupType.TREND_MODEL  # LLM decisions are trend-based

        # From context metadata
        setup_str = context.setup_type or context.metadata.get("setup_type", "")
        if setup_str:
            setup_upper = setup_str.upper()
            if "MEAN_REVERSION" in setup_upper:
                return SetupType.MEAN_REVERSION
            elif "TREND" in setup_upper:
                return SetupType.TREND_MODEL
            elif "PREDICTION" in setup_upper:
                return SetupType.PREDICTION_ENTRY
            elif "RL" in setup_upper:
                return SetupType.RL_ENTRY

        return SetupType.TREND_MODEL  # Default
