"""Session phase gating and market-time permissions.

This port preserves the v1 behaviour of explicit phase transitions:
Opening auction, AAA window, midday, power hour and close protection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class TradingPhase(str, Enum):
    OPENING_AUCTION = "OPENING_AUCTION"
    AAA_WINDOW = "AAA_WINDOW"
    MIDDAY = "MIDDAY"
    POWER_HOUR = "POWER_HOUR"
    CLOSE_PROTECTION = "CLOSE_PROTECTION"
    CLOSED = "CLOSED"


class AllowedAction(str, Enum):
    NO_TRADE = "NO_TRADE"
    AAA_ONLY = "AAA_ONLY"
    MR_ONLY = "MR_ONLY"
    ALL_MODELS = "ALL_MODELS"
    EXIT_ONLY = "EXIT_ONLY"


@dataclass(frozen=True)
class PhaseState:
    phase: TradingPhase
    allowed_action: AllowedAction
    is_blocked: bool
    size_multiplier: float
    reason: str
    is_event_day: bool = False
    day_of_week: str = ""


class SessionPhaseGate:
    """Evaluate trading permissions by clock and optional IB transitions."""

    _P1_START = time(9, 15)
    _P1_END = time(9, 30)
    _P1_END_MONDAY = time(9, 45)
    _P2_END = time(11, 30)
    _P3_END = time(14, 0)
    _P4_END = time(15, 15)
    _P5_END = time(15, 30)

    def __init__(
        self,
        event_dates: list[str] | None = None,
        friday_reduce: bool = True,
        thursday_reduce: bool = True,
        friday_skip: bool = False,
    ) -> None:
        self._event_dates = set(event_dates or [])
        self._friday_reduce = friday_reduce
        self._thursday_reduce = thursday_reduce
        self._friday_skip = friday_skip

    def evaluate(self, timestamp: datetime | None = None) -> PhaseState:
        now = timestamp or datetime.now()
        day_name = now.strftime("%A").upper()
        time_now = now.time()
        date_str = now.strftime("%Y-%m-%d")

        if date_str in self._event_dates:
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason=f"Event day ({date_str}) — NO TRADE",
                is_event_day=True,
                day_of_week=day_name,
            )

        if self._friday_skip and day_name == "FRIDAY":
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason="Friday skip enabled — NO TRADE",
                day_of_week=day_name,
            )

        if time_now < self._P1_START:
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason="Market not yet open (before 09:15)",
                day_of_week=day_name,
            )

        if time_now >= self._P5_END:
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason="Market closed (after 15:30)",
                day_of_week=day_name,
            )

        p1_end = self._P1_END_MONDAY if day_name == "MONDAY" else self._P1_END
        if time_now < p1_end:
            return PhaseState(
                phase=TradingPhase.OPENING_AUCTION,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=1.0,
                reason=(
                    f"Opening auction ({'extended to 09:45' if day_name == 'MONDAY' else '09:30'})"
                ),
                day_of_week=day_name,
            )

        if time_now < self._P2_END:
            size_mult = 0.5 if self._thursday_reduce and day_name == "THURSDAY" else 1.0
            return PhaseState(
                phase=TradingPhase.AAA_WINDOW,
                allowed_action=(
                    AllowedAction.AAA_ONLY if day_name == "THURSDAY" else AllowedAction.ALL_MODELS
                ),
                is_blocked=False,
                size_multiplier=size_mult,
                reason=(
                    f"AAA window{' (50% size)' if day_name == 'THURSDAY' else ''}"
                ),
                day_of_week=day_name,
            )

        if time_now < self._P3_END:
            return PhaseState(
                phase=TradingPhase.MIDDAY,
                allowed_action=AllowedAction.MR_ONLY,
                is_blocked=False,
                size_multiplier=1.0,
                reason="Midday — mean reversion only",
                day_of_week=day_name,
            )

        if time_now < self._P4_END:
            size_mult = 0.5 if self._friday_reduce and day_name == "FRIDAY" else 1.0
            return PhaseState(
                phase=TradingPhase.POWER_HOUR,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=size_mult,
                reason=f"Power hour{' (50% size)' if day_name == 'FRIDAY' else ''}",
                day_of_week=day_name,
            )

        return PhaseState(
            phase=TradingPhase.CLOSE_PROTECTION,
            allowed_action=AllowedAction.EXIT_ONLY,
            is_blocked=True,
            size_multiplier=0.0,
            reason="Close protection — exit only",
            day_of_week=day_name,
        )

    def evaluate_with_ib(
        self,
        timestamp: datetime | None = None,
        ib_complete: bool = False,
        ib_tested: bool = False,
        ib_broken: bool = False,
        ib_failed_extension: bool = False,
        ib_high: float = 0.0,
        ib_low: float = 0.0,
        current_price: float = 0.0,
    ) -> PhaseState:
        time_state = self.evaluate(timestamp)
        if time_state.phase in (TradingPhase.CLOSED, TradingPhase.CLOSE_PROTECTION):
            return time_state

        day_name = (timestamp or datetime.now()).strftime("%A").upper()
        _ = ib_high, ib_low, current_price

        if time_state.phase == TradingPhase.OPENING_AUCTION and ib_complete:
            return PhaseState(
                phase=TradingPhase.AAA_WINDOW,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=1.0,
                reason=f"IB confirmed early — transitioned to {TradingPhase.AAA_WINDOW.value}",
                day_of_week=day_name,
            )

        if time_state.phase == TradingPhase.AAA_WINDOW and ib_tested:
            return PhaseState(
                phase=TradingPhase.AAA_WINDOW,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=1.0,
                reason="IB tested — phase remains all models",
                day_of_week=day_name,
            )

        if time_state.phase == TradingPhase.MIDDAY and ib_broken:
            return PhaseState(
                phase=TradingPhase.POWER_HOUR,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=1.0,
                reason="IB broken with conviction — power hour logic active",
                day_of_week=day_name,
            )

        if time_state.phase == TradingPhase.POWER_HOUR and ib_failed_extension:
            return PhaseState(
                phase=TradingPhase.MIDDAY,
                allowed_action=AllowedAction.MR_ONLY,
                is_blocked=False,
                size_multiplier=1.0,
                reason="Extension failed — back to mean reversion",
                day_of_week=day_name,
            )

        return time_state

    def can_trade(self, timestamp: datetime | None = None) -> bool:
        return not self.evaluate(timestamp).is_blocked

    def is_aaa_allowed(self, timestamp: datetime | None = None) -> bool:
        state = self.evaluate(timestamp)
        return state.allowed_action in (AllowedAction.ALL_MODELS, AllowedAction.AAA_ONLY)

    def is_mr_allowed(self, timestamp: datetime | None = None) -> bool:
        state = self.evaluate(timestamp)
        return state.allowed_action in (AllowedAction.ALL_MODELS, AllowedAction.MR_ONLY)

