"""Bounded broker polling for unresolved OMS attempts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PollResult:
    attempt_id: str
    status: str
    snapshot: Any | None = None


class PollScheduler:
    def __init__(self, broker: Any, *, interval_seconds: float = 1.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.broker = broker
        self.interval_seconds = interval_seconds

    async def poll_once(self, attempt_ids: Iterable[str]) -> tuple[PollResult, ...]:
        results: list[PollResult] = []
        for attempt_id in attempt_ids:
            try:
                result = self.broker.get_order(attempt_id)
            except Exception as exc:
                results.append(PollResult(attempt_id, "UNAVAILABLE", str(exc)))
                continue
            results.append(
                PollResult(
                    attempt_id,
                    getattr(getattr(result, "order", None), "status", "UNKNOWN"),
                    getattr(result, "order", None),
                )
            )
        return tuple(results)

    async def run(
        self,
        attempt_ids: Callable[[], Iterable[str]],
        on_result: Callable[[PollResult], Awaitable[None] | None],
        *,
        stop: asyncio.Event | None = None,
    ) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            for result in await self.poll_once(attempt_ids()):
                callback_result = on_result(result)
                if asyncio.iscoroutine(callback_result):
                    await callback_result
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue
