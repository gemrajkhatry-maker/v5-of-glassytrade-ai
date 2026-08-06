"""Regime hysteresis store — thread-safe per-symbol hysteresis state management.

Replaces the module-level mutable _regime_hysteresis dict with an
instance-managed, thread-safe store that can be injected via DI.
"""

from __future__ import annotations

import threading

from quant.probability.regime import RegimeHysteresis


class RegimeHysteresisStore:
    """Thread-safe store for per-symbol regime hysteresis state.

    Shared across all pipeline invocations. Each symbol gets its own
    RegimeHysteresis instance to prevent regime flip-flopping.
    """

    def __init__(self, min_persistence: int = 3) -> None:
        self._min_persistence = min_persistence
        self._store: dict[str, RegimeHysteresis] = {}
        self._lock = threading.Lock()

    def get(self, symbol: str) -> RegimeHysteresis:
        """Get or create a RegimeHysteresis instance for a symbol."""
        with self._lock:
            if symbol not in self._store:
                self._store[symbol] = RegimeHysteresis(
                    min_persistence=self._min_persistence,
                )
            return self._store[symbol]
