"""Unified risk policy — single source of truth for all risk thresholds."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPolicy:
    """All risk thresholds in one place. Injected at bootstrap."""
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    max_concurrent_positions: int = 5
    max_portfolio_notional_pct: float = 0.60
    max_per_symbol_notional_pct: float = 0.20
    spread_blowout_threshold: float = 0.03
    hard_max_hold_seconds: float = 7200.0
    breakeven_at_r_multiple: float = 1.0
    trail_activation_r_multiple: float = 1.0
    kill_switch_drawdown_pct: float = 0.05
    session_time_stop_balanced: float = 1200.0
    session_time_stop_imbalanced: float = 1800.0
    session_time_stop_expiry: float = 600.0

    def is_daily_loss_acceptable(self, daily_loss_pct: float) -> bool:
        return daily_loss_pct < self.max_daily_loss_pct

    def is_portfolio_exposure_acceptable(
        self, portfolio_notional: float, equity: float
    ) -> bool:
        return portfolio_notional < equity * self.max_portfolio_notional_pct
