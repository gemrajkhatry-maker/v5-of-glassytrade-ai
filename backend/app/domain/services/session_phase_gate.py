"""Session Phase Gate — strict 5-phase IST time gate for NSE options.

Blocks all model evaluation outside allowed windows.
This is the FIRST gate in the pipeline — if phase = blocked, set MODEL OUTPUT = SKIP.

Phases:
  Phase 1 — Opening Noise     : 09:15-09:30 IST → NO TRADE, build profile
  Phase 2 — AAA Window        : 09:30-11:30 IST → ALL MODELS ACTIVE
  Phase 3 — Midday            : 11:30-14:00 IST → MEAN REVERSION ONLY
  Phase 4 — Power Hour        : 14:00-15:15 IST → ALL MODELS ACTIVE
  Phase 5 — Close Protection  : 15:15-15:30 IST → EXIT ONLY, no new entries

Day-of-week filters:
  MONDAY:   Extend Phase 1 to 09:45 IST
  THURSDAY: Reduce size 50%, Phase 2 only, use next-week expiry
  FRIDAY:   Configurable reduce/skip flag per instrument
  EVENT DAYS: NO TRADE flag, full block

#29: IB-based phase transitions added via evaluate_with_ib():
  Phase 1 ends when IB is confirmed (enough volume to define it)
  Phase 2 begins when price first tests the IB boundary
  Phase 3 activates when price closes outside IB with conviction volume
  Phase 4 is active until a failed extension is detected
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum

logger = logging.getLogger(__name__)


class TradingPhase(str, Enum):
    OPENING_AUCTION = "OPENING_AUCTION"  # 09:15-09:30 — institutional flow, all models active
    AAA_WINDOW = "AAA_WINDOW"  # 09:30-11:30 — all models active
    MIDDAY = "MIDDAY"  # 11:30-14:00 — mean reversion only
    POWER_HOUR = "POWER_HOUR"  # 14:00-15:15 — all models active
    CLOSE_PROTECTION = "CLOSE_PROTECTION"  # 15:15-15:30 — exit only
    CLOSED = "CLOSED"  # outside market hours


class AllowedAction(str, Enum):
    NO_TRADE = "NO_TRADE"
    AAA_ONLY = "AAA_ONLY"
    MR_ONLY = "MR_ONLY"
    ALL_MODELS = "ALL_MODELS"
    EXIT_ONLY = "EXIT_ONLY"


@dataclass(frozen=True)
class PhaseState:
    """Immutable session phase snapshot."""

    phase: TradingPhase
    allowed_action: AllowedAction
    is_blocked: bool  # True if NO_TRADE or EXIT_ONLY
    size_multiplier: float  # 0.0-1.0 (THURSDAY reduces to 0.5)
    reason: str  # Human-readable reason
    is_event_day: bool = False
    day_of_week: str = ""  # MONDAY, TUESDAY, etc.


class SessionPhaseGate:
    """Strict 5-phase IST time gate.

    Always evaluates FIRST in the pipeline. If blocked, no model evaluation occurs.
    """

    # Phase 1: Opening Noise (extended on Monday)
    _P1_START = time(9, 15)
    _P1_END = time(9, 30)
    _P1_END_MONDAY = time(9, 45)

    # Phase 2: AAA Window
    _P2_START = time(9, 30)
    _P2_END = time(11, 30)

    # Phase 3: Midday
    _P3_START = time(11, 30)
    _P3_END = time(14, 0)

    # Phase 4: Power Hour
    _P4_START = time(14, 0)
    _P4_END = time(15, 15)

    # Phase 5: Close Protection
    _P5_START = time(15, 15)
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
        """Evaluate current phase based on IST time.

        Args:
            timestamp: IST datetime (default: now)
        """
        now = timestamp or datetime.now()
        day_name = now.strftime("%A").upper()
        time_now = now.time()
        date_str = now.strftime("%Y-%m-%d")

        # Check event day
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

        # Friday skip (Fabio Gap #2b)
        if self._friday_skip and day_name == "FRIDAY":
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason="Friday skip enabled — NO TRADE",
                day_of_week=day_name,
            )

        # Before market opens
        if time_now < self._P1_START:
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason="Market not yet open (before 09:15)",
                day_of_week=day_name,
            )

        # After market closes
        if time_now >= self._P5_END:
            return PhaseState(
                phase=TradingPhase.CLOSED,
                allowed_action=AllowedAction.NO_TRADE,
                is_blocked=True,
                size_multiplier=0.0,
                reason="Market closed (after 15:30)",
                day_of_week=day_name,
            )

        # Phase 1: Opening Auction (Fabio: institutional players show hands here)
        p1_end = self._P1_END_MONDAY if day_name == "MONDAY" else self._P1_END
        if time_now < p1_end:
            return PhaseState(
                phase=TradingPhase.OPENING_AUCTION,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=1.0,
                reason=f"Opening auction ({'extended 09:45' if day_name == 'MONDAY' else '09:30'}) — institutional flow active",
                day_of_week=day_name,
            )

        # Phase 2: AAA Window
        if time_now < self._P2_END:
            size_mult = 0.5 if self._thursday_reduce and day_name == "THURSDAY" else 1.0
            return PhaseState(
                phase=TradingPhase.AAA_WINDOW,
                allowed_action=AllowedAction.AAA_ONLY
                if day_name == "THURSDAY"
                else AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=size_mult,
                reason=f"AAA Window{' (50% size)' if day_name == 'THURSDAY' else ''}",
                day_of_week=day_name,
            )

        # Phase 3: Midday
        if time_now < self._P3_END:
            return PhaseState(
                phase=TradingPhase.MIDDAY,
                allowed_action=AllowedAction.MR_ONLY,
                is_blocked=False,
                size_multiplier=1.0,
                reason="Midday — mean reversion only",
                day_of_week=day_name,
            )

        # Phase 4: Power Hour
        if time_now < self._P4_END:
            size_mult = 0.5 if self._friday_reduce and day_name == "FRIDAY" else 1.0
            return PhaseState(
                phase=TradingPhase.POWER_HOUR,
                allowed_action=AllowedAction.ALL_MODELS,
                is_blocked=False,
                size_multiplier=size_mult,
                reason=f"Power Hour{' (50% size)' if day_name == 'FRIDAY' else ''}",
                day_of_week=day_name,
            )

        # Phase 5: Close Protection
        return PhaseState(
            phase=TradingPhase.CLOSE_PROTECTION,
            allowed_action=AllowedAction.EXIT_ONLY,
            is_blocked=True,
            size_multiplier=0.0,
            reason="Close protection — exit only, no new entries",
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
        """Evaluate phase with IB-based transitions (#29).

        Fabio's phases are market-structure-based, not clock-based:
        - Phase 1 ends when IB is confirmed (enough volume to define it)
        - Phase 2 begins when price first tests IB boundary
        - Phase 3 activates when price closes outside IB with conviction
        - Phase 4 is active until failed extension detected

        Args:
            timestamp: IST datetime
            ib_complete: IB has been confirmed (enough volume/range)
            ib_tested: Price has tested IB boundary
            ib_broken: Price has closed outside IB with conviction volume
            ib_failed_extension: Extension phase failed (price returned to IB)
            ib_high: IB high price
            ib_low: IB low price
            current_price: Current market price
        """
        # Always respect hard time boundaries (market open/close)
        time_state = self.evaluate(timestamp)
        if time_state.phase in (TradingPhase.CLOSED, TradingPhase.CLOSE_PROTECTION):
            return time_state

        now = timestamp or datetime.now()
        day_name = now.strftime("%A").upper()

        # #29: IB-based phase transitions override time-based phases

        # Phase 1: If IB is complete early, transition to Phase 2
        if time_state.phase == TradingPhase.OPENING_AUCTION:
            if ib_complete:
                return PhaseState(
                    phase=TradingPhase.AAA_WINDOW,
                    allowed_action=AllowedAction.ALL_MODELS,
                    is_blocked=False,
                    size_multiplier=1.0,
                    reason=f"IB confirmed early — Phase 2 active (was {time_state.phase})",
                    day_of_week=day_name,
                )
            return time_state

        # Phase 2: IB tested → normal AAA window
        if time_state.phase == TradingPhase.AAA_WINDOW:
            if ib_tested:
                return PhaseState(
                    phase=TradingPhase.AAA_WINDOW,
                    allowed_action=AllowedAction.ALL_MODELS,
                    is_blocked=False,
                    size_multiplier=1.0,
                    reason="IB tested — Phase 2 active (all models)",
                    day_of_week=day_name,
                )
            return time_state

        # Phase 3: IB broken with conviction → extension phase
        if time_state.phase == TradingPhase.MIDDAY:
            if ib_broken:
                return PhaseState(
                    phase=TradingPhase.POWER_HOUR,
                    allowed_action=AllowedAction.ALL_MODELS,
                    is_blocked=False,
                    size_multiplier=1.0,
                    reason="IB broken with conviction — Phase 3 extension active",
                    day_of_week=day_name,
                )
            return time_state

        # Phase 4: Failed extension → revert to mean reversion
        if time_state.phase == TradingPhase.POWER_HOUR:
            if ib_failed_extension:
                return PhaseState(
                    phase=TradingPhase.MIDDAY,
                    allowed_action=AllowedAction.MR_ONLY,
                    is_blocked=False,
                    size_multiplier=1.0,
                    reason="Extension failed — reverted to mean reversion only",
                    day_of_week=day_name,
                )
            return time_state

        return time_state

    def can_trade(self, timestamp: datetime | None = None) -> bool:
        """Quick check: is trading allowed right now?"""
        state = self.evaluate(timestamp)
        return not state.is_blocked

    def is_aaa_allowed(self, timestamp: datetime | None = None) -> bool:
        """Is the AAA Trend Model allowed right now?"""
        state = self.evaluate(timestamp)
        return state.allowed_action in (
            AllowedAction.ALL_MODELS,
            AllowedAction.AAA_ONLY,
        )

    def is_mr_allowed(self, timestamp: datetime | None = None) -> bool:
        """Is the Mean Reversion Model allowed right now?"""
        state = self.evaluate(timestamp)
        return state.allowed_action in (AllowedAction.ALL_MODELS, AllowedAction.MR_ONLY)
