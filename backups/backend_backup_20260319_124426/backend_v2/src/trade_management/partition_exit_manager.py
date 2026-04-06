"""
Partition exit manager — P1/P2/P3 exits + BE + counter-aggression.

P1: 30% at 33% R (weak momentum only)
P2: 50% at target (always)
P3: 20% trail if CVD strong, exit if weak
Break-even: 35% of R toward target
Counter-aggression: 2+ opposite signals = exit ALL
"""

from dataclasses import dataclass
from typing import List

from src.config.engine_config import CFG


@dataclass
class ExitSignal:
    """Exit signal for position management."""

    exit_type: str  # PARTITION_1, PARTITION_2, PARTITION_3, COUNTER_AGGRESSION, BREAK_EVEN
    exit_pct: float  # Percentage of position to exit


@dataclass
class ManagedPosition:
    """Position being managed."""

    entry_price: float
    initial_stop: float
    target: float
    direction: str  # LONG or SHORT
    lots: int
    p1_taken: bool = False
    p2_taken: bool = False
    p3_taken: bool = False
    breakeven_set: bool = False
    counter_aggression_count: int = 0


class PartitionExitManager:
    """
    Manage position exits in 3 partitions.

    P1: Seed recovery at 33% R (if momentum weak)
    P2: Mandatory at target
    P3: Trail if strong, exit if weak
    """

    def check_exits(
        self,
        position: ManagedPosition,
        current_price: float,
        cvd_slope: float,
    ) -> List[ExitSignal]:
        """
        Check for exit signals.

        Args:
            position: Current position state
            current_price: Current market price
            cvd_slope: Current CVD slope

        Returns:
            List of exit signals.
        """
        signals = []

        # Calculate risk and unrealized
        risk = abs(position.entry_price - position.initial_stop)
        if position.direction == "LONG":
            unrealized = current_price - position.entry_price
        else:
            unrealized = position.entry_price - current_price

        # P1: 30% at 33% R IF momentum weak
        if not position.p1_taken and unrealized >= risk * CFG.p1_trigger_r:
            if abs(cvd_slope) < CFG.cvd_strong_slope:  # Weak momentum
                signals.append(ExitSignal("PARTITION_1", CFG.p1_pct))
                position.p1_taken = True

        # P2: 50% at target (ALWAYS)
        if not position.p2_taken:
            if position.direction == "LONG" and current_price >= position.target:
                signals.append(ExitSignal("PARTITION_2", CFG.p2_pct))
                position.p2_taken = True
            elif position.direction == "SHORT" and current_price <= position.target:
                signals.append(ExitSignal("PARTITION_2", CFG.p2_pct))
                position.p2_taken = True

        # P3: 20% trail or exit
        if position.p2_taken and not position.p3_taken:
            if abs(cvd_slope) >= CFG.cvd_strong_slope:  # Strong momentum → trail
                # Trail formula: SL = current - (remaining × 0.40)
                remaining = abs(position.target - current_price)
                trail_distance = remaining * CFG.trail_remaining_pct
                # Trail logic handled externally
                pass
            else:  # Weak → exit with P2
                signals.append(ExitSignal("PARTITION_3", CFG.p3_pct))
                position.p3_taken = True

        # Counter-aggression: 2+ opposite signals = exit ALL
        if position.counter_aggression_count >= CFG.counter_aggression_exit_count:
            signals.append(ExitSignal("COUNTER_AGGRESSION", 1.0))

        # Break-even: at 35% of R toward target
        if not position.breakeven_set and unrealized >= risk * CFG.breakeven_trigger_r:
            signals.append(ExitSignal("BREAK_EVEN", 0.0))  # Just move SL
            position.breakeven_set = True

        return signals