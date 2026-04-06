"""Partition Exit Manager — P1/P2/P3 partition exits per Fabio AMT spec (FR-08).

Exit structure:
  P1 (30%): Exit at 33% of R IF momentum weak (skip if CVD strong)
  P2 (50%): ALWAYS exit at target (session POC)
  P3 (20%): Trail if CVD slope > 2.0, else exit with P2
  Break-even: Move SL to entry at 35% of R toward target
  Counter-aggression: 2+ opposite signals = exit ALL
  Trail formula: SL = current - (remaining_to_target × 0.40)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.domain.constants import CVD_STRONG_SLOPE

logger = logging.getLogger(__name__)


@dataclass
class ExitSignal:
    """Signal to exit a portion of a position."""

    exit_type: str  # "PARTITION_1" | "PARTITION_2" | "PARTITION_3" | "COUNTER_AGGRESSION" | "BREAK_EVEN" | "TRAIL"
    size_pct: float  # 0.0-1.0 (fraction of position to exit)
    price: float  # Exit price
    reason: str


@dataclass
class PartitionState:
    """Tracks which partitions have been taken."""

    p1_taken: bool = False
    p2_taken: bool = False
    p3_taken: bool = False
    breakeven_set: bool = False
    counter_aggression_count: int = 0
    trail_sl: float = 0.0


class PartitionExitManager:
    """Manages position exits in 3 partitions (FR-08)."""

    # Partition sizes
    P1_SIZE = 0.30  # 30% at 33% R
    P2_SIZE = 0.50  # 50% at target
    P3_SIZE = 0.20  # 20% trail

    # Trigger levels
    P1_R_MULTIPLIER = 0.33  # 33% of R
    BE_R_MULTIPLIER = 0.35  # 35% of R toward target
    TRAIL_REMAINING_RATIO = 0.40  # 40% of remaining distance

    def check_exits(
        self,
        entry_price: float,
        initial_stop: float,
        take_profit: float,
        current_price: float,
        is_long: bool,
        cvd_slope: float,
        state: PartitionState,
        market_state: str = "BALANCED",
    ) -> list[ExitSignal]:
        """Check all exit conditions and return exit signals.

        Args:
            entry_price: Position entry price.
            initial_stop: Original stop loss.
            take_profit: Target price.
            current_price: Current market price.
            is_long: True for long position.
            cvd_slope: Current CVD slope (positive = buying pressure).
            state: Current partition state.
            market_state: "BALANCED" or "IMBALANCED" — affects P1 behavior.

        Returns:
            List of ExitSignal to execute (may be empty).

        Market state awareness (Fix #6):
            BALANCED: P1 fires aggressively at 0.25R (mean reversion regime).
            IMBALANCED: P1 is skipped entirely to let trend run.
        """
        signals = []
        risk = abs(entry_price - initial_stop)
        if risk <= 0:
            return signals

        if is_long:
            unrealised = current_price - entry_price
            towards_target = current_price - entry_price
            remaining = max(0, take_profit - current_price)
        else:
            unrealised = entry_price - current_price
            towards_target = entry_price - current_price
            remaining = max(0, current_price - take_profit)

        r_multiple = unrealised / risk if risk > 0 else 0.0
        towards_target_r = towards_target / risk if risk > 0 else 0.0

        # Counter-aggression: 2+ opposite signals = exit ALL (FR-08-06)
        if state.counter_aggression_count >= 2:
            signals.append(
                ExitSignal(
                    exit_type="COUNTER_AGGRESSION",
                    size_pct=1.0,
                    price=current_price,
                    reason=f"Counter-aggression: {state.counter_aggression_count} opposite signals",
                )
            )
            logger.warning(
                "COUNTER_AGGRESSION EXIT: %d opposite signals",
                state.counter_aggression_count,
            )
            return signals

        # Break-even: move SL to entry at 35% of R (FR-08-07)
        if not state.breakeven_set and towards_target_r >= self.BE_R_MULTIPLIER:
            state.breakeven_set = True
            state.trail_sl = entry_price
            logger.info(
                "BREAK-EVEN triggered at %.2f R toward target", towards_target_r
            )

        # P1: state-aware profit taking (FR-08-01/02)
        if not state.p1_taken:
            is_imbalanced = "TREND" in market_state.upper() or "IMBALANCE" in market_state.upper()

            if is_imbalanced:
                # IMBALANCED: skip P1 entirely — let trend run, don't clip winners
                logger.debug("P1 skipped: IMBALANCED regime, momentum may continue")
            elif r_multiple >= 0.25:
                # BALANCED: lower threshold (0.25R instead of 0.33R) for mean reversion.
                # Fire P1 regardless of CVD — reversion is likely in balanced markets.
                signals.append(
                    ExitSignal(
                        exit_type="PARTITION_1",
                        size_pct=self.P1_SIZE,
                        price=current_price,
                        reason=f"P1: mean-reversion seed recovery at {r_multiple:.1%} R",
                    )
                )
                state.p1_taken = True
                logger.info(
                    "P1 exit at %.1f%% R (BALANCED regime)", r_multiple * 100
                )

        # P2: 50% at target ALWAYS (FR-08-03)
        if not state.p2_taken:
            at_target = (is_long and current_price >= take_profit) or (
                not is_long and current_price <= take_profit
            )
            if at_target:
                signals.append(
                    ExitSignal(
                        exit_type="PARTITION_2",
                        size_pct=self.P2_SIZE,
                        price=current_price,
                        reason="P2: target reached, mandatory exit",
                    )
                )
                state.p2_taken = True
                # Move P3 SL to P2 exit price
                state.trail_sl = current_price
                logger.info("P2 exit at target %.2f", current_price)

        # P3: 20% trail or exit (FR-08-04/05)
        if state.p2_taken and not state.p3_taken:
            if abs(cvd_slope) >= CVD_STRONG_SLOPE:
                # Strong momentum → trail
                if remaining > 0:
                    new_sl = (
                        current_price - (remaining * self.TRAIL_REMAINING_RATIO)
                        if is_long
                        else current_price + (remaining * self.TRAIL_REMAINING_RATIO)
                    )
                    if (is_long and new_sl > state.trail_sl) or (
                        not is_long and new_sl < state.trail_sl
                    ):
                        state.trail_sl = new_sl
                        logger.info("P3 trail: SL moved to %.2f", new_sl)
            else:
                # Weak momentum → exit P3 with P2
                signals.append(
                    ExitSignal(
                        exit_type="PARTITION_3",
                        size_pct=self.P3_SIZE,
                        price=current_price,
                        reason="P3: momentum weak, exit with P2",
                    )
                )
                state.p3_taken = True
                logger.info("P3 exit (CVD weak, slope %.2f)", cvd_slope)

        # Check if trail SL is hit
        if state.p2_taken and not state.p3_taken and state.trail_sl > 0:
            sl_hit = (is_long and current_price <= state.trail_sl) or (
                not is_long and current_price >= state.trail_sl
            )
            if sl_hit:
                signals.append(
                    ExitSignal(
                        exit_type="TRAIL",
                        size_pct=self.P3_SIZE,
                        price=current_price,
                        reason=f"Trail SL hit at {state.trail_sl:.2f}",
                    )
                )
                state.p3_taken = True
                logger.info("P3 trail exit at SL %.2f", state.trail_sl)

        return signals

    def record_counter_aggression(
        self,
        state: PartitionState,
        signal_direction: str,
        position_direction: str,
    ) -> None:
        """Record a counter-aggression signal (opposite to position direction)."""
        if signal_direction != position_direction:
            state.counter_aggression_count += 1
            logger.debug("Counter-aggression count: %d", state.counter_aggression_count)
