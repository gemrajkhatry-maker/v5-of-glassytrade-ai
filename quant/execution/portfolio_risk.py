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

from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.instrument_registry import root_token


class PortfolioRiskAuthority:
    def __init__(
        self,
        starting_equity: float = float(INITIAL_CAPITAL),
        max_portfolio_risk_pct: float = 0.95,   # max aggregate open risk: 95% of capital (aggressive)
        max_portfolio_daily_loss_pct: float = 0.95,  # global kill: 95% realized daily loss
    ) -> None:
        self._starting_equity = starting_equity
        self._max_open_risk = starting_equity * max_portfolio_risk_pct
        self._max_daily_loss = starting_equity * max_portfolio_daily_loss_pct
        self._lock = threading.RLock()
        self._open_risk = 0.0          # sum of (entry - sl) * qty for open positions
        self._realized_pnl = 0.0       # sum of closed-trade pnl across engines today
        self._active_roots: dict[str, str] = {}  # root -> active symbol

    def register_open(self, risk_rupees: float, symbol: str = "", is_pyramid: bool = False) -> bool:
        """Register a new position's rupee risk. False = rejected (would breach or concurrent root)."""
        with self._lock:
            if self._realized_pnl <= -self._max_daily_loss:
                return False
            if self._open_risk + max(0.0, risk_rupees) > self._max_open_risk:
                return False
            if symbol and not is_pyramid:
                root = root_token(symbol)
                if root and root in self._active_roots:
                    return False
                if root:
                    self._active_roots[root] = symbol
            self._open_risk += max(0.0, risk_rupees)
            return True

    def record_close(self, risk_rupees: float, pnl: float, symbol: str = "", is_full_close: bool = False) -> None:
        """Release a closed position's reserved risk and record realized P&L."""
        with self._lock:
            self._open_risk = max(0.0, self._open_risk - max(0.0, risk_rupees))
            self._realized_pnl += pnl
            if symbol and is_full_close:
                root = root_token(symbol)
                if root and self._active_roots.get(root) == symbol:
                    self._active_roots.pop(root, None)

    def release(self, risk_rupees: float, symbol: str = "") -> None:
        """Unwind a reserved amount that never became an open position (C3).

        Used when an entry's broker submission fails after ``register_open``
        succeeded — the reservation must be returned so it does not leak for
        the rest of the day. Unlike ``record_close`` it does not touch
        realized P&L, because no trade happened.
        """
        with self._lock:
            self._open_risk = max(0.0, self._open_risk - max(0.0, risk_rupees))
            if symbol:
                root = root_token(symbol)
                if root and self._active_roots.get(root) == symbol:
                    self._active_roots.pop(root, None)

    def can_accept(self, risk_rupees: float, symbol: str = "", is_pyramid: bool = False) -> tuple[bool, str]:
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
            if symbol and not is_pyramid:
                root = root_token(symbol)
                if root and root in self._active_roots:
                    return False, (
                        f"concurrent root position: {root} already active in {self._active_roots[root]}"
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

    @property
    def active_roots(self) -> dict[str, str]:
        with self._lock:
            return dict(self._active_roots)

    def active_symbol_for_root(self, root_or_symbol: str) -> str | None:
        with self._lock:
            root = root_token(root_or_symbol)
            return self._active_roots.get(root)

