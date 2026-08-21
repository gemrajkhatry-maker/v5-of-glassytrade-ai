"""Portfolio-level risk authority shared across all engine threads.

Paper mode runs one SessionRisk per engine (per-symbol halts, per-symbol
equity). That lets the aggregate book risk 8x the intended capital. This
authority adds the missing cross-engine ceiling:

- ``register_open`` / ``record_close`` track aggregate open rupee risk and
  realized daily P&L across every engine.
- ``can_accept`` rejects a NEW position when aggregate open risk or realized
  loss would breach portfolio limits.

Design: coarse single RLock; called once per entry/exit (not per tick), so
contention is negligible. Engines call it from their own thread — the lock
only serializes bookkeeping, never trading logic.
"""

from __future__ import annotations

import threading


class PortfolioRiskAuthority:
    def __init__(
        self,
        starting_equity: float = 1_000_000.0,
        max_portfolio_risk_pct: float = 0.04,   # max aggregate open risk: 4% of capital
        max_portfolio_daily_loss_pct: float = 0.06,  # global kill: 6% realized daily loss
    ) -> None:
        self._starting_equity = starting_equity
        self._max_open_risk = starting_equity * max_portfolio_risk_pct
        self._max_daily_loss = starting_equity * max_portfolio_daily_loss_pct
        self._lock = threading.RLock()
        self._open_risk = 0.0          # sum of (entry - sl) * qty for open positions
        self._realized_pnl = 0.0       # sum of closed-trade pnl across engines today

    def register_open(self, risk_rupees: float) -> bool:
        """Register a new position's rupee risk. False = rejected (would breach)."""
        with self._lock:
            if self._open_risk + max(0.0, risk_rupees) > self._max_open_risk:
                return False
            self._open_risk += max(0.0, risk_rupees)
            return True

    def record_close(self, risk_rupees: float, pnl: float) -> None:
        """Release a closed position's reserved risk and record realized P&L."""
        with self._lock:
            self._open_risk = max(0.0, self._open_risk - max(0.0, risk_rupees))
            self._realized_pnl += pnl

    def can_accept(self, risk_rupees: float) -> tuple[bool, str]:
        with self._lock:
            if self._open_risk + max(0.0, risk_rupees) > self._max_open_risk:
                return False, (
                    f"portfolio open-risk limit: {self._open_risk:.0f}+{risk_rupees:.0f} "
                    f"> {self._max_open_risk:.0f}"
                )
            if self._realized_pnl <= -self._max_daily_loss:
                return False, (
                    f"portfolio daily-loss halt: {self._realized_pnl:.0f} "
                    f"<= -{self._max_daily_loss:.0f}"
                )
            return True, ""

    @property
    def open_risk(self) -> float:
        with self._lock:
            return self._open_risk

    @property
    def realized_pnl(self) -> float:
        with self._lock:
            return self._realized_pnl
