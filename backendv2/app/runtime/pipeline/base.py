"""Pipeline stage base class and utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.runtime.pipeline.events import PipelineEvent


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
