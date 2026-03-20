"""Pipeline registry — discovers, instantiates and wires processors from YAML config.

Usage:
    registry = ProcessorRegistry()
    pipeline = await registry.build_from_yaml("pipelines/production.yaml")
    await pipeline.run()
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # PyYAML — already in requirements

from app.pipeline.channel import Channel
from app.pipeline.processor import Processor, ProcessorConfig

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Parsed YAML pipeline config."""
    name: str
    description: str = ""
    channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    processors: list[dict[str, Any]] = field(default_factory=list)


class ProcessorRegistry:
    """Discovers and instantiates processors by dotted class path."""

    def __init__(self) -> None:
        self._cache: dict[str, type] = {}

    def resolve(self, dotted_path: str) -> type:
        """Import and return processor class by dotted path.

        Example: "app.pipeline.processors.ingest.DhanWsIngestor"
        """
        if dotted_path in self._cache:
            return self._cache[dotted_path]
        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        self._cache[dotted_path] = cls
        return cls


class Pipeline:
    """A wired set of processors and channels ready to run."""

    def __init__(
        self,
        name: str,
        processors: list[tuple[Processor, dict[str, Channel], dict[str, Channel]]],
        channels: dict[str, Channel],
    ) -> None:
        self.name = name
        self._processors = processors
        self._channels = channels
        self._tasks: list[Any] = []

    async def run(self) -> None:
        """Start all processors as concurrent asyncio tasks."""
        logger.info("Pipeline '%s': starting %d processors", self.name, len(self._processors))
        self._tasks = [
            asyncio.create_task(
                self._run_processor(proc, inbox, outbox),
                name=f"processor:{proc.name}",
            )
            for proc, inbox, outbox in self._processors
        ]
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Pipeline '%s': shutting down", self.name)
            raise

    async def stop(self) -> None:
        """Cancel all processor tasks."""
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_processor(
        self,
        proc: Processor,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Run one processor with error isolation."""
        try:
            await proc.process(inbox, outbox)
        except asyncio.CancelledError:
            await proc.teardown()
            raise
        except Exception:
            logger.exception("Processor '%s' crashed — isolated", proc.name)

    def channel_stats(self) -> list[dict]:
        return [ch.stats for ch in self._channels.values()]


async def build_pipeline_from_yaml(yaml_path: str | Path, registry: ProcessorRegistry | None = None) -> Pipeline:
    """Read a YAML pipeline config and return a wired, ready-to-run Pipeline."""
    if registry is None:
        registry = ProcessorRegistry()

    path = Path(yaml_path)
    with path.open() as f:
        raw = yaml.safe_load(f)

    cfg = PipelineConfig(
        name=raw.get("name", path.stem),
        description=raw.get("description", ""),
        channels=raw.get("channels", {}),
        processors=raw.get("processors", []),
    )

    # Build channels
    channels: dict[str, Channel] = {}
    for ch_name, ch_cfg in cfg.channels.items():
        capacity = ch_cfg.get("capacity", 1000)
        channels[ch_name] = Channel(name=ch_name, capacity=capacity)
        logger.debug("Channel created: %s (capacity=%d)", ch_name, capacity)

    # Build and setup processors
    wired: list[tuple[Processor, dict[str, Channel], dict[str, Channel]]] = []
    for proc_cfg_raw in cfg.processors:
        proc_config = ProcessorConfig(
            name=proc_cfg_raw["name"],
            processor_class=proc_cfg_raw["class"],
            inbox={k: v for k, v in proc_cfg_raw.get("inbox", {}).items()},
            outbox={k: v for k, v in proc_cfg_raw.get("outbox", {}).items()},
            settings=proc_cfg_raw.get("settings", {}),
        )
        cls = registry.resolve(proc_config.processor_class)
        proc: Processor = cls()
        await proc.setup(proc_config)

        inbox = {alias: channels[ch_name] for alias, ch_name in proc_config.inbox.items()}
        outbox = {alias: channels[ch_name] for alias, ch_name in proc_config.outbox.items()}
        wired.append((proc, inbox, outbox))
        logger.info("Processor wired: %s (%s)", proc_config.name, proc_config.processor_class)

    return Pipeline(name=cfg.name, processors=wired, channels=channels)
