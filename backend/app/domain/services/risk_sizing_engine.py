"""Risk Sizing Engine — deterministic Kelly-based position sizing with theta decay.

CHANGE 5: Replace any LLM-based sizing with deterministic formula.

  BASE RISK: 0.30% of equity (hard clamp 0.25%-0.50%)
  DYNAMIC CUSHION: +20% of session PnL when winning
  CONSECUTIVE LOSS: reduce to 0.25% on 2+ losses
  LOT CALC: floor(max_risk / (stop_points × lot_size))
  SCALE-IN: 40% / 30% / 30% plan
  RR MINIMUM: 2.0 (ideal 2.5-4.0)
  THETA: Options time decay adjustment (NSE-specific)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Protocol, Optional

# ---------------------------------------------------------------------------
# ExchangeConfig Protocol - Interface for getting instrument lot sizes
# ---------------------------------------------------------------------------

class ExchangeConfig(Protocol):
    """Protocol for exchange-specific configuration (lot sizes, etc.)."""
    
    def get_lot_size(self, underlying: str) -> int:
        """Get lot size for an underlying symbol.
        
        Args:
            underlying: Symbol like "NIFTY", "BANKNIFTY", "CRUDEOIL", etc.
            
        Returns:
            Lot size (e.g., 25 for NIFTY options, 15 for BANKNIFTY).
        """
        ...


@dataclass
class DefaultExchangeConfig:
    """Default exchange config with hardcoded lot sizes (fallback).
    
    Note: Prefer passing a real ExchangeConfig implementation that fetches
    lot sizes from the broker's instrument cache for accuracy.
    """
    
    # Correct lot sizes per exchange specification
    _LOT_SIZES = {
        "NIFTY": 25,       # NIFTY options lot size (not 65 which is futures)
        "BANKNIFTY": 15,
        "FINNIFTY": 40,
        "CRUDEOIL": 100,
        "NATURALGAS": 1250,
        "GOLD": 1,
        "SILVER": 30,
        "GOLDM": 10,
        "SILVERM": 5,
    }
    
    def get_lot_size(self, underlying: str) -> int:
        """Get lot size for an underlying symbol."""
        return self._LOT_SIZES.get(underlying, 1)


class RiskTier(str, Enum):
    STANDARD = "STANDARD"  # 0.30% base risk
    REDUCED = "REDUCED"  # 0.25% (2+ consecutive losses)
    ELEVATED = "ELEVATED"  # 0.50% (cushion available)


class SessionPhase(str, Enum):
    """NSE Session Phases per Rule 1 from AMT spec."""
    
    OPENING_NOISE = "OPENING_NOISE"      # 09:15–09:30 IST - DO NOT TRADE
    PRIMARY_WINDOW = "PRIMARY_WINDOW"    # 09:30–11:30 IST - AAA WINDOW (best)
    MIDDAY_CONSOLIDATION = "MIDDAY_CONSOLIDATION"  # 11:30–14:00 IST - Mean Reversion only
    POWER_HOUR = "POWER_HOUR"            # 14:00–15:15 IST - AAA WINDOW
    CLOSE_PROTECTION = "CLOSE_PROTECTION"  # 15:15–15:30 IST - NO NEW ENTRIES


def get_nse_session_phase(current_time) -> SessionPhase:
    """Determine NSE session phase from current time.
    
    Rule 1 from AMT spec:
        Phase 1 — Opening Noise (09:15 – 09:30 IST): DO NOT TRADE
            Monday: Extended to 09:45 due to gap risk
        Phase 2 — Primary Setup Window (09:30 – 11:30 IST): AAA WINDOW
        Phase 3 — Midday Consolidation (11:30 – 14:00 IST): Mean Reversion only
        Phase 4 — Power Hour (14:00 – 15:15 IST): AAA WINDOW
        Phase 5 — Close Protection (15:15 – 15:30 IST): NO NEW ENTRIES
    """
    import datetime
    
    # Handle both datetime and time objects
    if isinstance(current_time, datetime.datetime):
        hour = current_time.hour
        minute = current_time.minute
        weekday = current_time.weekday()  # 0=Monday
    else:
        hour = current_time.hour
        minute = current_time.minute
        weekday = None  # No date info, use default
    
    time_minutes = hour * 60 + minute
    
    if time_minutes < 9 * 60 + 15:  # Before 09:15
        return SessionPhase.OPENING_NOISE
    elif weekday == 0:  # Monday - extended gap risk window
        if time_minutes < 9 * 60 + 45:  # 09:15–09:45 on Monday
            return SessionPhase.OPENING_NOISE
        elif time_minutes < 11 * 60 + 30:  # 09:45–11:30
            return SessionPhase.PRIMARY_WINDOW
    elif time_minutes < 9 * 60 + 30:  # 09:15–09:30 (non-Monday)
        return SessionPhase.OPENING_NOISE
    elif time_minutes < 11 * 60 + 30:  # 09:30–11:30
        return SessionPhase.PRIMARY_WINDOW
    elif time_minutes < 14 * 60:  # 11:30–14:00
        return SessionPhase.MIDDAY_CONSOLIDATION
    elif time_minutes < 15 * 60 + 15:  # 14:00–15:15
        return SessionPhase.POWER_HOUR
    elif time_minutes < 15 * 60 + 30:  # 15:15–15:30
        return SessionPhase.CLOSE_PROTECTION
    else:
        return SessionPhase.CLOSE_PROTECTION  # After hours


@dataclass(frozen=True)
class SizingResult:
    """Result of risk sizing calculation."""

    risk_pct: float
    max_risk_amount: float
    lots: int
    stop_points: float
    target_points: float
    rr_ratio: float
    risk_tier: RiskTier
    allowed: bool
    reason: str
    scale_in_1: int  # lots for first entry (40%)
    scale_in_2: int  # lots for second entry (30%)
    scale_in_3: int  # lots for third entry (30%)
    # Theta-aware fields for options
    theta_decay_risk: float = 0.0  # Estimated theta per day
    holding_cost_ratio: float = 0.0  # theta / expected_profit
    theta_adjusted_lots: int = 0  # Reduced lots if theta is high
    
    # Breakeven management (Rule 5: "In 1 minute the position is risk-free")
    breakeven_points: float = 0.0  # Points to move stop for breakeven
    breakeven_minutes: int = 1  # Target minutes to reach breakeven
    breakeven_triggered: bool = False  # Set when 1R moves in favor
    
    # Spread validation (Rule B5: bid-ask spread < 2% of premium)
    bid_ask_spread_ok: bool = True  # True if spread < 2% of premium
    spread_pct: float = 0.0  # Actual spread as % of premium
    
    # Liquidity filters (Rule: min OI, min volume for selected options)
    liquidity_ok: bool = True  # True if OI and volume pass thresholds
    oi_ok: bool = True  # True if OI meets minimum threshold
    volume_ok: bool = True  # True if volume meets minimum threshold
    
    # IV crush filter (Rule B6: reduce position size around events)
    iv_event_risk: bool = False  # True if trading near IV crush event
    iv_reduced_lots: int = 0  # Lots reduced due to IV event
    
    # Day-of-week filters (Rule B8: expiry Thursday, Friday)
    weekday_risk: bool = False  # True if trading on restricted weekday
    weekday_reduced_lots: int = 0  # Lots reduced due to weekday risk
    
    # OI wall integration (Rule B7: protection levels from option chain)
    oi_wall_support: Optional[float] = None  # Put wall strike (support level)
    oi_wall_resistance: Optional[float] = None  # Call wall strike (resistance level)


@dataclass(frozen=True)
class BreakevenAction:
    """Action to take for breakeven management."""
    move_to_breakeven: bool = False
    new_stop_price: float = 0.0
    trigger_reason: str = ""  # "1R", "volume_confirmation", or "cushion"


class RiskSizingEngine:
    """Deterministic Kelly-based position sizing with theta awareness.

    No LLM involvement. Pure math. Sub-millisecond execution.
    For options trading, factors in time decay (theta) from Fabio's spec.
    """

    # Default lot sizes per instrument - FALLBACK only
    # Correct values: NIFTY=25 (options), BANKNIFTY=15, etc.
    # Prefer passing ExchangeConfig to use broker's instrument cache
    DEFAULT_LOT_SIZES = {
        "NIFTY": 25,       # NIFTY options (corrected from 65)
        "BANKNIFTY": 15,
        "FINNIFTY": 40,
        "CRUDEOIL": 100,
        "NATURALGAS": 1250,
        "GOLD": 1,
        "SILVER": 30,
        "GOLDM": 10,
        "SILVERM": 5,
    }

    def __init__(
        self,
        base_risk_pct: float = 0.0030,  # 0.30%
        min_risk_pct: float = 0.0025,  # 0.25%
        max_risk_pct: float = 0.0050,  # 0.50%
        cushion_multiplier: float = 0.20,  # 20% of session PnL
        consecutive_loss_threshold: int = 2,  # reduce to min on 2+ losses
        min_rr: float = 2.0,  # minimum risk:reward
        theta_risk_threshold: float = 0.20,  # theta must be < 20% of expected profit
        exchange_config: ExchangeConfig | None = None,  # ExchangeConfig for lot sizes
    ) -> None:
        """Initialize RiskSizingEngine.
        
        Args:
            base_risk_pct: Base risk percentage per trade (0.30% = 0.0030).
            min_risk_pct: Minimum risk percentage (0.25% = 0.0025).
            max_risk_pct: Maximum risk percentage (0.50% = 0.0050).
            cushion_multiplier: Multiplier for session PnL cushion (0.20 = 20%).
            consecutive_loss_threshold: Losses before reducing risk (default 2).
            min_rr: Minimum risk-reward ratio (default 2.0).
            theta_risk_threshold: Max theta as % of expected profit (0.20 = 20%).
            exchange_config: ExchangeConfig for dynamic lot sizes from broker.
                          If None, uses DEFAULT_LOT_SIZES (correct values now).
        """
        self._base_risk = base_risk_pct
        self._min_risk = min_risk_pct
        self._max_risk = max_risk_pct
        self._cushion_mult = cushion_multiplier
        self._consec_loss_thresh = consecutive_loss_threshold
        self._min_rr = min_rr
        self._theta_risk_threshold = theta_risk_threshold
        self._exchange_config = exchange_config

    def calculate(
        self,
        equity: float,
        session_pnl: float,
        consecutive_losses: int,
        underlying: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        direction: str,
        theta: float = 0.0,  # Daily theta per contract
        expected_hold_minutes: int = 60,
        days_to_expiry: int = 5,
        current_time = None,  # Optional: datetime for session phase check
        premium: float = 0.0,  # Option premium for spread validation
        bid_ask_spread: float = 0.0,  # Spread in rupees for spread validation
        oi: int = 0,  # Open interest for liquidity filter
        volume: int = 0,  # Today's volume for liquidity filter
        iv_event: bool = False,  # True if trading near RBI/budget/election events
        oi_wall_support: Optional[float] = None,  # OI put wall strike (support)
        oi_wall_resistance: Optional[float] = None,  # OI call wall strike (resistance)
    ) -> SizingResult:
        """Calculate position size based on risk parameters.

        Args:
            equity: Current equity
            session_pnl: Current session PnL
            consecutive_losses: Number of consecutive losing trades
            underlying: "NIFTY", "BANKNIFTY", etc.
            entry_price: Planned entry price
            stop_price: Stop loss price
            target_price: Take profit price
            direction: "LONG" or "SHORT"
            theta: Daily theta (time decay) per contract
            expected_hold_minutes: Expected holding time in minutes
            days_to_expiry: Days until expiry (for theta normalization)
            current_time: Optional datetime for session phase enforcement
            premium: Option premium (for spread validation)
            bid_ask_spread: Bid-ask spread in currency units
            oi: Open interest for liquidity filter
            volume: Today's volume for liquidity filter
            iv_event: True if trading near IV crush events (RBI, budget, elections)
            oi_wall_support: OI put wall strike (support level) for stop placement
            oi_wall_resistance: OI call wall strike (resistance level) for stop placement
        """
        # Session phase check (Rule 1 from AMT spec)
        if current_time is not None:
            phase = get_nse_session_phase(current_time)
            if phase == SessionPhase.OPENING_NOISE:
                return SizingResult(
                    risk_pct=0.0,
                    max_risk_amount=0.0,
                    lots=0,
                    stop_points=0.0,
                    target_points=0.0,
                    rr_ratio=0.0,
                    risk_tier=RiskTier.STANDARD,
                    allowed=False,
                    reason="Session phase: Opening Noise (09:15-09:30) - DO NOT TRADE",
                    scale_in_1=0,
                    scale_in_2=0,
                    scale_in_3=0,
                    bid_ask_spread_ok=True,
                    spread_pct=0.0,
                    liquidity_ok=True,
                    oi_ok=True,
                    volume_ok=True,
                    iv_event_risk=False,
                    iv_reduced_lots=0,
                    weekday_risk=False,
                    weekday_reduced_lots=0,
                )
            if phase == SessionPhase.CLOSE_PROTECTION:
                return SizingResult(
                    risk_pct=0.0,
                    max_risk_amount=0.0,
                    lots=0,
                    stop_points=0.0,
                    target_points=0.0,
                    rr_ratio=0.0,
                    risk_tier=RiskTier.STANDARD,
                    allowed=False,
                    reason="Session phase: Close Protection (15:15-15:30) - NO NEW ENTRIES",
                    scale_in_1=0,
                    scale_in_2=0,
                    scale_in_3=0,
                    bid_ask_spread_ok=True,
                    spread_pct=0.0,
                    liquidity_ok=True,
                    oi_ok=True,
                    volume_ok=True,
                    iv_event_risk=False,
                    iv_reduced_lots=0,
                    weekday_risk=False,
                    weekday_reduced_lots=0,
                )
        
        # Bid-ask spread validation (Rule B5: spread < 2% of premium)
        spread_pct = 0.0
        spread_ok = True
        if premium > 0 and bid_ask_spread > 0:
            spread_pct = bid_ask_spread / premium
            if spread_pct > 0.02:  # 2% threshold
                spread_ok = False
        
        # Liquidity filters (Rule B1: min OI 10 lakh for NIFTY, 5 lakh for BANKNIFTY; min volume 50k)
        oi_threshold = 1000000 if underlying == "NIFTY" else 500000  # 10 lakh NIFTY, 5 lakh BANKNIFTY
        volume_threshold = 50000  # 50,000 contracts
        
        oi_ok = oi >= oi_threshold if oi > 0 else True  # Skip if no OI data
        volume_ok = volume >= volume_threshold if volume > 0 else True  # Skip if no volume data
        liquidity_ok = oi_ok and volume_ok
        
        # Expiry selection logic (Rule B2: minimum 3 days to expiry)
        if days_to_expiry < 3:
            return SizingResult(
                risk_pct=0.0,
                max_risk_amount=0.0,
                lots=0,
                stop_points=0.0,
                target_points=0.0,
                rr_ratio=0.0,
                risk_tier=RiskTier.STANDARD,
                allowed=False,
                reason=f"Expiry risk: Only {days_to_expiry} days to expiry (minimum 3 required)",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
                theta_decay_risk=0.0,
                holding_cost_ratio=0.0,
                theta_adjusted_lots=0,
                bid_ask_spread_ok=True,
                spread_pct=0.0,
                liquidity_ok=True,
                oi_ok=True,
                volume_ok=True,
                iv_event_risk=False,
                iv_reduced_lots=0,
                weekday_risk=True,
                weekday_reduced_lots=0,
            )
        
        # Risk tier selection
        if consecutive_losses >= self._consec_loss_thresh:
            risk_tier = RiskTier.REDUCED
            risk_pct = self._min_risk
        elif session_pnl > 0:
            available_risk = max(
                self._base_risk, session_pnl * self._cushion_mult / equity
            )
            risk_tier = RiskTier.ELEVATED
            risk_pct = min(available_risk, self._max_risk)
        else:
            risk_tier = RiskTier.STANDARD
            risk_pct = self._base_risk

        # Hard clamp
        risk_pct = max(self._min_risk, min(self._max_risk, risk_pct))

        # Max risk amount
        max_risk_amount = equity * risk_pct

        # Stop points and target points
        if direction == "LONG":
            stop_points = entry_price - stop_price
            target_points = target_price - entry_price
        else:
            stop_points = stop_price - entry_price
            target_points = entry_price - target_price

        # RR check
        if stop_points <= 0:
            return SizingResult(
                risk_pct=risk_pct,
                max_risk_amount=max_risk_amount,
                lots=0,
                stop_points=0,
                target_points=target_points,
                rr_ratio=0,
                risk_tier=risk_tier,
                allowed=False,
                reason="Invalid stop (stop <= entry)",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
                theta_decay_risk=0.0,
                holding_cost_ratio=0.0,
                theta_adjusted_lots=0,
            )

        # Get lot size from exchange config or defaults
        if self._exchange_config:
            lot_size = self._exchange_config.get_lot_size(underlying)
        else:
            lot_size = self.DEFAULT_LOT_SIZES.get(underlying, self.DEFAULT_LOT_SIZES.get("NIFTY", 25))

        rr_ratio = target_points / stop_points if stop_points > 0 else 0
        if rr_ratio < self._min_rr:
            return SizingResult(
                risk_pct=risk_pct,
                max_risk_amount=max_risk_amount,
                lots=0,
                stop_points=stop_points,
                target_points=target_points,
                rr_ratio=rr_ratio,
                risk_tier=risk_tier,
                allowed=False,
                reason=f"R:R={rr_ratio:.1f} < {self._min_rr}",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
                theta_decay_risk=0.0,
                holding_cost_ratio=0.0,
                theta_adjusted_lots=0,
            )

        # Theta calculation for options
        # Expected profit per contract = target_points * lot_size
        if self._exchange_config:
            lot_size = self._exchange_config.get_lot_size(underlying)
        else:
            lot_size = self.DEFAULT_LOT_SIZES.get(underlying, self.DEFAULT_LOT_SIZES.get("NIFTY", 25))
        expected_profit_per_contract = target_points * lot_size

        # Holding time in days
        hold_days = expected_hold_minutes / 375.0  # ~375 trading minutes per day

        # Theta cost = daily_theta * hold_days * lots
        theta_decay_risk = abs(theta) * hold_days

        # Holding cost ratio = theta cost / expected profit
        holding_cost_ratio = 0.0
        if expected_profit_per_contract > 0:
            holding_cost_ratio = theta_decay_risk / expected_profit_per_contract

        # Lot calculation with theta adjustment
        raw_lots = math.floor(max_risk_amount / (stop_points * lot_size))

        # Reduce lots if theta is too high (> threshold of expected profit)
        if holding_cost_ratio > self._theta_risk_threshold and raw_lots > 0:
            reduction_factor = max(0.5, 1.0 - holding_cost_ratio)
            lots = max(1, math.floor(raw_lots * reduction_factor))
            reason_suffix = f", theta-adjusted ({holding_cost_ratio:.1%} holding cost)"
        else:
            lots = raw_lots
            reason_suffix = ""
        
        # IV crush risk reduction (Rule B6: reduce by 50% around events)
        iv_event_risk = iv_event
        iv_reduced_lots = lots
        if iv_event and lots > 0:
            iv_reduced_lots = max(1, math.floor(lots * 0.5))  # Reduce by 50%
            if iv_reduced_lots != lots:
                reason_suffix += ", IV event - reduced position"
            lots = iv_reduced_lots

        if lots < 1:
            return SizingResult(
                risk_pct=risk_pct,
                max_risk_amount=max_risk_amount,
                lots=0,
                stop_points=stop_points,
                target_points=target_points,
                rr_ratio=rr_ratio,
                risk_tier=risk_tier,
                allowed=False,
                reason="Insufficient risk for 1 lot",
                scale_in_1=0,
                scale_in_2=0,
                scale_in_3=0,
                theta_decay_risk=theta_decay_risk,
                holding_cost_ratio=holding_cost_ratio,
                theta_adjusted_lots=0,
                bid_ask_spread_ok=spread_ok,
                spread_pct=spread_pct,
                liquidity_ok=liquidity_ok,
                oi_ok=oi_ok,
                volume_ok=volume_ok,
                iv_event_risk=iv_event_risk,
                iv_reduced_lots=0,
            )

        # Day-of-week filters (Rule B8: expiry Thursday, Friday restrictions)
        weekday_risk = False
        weekday_reduced_lots = lots
        if current_time is not None:
            weekday = current_time.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
            # Thursday = expiry day: high gamma, reduce by 50%
            if weekday == 3:  # Thursday
                weekday_risk = True
                weekday_reduced_lots = max(1, math.floor(lots * 0.5))
                if weekday_reduced_lots != lots:
                    reason_suffix += ", Expiry Thursday - reduced position"
                lots = weekday_reduced_lots
            # Friday: remove entirely per Fabio's NASDAQ rule
            elif weekday == 4:  # Friday
                return SizingResult(
                    risk_pct=0.0,
                    max_risk_amount=0.0,
                    lots=0,
                    stop_points=0.0,
                    target_points=0.0,
                    rr_ratio=0.0,
                    risk_tier=RiskTier.STANDARD,
                    allowed=False,
                    reason="No trading on Friday - weekend positioning risk",
                    scale_in_1=0,
                    scale_in_2=0,
                    scale_in_3=0,
                    theta_decay_risk=0.0,
                    holding_cost_ratio=0.0,
                    theta_adjusted_lots=0,
                    bid_ask_spread_ok=True,
                    spread_pct=0.0,
                    liquidity_ok=True,
                    oi_ok=True,
                    volume_ok=True,
                    iv_event_risk=False,
                    iv_reduced_lots=0,
                    weekday_risk=True,
                    weekday_reduced_lots=0,
                )

        # Scale-in plan: 40% / 30% / 30%
        scale_1 = max(1, math.floor(lots * 0.40))
        scale_2 = max(0, math.floor(lots * 0.30))
        scale_3 = lots - scale_1 - scale_2
        if scale_3 < 0:
            scale_3 = 0
            scale_2 = lots - scale_1

        # Breakeven calculation per Rule 5:
        # "In 1 minute the position is risk-free"
        # "As soon as we go high trail stop-loss and get back inside"
        breakeven_points = stop_points * 0.5  # Half the stop distance for safety buffer
        
        return SizingResult(
            risk_pct=risk_pct,
            max_risk_amount=max_risk_amount,
            lots=lots,
            stop_points=stop_points,
            target_points=target_points,
            rr_ratio=rr_ratio,
            risk_tier=risk_tier,
            allowed=True,
            reason=f"Lots={lots} ({scale_1}/{scale_2}/{scale_3}), R:R={rr_ratio:.1f}, risk={risk_pct:.2%}{reason_suffix}",
            scale_in_1=scale_1,
            scale_in_2=scale_2,
            scale_in_3=scale_3,
            theta_decay_risk=theta_decay_risk,
            holding_cost_ratio=holding_cost_ratio,
            theta_adjusted_lots=lots,
            breakeven_points=breakeven_points,
            breakeven_minutes=1,
            bid_ask_spread_ok=spread_ok,
            spread_pct=spread_pct,
            liquidity_ok=liquidity_ok,
            oi_ok=oi_ok,
            volume_ok=volume_ok,
            iv_event_risk=iv_event_risk,
            iv_reduced_lots=iv_reduced_lots,
            weekday_risk=weekday_risk,
            weekday_reduced_lots=weekday_reduced_lots,
            oi_wall_support=oi_wall_support,
            oi_wall_resistance=oi_wall_resistance,
        )

    def check_breakeven(
        self,
        sizing_result: SizingResult,
        entry_price: float,
        current_price: float,
        direction: str,
        minutes_since_entry: int = 0,
        floating_pnl: float = 0.0,
        original_risk_amount: float = 0.0,
    ) -> BreakevenAction:
        """Check if breakeven should be triggered per Rule 5.
        
        Rule 5 from AMT:
        - "In 1 minute the position is risk-free"
        - "As soon as we go high trail stop-loss"
        - Trigger conditions:
          1. Price moves 1R in your favor (primary)
          2. Strong volume/delta confirmation (secondary)
          3. Floating profit > initial risk (cushion-based)
        
        Args:
            sizing_result: The SizingResult from calculate()
            entry_price: Price at which position was entered
            current_price: Current market price
            direction: "LONG" or "SHORT"
            minutes_since_entry: Minutes since entry (for 1-min rule)
            floating_pnl: Current floating PnL
            original_risk_amount: Original risk amount in currency
            
        Returns:
            BreakevenAction with move_to_breakeven=True if should exit
        """
        if not sizing_result.allowed or sizing_result.lots == 0:
            return BreakevenAction()
        
        # Calculate price movement since entry
        if direction == "LONG":
            price_move = current_price - entry_price
        else:
            price_move = entry_price - current_price
        
        # 1R movement = stop_points * lot_size (in price terms for underlying)
        one_r_points = sizing_result.stop_points
        
        # Trigger condition 1: 1R move in favor (Fabio's primary rule)
        if price_move >= one_r_points:
            new_stop = entry_price + (sizing_result.breakeven_points if direction == "LONG" else -sizing_result.breakeven_points)
            return BreakevenAction(
                move_to_breakeven=True,
                new_stop_price=new_stop,
                trigger_reason="1R",
            )
        
        # Trigger condition 2: Floating profit > initial risk (cushion condition)
        if floating_pnl > 0 and original_risk_amount > 0 and floating_pnl >= original_risk_amount:
            new_stop = entry_price + (sizing_result.breakeven_points if direction == "LONG" else -sizing_result.breakeven_points)
            return BreakevenAction(
                move_to_breakeven=True,
                new_stop_price=new_stop,
                trigger_reason="cushion",
            )
        
        return BreakevenAction()