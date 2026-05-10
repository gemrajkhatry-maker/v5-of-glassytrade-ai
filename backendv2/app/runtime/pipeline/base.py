"""Pipeline stage base class and utilities."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.runtime.pipeline.events import PipelineEvent


class SymbolStateMixin:
    """Mixin for pipeline stages that maintain per-symbol state.

    Provides TTL-based eviction and max-capacity enforcement to prevent
    unbounded memory growth when tracking many symbols.
    """

    def __init__(
        self,
        max_symbols: int = 500,
        ttl_seconds: float = 86400.0,
        prune_interval: int = 100,
    ) -> None:
        self._max_symbols = max_symbols
        self._ttl_seconds = ttl_seconds
        self._prune_interval = prune_interval
        self._state: dict[str, tuple[Any, float]] = {}
        self._call_count = 0

    def get_state(self, symbol: str) -> Any | None:
        """Return state for symbol if not expired, else None."""
        self._maybe_prune()
        entry = self._state.get(symbol)
        if entry is None:
            return None
        state, ts = entry
        if time.monotonic() - ts > self._ttl_seconds:
            self._state.pop(symbol, None)
            return None
        return state

    def set_state(self, symbol: str, state: Any) -> None:
        """Store state for symbol with current timestamp."""
        self._state[symbol] = (state, time.monotonic())
        if len(self._state) > self._max_symbols:
            self._evict_oldest()

    def _maybe_prune(self) -> None:
        """Prune expired entries periodically based on call count."""
        self._call_count += 1
        if self._call_count % self._prune_interval == 0:
            self._prune()

    def _prune(self) -> None:
        """Remove all expired entries."""
        now = time.monotonic()
        expired = [
            s for s, (_, ts) in self._state.items()
            if now - ts > self._ttl_seconds
        ]
        for s in expired:
            del self._state[s]

    def _evict_oldest(self) -> None:
        """Evict the oldest entry when max capacity is exceeded."""
        if not self._state:
            return
        oldest = min(self._state.items(), key=lambda item: item[1][1])
        del self._state[oldest[0]]

    def clear_all_state(self) -> None:
        """Remove all state entries."""
        self._state.clear()


class PipelineStageBase(ABC):
    """Abstract base class for all pipeline stages.

    Provides default no-op implementations for lifecycle methods so that
    concrete stages only need to override what they actually use.  This
    eliminates the shotgun-surgery problem where adding a lifecycle hook
    requires touching every stage file.
    """

    @property
    @abstractmethod
    def stage_name(self) -> str:
        """Human-readable name used in metrics and snapshots."""

    @abstractmethod
    def process(self, event: PipelineEvent | object) -> list[PipelineEvent | object]:
        """Process one input event and return zero or more output events.

        Must be deterministic, exception-safe, and allocation-free in the
        hot path.
        """

    def warmup(self) -> None:
        """Pre-allocate state.  Default: no-op."""

    def teardown(self) -> None:
        """Flush / persist state.  Default: no-op."""

    def reset(self) -> None:
        """Reset to initial state.  Default: delegates to ``warmup``."""
        self.warmup()

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of internal state.

        Default: empty dict.
        """
        return {}
