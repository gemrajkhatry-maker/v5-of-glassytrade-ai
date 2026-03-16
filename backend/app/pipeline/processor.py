"""Processor Protocol and base class.

Every pipeline stage implements Processor. The contract is minimal:
  - setup(config): called once at startup
  - process(inbox, outbox): runs forever, reads from inbox, writes to outbox
  - teardown(): graceful shutdown

Processors MUST NOT import other processor classes. The only coupling between
two processors is the Message type they exchange.
"""
from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.pipeline.channel import Channel

logger = logging.getLogger(__name__)


@dataclass
class ProcessorConfig:
    """Configuration for a single processor instance."""
    name: str
    processor_class: str          # dotted import path
    inbox: dict[str, str] = field(default_factory=dict)   # channel_alias -> channel_name
    outbox: dict[str, str] = field(default_factory=dict)  # channel_alias -> channel_name
    settings: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Processor(Protocol):
    """Protocol that every pipeline processor must satisfy."""

    name: str

    async def setup(self, config: ProcessorConfig) -> None:
        """Load models, open connections. Called once before process()."""
        ...

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Main loop. Reads from inbox channels, writes to outbox channels.

        Must handle asyncio.CancelledError gracefully — do not swallow it.
        Must be robust to individual message failures (log + continue).
        """
        ...

    async def teardown(self) -> None:
        """Close connections, flush buffers. Called on shutdown."""
        ...


class BaseProcessor:
    """Convenience base class implementing safe defaults for Processor."""

    name: str = "unnamed"

    async def setup(self, config: ProcessorConfig) -> None:
        self.name = config.name
        self._settings = config.settings

    async def teardown(self) -> None:
        pass

    async def _safe_send(self, channel: Channel, msg: object) -> bool:
        """Send to channel, catching Full errors. Returns True on success."""
        try:
            await channel.send(msg)
            return True
        except Exception as e:
            logger.error("[%s] Failed to send to channel: %s", self.name, e)
            return False

    @abstractmethod
    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None: ...
