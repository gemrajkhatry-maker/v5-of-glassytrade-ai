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
        max_portfolio_risk_pct: float = 0.25,   # max aggregate open risk: 25% of capital
        max_portfolio_daily_loss_pct: float = 0.15,  # global kill: 15% realized daily loss
        separate_by: str = "root",  # "root" | "symbol" | "instrument_type"
        max_root_risk_pct: float | None = None,
        max_exchange_risk_pct: float | None = None,
    ) -> None:
        self._starting_equity = starting_equity
        self._max_open_risk = starting_equity * max_portfolio_risk_pct
        self._max_daily_loss = starting_equity * max_portfolio_daily_loss_pct
        self._hard_notional_cap = starting_equity * 0.50
        self._open_notional = 0.0
        self._separate_by = separate_by
        self._lock = threading.RLock()
        self._open_risk = 0.0          # sum of (entry - sl) * qty for open positions
        self._realized_pnl = 0.0       # sum of closed-trade pnl across engines today
        self._max_root_risk = (
            starting_equity * max_root_risk_pct
            if max_root_risk_pct is not None else None
        )
        self._max_exchange_risk = (
            starting_equity * max_exchange_risk_pct
            if max_exchange_risk_pct is not None else None
        )
        self._root_open_risk: dict[str, float] = {}
        self._exchange_open_risk: dict[str, float] = {}
        self._active_roots: dict[str, str] = {}  # lock_key -> active symbol

    def _lock_key(self, symbol: str) -> str:
        if not symbol:
            return ""
        if self._separate_by == "symbol":
            return symbol
        root = root_token(symbol)
        if not root:
            return symbol
        if self._separate_by == "instrument_type":
            from quant.contracts.instrument_registry import is_option_contract
            return f"{root}:{'OPT' if is_option_contract(symbol) else 'FUT'}"
        return root

    def _exchange_key(self, symbol: str) -> str:
        spec = __import__("quant.contracts.instrument_registry", fromlist=["DEFAULT_REGISTRY"]).DEFAULT_REGISTRY.try_resolve(symbol)
        return str(getattr(spec, "exchange", "")).upper() or "UNKNOWN"

    def _budget_available(self, risk_rupees: float, symbol: str) -> bool:
        if not symbol:
            return True
        amount = max(0.0, risk_rupees)
        root = root_token(symbol)
        if self._max_root_risk is not None and self._root_open_risk.get(root, 0.0) + amount > self._max_root_risk:
            return False
        exchange = self._exchange_key(symbol)
        if self._max_exchange_risk is not None and self._exchange_open_risk.get(exchange, 0.0) + amount > self._max_exchange_risk:
            return False
        return True

    def _add_budget(self, risk_rupees: float, symbol: str) -> None:
        if not symbol:
            return
        amount = max(0.0, risk_rupees)
        root = root_token(symbol)
        exchange = self._exchange_key(symbol)
        self._root_open_risk[root] = self._root_open_risk.get(root, 0.0) + amount
        self._exchange_open_risk[exchange] = self._exchange_open_risk.get(exchange, 0.0) + amount

    def _release_budget(self, risk_rupees: float, symbol: str) -> None:
        if not symbol:
            return
        amount = max(0.0, risk_rupees)
        root = root_token(symbol)
        exchange = self._exchange_key(symbol)
        self._root_open_risk[root] = max(0.0, self._root_open_risk.get(root, 0.0) - amount)
        self._exchange_open_risk[exchange] = max(0.0, self._exchange_open_risk.get(exchange, 0.0) - amount)

    def root_open_risk(self, root_or_symbol: str) -> float:
        with self._lock:
            return self._root_open_risk.get(root_token(root_or_symbol), 0.0)

    def exchange_open_risk(self, exchange: str) -> float:
        with self._lock:
            return self._exchange_open_risk.get(str(exchange).upper(), 0.0)

    def register_open(self, risk_rupees: float, symbol: str = "", is_pyramid: bool = False) -> bool:
        """Register a new position's rupee risk. False = rejected (would breach or concurrent root)."""
        with self._lock:
            if self._realized_pnl <= -self._max_daily_loss:
                return False
            if self._open_notional + max(0.0, risk_rupees) > self._hard_notional_cap:
                return False
            if self._open_risk + max(0.0, risk_rupees) > self._max_open_risk:
                return False
            if not self._budget_available(risk_rupees, symbol):
                return False
            if symbol and not is_pyramid:
                key = self._lock_key(symbol)
                if key and key in self._active_roots:
                    return False
                if key:
                    self._active_roots[key] = symbol
            self._open_risk += max(0.0, risk_rupees)
            self._open_notional += max(0.0, risk_rupees)
            self._add_budget(risk_rupees, symbol)
            return True

    def record_close(self, risk_rupees: float, pnl: float, symbol: str = "", is_full_close: bool = False) -> None:
        """Release a closed position's reserved risk and record realized P&L."""
        with self._lock:
            self._open_risk = max(0.0, self._open_risk - max(0.0, risk_rupees))
            self._open_notional = max(0.0, self._open_notional - max(0.0, risk_rupees))
            self._release_budget(risk_rupees, symbol)
            self._realized_pnl += pnl
            if symbol and is_full_close:
                key = self._lock_key(symbol)
                if key and self._active_roots.get(key) == symbol:
                    self._active_roots.pop(key, None)

    def release(self, risk_rupees: float, symbol: str = "") -> None:
        """Unwind a reserved amount that never became an open position (C3).

        Used when an entry's broker submission fails after ``register_open``
        succeeded — the reservation must be returned so it does not leak for
        the rest of the day. Unlike ``record_close`` it does not touch
        realized P&L, because no trade happened.
        """
        with self._lock:
            self._open_risk = max(0.0, self._open_risk - max(0.0, risk_rupees))
            self._open_notional = max(0.0, self._open_notional - max(0.0, risk_rupees))
            self._release_budget(risk_rupees, symbol)
            if symbol:
                key = self._lock_key(symbol)
                if key and self._active_roots.get(key) == symbol:
                    self._active_roots.pop(key, None)

    def can_accept(self, risk_rupees: float, symbol: str = "", is_pyramid: bool = False) -> tuple[bool, str]:
        with self._lock:
            if self._open_notional + max(0.0, risk_rupees) > self._hard_notional_cap:
                return False, (
                    f"hard equity cap 50%: aggregate open {self._open_notional:.0f}+{risk_rupees:.0f} "
                    f"> {self._hard_notional_cap:.0f}"
                )
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
            if not self._budget_available(risk_rupees, symbol):
                return False, "correlation or exchange risk budget exceeded"
            if symbol and not is_pyramid:
                key = self._lock_key(symbol)
                if key and key in self._active_roots:
                    return False, (
                        f"concurrent root position: {key} already active in {self._active_roots[key]}"
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

