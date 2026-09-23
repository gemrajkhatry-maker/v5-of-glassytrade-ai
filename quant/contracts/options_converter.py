"""Greek Delta Scale Translation (OptionConverter).

Bridges underlying futures structural analysis with option execution:
1. Underlying point risk measured from structural invalidation:
       D_und = |P_und_entry - P_und_stop|
2. Option premium stop calculated via Greek Delta (Δ):
       P_opt_stop = max(P_opt_entry - (D_und * |Δ|), 2 * tau_opt)
3. Fabio's Anti-Slippage Offset: For directional breakouts, the stop is set
   1 to 2 ticks inside the extreme swing level rather than outside, exiting
   the position prior to the retail stop cascade.
4. Option target and Greek-adjusted R:R evaluation:
       (P_opt_target - P_opt_entry) / (P_opt_entry - P_opt_stop) >= 1.5
"""

from __future__ import annotations


from quant.contracts.tick_utils import (
    round_down_to_tick,
    round_up_to_tick,
)


class OptionConverter:
    """Mathematical translation between underlying futures reference levels and option contracts."""

    @staticmethod
    def compute_option_stop(
        und_entry: float,
        und_stop: float,
        opt_entry: float,
        delta: float,
        opt_tick_size: float = 0.05,
        und_tick_size: float = 0.05,
        is_breakout: bool = False,
        anti_slippage_ticks: int = 1,
    ) -> float:
        """Calculate option premium stop from underlying invalidation level.

        Args:
            und_entry: Underlying price at entry.
            und_stop: Underlying structural invalidation level.
            opt_entry: Option entry premium.
            delta: Option Greek Delta (|Δ| is used).
            opt_tick_size: Option minimum tick size (tau_opt).
            und_tick_size: Underlying minimum tick size.
            is_breakout: If True, applies Fabio's anti-slippage offset inside extreme level.
            anti_slippage_ticks: Number of ticks (1-2) inside extreme level for breakout exit.

        Returns:
            Calculated option stop loss premium, clamped to >= 2 * opt_tick_size.
        """
        abs_delta = abs(delta) if abs(delta) > 1e-4 else 0.5

        # Measure raw underlying risk distance
        d_und = abs(und_entry - und_stop)

        # Fabio's Anti-Slippage Offset:
        # Exit 1-2 ticks inside the extreme swing level prior to the retail stop cascade
        if is_breakout and anti_slippage_ticks > 0:
            offset = anti_slippage_ticks * und_tick_size
            d_und = max(d_und - offset, und_tick_size)

        opt_risk = d_und * abs_delta
        raw_stop = opt_entry - opt_risk

        min_floor = 2.0 * opt_tick_size
        clamped_stop = max(raw_stop, min_floor)

        return round_down_to_tick(clamped_stop, opt_tick_size)

    @staticmethod
    def compute_option_target(
        und_entry: float,
        und_target: float,
        opt_entry: float,
        delta: float,
        opt_tick_size: float = 0.05,
    ) -> float:
        """Calculate option premium target from underlying target level."""
        abs_delta = abs(delta) if abs(delta) > 1e-4 else 0.5
        d_und_target = abs(und_target - und_entry)
        opt_reward = d_und_target * abs_delta
        raw_target = opt_entry + opt_reward
        return round_up_to_tick(raw_target, opt_tick_size)

    @staticmethod
    def compute_option_rr(
        opt_entry: float,
        opt_stop: float,
        opt_target: float,
    ) -> float:
        """Calculate Greek-adjusted Risk-to-Reward ratio."""
        risk = opt_entry - opt_stop
        if risk <= 1e-6:
            return 0.0
        reward = opt_target - opt_entry
        return reward / risk

    @staticmethod
    def is_rr_acceptable(
        opt_entry: float,
        opt_stop: float,
        opt_target: float,
        min_rr: float = 1.5,
    ) -> bool:
        """Assert (P_opt_target - P_opt_entry) / (P_opt_entry - P_opt_stop) >= min_rr."""
        return OptionConverter.compute_option_rr(opt_entry, opt_stop, opt_target) >= min_rr


__all__ = [
    "OptionConverter",
]
