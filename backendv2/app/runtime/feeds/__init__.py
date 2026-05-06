"""Feed source contracts and concrete feed implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from app.runtime.pipeline.events import Tick


class FeedSource(ABC):
    """Abstract contract shared by live feed sources."""

    @abstractmethod
    def name(self) -> str:
        """Return a human-readable feed name."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Initialize feed resources."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Release feed resources."""
        ...

    @abstractmethod
    def stream(self) -> Iterator[Tick]:
        """Yield `Tick` events in deterministic order."""
        ...

    @property
    @abstractmethod
    def symbols(self) -> list[str]:
        """Symbols handled by this feed."""
        ...

    def snapshot(self) -> dict:
        """Capture feed metadata for observability."""
        return {}

    def restore(self, payload: dict) -> None:
        """Restore optional runtime metadata for compatibility."""
        _ = payload


from .live import LiveFeed
from .dhan_feed import DhanFeedSource

__all__ = [
    "FeedSource",
    "LiveFeed",
    "DhanFeedSource",
]