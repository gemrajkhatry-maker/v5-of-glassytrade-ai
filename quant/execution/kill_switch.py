"""Kill Switch — thread-safe emergency trading halt mechanism.

Replaces the class-level mutable RiskManager._global_halt with an
instance-managed shared object that can be injected via DI.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class KillSwitch:
    """Thread-safe emergency trading halt flag.

    Shared across all RiskManager instances. When activated,
    all trading is blocked until manually resumed.
    """

    def __init__(self) -> None:
        self._halted = False
        self._lock = threading.Lock()

    @property
    def is_halted(self) -> bool:
        """Check if trading is globally halted."""
        with self._lock:
            return self._halted

    def halt(self) -> None:
        """Activate emergency kill switch."""
        with self._lock:
            self._halted = True
        logger.warning("Trading FORCE HALTED via emergency kill switch")

    def resume(self) -> None:
        """Clear emergency kill switch (does NOT clear daily halts)."""
        with self._lock:
            self._halted = False
        logger.info("Emergency kill switch cleared")
