"""Sequence-safe projection stream with resnapshot signaling."""

from __future__ import annotations

from collections.abc import AsyncIterable, Awaitable, Callable, Iterable
from typing import Any

from glassytrade.api.websocket.protocol import SequenceGap, validate_ws_message


class ProjectionStream:
    def __init__(
        self,
        source: Iterable[dict[str, Any]] | AsyncIterable[dict[str, Any]],
        *,
        on_resnapshot: Callable[[], Awaitable[None] | None] | None = None,
    ) -> None:
        self.source = source
        self.on_resnapshot = on_resnapshot

    def __aiter__(self) -> "ProjectionStream":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not hasattr(self, "_iterator"):
            self._iterator = self._as_async_iterator(self.source)
            self._sequence: int | None = None
        try:
            message = await self._iterator.__anext__()
        except StopAsyncIteration:
            raise
        try:
            validated = validate_ws_message(message)
            if self._sequence is not None and validated["type"] == "delta":
                if validated["baseSequence"] != self._sequence:
                    raise SequenceGap("delta does not follow current sequence")
            self._sequence = validated["sequence"]
            return validated
        except SequenceGap:
            self._sequence = None
            if self.on_resnapshot is not None:
                result = self.on_resnapshot()
                if hasattr(result, "__await__"):
                    await result
            return await self.__anext__()

    @staticmethod
    async def _as_async_iterator(source):
        if hasattr(source, "__aiter__"):
            async for item in source:
                yield item
        else:
            for item in source:
                yield item
