"""Partition exit manager — 3-part exit framework (FR-08)."""

from __future__ import annotations

import logging

from app.domain.exit.model.exit_models import ExitSignal, PartitionState

logger = logging.getLogger(__name__)


CVD_STRONG_SLOPE = 0.5


class PartitionExitManager:
    """Evaluate partitioned exits and counter-aggression overrides."""

    P1_SIZE = 0.30
    P2_SIZE = 0.40
    P3_SIZE = 0.30

    P1_R_MULTIPLIER = 1.0
    P2_R_MULTIPLIER = 2.0
    TRAIL_REMAINING_RATIO = 0.40

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
        signals: list[ExitSignal] = []
        risk = abs(entry_price - initial_stop)
        if risk <= 0:
            return signals

        if is_long:
            unrealised = current_price - entry_price
            remaining = max(0.0, take_profit - current_price)
        else:
            unrealised = entry_price - current_price
            remaining = max(0.0, current_price - take_profit)

        r_multiple = unrealised / risk if risk > 0 else 0.0
        towards_target_r = (current_price - entry_price) / risk if is_long else (entry_price - current_price) / risk

        if state.counter_aggression_count >= 2:
            signals.append(
                ExitSignal(
                    exit_type="COUNTER_AGGRESSION",
                    size_pct=1.0,
                    price=current_price,
                    reason=f"Counter-aggression: {state.counter_aggression_count} opposite signals",
                )
            )
            logger.warning("Counter-aggression exit: %d opposite signals", state.counter_aggression_count)
            return signals

        if not state.breakeven_set and towards_target_r >= 1.0:
            state.breakeven_set = True
            state.trail_sl = entry_price
            logger.info("BREAK-EVEN set at %.2fR toward target", towards_target_r)

        if not state.p1_taken:
            is_imbalanced = "IMBAL" in market_state.upper() or "TREND" in market_state.upper()
            if is_imbalanced:
                cvd_confirms = (
                    (is_long and cvd_slope >= CVD_STRONG_SLOPE)
                    or (not is_long and cvd_slope <= -CVD_STRONG_SLOPE)
                )
                if r_multiple >= self.P1_R_MULTIPLIER and cvd_confirms:
                    state.p1_taken = True
                    signals.append(
                        ExitSignal(
                            exit_type="PARTITION_1",
                            size_pct=self.P1_SIZE,
                            price=current_price,
                            reason=f"P1 at {r_multiple:.1%}R with CVD confirmation",
                        )
                    )
            elif r_multiple >= self.P1_R_MULTIPLIER:
                state.p1_taken = True
                signals.append(
                    ExitSignal(
                        exit_type="PARTITION_1",
                        size_pct=self.P1_SIZE,
                        price=current_price,
                        reason=f"P1 at {r_multiple:.1%}R",
                    )
                )

        if not state.p2_taken and r_multiple >= self.P2_R_MULTIPLIER:
            state.p2_taken = True
            state.trail_sl = current_price
            signals.append(
                ExitSignal(
                    exit_type="PARTITION_2",
                    size_pct=self.P2_SIZE,
                    price=current_price,
                    reason=f"P2 at {r_multiple:.1%}R",
                )
            )

        if state.p2_taken and not state.p3_taken:
            if abs(cvd_slope) >= CVD_STRONG_SLOPE and remaining > 0:
                new_sl = (
                    current_price - (remaining * self.TRAIL_REMAINING_RATIO)
                    if is_long
                    else current_price + (remaining * self.TRAIL_REMAINING_RATIO)
                )
                if (is_long and new_sl > state.trail_sl) or (not is_long and new_sl < state.trail_sl):
                    state.trail_sl = new_sl
            else:
                state.p3_taken = True
                signals.append(
                    ExitSignal(
                        exit_type="PARTITION_3",
                        size_pct=self.P3_SIZE,
                        price=current_price,
                        reason="P3: momentum weak, close runner",
                    )
                )

        if state.p2_taken and not state.p3_taken and state.trail_sl > 0:
            sl_hit = (is_long and current_price <= state.trail_sl) or (
                not is_long and current_price >= state.trail_sl
            )
            if sl_hit:
                state.p3_taken = True
                signals.append(
                    ExitSignal(
                        exit_type="TRAIL",
                        size_pct=self.P3_SIZE,
                        price=current_price,
                        reason=f"Trail SL hit at {state.trail_sl:.2f}",
                    )
                )

        return signals

    def record_counter_aggression(
        self, state: PartitionState, signal_direction: str, position_direction: str
    ) -> None:
        if signal_direction != position_direction:
            state.counter_aggression_count += 1
            logger.debug("Counter-aggression count=%d", state.counter_aggression_count)
